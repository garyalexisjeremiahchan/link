from typing import Optional
from fastapi import APIRouter, Request, Response, Depends, HTTPException, BackgroundTasks, status
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.db import get_db, AsyncSessionLocal
from app.models import ShortLink, Domain, ClickEvent, utcnow
from app.utils import anonymize_ip, detect_device_type
from app.config import settings

router = APIRouter(tags=["redirect"])

def clean_host(host_header: Optional[str]) -> str:
    if not host_header:
        return "link.gajc.site"
    # Remove port if present (e.g., localhost:8000 -> localhost)
    return host_header.split(":")[0].strip().lower()

async def log_click_event_background(
    link_id: int,
    ip_hash: str,
    referrer: Optional[str],
    user_agent: Optional[str],
    device_type: str,
    is_qr: bool
):
    async with AsyncSessionLocal() as session:
        # 1. Insert ClickEvent
        ev = ClickEvent(
            short_link_id=link_id,
            timestamp=utcnow(),
            ip_hash=ip_hash,
            referrer=referrer[:1000] if referrer else None,
            user_agent=user_agent[:1000] if user_agent else None,
            device_type=device_type,
            is_qr=is_qr,
        )
        session.add(ev)
        # 2. Increment total_clicks
        await session.execute(
            update(ShortLink).where(ShortLink.id == link_id).values(total_clicks=ShortLink.total_clicks + 1)
        )
        await session.commit()

def render_not_found_page(domain_name: str, slug: str) -> HTMLResponse:
    if "amp.ad" in domain_name:
        brand_name = "Amplify Asia Pacific"
        home_url = "https://amplifyasiapacific.org"
    else:
        brand_name = "Free Community Church"
        home_url = "https://freecomchurch.org"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Link Not Found — {brand_name}</title>
    <link rel="icon" type="image/svg+xml" href="/static/brand/fcc-app-icon-light.svg">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Mulish:ital,wght@0,400;0,700;0,800;1,800&display=swap" rel="stylesheet">
    <style>
        :root {{
            --color-bg: #FFFFFF;
            --color-text: #1F2328;
            --color-text-muted: #5B6168;
            --color-primary: #1C7678;
            --color-primary-hover: #186668;
            --color-accent: #F8DC29;
            --font-sans: 'Mulish', -apple-system, BlinkMacSystemFont, sans-serif;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: var(--font-sans);
            background: #F7F8F8;
            color: var(--color-text);
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            padding: 24px;
        }}
        .card {{
            background: #FFFFFF;
            border: 1px solid #DDE1E3;
            border-radius: 4px;
            padding: 40px 32px;
            max-width: 480px;
            width: 100%;
            text-align: center;
            box-shadow: 0 4px 12px rgba(20, 22, 26, 0.06);
        }}
        .logo {{
            width: 64px;
            height: 64px;
            margin: 0 auto 20px;
        }}
        .badge {{
            display: inline-block;
            background: #D9EEEE;
            color: #135153;
            font-size: 13px;
            font-weight: 800;
            letter-spacing: 0.16em;
            text-transform: uppercase;
            padding: 4px 12px;
            border-radius: 999px;
            margin-bottom: 16px;
        }}
        h1 {{
            font-size: 26px;
            font-weight: 800;
            color: #14161A;
            margin-bottom: 12px;
        }}
        p {{
            font-size: 15px;
            color: var(--color-text-muted);
            line-height: 1.6;
            margin-bottom: 24px;
        }}
        .slug {{
            font-family: monospace;
            background: #EEF0F1;
            padding: 2px 6px;
            border-radius: 4px;
            color: #14161A;
        }}
        .btn {{
            display: inline-block;
            background: var(--color-primary);
            color: #FFFFFF;
            text-decoration: none;
            padding: 12px 28px;
            border-radius: 999px;
            font-weight: 700;
            font-size: 15px;
            transition: background 0.15s ease;
        }}
        .btn:hover {{
            background: var(--color-primary-hover);
        }}
    </style>
</head>
<body>
    <div class="card">
        <img class="logo" src="/static/brand/fcc-dove-light.svg" alt="FCC Dove">
        <div class="badge">404 Not Found</div>
        <h1>Link Expired or Not Found</h1>
        <p>The short link <span class="slug">/{slug}</span> does not exist or has been retired.</p>
        <a class="btn" href="{home_url}">Visit {brand_name}</a>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=status.HTTP_404_NOT_FOUND)

@router.get("/{slug}")
async def resolve_short_link(
    slug: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    host = clean_host(request.headers.get("host"))
    clean_slug_str = slug.strip().lower()

    # Reserved routes that should not be captured as slugs
    reserved = {"api", "auth", "static", "login", "admin", "favicon.ico", "healthz"}
    if clean_slug_str in reserved:
        raise HTTPException(status_code=404)

    # 1. Check matching domain
    # If host matches fcc.li or amp.ad, filter strictly by that domain
    res = await db.execute(select(Domain).where(Domain.name == host))
    domain = res.scalar_one_or_none()

    if domain:
        link_res = await db.execute(
            select(ShortLink).where(
                ShortLink.domain_id == domain.id,
                ShortLink.slug == clean_slug_str,
                ShortLink.is_active == True
            )
        )
        link = link_res.scalar_one_or_none()
    else:
        # Development / staging fallback (e.g. host is link.gajc.site or localhost):
        # search across active links
        link_res = await db.execute(
            select(ShortLink).options(selectinload(ShortLink.domain))
            .where(ShortLink.slug == clean_slug_str, ShortLink.is_active == True)
        )
        link = link_res.scalar_one_or_none()

    if not link:
        return render_not_found_page(host, slug)

    # Detect click metadata
    ip = request.client.host if request.client else None
    ip_hash = anonymize_ip(ip)
    referrer = request.headers.get("referer")
    user_agent = request.headers.get("user-agent")
    device_type = detect_device_type(user_agent)
    is_qr = request.query_params.get("src", "").lower() == "qr"

    # Queue background task to record click event
    background_tasks.add_task(
        log_click_event_background,
        link.id,
        ip_hash,
        referrer,
        user_agent,
        device_type,
        is_qr
    )

    # Return HTTP 302 Found redirect
    return RedirectResponse(url=link.destination_url, status_code=status.HTTP_302_FOUND)
