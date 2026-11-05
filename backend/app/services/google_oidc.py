"""Google sign-in: OIDC authorization code flow with PKCE, state and nonce.

Google is only an identity check — after this the backend issues its own session. Scopes are
openid, email and profile only. The ID token is verified with google-auth (signature, issuer,
audience, expiry); the nonce and email_verified are checked here.
"""
import base64
import hashlib
import secrets
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User
from app.services.user_admin import activate

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
ISSUERS = ("accounts.google.com", "https://accounts.google.com")
CALLBACK_PATH = "/api/auth/google/callback"


class SignInRefused(Exception):
    """Sign-in can't proceed; `code` goes to the SPA's /signin?error=…"""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def redirect_uri() -> str:
    return f"{settings.public_base_url}{CALLBACK_PATH}"


def start_login(next_path: str) -> tuple[str, dict]:
    """(Google authorization URL, state payload to keep in the signed cookie)."""
    if not settings.google_client_id:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return f"{AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}", {
        "state": state, "nonce": nonce, "verifier": verifier, "next": next_path,
    }


async def exchange_code(code: str, verifier: str) -> str:
    """Authorization code → ID token (server to server)."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(TOKEN_ENDPOINT, data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        })
    if resp.status_code != 200 or "id_token" not in resp.json():
        raise SignInRefused("google_exchange_failed")
    return resp.json()["id_token"]


def verify_id_token(id_token: str) -> dict:
    """Signature, issuer, audience and expiry via google-auth. Mocked in tests."""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    claims = google_id_token.verify_oauth2_token(id_token, google_requests.Request(), settings.google_client_id)
    if claims.get("iss") not in ISSUERS:
        raise ValueError("wrong issuer")
    return claims


def check_claims(claims: dict, nonce: str) -> dict:
    if claims.get("nonce") != nonce:
        raise SignInRefused("nonce_mismatch")
    if claims.get("email_verified") is not True or not claims.get("email"):
        raise SignInRefused("email_not_verified")
    if not claims.get("sub"):
        raise SignInRefused("no_subject")
    return claims


async def sign_in(db: AsyncSession, claims: dict) -> User:
    """Apply the sign-in rules, in order:
    1. match by Google subject;
    2. else an existing row with this email and no subject yet (seeded owner / invite) — bind the subject;
    3. else create a pending user.
    Disabled users are refused. The subject, once bound, is never replaced."""
    subject = claims["sub"]
    email = claims["email"].strip()
    name = (claims.get("name") or email.split("@")[0])[:100]

    user = (await db.execute(select(User).where(User.external_subject == subject))).scalar_one_or_none()
    if user is None:
        by_email = (await db.execute(
            select(User).where(func.lower(User.email) == email.lower())
        )).scalar_one_or_none()
        if by_email is not None:
            if by_email.external_subject is not None:
                # Same email, different Google account: never rebind.
                raise SignInRefused("email_linked_to_another_google_account")
            by_email.external_subject = subject
            user = by_email
            if user.status == "active":
                await activate(db, user)  # seeds categories for a first-time invited user
        else:
            user = User(email=email, display_name=name, role="user", status="pending", external_subject=subject)
            db.add(user)
    if user.status == "disabled":
        await db.rollback()
        raise SignInRefused("disabled")
    if not user.display_name or user.display_name == user.email.split("@")[0]:
        user.display_name = name
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)
    return user


async def complete_login(db: AsyncSession, code: Optional[str], state: Optional[str], saved: Optional[dict]) -> tuple[User, str]:
    """Callback: check state, exchange the code, verify the token, apply the rules. → (user, next)."""
    if not saved or not code or not state or state != saved.get("state"):
        raise SignInRefused("invalid_state")
    id_token = await exchange_code(code, saved["verifier"])
    try:
        claims = verify_id_token(id_token)
    except ValueError:
        raise SignInRefused("invalid_id_token")
    check_claims(claims, saved["nonce"])
    return await sign_in(db, claims), saved.get("next") or "/"
