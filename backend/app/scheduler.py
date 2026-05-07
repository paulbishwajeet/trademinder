# backend/app/scheduler.py
from datetime import datetime, time
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.database import AsyncSessionLocal

scheduler = AsyncIOScheduler(timezone="America/New_York")


def is_market_hours() -> bool:
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    return time(9, 30) <= now.time() <= time(16, 0)


async def price_refresh_job() -> None:
    if not is_market_hours():
        return
    from app.services.price_fetcher import refresh_open_trades
    async with AsyncSessionLocal() as db:
        await refresh_open_trades(db)


async def alert_engine_job() -> None:
    if not is_market_hours():
        return
    from app.services.alert_engine import run as run_alert_engine
    async with AsyncSessionLocal() as db:
        await run_alert_engine(db)


async def signal_engine_job() -> None:
    if not is_market_hours():
        return
    from app.services.signal_engine import run as run_signal_engine
    async with AsyncSessionLocal() as db:
        await run_signal_engine(db)


def start_scheduler(interval_minutes: int | None = None) -> None:
    minutes = interval_minutes or settings.price_refresh_interval_minutes
    scheduler.add_job(price_refresh_job, "interval", minutes=minutes, id="price_refresh")
    scheduler.add_job(alert_engine_job, "interval", minutes=minutes, seconds=30, id="alert_engine")
    scheduler.add_job(signal_engine_job, "interval", minutes=minutes, seconds=60, id="signal_engine")
    scheduler.start()
