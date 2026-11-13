"""Market data provider status and the in-app Schwab reconnect (admin only) — drive the SPA's Schwab banner and
Settings → Market data."""
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.deps import require_admin
from app.models.user import User
from app.schemas.market_data import (
    MarketDataStatusResponse, ReconnectCompleteRequest, ReconnectStartResponse,
)
from app.services import schwab_reconnect
from app.services.market_data import compute_state, get_market_data

router = APIRouter(prefix="/api/market-data", tags=["market-data"])


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
    )


def _reconnect_error(exc: schwab_reconnect.ReconnectError) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content={"detail": exc.message, "code": exc.code})


@router.get("/status", response_model=MarketDataStatusResponse)
async def market_data_status(user: User = Depends(require_admin)):
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
