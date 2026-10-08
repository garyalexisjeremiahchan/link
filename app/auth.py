from typing import Optional
from fastapi import Request, HTTPException, status, Depends
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.config import settings
from app.models import User
from app.db import get_db

serializer = URLSafeTimedSerializer(settings.SECRET_KEY)
SESSION_COOKIE_NAME = "fcc_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 14  # 14 days

def create_session_token(user_id: int) -> str:
    return serializer.dumps({"user_id": user_id})

def verify_session_token(token: str) -> Optional[int]:
    try:
        data = serializer.loads(token, max_age=SESSION_MAX_AGE)
        return data.get("user_id")
    except (BadSignature, SignatureExpired):
        return None

async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> Optional[User]:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    user_id = verify_session_token(token)
    if not user_id:
        return None
    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    return user

async def require_approved_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    user = await get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if user.status == "pending":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is pending approval from an administrator."
        )
    if user.status != "approved":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access revoked")
    return user

async def require_admin_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    user = await require_approved_user(request, db)
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin permissions required")
    return user

async def require_superadmin_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    user = await require_approved_user(request, db)
    if not user.is_superadmin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super Admin permissions required")
    return user
