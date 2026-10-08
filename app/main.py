from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.db import init_db, get_db
from app.models import User, Domain
from app.auth import get_current_user
from app.routers.auth import router as auth_router
from app.routers.links import router as links_router
from app.routers.admin import router as admin_router
from app.routers.analytics import router as analytics_router
from app.routers.redirect import router as redirect_router, clean_host

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure tables created and default superadmin seeded
    await init_db()
    yield
    # Shutdown

app = FastAPI(
    title=settings.APP_NAME,
    description="URL Shortener and Link Intelligence Platform for fcc.li and amp.ad",
    lifespan=lifespan
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates
templates = Jinja2Templates(directory="templates")

# Health Check for Docker / Nginx
@app.get("/healthz", tags=["health"])
async def health_check():
    return {"status": "ok", "app": settings.APP_NAME}

# Main Root Handler
@app.get("/", response_class=HTMLResponse)
async def index_root(
    request: Request,
    user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    host = clean_host(request.headers.get("host"))

    # Phase 1 Root Handling for Short Link Domains
    if host == "fcc.li":
        return RedirectResponse(url="https://freecomchurch.org/", status_code=302)
    elif host == "amp.ad":
        return RedirectResponse(url="https://amplifyasiapacific.org/", status_code=302)

    # Management Domain: link.gajc.site (and local dev)
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "dev_mode": settings.DEV_AUTH_BYPASS,
                "superadmin_email": settings.DEFAULT_SUPERADMIN,
                "pending": False,
                "error": None
            }
        )

    if user.status == "pending":
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "dev_mode": False,
                "superadmin_email": settings.DEFAULT_SUPERADMIN,
                "pending": True,
                "error": None
            }
        )

    if user.status != "approved":
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "dev_mode": False,
                "superadmin_email": settings.DEFAULT_SUPERADMIN,
                "pending": False,
                "error": "Access to the FCC Link management portal has been revoked."
            }
        )

    # User is approved: show Dashboard
    if user.is_superadmin:
        all_doms_res = await db.execute(select(Domain))
        user_domains = [d.name for d in all_doms_res.scalars().all()]
    else:
        user_domains = [d.name for d in user.domains]

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "user_domains": user_domains
        }
    )

# Dedicated /login page
@app.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    user: Optional[User] = Depends(get_current_user)
):
    if user and user.status == "approved":
        return RedirectResponse(url="/")

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "dev_mode": settings.DEV_AUTH_BYPASS,
            "superadmin_email": settings.DEFAULT_SUPERADMIN,
            "pending": user.status == "pending" if user else False,
            "error": None
        }
    )

# Register API & Service Routers
app.include_router(auth_router)
app.include_router(links_router)
app.include_router(admin_router)
app.include_router(analytics_router)

# Register Redirection Router LAST to capture /{slug}
app.include_router(redirect_router)
