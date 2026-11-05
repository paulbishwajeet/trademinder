from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.services.auth import SESSION_COOKIE, cookie_kwargs, resolve_extension_token, resolve_session


async def get_signed_in_user(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> User:
    """Who is calling: a session cookie (the SPA) or a bearer extension token (the extension).

    401 when there are no valid credentials, 403 for a disabled user. Pending users pass — only
    `/api/me` uses this directly; everything else goes through get_current_user.
    """
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        user = await resolve_extension_token(db, auth[7:].strip())
        if user is None:
            raise HTTPException(status_code=401, detail="Not signed in")
        request.state.auth_kind = "token"
    else:
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            raise HTTPException(status_code=401, detail="Not signed in")
        user, slid = await resolve_session(db, token)
        if user is None:
            raise HTTPException(status_code=401, detail="Not signed in")
        if slid:  # sliding expiry: re-issue the cookie with a fresh lifetime
            response.set_cookie(SESSION_COOKIE, token, max_age=settings.session_days * 86400, **cookie_kwargs())
        request.state.auth_kind = "session"
    if user.status == "disabled":
        raise HTTPException(status_code=403, detail="Account disabled")
    # Hand routers a detached snapshot (as before Part 5): services may expire_all() their session,
    # and the caller's identity must not be lazily reloaded or written back through it.
    db.expunge(user)
    return user


async def get_current_user(user: User = Depends(get_signed_in_user)) -> User:
    """The single current-user seam. Every router touching user-owned data depends on this.
    Only active users pass; a pending user gets 403 until an admin approves them."""
    if user.status != "active":
        raise HTTPException(status_code=403, detail="Waiting for approval")
    return user


async def require_session_user(request: Request, user: User = Depends(get_current_user)) -> User:
    """Routes only a signed-in browser may call (minting extension tokens), never a bearer token."""
    if getattr(request.state, "auth_kind", None) != "session":
        raise HTTPException(status_code=403, detail="Sign in to the portal to do this")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Admin-only routes (an extra permission on a normal, active account)."""
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
