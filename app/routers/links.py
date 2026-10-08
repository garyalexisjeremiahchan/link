import csv
import io
import re
import secrets
import string
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks, UploadFile, File
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, delete
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models import ShortLink, Domain, User, LinkTag, ClickEvent, utcnow
from app.auth import require_approved_user
from app.qr import generate_qr_png, generate_qr_svg
from app.utils import fetch_url_metadata

router = APIRouter(prefix="/api/links", tags=["links"])

class LinkCreate(BaseModel):
    domain: str
    destination_url: str
    slug: Optional[str] = None
    title: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None

class LinkUpdate(BaseModel):
    destination_url: Optional[str] = None
    title: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None
    tags: Optional[List[str]] = None

def generate_random_slug(length: int = 6) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))

def sanitize_slug(slug: str) -> str:
    slug = slug.strip().lower()
    # Allow alphanumeric, hyphens, and underscores
    slug = re.sub(r"[^a-z0-9\-_]", "", slug)
    return slug

async def ensure_user_has_domain(user: User, domain_name: str, db: AsyncSession) -> Domain:
    res = await db.execute(select(Domain).where(Domain.name == domain_name))
    domain = res.scalar_one_or_none()
    if not domain:
        raise HTTPException(status_code=400, detail=f"Domain '{domain_name}' is not recognized")
    
    if user.is_superadmin:
        return domain

    # Check allowed domains for user
    allowed_domain_ids = {d.id for d in user.domains}
    if domain.id not in allowed_domain_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You do not have permission to manage links for '{domain_name}'"
        )
    return domain

@router.get("")
async def list_links(
    domain: Optional[str] = None,
    q: Optional[str] = None,
    user: User = Depends(require_approved_user),
    db: AsyncSession = Depends(get_db)
):
    # Determine allowed domain IDs for user
    allowed_domains_map = {d.id: d.name for d in user.domains}
    if user.is_superadmin:
        all_doms_res = await db.execute(select(Domain))
        allowed_domains_map = {d.id: d.name for d in all_doms_res.scalars().all()}

    query = select(ShortLink).options(selectinload(ShortLink.domain), selectinload(ShortLink.tags))

    if domain and domain.lower() != "all":
        # Specific domain filter
        res = await db.execute(select(Domain).where(Domain.name == domain.strip()))
        dom_obj = res.scalar_one_or_none()
        if not dom_obj or dom_obj.id not in allowed_domains_map:
            raise HTTPException(status_code=403, detail="Unauthorized domain filter")
        query = query.where(ShortLink.domain_id == dom_obj.id)
    else:
        # Constrain to all allowed domains
        query = query.where(ShortLink.domain_id.in_(list(allowed_domains_map.keys())))

    if q:
        search_term = f"%{q.strip().lower()}%"
        query = query.where(
            or_(
                func.lower(ShortLink.slug).like(search_term),
                func.lower(ShortLink.title).like(search_term),
                func.lower(ShortLink.destination_url).like(search_term)
            )
        )

    query = query.order_by(ShortLink.created_at.desc())
    res = await db.execute(query)
    links = res.scalars().all()

    return [
        {
            "id": link.id,
            "domain": link.domain.name,
            "slug": link.slug,
            "short_url": f"https://{link.domain.name}/{link.slug}",
            "destination_url": link.destination_url,
            "title": link.title or link.slug,
            "notes": link.notes,
            "is_active": link.is_active,
            "total_clicks": link.total_clicks,
            "tags": [t.name for t in link.tags],
            "created_at": link.created_at.isoformat(),
            "updated_at": link.updated_at.isoformat(),
        }
        for link in links
    ]

@router.post("")
async def create_link(
    data: LinkCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_approved_user),
    db: AsyncSession = Depends(get_db)
):
    domain = await ensure_user_has_domain(user, data.domain, db)
    
    slug = sanitize_slug(data.slug) if data.slug else generate_random_slug()
    if not slug:
        slug = generate_random_slug()

    # Check collision on this specific domain
    existing = await db.execute(
        select(ShortLink).where(ShortLink.domain_id == domain.id, ShortLink.slug == slug)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The slug '{slug}' already exists on domain '{domain.name}'"
        )

    title = data.title
    short_link = ShortLink(
        domain_id=domain.id,
        slug=slug,
        destination_url=data.destination_url.strip(),
        title=title,
        notes=data.notes,
        is_active=True,
        total_clicks=0,
        created_by_user_id=user.id,
    )
    db.add(short_link)
    await db.commit()
    await db.refresh(short_link)

    # Background task to fetch metadata if title missing
    if not title:
        async def scrape_and_update(link_id: int, target_url: str):
            meta = await fetch_url_metadata(target_url)
            if meta.get("title"):
                from app.db import AsyncSessionLocal
                async with AsyncSessionLocal() as s:
                    item_res = await s.execute(select(ShortLink).where(ShortLink.id == link_id))
                    item = item_res.scalar_one_or_none()
                    if item and not item.title:
                        item.title = meta["title"]
                        await s.commit()

        background_tasks.add_task(scrape_and_update, short_link.id, short_link.destination_url)

    return {
        "id": short_link.id,
        "domain": domain.name,
        "slug": short_link.slug,
        "short_url": f"https://{domain.name}/{short_link.slug}",
        "destination_url": short_link.destination_url,
        "title": short_link.title,
        "total_clicks": short_link.total_clicks,
        "created_at": short_link.created_at.isoformat(),
    }

@router.put("/{link_id}")
async def update_link(
    link_id: int,
    data: LinkUpdate,
    user: User = Depends(require_approved_user),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(
        select(ShortLink).options(selectinload(ShortLink.domain)).where(ShortLink.id == link_id)
    )
    link = res.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    await ensure_user_has_domain(user, link.domain.name, db)

    if data.destination_url is not None:
        link.destination_url = data.destination_url.strip()
    if data.title is not None:
        link.title = data.title.strip()
    if data.notes is not None:
        link.notes = data.notes.strip()
    if data.is_active is not None:
        link.is_active = data.is_active
    link.updated_at = utcnow()

    await db.commit()
    return {"status": "success", "id": link.id}

@router.delete("/{link_id}")
async def delete_link(
    link_id: int,
    user: User = Depends(require_approved_user),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(
        select(ShortLink).options(selectinload(ShortLink.domain)).where(ShortLink.id == link_id)
    )
    link = res.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    await ensure_user_has_domain(user, link.domain.name, db)
    await db.delete(link)
    await db.commit()
    return {"status": "success"}

@router.get("/{link_id}/qr.png")
async def get_link_qr_png(
    link_id: int,
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(
        select(ShortLink).options(selectinload(ShortLink.domain)).where(ShortLink.id == link_id)
    )
    link = res.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    short_url = f"https://{link.domain.name}/{link.slug}?src=qr"
    png_bytes = generate_qr_png(short_url)
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="{link.slug}-qr.png"'}
    )

@router.get("/{link_id}/qr.svg")
async def get_link_qr_svg(
    link_id: int,
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(
        select(ShortLink).options(selectinload(ShortLink.domain)).where(ShortLink.id == link_id)
    )
    link = res.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    short_url = f"https://{link.domain.name}/{link.slug}?src=qr"
    svg_content = generate_qr_svg(short_url)
    return Response(
        content=svg_content,
        media_type="image/svg+xml",
        headers={"Content-Disposition": f'inline; filename="{link.slug}-qr.svg"'}
    )

@router.post("/preview-metadata")
async def preview_metadata(url: str = Query(...)):
    return await fetch_url_metadata(url)

@router.post("/import-rebrandly-csv")
async def import_rebrandly_csv(
    file: UploadFile = File(...),
    user: User = Depends(require_approved_user),
    db: AsyncSession = Depends(get_db)
):
    """Import links from a Rebrandly exported CSV."""
    content = await file.read()
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    imported_count = 0
    skipped_count = 0

    # Cache domain objects
    dom_res = await db.execute(select(Domain))
    domains_by_name = {d.name.lower(): d for d in dom_res.scalars().all()}

    for row in reader:
        # Rebrandly column headers can be: "Domain", "Slashtag" or "Slug", "Destination" or "Destination URL", "Title", "Clicks"
        dom_name = (row.get("Domain") or row.get("domain") or "fcc.li").strip().lower()
        slug = sanitize_slug(row.get("Slashtag") or row.get("Slug") or row.get("slug") or "")
        destination = (row.get("Destination") or row.get("Destination URL") or row.get("destination") or "").strip()
        title = (row.get("Title") or row.get("title") or "").strip()
        clicks_raw = row.get("Clicks") or row.get("clicks") or "0"
        try:
            clicks = int(float(str(clicks_raw).strip()))
        except (ValueError, TypeError):
            clicks = 0

        if not slug or not destination:
            skipped_count += 1
            continue

        domain = domains_by_name.get(dom_name)
        if not domain:
            skipped_count += 1
            continue

        # Check domain authorization
        if not user.is_superadmin and domain.id not in {d.id for d in user.domains}:
            skipped_count += 1
            continue

        # Check collision
        existing = await db.execute(
            select(ShortLink).where(ShortLink.domain_id == domain.id, ShortLink.slug == slug)
        )
        if existing.scalar_one_or_none():
            skipped_count += 1
            continue

        link = ShortLink(
            domain_id=domain.id,
            slug=slug,
            destination_url=destination,
            title=title or slug,
            total_clicks=clicks,
            is_active=True,
            created_by_user_id=user.id
        )
        db.add(link)
        imported_count += 1

    await db.commit()
    return {"imported": imported_count, "skipped": skipped_count}

@router.get("/export-csv")
async def export_links_csv(
    user: User = Depends(require_approved_user),
    db: AsyncSession = Depends(get_db)
):
    allowed_domain_ids = [d.id for d in user.domains]
    if user.is_superadmin:
        all_doms_res = await db.execute(select(Domain))
        allowed_domain_ids = [d.id for d in all_doms_res.scalars().all()]

    res = await db.execute(
        select(ShortLink).options(selectinload(ShortLink.domain))
        .where(ShortLink.domain_id.in_(allowed_domain_ids))
        .order_by(ShortLink.created_at.desc())
    )
    links = res.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Domain", "Slug", "Short URL", "Destination URL", "Title", "Total Clicks", "Created At"])
    for link in links:
        writer.writerow([
            link.domain.name,
            link.slug,
            f"https://{link.domain.name}/{link.slug}",
            link.destination_url,
            link.title or "",
            link.total_clicks,
            link.created_at.isoformat()
        ])

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="fcc-links-export.csv"'}
    )
