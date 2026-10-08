from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models import ShortLink, ClickEvent, Domain, User, utcnow
from app.auth import require_approved_user

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

@router.get("/link/{link_id}")
async def get_link_analytics(
    link_id: int,
    period: str = Query("30d", pattern="^(30d|12m)$"),
    user: User = Depends(require_approved_user),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(
        select(ShortLink).options(selectinload(ShortLink.domain)).where(ShortLink.id == link_id)
    )
    link = res.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    # Domain check
    if not user.is_superadmin and link.domain_id not in {d.id for d in user.domains}:
        raise HTTPException(status_code=403, detail="Unauthorized")

    now = utcnow()

    # 1. Overall stats
    clicks_count_res = await db.execute(
        select(func.count(ClickEvent.id)).where(ClickEvent.short_link_id == link.id)
    )
    total_clicks = clicks_count_res.scalar() or link.total_clicks

    qr_count_res = await db.execute(
        select(func.count(ClickEvent.id)).where(ClickEvent.short_link_id == link.id, ClickEvent.is_qr == True)
    )
    qr_scans = qr_count_res.scalar() or 0

    today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    clicks_today_res = await db.execute(
        select(func.count(ClickEvent.id)).where(
            ClickEvent.short_link_id == link.id,
            ClickEvent.timestamp >= today_start
        )
    )
    clicks_today = clicks_today_res.scalar() or 0

    last_click_res = await db.execute(
        select(ClickEvent.timestamp).where(ClickEvent.short_link_id == link.id).order_by(ClickEvent.timestamp.desc()).limit(1)
    )
    last_click = last_click_res.scalar_one_or_none()

    # 2. Time series for Chart.js
    labels = []
    click_data = []
    qr_data = []

    if period == "30d":
        start_date = now.date() - timedelta(days=29)
        # Generate all 30 days
        day_map = {start_date + timedelta(days=i): {"clicks": 0, "qr": 0} for i in range(30)}

        # Fetch records
        ev_res = await db.execute(
            select(ClickEvent.timestamp, ClickEvent.is_qr).where(
                ClickEvent.short_link_id == link.id,
                ClickEvent.timestamp >= datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
            )
        )
        for ts, is_qr in ev_res.all():
            d = ts.date()
            if d in day_map:
                day_map[d]["clicks"] += 1
                if is_qr:
                    day_map[d]["qr"] += 1

        for d in sorted(day_map.keys()):
            labels.append(d.strftime("%b %d"))
            click_data.append(day_map[d]["clicks"])
            qr_data.append(day_map[d]["qr"])

    elif period == "12m":
        # Past 12 months
        # We start from 11 months ago
        current_year = now.year
        current_month = now.month
        
        months = []
        for i in range(11, -1, -1):
            m = current_month - i
            y = current_year
            while m <= 0:
                m += 12
                y -= 1
            months.append((y, m))

        month_map = {f"{y}-{m:02d}": {"clicks": 0, "qr": 0} for (y, m) in months}

        # Earliest date
        first_y, first_m = months[0]
        start_dt = datetime(first_y, first_m, 1, tzinfo=timezone.utc)

        ev_res = await db.execute(
            select(ClickEvent.timestamp, ClickEvent.is_qr).where(
                ClickEvent.short_link_id == link.id,
                ClickEvent.timestamp >= start_dt
            )
        )
        for ts, is_qr in ev_res.all():
            key = f"{ts.year}-{ts.month:02d}"
            if key in month_map:
                month_map[key]["clicks"] += 1
                if is_qr:
                    month_map[key]["qr"] += 1

        for (y, m) in months:
            key = f"{y}-{m:02d}"
            dt_obj = datetime(y, m, 1)
            labels.append(dt_obj.strftime("%b %Y"))
            click_data.append(month_map[key]["clicks"])
            qr_data.append(month_map[key]["qr"])

    # 3. Device breakdown
    device_res = await db.execute(
        select(ClickEvent.device_type, func.count(ClickEvent.id))
        .where(ClickEvent.short_link_id == link.id)
        .group_by(ClickEvent.device_type)
    )
    devices = {dev: count for dev, count in device_res.all()}

    # 4. Top Referrers
    ref_res = await db.execute(
        select(ClickEvent.referrer, func.count(ClickEvent.id))
        .where(ClickEvent.short_link_id == link.id, ClickEvent.referrer != None, ClickEvent.referrer != "")
        .group_by(ClickEvent.referrer)
        .order_by(func.count(ClickEvent.id).desc())
        .limit(5)
    )
    top_referrers = [{"referrer": ref, "clicks": cnt} for ref, cnt in ref_res.all()]

    return {
        "short_link": {
            "id": link.id,
            "slug": link.slug,
            "domain": link.domain.name,
            "short_url": f"https://{link.domain.name}/{link.slug}",
            "destination_url": link.destination_url,
            "title": link.title,
            "created_at": link.created_at.isoformat(),
        },
        "period": period,
        "total_clicks": total_clicks,
        "qr_scans": qr_scans,
        "direct_clicks": max(0, total_clicks - qr_scans),
        "clicks_today": clicks_today,
        "last_click": last_click.isoformat() if last_click else None,
        "chart": {
            "labels": labels,
            "clicks": click_data,
            "qr_scans": qr_data,
        },
        "devices": devices,
        "top_referrers": top_referrers,
    }

@router.get("/overview")
async def get_overview_analytics(
    user: User = Depends(require_approved_user),
    db: AsyncSession = Depends(get_db)
):
    allowed_domain_ids = [d.id for d in user.domains]
    if user.is_superadmin:
        all_doms_res = await db.execute(select(Domain))
        allowed_domain_ids = [d.id for d in all_doms_res.scalars().all()]

    total_links_res = await db.execute(
        select(func.count(ShortLink.id)).where(ShortLink.domain_id.in_(allowed_domain_ids))
    )
    total_links = total_links_res.scalar() or 0

    total_clicks_res = await db.execute(
        select(func.coalesce(func.sum(ShortLink.total_clicks), 0)).where(ShortLink.domain_id.in_(allowed_domain_ids))
    )
    total_clicks = total_clicks_res.scalar() or 0

    # Top 5 links
    top_links_res = await db.execute(
        select(ShortLink).options(selectinload(ShortLink.domain))
        .where(ShortLink.domain_id.in_(allowed_domain_ids))
        .order_by(ShortLink.total_clicks.desc())
        .limit(5)
    )
    top_links = [
        {
            "id": l.id,
            "slug": l.slug,
            "domain": l.domain.name,
            "title": l.title,
            "destination_url": l.destination_url,
            "total_clicks": l.total_clicks
        }
        for l in top_links_res.scalars().all()
    ]

    return {
        "total_links": total_links,
        "total_clicks": total_clicks,
        "top_links": top_links
    }
