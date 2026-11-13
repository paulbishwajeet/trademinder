# backend/app/services/schwab_oauth.py
"""Schwab OAuth primitives shared by the in-app reconnect and scripts/schwab_auth.py.

Standalone on purpose: stdlib, httpx and asyncpg only — never app.config or other app modules — so the CLI
script keeps running with nothing but SCHWAB_APP_KEY, SCHWAB_APP_SECRET and DATABASE_URL from .env.

Never log tokens, authorization codes or redirect URLs from here.
"""
import base64
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg
import httpx

AUTHORIZE_URL = "https://api.schwabapi.com/v1/oauth/authorize"
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
# The one callback registered on the Schwab app. Nothing listens there: after login the browser fails to load
# it and the user copies the address (which carries the code) instead.
REDIRECT_URI = "https://127.0.0.1:8765/callback"
# Fixed life of a refresh token from the original authorization (refreshing the access token doesn't extend it).
REFRESH_TOKEN_DAYS = 7

MAX_REDIRECT_URL_LENGTH = 4096


@dataclass(frozen=True, repr=False)
class TokenSet:
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime

    def __repr__(self) -> str:  # never print the tokens themselves
        return f"TokenSet(access_expires_at={self.access_expires_at!r}, refresh_expires_at={self.refresh_expires_at!r})"


class RedirectUrlError(Exception):
    """The pasted address isn't a usable Schwab redirect. `reason`: bad_url | authorization_denied |
    missing_code | missing_state."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class CodeRejected(Exception):
    """Schwab refused the authorization code (expired, already used, or not ours)."""

    def __init__(self, status: int, error: Optional[str]):
        super().__init__(f"HTTP {status} {error or ''}".strip())
        self.status = status
        self.error = error


class SchwabUnreachable(Exception):
    """Network error, timeout, 5xx or an unreadable token response."""


def authorize_url(app_key: str, state: Optional[str] = None) -> str:
    """The Schwab login URL. Without `state` this is exactly the URL the CLI has always used."""
    params = {"response_type": "code", "client_id": app_key, "redirect_uri": REDIRECT_URI}
    if state is not None:
        params["state"] = state
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def parse_redirect_url(url: str, *, require_state: bool = True) -> tuple[str, Optional[str]]:
    """(code, state) from the address the browser landed on after the Schwab login.

    The scheme, host, port and path must be the registered callback. The code is URL-decoded (Schwab codes
    contain an encoded '@'), as the CLI always did."""
    url = (url or "").strip()
    if not url or len(url) > MAX_REDIRECT_URL_LENGTH:
        raise RedirectUrlError("bad_url")
    try:
        parsed = urllib.parse.urlparse(url)
        expected = urllib.parse.urlparse(REDIRECT_URI)
        same_place = (
            parsed.scheme.lower() == expected.scheme
            and (parsed.hostname or "").lower() == expected.hostname
            and parsed.port == expected.port
            and parsed.path.rstrip("/") == expected.path
        )
    except ValueError:  # e.g. a non-numeric port
        raise RedirectUrlError("bad_url")
    if not same_place:
        raise RedirectUrlError("bad_url")

    params = urllib.parse.parse_qs(parsed.query)
    if "error" in params:
        raise RedirectUrlError("authorization_denied")
    code = (params.get("code") or [""])[0]
    if not code:
        raise RedirectUrlError("missing_code")
    state = (params.get("state") or [None])[0]
    if require_state and not state:
        raise RedirectUrlError("missing_state")
    # parse_qs already turned %40 into '@'; unquote again exactly like the CLI (a no-op on a decoded code).
    return urllib.parse.unquote(code), state


def exchange_code(app_key: str, app_secret: str, code: str, *, timeout: float = 15) -> TokenSet:
    """Swap an authorization code for tokens (the CLI's exact request). Refresh expiry = now + 7 days."""
    creds = base64.b64encode(f"{app_key}:{app_secret}".encode()).decode()
    try:
        resp = httpx.post(
            TOKEN_URL,
            headers={"Authorization": f"Basic {creds}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise SchwabUnreachable(type(exc).__name__) from None
    if resp.status_code in (400, 401, 403):
        raise CodeRejected(resp.status_code, _error_field(resp))
    if resp.status_code != 200:
        raise SchwabUnreachable(f"HTTP {resp.status_code}")
    try:
        data = resp.json()
        now = datetime.now(timezone.utc)
        return TokenSet(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            access_expires_at=now + timedelta(seconds=data["expires_in"]),
            refresh_expires_at=now + timedelta(days=REFRESH_TOKEN_DAYS),
        )
    except (ValueError, KeyError, TypeError):
        raise SchwabUnreachable("unreadable token response") from None


def _error_field(resp: httpx.Response) -> Optional[str]:
    """Schwab's short OAuth error name (e.g. invalid_grant) — never the whole body."""
    try:
        body = resp.json()
    except ValueError:
        return None
    error = body.get("error") if isinstance(body, dict) else None
    return error if isinstance(error, str) and error.isidentifier() and len(error) <= 40 else None


async def store_tokens(database_url: str, tokens: TokenSet) -> None:
    """Upsert the single schwab_tokens row (id=1); updated_at = NOW() is what the provider watches."""
    conn = await asyncpg.connect(database_url.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        await conn.execute("""
            INSERT INTO schwab_tokens (id, access_token, refresh_token, access_expires_at, refresh_expires_at, updated_at)
            VALUES (1, $1, $2, $3, $4, NOW())
            ON CONFLICT (id) DO UPDATE SET
                access_token = EXCLUDED.access_token,
                refresh_token = EXCLUDED.refresh_token,
                access_expires_at = EXCLUDED.access_expires_at,
                refresh_expires_at = EXCLUDED.refresh_expires_at,
                updated_at = NOW()
        """, tokens.access_token, tokens.refresh_token, tokens.access_expires_at, tokens.refresh_expires_at)
    finally:
        await conn.close()
