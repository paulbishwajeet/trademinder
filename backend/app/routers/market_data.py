"""Market data provider status and the in-app Schwab reconnect (admin only) — drive the SPA's Schwab banner and
Settings → Market data. Plus the token sync: production's secret-only export (`sync_router`, mounted outside the
session seam) and the follower's admin "pull now"."""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse

from app.config import settings
from app.deps import require_admin
from app.models.user import User
from app.schemas.market_data import (
    MarketDataStatusResponse, ReconnectCompleteRequest, ReconnectStartResponse, TokenExportResponse,
)
from app.services import schwab_reconnect, schwab_token_sync
from app.services.market_data import PullRateLimited, SchwabAPIError, compute_state, get_market_data
from app.services.market_data_errors import MarketDataUnavailable

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/market-data", tags=["market-data"])
# Server to server only: authenticated by the sync secret header, never by a session or extension token.
# app.main includes it WITHOUT the get_current_user seam.
sync_router = APIRouter(prefix="/api/market-data/sync", tags=["market-data"], include_in_schema=False)


async def _status_response() -> MarketDataStatusResponse:
    provider = get_market_data()
    # Provider calls are synchronous (and may read the token row): keep them off the event loop.
    status = await asyncio.get_running_loop().run_in_executor(None, provider.status)
    now = datetime.now(timezone.utc)
    hours = None
    if status.refresh_expires_at is not None:
        hours = round((status.refresh_expires_at - now).total_seconds() / 3600, 1)
    return MarketDataStatusResponse(
        provider=status.provider,
        state=compute_state(status.refresh_expires_at, status.offline, now),
        refresh_expires_at=status.refresh_expires_at,
        hours_remaining=hours,
        last_success_at=status.last_success_at,
        last_error=status.last_error,
        token_source=status.token_source,
        last_pull_at=status.last_pull_at,
        last_pull_outcome=status.last_pull_outcome,
    )


def _reconnect_error(exc: schwab_reconnect.ReconnectError) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content={"detail": exc.message, "code": exc.code})


@router.get("/status", response_model=MarketDataStatusResponse)
async def market_data_status(user: User = Depends(require_admin)):
    return await _status_response()


@router.post("/sync/pull", response_model=MarketDataStatusResponse)
async def pull_now(user: User = Depends(require_admin)):
    """Follower only: pull the token pair from production now (≤ once a minute). The outcome is in the status."""
    if not settings.token_follower:
        return JSONResponse(status_code=409, content={
            "detail": "This server refreshes its own Schwab tokens; there is nothing to pull.", "code": "not_follower",
        })
    try:
        await asyncio.get_running_loop().run_in_executor(None, get_market_data().pull_now)
    except PullRateLimited as exc:
        return JSONResponse(status_code=429, content={
            "detail": f"Tokens were pulled less than a minute ago. Try again in {exc.retry_after_seconds} s.",
            "code": "pull_rate_limited", "retry_after_seconds": exc.retry_after_seconds,
        })
    return await _status_response()


@router.post("/reconnect/start", response_model=ReconnectStartResponse)
async def reconnect_start(user: User = Depends(require_admin)):
    try:
        url, expires_at = schwab_reconnect.start(user.id)
    except schwab_reconnect.ReconnectError as exc:
        return _reconnect_error(exc)
    return ReconnectStartResponse(authorize_url=url, state_expires_at=expires_at)


@router.post("/reconnect/complete", response_model=MarketDataStatusResponse)
async def reconnect_complete(body: ReconnectCompleteRequest, user: User = Depends(require_admin)):
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, schwab_reconnect.complete, user.id, body.redirect_url)
    except schwab_reconnect.ReconnectError as exc:
        return _reconnect_error(exc)
    return await _status_response()


@sync_router.post("/tokens", response_model=TokenExportResponse)
async def export_tokens(x_token_sync_secret: Optional[str] = Header(default=None)):
    """Production → token follower. 404 unless SCHWAB_TOKEN_SYNC_SECRET is set here (and this isn't a follower);
    401 for a missing or wrong secret; 503 upstream_offline when this server's Schwab connection is offline.
    Production stays the only refresher: the provider refreshes under its own lock if < 10 minutes are left."""
    if not settings.token_export_enabled:
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    if not schwab_token_sync.secret_matches(settings.schwab_token_sync_secret, x_token_sync_secret):
        log.warning("Schwab token export: rejected (bad or missing secret)")
        return JSONResponse(status_code=401, content={"detail": "Unauthorized", "code": "sync_unauthorized"})
    try:
        tokens = await asyncio.get_running_loop().run_in_executor(None, get_market_data().export_tokens)
    except MarketDataUnavailable:
        log.warning("Schwab token export: upstream offline")
        return JSONResponse(status_code=503, content={
            "detail": "Production's Schwab connection is offline", "code": schwab_token_sync.UPSTREAM_OFFLINE,
        })
    except SchwabAPIError:
        log.warning("Schwab token export: refresh failed")
        return JSONResponse(status_code=502, content={"detail": "Token refresh failed", "code": "upstream_error"})
    log.warning("Schwab token export: ok; access token expires %s", tokens.access_expires_at.isoformat(timespec="seconds"))
    body = TokenExportResponse(
        access_token=tokens.access_token, refresh_token=tokens.refresh_token,
        access_expires_at=tokens.access_expires_at, refresh_expires_at=tokens.refresh_expires_at,
    )
    return JSONResponse(content=body.model_dump(mode="json"), headers={"Cache-Control": "no-store"})
