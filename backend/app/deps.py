from fastapi import Depends, HTTPException, Response
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User

_owner: User | None = None


async def get_current_user(db: AsyncSession = Depends(get_db)) -> User:
    """The single current-user seam. Every router touching user-owned data depends on this.

    For now it returns the owner seeded by migration 015 (looked up once by OWNER_EMAIL, then cached
    in memory). Part 5 replaces this body with session / API-token resolution; nothing else changes.
    """
    global _owner
    if _owner is None:
        email = (settings.owner_email or "").strip().lower()
        if not email:
            raise HTTPException(status_code=500, detail="OWNER_EMAIL is not configured")
        user = (await db.execute(select(User).where(func.lower(User.email) == email))).scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=500, detail="Owner user not found — run `alembic upgrade head`")
        db.expunge(user)  # detached snapshot; only user.id is read downstream
        _owner = user
    return _owner


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Admin-only routes. Goes through the current-user seam, so Part 5's real login applies too."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user


MARKET_DATA_HEADER = "X-Market-Data-Offline"


async def market_data_flag(response: Response) -> bool:
    """For endpoints that mix database rows with market-derived fields: sets the response-level
    X-Market-Data-Offline header and tells the endpoint whether to blank those fields."""
    from app.services.market_data import market_data_offline_now

    offline = await market_data_offline_now()
    response.headers[MARKET_DATA_HEADER] = "true" if offline else "false"
    return offline
