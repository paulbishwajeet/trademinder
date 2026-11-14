"""Schwab token sync: one Schwab grant, owned by production.

A new Schwab login invalidates the previous refresh token, so only production reconnects and refreshes. Dev runs
as a "token follower" (SCHWAB_TOKEN_SYNC_URL + SCHWAB_TOKEN_SYNC_SECRET) and pulls the current pair from
production's export endpoint (POST /api/market-data/sync/tokens, secret header only) instead of calling Schwab's
token endpoint. This module is the HTTP side of that pull and the secret check; the provider
(app.services.schwab_client) decides when to pull and owns the lock, rate limit and offline state.

Never log or return tokens, the secret, or response bodies.
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import httpx

from app.services.schwab_oauth import TokenSet

HEADER = "X-Token-Sync-Secret"
EXPORT_PATH = "/api/market-data/sync/tokens"
PULL_TIMEOUT_SECONDS = 15

# Pull outcomes (status endpoint, logs). Short codes only.
OK = "ok"
UNREACHABLE = "unreachable"            # connection error, timeout, or an unexpected 5xx
UPSTREAM_OFFLINE = "upstream_offline"  # production's own Schwab connection is offline
UNAUTHORIZED = "unauthorized"          # production rejected the secret
DISABLED = "disabled"                  # production has no export (secret not set there): 404
INVALID_RESPONSE = "invalid_response"  # 200 without a usable token pair

OUTCOME_REASONS = {
    UNREACHABLE: "Production unreachable for Schwab token sync",
    UPSTREAM_OFFLINE: "Production's Schwab connection is offline — reconnect in production",
    UNAUTHORIZED: "Production rejected the token sync secret (SCHWAB_TOKEN_SYNC_SECRET differs)",
    DISABLED: "Token sync is not enabled on production (set SCHWAB_TOKEN_SYNC_SECRET there)",
    INVALID_RESPONSE: "Production returned an unusable token response",
}


@dataclass(frozen=True, repr=False)
class PullResult:
    outcome: str
    tokens: Optional[TokenSet] = None
    http_status: Optional[int] = None


def secret_matches(configured: str, presented: Optional[str]) -> bool:
    """Constant-time comparison; False when either side is empty."""
    if not configured or not presented:
        return False
    return hmac.compare_digest(configured.encode(), presented.encode())


def _parse_time(value) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("naive datetime")
    return parsed


def pull(base_url: str, secret: str) -> PullResult:
    """One HTTPS call to production's export endpoint. Certificate verification is on; redirects are not
    followed. Never raises for HTTP or network failures: the outcome says what happened."""
    try:
        resp = httpx.post(
            f"{base_url}{EXPORT_PATH}",
            headers={HEADER: secret},
            timeout=PULL_TIMEOUT_SECONDS,
            follow_redirects=False,
        )
    except httpx.HTTPError:
        return PullResult(UNREACHABLE)

    if resp.status_code == 200:
        try:
            body = resp.json()
            tokens = TokenSet(
                access_token=str(body["access_token"]),
                refresh_token=str(body["refresh_token"]),
                access_expires_at=_parse_time(body["access_expires_at"]),
                refresh_expires_at=_parse_time(body["refresh_expires_at"]),
            )
        except Exception:
            return PullResult(INVALID_RESPONSE, http_status=200)
        if not tokens.access_token or not tokens.refresh_token:
            return PullResult(INVALID_RESPONSE, http_status=200)
        return PullResult(OK, tokens=tokens, http_status=200)

    code = None
    try:
        body = resp.json()
        code = body.get("code") if isinstance(body, dict) else None
    except Exception:
        pass
    if resp.status_code == 503 and code == UPSTREAM_OFFLINE:
        return PullResult(UPSTREAM_OFFLINE, http_status=503)
    if resp.status_code == 401:
        return PullResult(UNAUTHORIZED, http_status=401)
    if resp.status_code == 404:
        return PullResult(DISABLED, http_status=404)
    if resp.status_code >= 500:
        return PullResult(UNREACHABLE, http_status=resp.status_code)
    return PullResult(INVALID_RESPONSE, http_status=resp.status_code)
