"""Sessions, extension tokens and the signed login-state cookie.

Every credential is a random token whose SHA-256 is the only thing stored. Sessions slide (at most
once a minute); extension tokens record last use (at most once a minute) and are revoked, not deleted.
"""
import base64
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.auth import ExtensionToken, UserSession
from app.models.user import User

SESSION_COOKIE = "tm_session"
LOGIN_STATE_COOKIE = "tm_login"
LOGIN_STATE_TTL_SECONDS = 600
TOUCH_INTERVAL = timedelta(minutes=1)
EXTENSION_TOKEN_PREFIX = "tme_"
_EXTENSION_ID = re.compile(r"[a-p]{32}")


def new_token(prefix: str = "") -> str:
    return prefix + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── signed login-state cookie (PKCE verifier, state, nonce, next) ───────────

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def sign_state(payload: dict) -> str:
    body = _b64(json.dumps({**payload, "exp": int(time.time()) + LOGIN_STATE_TTL_SECONDS}).encode())
    mac = hmac.new(settings.auth_state_secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(mac)}"


def read_state(value: Optional[str]) -> Optional[dict]:
    """The payload if the signature is valid and it hasn't expired; otherwise None."""
    if not value or "." not in value:
        return None
    body, mac = value.rsplit(".", 1)
    expected = hmac.new(settings.auth_state_secret.encode(), body.encode(), hashlib.sha256).digest()
    try:
        if not hmac.compare_digest(_unb64(mac), expected):
            return None
        payload = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload


def safe_next(value: Optional[str]) -> str:
    """Only same-site relative paths ('/x', never '//x' or 'https://x'); default '/'."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    return value


# ── sessions ────────────────────────────────────────────────────────────────

async def create_session(db: AsyncSession, user: User, user_agent: Optional[str]) -> str:
    token = new_token()
    now = _now()
    db.add(UserSession(
        token_hash=hash_token(token), user_id=user.id, created_at=now, last_seen_at=now,
        expires_at=now + timedelta(days=settings.session_days),
        user_agent=(user_agent or "")[:300] or None,
    ))
    await db.commit()
    return token


async def resolve_session(db: AsyncSession, token: str) -> tuple[Optional[User], bool]:
    """(user, slid) for a valid session token, else (None, False). Expired rows are deleted.
    A session slides — new expiry, cookie re-issued by the caller — at most once a minute."""
    session = await db.get(UserSession, hash_token(token))
    if session is None:
        return None, False
    now = _now()
    if session.expires_at <= now:
        await db.delete(session)
        await db.commit()
        return None, False
    user = await db.get(User, session.user_id)
    if user is None:
        return None, False
    slid = False
    if now - session.last_seen_at >= TOUCH_INTERVAL:
        session.last_seen_at = now
        session.expires_at = now + timedelta(days=settings.session_days)
        await db.commit()
        slid = True
    return user, slid


async def delete_session(db: AsyncSession, token: str) -> None:
    await db.execute(delete(UserSession).where(UserSession.token_hash == hash_token(token)))
    await db.commit()


async def kill_credentials(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Disabling a user: every session ends and every extension token is revoked, immediately."""
    await db.execute(delete(UserSession).where(UserSession.user_id == user_id))
    await db.execute(
        update(ExtensionToken)
        .where(ExtensionToken.user_id == user_id, ExtensionToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


def cookie_kwargs() -> dict:
    return {
        "httponly": True,
        "secure": settings.secure_cookies,
        "samesite": "lax",
        "path": "/",
    }


# ── extension tokens ────────────────────────────────────────────────────────

def validate_extension_redirect(redirect_uri: str) -> str:
    """The only acceptable target: exactly https://<allow-listed id>.chromiumapp.org/ — what
    chrome.identity.getRedirectURL() returns. Anything else is rejected."""
    match = re.fullmatch(r"https://([a-p]{32})\.chromiumapp\.org/", redirect_uri or "")
    if not match or match.group(1) not in settings.extension_id_list:
        raise HTTPException(status_code=400, detail="This extension is not allowed to connect")
    return redirect_uri


async def create_extension_token(db: AsyncSession, user: User, device_name: str) -> str:
    token = new_token(EXTENSION_TOKEN_PREFIX)
    db.add(ExtensionToken(
        user_id=user.id, device_name=device_name.strip()[:100] or "Chrome extension",
        token_hash=hash_token(token), token_prefix=token[: len(EXTENSION_TOKEN_PREFIX) + 4],
    ))
    await db.commit()
    return token


async def resolve_extension_token(db: AsyncSession, token: str) -> Optional[User]:
    row = (await db.execute(
        select(ExtensionToken).where(ExtensionToken.token_hash == hash_token(token))
    )).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return None
    user = await db.get(User, row.user_id)
    now = _now()
    if user is not None and (row.last_used_at is None or now - row.last_used_at >= TOUCH_INTERVAL):
        row.last_used_at = now
        await db.commit()
    return user


async def list_extension_tokens(db: AsyncSession, user: User) -> list[ExtensionToken]:
    stmt = (
        select(ExtensionToken)
        .where(ExtensionToken.user_id == user.id, ExtensionToken.revoked_at.is_(None))
        .order_by(ExtensionToken.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def revoke_extension_token(db: AsyncSession, user: User, token_id: uuid.UUID) -> None:
    row = await db.get(ExtensionToken, token_id)
    if row is None or row.user_id != user.id or row.revoked_at is not None:
        raise HTTPException(status_code=404, detail="Token not found")
    row.revoked_at = _now()
    await db.commit()


async def revoke_extension_token_value(db: AsyncSession, token: str) -> None:
    await db.execute(
        update(ExtensionToken)
        .where(ExtensionToken.token_hash == hash_token(token), ExtensionToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    await db.commit()
