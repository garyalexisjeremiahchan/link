import pytest
import pytest_asyncio
import io
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select

from app.main import app as fastapi_app
from app.config import settings
from app.models import Base, User, Domain, ShortLink, ClickEvent
from app.db import get_db, init_db

from sqlalchemy.pool import StaticPool

# Use in-memory SQLite with StaticPool so all connections share the same memory DB
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)

TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

async def override_get_db():
    async with TestingSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

fastapi_app.dependency_overrides[get_db] = override_get_db

import app.db as db_mod
import app.routers.redirect as redir_mod
import app.routers.links as links_mod
db_mod.AsyncSessionLocal = TestingSessionLocal
redir_mod.AsyncSessionLocal = TestingSessionLocal
links_mod.AsyncSessionLocal = TestingSessionLocal

@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed domains & default superadmin
    async with TestingSessionLocal() as session:
        # Seed domains
        for d_name in ["fcc.li", "amp.ad", "link.gajc.site"]:
            root = "https://freecomchurch.org/" if d_name == "fcc.li" else ("https://amplifyasiapacific.org/" if d_name == "amp.ad" else None)
            session.add(Domain(name=d_name, is_active=True, root_redirect_url=root))
        await session.commit()

        # Seed superadmin
        superadmin = User(
            email=settings.DEFAULT_SUPERADMIN,
            name="Super Admin",
            role="superadmin",
            status="approved"
        )
        session.add(superadmin)
        await session.commit()
        await session.refresh(superadmin)

        # Assign domains
        doms = (await session.execute(select(Domain))).scalars().all()
        from app.models import UserDomain
        for d in doms:
            session.add(UserDomain(user_id=superadmin.id, domain_id=d.id))
        await session.commit()

    yield

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest.mark.asyncio
async def test_health_check():
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

@pytest.mark.asyncio
async def test_root_domain_redirections():
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # fcc.li root should redirect to freecomchurch.org
        resp = await client.get("/", headers={"Host": "fcc.li"}, follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "https://freecomchurch.org/"

        # amp.ad root should redirect to amplifyasiapacific.org
        resp = await client.get("/", headers={"Host": "amp.ad"}, follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "https://amplifyasiapacific.org/"

@pytest.mark.asyncio
async def test_dev_login_and_auth_me():
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Dev login as superadmin
        login_resp = await client.get(
            f"/auth/dev-login?email={settings.DEFAULT_SUPERADMIN}",
            follow_redirects=False
        )
        assert login_resp.status_code == 302
        cookie = login_resp.cookies.get("fcc_session")
        assert cookie is not None

        # Check /auth/me
        me_resp = await client.get("/auth/me", cookies={"fcc_session": cookie})
        assert me_resp.status_code == 200
        data = me_resp.json()
        assert data["authenticated"] is True
        assert data["email"] == settings.DEFAULT_SUPERADMIN
        assert data["role"] == "superadmin"

@pytest.mark.asyncio
async def test_short_link_lifecycle_and_slug_collision():
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Login
        login_resp = await client.get(
            f"/auth/dev-login?email={settings.DEFAULT_SUPERADMIN}",
            follow_redirects=False
        )
        cookie = login_resp.cookies.get("fcc_session")

        # 1. Create short link on fcc.li
        create_resp = await client.post(
            "/api/links",
            json={
                "domain": "fcc.li",
                "slug": "easter2026",
                "destination_url": "https://freecomchurch.org/events/easter-2026",
                "title": "Easter Celebration 2026",
                "notes": "Sunday bulletin link"
            },
            cookies={"fcc_session": cookie}
        )
        assert create_resp.status_code == 200
        link_data = create_resp.json()
        link_id = link_data["id"]
        assert link_data["slug"] == "easter2026"
        assert link_data["domain"] == "fcc.li"

        # 2. Duplicate slug on same domain must return 409
        dup_resp = await client.post(
            "/api/links",
            json={
                "domain": "fcc.li",
                "slug": "easter2026",
                "destination_url": "https://different-url.com"
            },
            cookies={"fcc_session": cookie}
        )
        assert dup_resp.status_code == 409

        # 3. Same slug on DIFFERENT domain (amp.ad) must SUCCEED
        diff_dom_resp = await client.post(
            "/api/links",
            json={
                "domain": "amp.ad",
                "slug": "easter2026",
                "destination_url": "https://amplifyasiapacific.org/easter",
                "title": "Amplify Easter"
            },
            cookies={"fcc_session": cookie}
        )
        assert diff_dom_resp.status_code == 200
        assert diff_dom_resp.json()["domain"] == "amp.ad"

        # 4. Update link
        update_resp = await client.put(
            f"/api/links/{link_id}",
            json={
                "destination_url": "https://freecomchurch.org/events/easter-updated",
                "title": "Updated Easter 2026"
            },
            cookies={"fcc_session": cookie}
        )
        assert update_resp.status_code == 200

        # 5. Search links
        list_resp = await client.get("/api/links?domain=fcc.li&q=easter", cookies={"fcc_session": cookie})
        assert list_resp.status_code == 200
        items = list_resp.json()
        assert len(items) == 1
        assert items[0]["destination_url"] == "https://freecomchurch.org/events/easter-updated"

        # 6. Test Redirection for fcc.li/easter2026
        redir_resp = await client.get("/easter2026", headers={"Host": "fcc.li"}, follow_redirects=False)
        assert redir_resp.status_code == 302
        assert redir_resp.headers["location"] == "https://freecomchurch.org/events/easter-updated"

        # 7. Test QR PNG & SVG Generation
        qr_png_resp = await client.get(f"/api/links/{link_id}/qr.png", cookies={"fcc_session": cookie})
        assert qr_png_resp.status_code == 200
        assert qr_png_resp.headers["content-type"] == "image/png"
        assert qr_png_resp.content.startswith(b"\x89PNG")

        qr_svg_resp = await client.get(f"/api/links/{link_id}/qr.svg", cookies={"fcc_session": cookie})
        assert qr_svg_resp.status_code == 200
        assert "image/svg" in qr_svg_resp.headers["content-type"]
        assert "<svg" in qr_svg_resp.text

        # 8. Delete link
        del_resp = await client.delete(f"/api/links/{link_id}", cookies={"fcc_session": cookie})
        assert del_resp.status_code == 200

        # 9. Verify 404 after deletion
        not_found_resp = await client.get("/easter2026", headers={"Host": "fcc.li"}, follow_redirects=False)
        assert not_found_resp.status_code == 404
        assert "Link Expired or Not Found" in not_found_resp.text

@pytest.mark.asyncio
async def test_rebrandly_csv_import_and_export():
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Login
        login_resp = await client.get(
            f"/auth/dev-login?email={settings.DEFAULT_SUPERADMIN}",
            follow_redirects=False
        )
        cookie = login_resp.cookies.get("fcc_session")

        # Mock CSV data in Rebrandly format
        csv_data = (
            "Domain,Slashtag,Destination,Title,Clicks\n"
            "fcc.li,donate,https://freecomchurch.org/give,Give to FCC,142\n"
            "amp.ad,conference,https://amplifyasiapacific.org/conf2026,Asia Pacific Conf,88\n"
        )
        files = {
            "file": ("rebrandly_export.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")
        }

        import_resp = await client.post(
            "/api/links/import-rebrandly-csv",
            files=files,
            cookies={"fcc_session": cookie}
        )
        assert import_resp.status_code == 200
        res_json = import_resp.json()
        assert res_json["imported"] == 2
        assert res_json["skipped"] == 0

        # Export CSV
        export_resp = await client.get("/api/links/export-csv", cookies={"fcc_session": cookie})
        assert export_resp.status_code == 200
        assert "fcc.li,donate" in export_resp.text
        assert "amp.ad,conference" in export_resp.text

@pytest.mark.asyncio
async def test_admin_user_approval_and_domain_rbac():
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create a pending normal user
        login_normal = await client.get(
            "/auth/dev-login?email=volunteer@freecomchurch.org",
            follow_redirects=False
        )
        volunteer_cookie = login_normal.cookies.get("fcc_session")

        # Superadmin logs in
        login_admin = await client.get(
            f"/auth/dev-login?email={settings.DEFAULT_SUPERADMIN}",
            follow_redirects=False
        )
        admin_cookie = login_admin.cookies.get("fcc_session")

        # List users as superadmin
        users_resp = await client.get("/api/admin/users", cookies={"admin_cookie": admin_cookie, "fcc_session": admin_cookie})
        assert users_resp.status_code == 200
        users = users_resp.json()
        vol_user = next((u for u in users if u["email"] == "volunteer@freecomchurch.org"), None)
        assert vol_user is not None

        # Superadmin restricts volunteer to ONLY 'fcc.li'
        approve_resp = await client.post(
            f"/api/admin/users/{vol_user['id']}/approve",
            json={
                "role": "user",
                "allowed_domains": ["fcc.li"]
            },
            cookies={"fcc_session": admin_cookie}
        )
        assert approve_resp.status_code == 200

        # Volunteer should be able to create link on fcc.li
        ok_create = await client.post(
            "/api/links",
            json={
                "domain": "fcc.li",
                "slug": "youth-camp",
                "destination_url": "https://freecomchurch.org/youth"
            },
            cookies={"fcc_session": volunteer_cookie}
        )
        assert ok_create.status_code == 200

        # Volunteer should be FORBIDDEN from creating link on amp.ad
        forbidden_create = await client.post(
            "/api/links",
            json={
                "domain": "amp.ad",
                "slug": "youth-camp",
                "destination_url": "https://amplifyasiapacific.org/youth"
            },
            cookies={"fcc_session": volunteer_cookie}
        )
        assert forbidden_create.status_code == 403

@pytest.mark.asyncio
async def test_analytics_endpoints():
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Login
        login_resp = await client.get(
            f"/auth/dev-login?email={settings.DEFAULT_SUPERADMIN}",
            follow_redirects=False
        )
        cookie = login_resp.cookies.get("fcc_session")

        # Create link
        create_resp = await client.post(
            "/api/links",
            json={
                "domain": "fcc.li",
                "slug": "stats-test",
                "destination_url": "https://freecomchurch.org/stats"
            },
            cookies={"fcc_session": cookie}
        )
        assert create_resp.status_code == 200
        link_id = create_resp.json()["id"]

        # Simulate click
        redir_resp = await client.get("/stats-test", headers={"Host": "fcc.li"}, follow_redirects=False)
        assert redir_resp.status_code == 302

        # Simulate QR scan click
        qr_redir_resp = await client.get("/stats-test?src=qr", headers={"Host": "fcc.li"}, follow_redirects=False)
        assert qr_redir_resp.status_code == 302

        # Query 30d analytics
        analytics_30d = await client.get(f"/api/analytics/link/{link_id}?period=30d", cookies={"fcc_session": cookie})
        assert analytics_30d.status_code == 200
        data_30d = analytics_30d.json()
        assert data_30d["period"] == "30d"
        assert len(data_30d["chart"]["labels"]) == 30
        assert data_30d["total_clicks"] >= 2
        assert data_30d["qr_scans"] >= 1

        # Query 12m analytics
        analytics_12m = await client.get(f"/api/analytics/link/{link_id}?period=12m", cookies={"fcc_session": cookie})
        assert analytics_12m.status_code == 200
        data_12m = analytics_12m.json()
        assert data_12m["period"] == "12m"
        assert len(data_12m["chart"]["labels"]) == 12

        # Overview analytics
        overview_resp = await client.get("/api/analytics/overview", cookies={"fcc_session": cookie})
        assert overview_resp.status_code == 200
        overview = overview_resp.json()
        assert overview["total_links"] >= 1
        assert overview["total_clicks"] >= 2
