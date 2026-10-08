from typing import Optional
from fastapi import APIRouter, Request, Response, Depends, HTTPException, status
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from authlib.integrations.starlette_client import OAuth
from app.config import settings
from app.db import get_db
from app.models import User, Domain, UserDomain
from app.auth import (
    create_session_token, get_current_user, SESSION_COOKIE_NAME, SESSION_MAX_AGE
)
from app.models import utcnow

router = APIRouter(prefix="/auth", tags=["auth"])

oauth = OAuth()
if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET:
    oauth.register(
        name="google",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

@router.get("/login")
async def login(request: Request):
    if not settings.GOOGLE_CLIENT_ID:
        # If Google credentials are not set, direct to dev-login page
        return RedirectResponse(url="/login?dev_mode=true")
    redirect_uri = settings.GOOGLE_REDIRECT_URI
    return await oauth.google.authorize_redirect(request, redirect_uri)

@router.get("/callback")
async def auth_callback(request: Request, db: AsyncSession = Depends(get_db)):
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=400, detail="Google OAuth not configured")
    try:
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get("userinfo")
        if not user_info:
            raise HTTPException(status_code=400, detail="Failed to retrieve user profile from Google")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth error: {str(e)}")

    email = user_info.get("email", "").lower().strip()
    name = user_info.get("name")
    picture = user_info.get("picture")

    if not email:
        raise HTTPException(status_code=400, detail="No email returned from Google")

    # Check if user exists
    res = await db.execute(select(User).where(User.email == email))
    user = res.scalar_one_or_none()

    if not user:
        # Check if this is the default superadmin
        is_super = (email == settings.DEFAULT_SUPERADMIN.lower().strip())
        role = "superadmin" if is_super else "user"
        user_status = "approved" if is_super else "pending"
        
        user = User(
            email=email,
            name=name,
            avatar_url=picture,
            role=role,
            status=user_status,
            last_login_at=utcnow(),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        # Superadmin gets access to all domains
        if is_super:
            dom_res = await db.execute(select(Domain))
            for dom in dom_res.scalars().all():
                db.add(UserDomain(user_id=user.id, domain_id=dom.id))
            await db.commit()
    else:
        # Update profile info and last login
        user.name = name or user.name
        user.avatar_url = picture or user.avatar_url
        user.last_login_at = utcnow()
        # Ensure default superadmin role is preserved
        if email == settings.DEFAULT_SUPERADMIN.lower().strip() and user.role != "superadmin":
            user.role = "superadmin"
            user.status = "approved"
        await db.commit()

    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    session_token = create_session_token(user.id)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return response

@router.get("/dev-login")
async def dev_login(email: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Mock login endpoint for local testing when DEV_AUTH_BYPASS is active."""
    if not settings.DEV_AUTH_BYPASS:
        raise HTTPException(status_code=403, detail="Dev login disabled in production")
    
    clean_email = email.lower().strip()
    res = await db.execute(select(User).where(User.email == clean_email))
    user = res.scalar_one_or_none()
    
    if not user:
        is_super = (clean_email == settings.DEFAULT_SUPERADMIN.lower().strip())
        role = "superadmin" if is_super else "user"
        user_status = "approved" if is_super else "approved"  # Auto-approve in dev mode for convenience
        
        user = User(
            email=clean_email,
            name=clean_email.split("@")[0].capitalize(),
            role=role,
            status=user_status,
            last_login_at=utcnow(),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        # Grant access to all domains in dev mode
        dom_res = await db.execute(select(Domain))
        for dom in dom_res.scalars().all():
            db.add(UserDomain(user_id=user.id, domain_id=dom.id))
        await db.commit()
    else:
        user.last_login_at = utcnow()
        await db.commit()

    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    session_token = create_session_token(user.id)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(key=SESSION_COOKIE_NAME)
    return response

@router.get("/me")
async def get_me(user: Optional[User] = Depends(get_current_user)):
    if not user:
        return JSONResponse({"authenticated": False})
    
    allowed_domains = [d.name for d in user.domains] if not user.is_superadmin else [d.name for d in user.domains]
    return {
        "authenticated": True,
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "avatar_url": user.avatar_url,
        "role": user.role,
        "status": user.status,
        "allowed_domains": allowed_domains
    }
