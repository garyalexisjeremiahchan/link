from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models import User, Domain, UserDomain
from app.auth import require_admin_user, require_superadmin_user
from app.config import settings

router = APIRouter(prefix="/api/admin", tags=["admin"])

class UserUpdate(BaseModel):
    role: Optional[str] = None  # "admin", "user"
    status: Optional[str] = None  # "approved", "pending", "revoked"
    allowed_domains: Optional[List[str]] = None

class UserApprove(BaseModel):
    role: str = "user"
    allowed_domains: List[str] = ["fcc.li"]

class DomainCreate(BaseModel):
    name: str
    root_redirect_url: Optional[str] = None

@router.get("/users")
async def list_users(
    admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(User).options(selectinload(User.domains)).order_by(User.created_at.desc()))
    users = res.scalars().all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "name": u.name or u.email.split("@")[0],
            "avatar_url": u.avatar_url,
            "role": u.role,
            "status": u.status,
            "allowed_domains": [d.name for d in u.domains],
            "created_at": u.created_at.isoformat(),
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            "is_default_superadmin": (u.email.lower() == settings.DEFAULT_SUPERADMIN.lower())
        }
        for u in users
    ]

@router.post("/users/{user_id}/approve")
async def approve_user(
    user_id: int,
    data: UserApprove,
    admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(User).options(selectinload(User.domains)).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.status = "approved"
    if admin.is_superadmin and data.role in ("admin", "user"):
        user.role = data.role

    # Update domains if superadmin
    if admin.is_superadmin and data.allowed_domains:
        # Clear existing
        await db.execute(delete(UserDomain).where(UserDomain.user_id == user.id))
        # Add new
        for dom_name in data.allowed_domains:
            d_res = await db.execute(select(Domain).where(Domain.name == dom_name.strip()))
            dom = d_res.scalar_one_or_none()
            if dom:
                db.add(UserDomain(user_id=user.id, domain_id=dom.id))

    await db.commit()
    return {"status": "success", "message": f"User {user.email} approved"}

@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    data: UserUpdate,
    admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(User).options(selectinload(User.domains)).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Guard default superadmin
    if user.email.lower() == settings.DEFAULT_SUPERADMIN.lower():
        if data.role and data.role != "superadmin":
            raise HTTPException(status_code=400, detail="Default superadmin cannot be demoted")
        if data.status and data.status != "approved":
            raise HTTPException(status_code=400, detail="Default superadmin cannot be deactivated")

    # Regular admin can only update non-admin users
    if not admin.is_superadmin and user.is_admin:
        raise HTTPException(status_code=403, detail="Only Super Admin can modify other administrators")

    if data.status:
        user.status = data.status

    if data.role and admin.is_superadmin:
        user.role = data.role

    # Domain permissions can be changed by superadmin
    if data.allowed_domains is not None and admin.is_superadmin:
        await db.execute(delete(UserDomain).where(UserDomain.user_id == user.id))
        for dom_name in data.allowed_domains:
            d_res = await db.execute(select(Domain).where(Domain.name == dom_name.strip()))
            dom = d_res.scalar_one_or_none()
            if dom:
                db.add(UserDomain(user_id=user.id, domain_id=dom.id))

    await db.commit()
    return {"status": "success"}

@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.email.lower() == settings.DEFAULT_SUPERADMIN.lower():
        raise HTTPException(status_code=400, detail="Default superadmin cannot be deleted")

    if not admin.is_superadmin and user.is_admin:
        raise HTTPException(status_code=403, detail="Only Super Admin can delete administrators")

    await db.delete(user)
    await db.commit()
    return {"status": "success"}

@router.get("/domains")
async def list_domains(
    admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(Domain).order_by(Domain.name.asc()))
    domains = res.scalars().all()
    return [
        {
            "id": d.id,
            "name": d.name,
            "is_active": d.is_active,
            "root_redirect_url": d.root_redirect_url,
            "created_at": d.created_at.isoformat()
        }
        for d in domains
    ]

@router.post("/domains")
async def create_domain(
    data: DomainCreate,
    superadmin: User = Depends(require_superadmin_user),
    db: AsyncSession = Depends(get_db)
):
    clean_name = data.name.strip().lower()
    res = await db.execute(select(Domain).where(Domain.name == clean_name))
    if res.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Domain already exists")

    domain = Domain(name=clean_name, root_redirect_url=data.root_redirect_url)
    db.add(domain)
    await db.commit()
    await db.refresh(domain)
    return {"id": domain.id, "name": domain.name}
