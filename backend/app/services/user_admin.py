"""User lifecycle (activation, invites, approvals) and the admin guards.

The admin manages accounts only: nothing here reads trading data.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.user import User
from app.services.auth import kill_credentials

# The category library every user starts with (same set the owner was seeded with).
DEFAULT_CATEGORIES = [
    ("WHEEL", "#3B82F6", "🔄"), ("SWING", "#06B6D4", "📈"), ("HOLD", "#10B981", "🌱"),
    ("LEAP", "#8B5CF6", "🚀"), ("PUT_SPREAD", "#F59E0B", "📉"), ("CALL_SPREAD", "#F97316", "📈"),
    ("IRON_CONDOR", "#EF4444", "🦅"), ("IRON_BUTTERFLY", "#EC4899", "🦋"), ("SKIP", "#6B7280", "⏭"),
    ("HOPS", "#84CC16", "🌿"), ("BUY_WRITE", "#14B8A6", "📝"), ("SPECULATIVE", "#D946EF", "🎲"),
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def seed_default_categories(db: AsyncSession, user: User) -> None:
    """Give a user the default category library unless they already have categories."""
    if await db.scalar(select(exists().where(Category.user_id == user.id))):
        return
    for position, (name, color, icon) in enumerate(DEFAULT_CATEGORIES, start=1):
        db.add(Category(user_id=user.id, name=name, color=color, icon=icon, is_system=True, sort_order=position))


async def activate(db: AsyncSession, user: User, by: Optional[User] = None) -> None:
    user.status = "active"
    if by is not None:
        user.approved_by = by.id
        user.approved_at = _now()
    await seed_default_categories(db, user)


async def _active_admin_count(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.status == "active"))


async def _get_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


async def _guard_removal_of_admin(db: AsyncSession, actor: User, target: User, action: str) -> None:
    """No admin can disable/demote themselves, and the last active admin can't be removed."""
    if target.id == actor.id:
        raise HTTPException(status_code=400, detail=f"You can't {action} yourself")
    if target.role == "admin" and target.status == "active" and await _active_admin_count(db) <= 1:
        raise HTTPException(status_code=400, detail=f"Can't {action} the last active admin")


async def list_users(db: AsyncSession, status: Optional[str]) -> list[User]:
    stmt = select(User).order_by(User.created_at)
    if status:
        stmt = stmt.where(User.status == status)
    return list((await db.execute(stmt)).scalars().all())


async def invite(db: AsyncSession, actor: User, email: str, role: str) -> User:
    email = email.strip()
    if await db.scalar(select(exists().where(func.lower(User.email) == email.lower()))):
        raise HTTPException(status_code=409, detail="A user with this email already exists")
    user = User(email=email, display_name=email.split("@")[0], role=role, status="active", invited_by=actor.id)
    db.add(user)
    await db.flush()
    await activate(db, user, by=actor)  # pre-approved: active on first Google sign-in
    await db.commit()
    return user


async def approve(db: AsyncSession, actor: User, user_id: uuid.UUID) -> User:
    user = await _get_user(db, user_id)
    if user.status != "pending":
        raise HTTPException(status_code=400, detail="Only pending users can be approved")
    await activate(db, user, by=actor)
    await db.commit()
    return user


async def enable(db: AsyncSession, actor: User, user_id: uuid.UUID) -> User:
    user = await _get_user(db, user_id)
    if user.status != "disabled":
        raise HTTPException(status_code=400, detail="Only disabled users can be re-enabled")
    await activate(db, user, by=actor)
    await db.commit()
    return user


async def disable(db: AsyncSession, actor: User, user_id: uuid.UUID, action: str = "disable") -> User:
    user = await _get_user(db, user_id)
    if action == "reject" and user.status != "pending":
        raise HTTPException(status_code=400, detail="Only pending users can be rejected")
    await _guard_removal_of_admin(db, actor, user, action)
    user.status = "disabled"
    await kill_credentials(db, user.id)
    await db.commit()
    return user


async def set_role(db: AsyncSession, actor: User, user_id: uuid.UUID, role: str) -> User:
    user = await _get_user(db, user_id)
    if role == user.role:
        return user
    if role == "user":
        await _guard_removal_of_admin(db, actor, user, "demote")
    user.role = role
    await db.commit()
    return user
