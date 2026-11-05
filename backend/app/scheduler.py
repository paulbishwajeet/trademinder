# backend/app/scheduler.py
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.database import AsyncSessionLocal

scheduler = AsyncIOScheduler(timezone="America/New_York")
log = logging.getLogger(__name__)

# Whether the current offline period has been logged (log once on entry, once on recovery).
_offline_logged = False


async def market_offline() -> bool:
    """True while market data is offline. Logs the transition once per offline period."""
    global _offline_logged
    from app.services.market_data import market_data_offline_now

    offline = await market_data_offline_now()
    if offline and not _offline_logged:
        log.warning("Scheduler: market data offline — skipping price refresh and market-dependent "
                    "alert/signal rules until it is back (database-only alert rules keep running)")
    elif not offline and _offline_logged:
        log.warning("Scheduler: market data back online — resuming price refresh")
    _offline_logged = offline
    return offline


def is_market_hours() -> bool:
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    return time(9, 30) <= now.time() <= time(16, 0)


async def price_refresh_job() -> None:
    if not is_market_hours():
        return
    if await market_offline():
        return
    from app.services.market_data_errors import MarketDataUnavailable
    from app.services.price_fetcher import refresh_open_trades
    async with AsyncSessionLocal() as db:
        try:
            await refresh_open_trades(db)
        except MarketDataUnavailable:
            await market_offline()  # went offline mid-run: log it once; stored prices are untouched


async def alert_engine_job() -> None:
    if not is_market_hours():
        return
    from app.services.alert_engine import run as run_alert_engine
    offline = await market_offline()
    async with AsyncSessionLocal() as db:
        await run_alert_engine(db, market_offline=offline)


async def signal_engine_job() -> None:
    if not is_market_hours():
        return
    from app.services.signal_engine import run as run_signal_engine
    offline = await market_offline()
    async with AsyncSessionLocal() as db:
        await run_signal_engine(db, market_offline=offline)


def start_scheduler(interval_minutes: int | None = None) -> None:
    minutes = interval_minutes or settings.price_refresh_interval_minutes
    scheduler.add_job(price_refresh_job, "interval", minutes=minutes, id="price_refresh")
    scheduler.add_job(alert_engine_job, "interval", minutes=minutes, seconds=30, id="alert_engine")
    scheduler.add_job(signal_engine_job, "interval", minutes=minutes, seconds=60, id="signal_engine")
    scheduler.start()
