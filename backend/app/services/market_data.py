"""Market data provider boundary.

Every market data call in the app goes through `get_market_data()`, which returns the configured
provider (settings.market_data_provider; only "schwab" today). The interface keeps today's Schwab
return shapes — normalizing to provider-neutral shapes is deferred. yfinance (earnings calendar,
LEAPS scanner) is deliberately not behind this interface.

Market data is app-level and shared by all users.

Errors:
- `MarketDataUnavailable` — the provider is offline (refresh token expired, the refresh grant was
  rejected, no tokens, or not configured). The whole provider is down until someone re-runs
  scripts/schwab_auth.py; the provider stops calling upstream until the token row changes.
- `SchwabAPIError` — a per-call / per-ticker failure (e.g. a non-optionable symbol). Re-exported
  here so callers never import the Schwab module directly. It is NOT a subclass of
  MarketDataUnavailable and vice versa, so per-ticker handlers never swallow "offline".
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional, Protocol

import pandas as pd

from app.config import settings
from app.services.market_data_errors import MarketDataUnavailable
# Re-exported so callers catch per-ticker failures without importing the Schwab module.
from app.services.schwab_client import PullRateLimited, SchwabAPIError

if TYPE_CHECKING:
    from app.services.schwab_oauth import TokenSet


# Banner thresholds on the refresh token's remaining life (hours).
EXPIRING_HOURS = 72
CRITICAL_HOURS = 24

STATE_OK = "ok"
STATE_EXPIRING = "expiring"
STATE_CRITICAL = "critical"
STATE_OFFLINE = "offline"


def compute_state(refresh_expires_at: Optional[datetime], offline: bool, now: Optional[datetime] = None) -> str:
    """ok (> 72h left) · expiring (24h–72h) · critical (< 24h) · offline (expired, refresh failing,
    no tokens). Boundaries: exactly 72h is expiring, exactly 24h is expiring, 0h or less is offline."""
    if offline or refresh_expires_at is None:
        return STATE_OFFLINE
    now = now or datetime.now(timezone.utc)
    hours = (refresh_expires_at - now).total_seconds() / 3600
    if hours <= 0:
        return STATE_OFFLINE
    if hours < CRITICAL_HOURS:
        return STATE_CRITICAL
    if hours <= EXPIRING_HOURS:
        return STATE_EXPIRING
    return STATE_OK


@dataclass
class ProviderStatus:
    """Raw provider state; the status endpoint derives the banner state from it."""
    provider: str
    offline: bool
    refresh_expires_at: Optional[datetime]
    last_success_at: Optional[datetime]
    last_error: Optional[str]
    # "self" (this environment refreshes) or "production" (token follower; pulls from production)
    token_source: str = "self"
    last_pull_at: Optional[datetime] = None
    last_pull_outcome: Optional[str] = None


class MarketDataProvider(Protocol):
    """The four market data calls the app makes, plus status. Methods are synchronous (callers run
    them in a thread executor) and raise MarketDataUnavailable when the provider is offline."""

    name: str

    def get_quotes(self, tickers: list[str]) -> dict[str, dict]: ...

    def get_price_history(
        self, ticker: str, period_type: str, period: int, frequency_type: str, frequency: int,
    ) -> pd.DataFrame: ...

    def get_option_chain(
        self,
        ticker: str,
        contract_type: str = "CALL",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        strike_count: Optional[int] = None,
    ) -> dict: ...

    def get_instrument_fundamentals(self, ticker: str) -> dict: ...

    def is_offline(self) -> bool:
        """No I/O: True while the provider is known to be offline."""
        ...

    def refresh_offline_state(self) -> bool:
        """May read local state (never the upstream API); returns is_offline() afterwards."""
        ...

    def status(self) -> ProviderStatus: ...

    def export_tokens(self) -> "TokenSet":
        """Production: the current token pair with ≥ 10 minutes of access-token life (refreshing under the
        provider's own lock if needed), for a token follower. Raises MarketDataUnavailable when offline."""
        ...

    def pull_now(self) -> None:
        """Token follower: pull from production now. Raises PullRateLimited inside the one-minute window."""
        ...


SUPPORTED_PROVIDERS = ("schwab",)

_provider: Optional[MarketDataProvider] = None
_provider_lock = threading.Lock()


def get_market_data() -> MarketDataProvider:
    """The configured provider (a process-wide singleton)."""
    global _provider
    if _provider is None:
        with _provider_lock:
            if _provider is None:
                name = settings.market_data_provider
                if name == "schwab":
                    from app.services.schwab_client import SchwabClient
                    _provider = SchwabClient(
                        settings.schwab_app_key, settings.schwab_app_secret, settings.database_url,
                        sync_url=settings.schwab_token_sync_url, sync_secret=settings.schwab_token_sync_secret,
                    )
                else:  # settings validation rejects unknown names at startup
                    raise ValueError(f"Unknown market data provider: {name}")
    return _provider


def market_data_offline() -> bool:
    """Sync check, no I/O: True while the configured provider is known to be offline."""
    return get_market_data().is_offline()


async def market_data_offline_now() -> bool:
    """For async callers (mixed endpoints, scheduler). While offline it re-reads the token row
    (at most once a minute, off the event loop) so a CLI re-auth is noticed without any market
    call. While online it costs nothing."""
    import asyncio

    provider = get_market_data()
    if not provider.is_offline():
        return False
    return await asyncio.get_running_loop().run_in_executor(None, provider.refresh_offline_state)


async def prime_market_data() -> None:
    """At startup: load the provider's token state off the event loop, so expiry/offline is known
    before the first market call (mixed endpoints only consult is_offline())."""
    import asyncio
    import logging

    try:
        await asyncio.get_running_loop().run_in_executor(None, get_market_data().refresh_offline_state)
    except Exception as exc:  # never block startup on market data
        logging.getLogger(__name__).warning("Market data provider not primed: %s", exc)

__all__ = [
    "MarketDataProvider", "MarketDataUnavailable", "SchwabAPIError", "PullRateLimited", "ProviderStatus",
    "get_market_data", "market_data_offline", "market_data_offline_now", "compute_state",
    "STATE_OK", "STATE_EXPIRING", "STATE_CRITICAL", "STATE_OFFLINE", "SUPPORTED_PROVIDERS",
]
