"""Sign in with Google, logout. These routes (and /health) are the only ones outside the seam."""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.services import auth as auth_service
from app.services import google_oidc

router = APIRouter(prefix="/api/auth", tags=["auth"])

STATE_COOKIE_PATH = "/api/auth"


@router.get("/google/login")
async def google_login(next: Optional[str] = Query(None)):
    url, state = google_oidc.start_login(auth_service.safe_next(next))
    resp = RedirectResponse(url, status_code=302)
    resp.set_cookie(
        auth_service.LOGIN_STATE_COOKIE, auth_service.sign_state(state),
        max_age=auth_service.LOGIN_STATE_TTL_SECONDS, httponly=True,
        secure=settings.secure_cookies, samesite="lax", path=STATE_COOKIE_PATH,
    )
    return resp


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    saved = auth_service.read_state(request.cookies.get(auth_service.LOGIN_STATE_COOKIE))

    def back_to_signin(code_: str) -> RedirectResponse:
        resp = RedirectResponse(f"/signin?error={code_}", status_code=302)
        resp.delete_cookie(auth_service.LOGIN_STATE_COOKIE, path=STATE_COOKIE_PATH)
        return resp

    if error:
        return back_to_signin("google_" + error.replace("&", "")[:40])
    try:
        user, next_path = await google_oidc.complete_login(db, code, state, saved)
    except google_oidc.SignInRefused as refused:
        return back_to_signin(refused.code)

    token = await auth_service.create_session(db, user, request.headers.get("user-agent"))
    target = "/waiting" if user.status == "pending" else auth_service.safe_next(next_path)
    resp = RedirectResponse(target, status_code=302)
    resp.delete_cookie(auth_service.LOGIN_STATE_COOKIE, path=STATE_COOKIE_PATH)  # single use
    resp.set_cookie(
        auth_service.SESSION_COOKIE, token, max_age=settings.session_days * 86400, **auth_service.cookie_kwargs(),
    )
    return resp


@router.post("/logout", status_code=204)
async def logout(request: Request, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(auth_service.SESSION_COOKIE)
    if token:
        await auth_service.delete_session(db, token)
    resp = Response(status_code=204)
    resp.delete_cookie(auth_service.SESSION_COOKIE, path="/")
    return resp
