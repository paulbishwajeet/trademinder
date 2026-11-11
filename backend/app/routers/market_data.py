"""Market data provider status (admin only) — drives the SPA's Schwab expiry banner."""
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.deps import require_admin
from app.models.user import User
from app.schemas.market_data import MarketDataStatusResponse
from app.services.market_data import compute_state, get_market_data

router = APIRouter(prefix="/api/market-data", tags=["market-data"])


@router.get("/status", response_model=MarketDataStatusResponse)
async def market_data_status(user: User = Depends(require_admin)):
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
