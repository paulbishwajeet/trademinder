# backend/tests/test_alert_engine.py
import uuid
import pytest
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import AsyncClient

from app.models.trade import Trade
from app.models.alert import Alert
from app.models.rationale import Rationale
from app.services.alert_engine import run as run_alert_engine


TRADE_PAYLOAD = {
    "type": "Sell",
    "category": "Wheel",
    "strategy": "Put",
    "ticker": "AAPL",
    "open_date": str(date.today()),
    "strike_price": "190.00",
    "premium": "4.00",
    "quantity": 1,
}


async def _create_trade(client: AsyncClient) -> str:
    resp = await client.post("/api/trades", json=TRADE_PAYLOAD)
    assert resp.status_code == 201
    return resp.json()["id"]


async def _set_price_and_pnl(db: AsyncSession, trade_id: str,
                               current_price: float | None = None,
                               unrealized_pnl: float | None = None):
    stmt = select(Trade).where(Trade.id == uuid.UUID(trade_id))
    r = await db.execute(stmt)
    trade = r.scalar_one()
    if current_price is not None:
        trade.current_price = current_price
    if unrealized_pnl is not None:
        trade.unrealized_pnl = unrealized_pnl
    await db.commit()


async def test_profit_target_fires(client: AsyncClient, db_session: AsyncSession):
    trade_id = await _create_trade(client)
    # max_profit = 4.00 * 1 * 100 = 400; need pnl >= 200 (50%)
    await _set_price_and_pnl(db_session, trade_id, current_price=196.0, unrealized_pnl=210.0)

    result = await run_alert_engine(db_session)
    assert result["alerts_created"] >= 1

    stmt = select(Alert).where(
        Alert.trade_id == uuid.UUID(trade_id),
        Alert.alert_type == "profit_target",
    )
    r = await db_session.execute(stmt)
    assert r.scalar_one_or_none() is not None


async def test_profit_target_deduplicates(client: AsyncClient, db_session: AsyncSession):
    trade_id = await _create_trade(client)
    await _set_price_and_pnl(db_session, trade_id, current_price=196.0, unrealized_pnl=210.0)

    await run_alert_engine(db_session)
    await run_alert_engine(db_session)

    stmt = select(Alert).where(
        Alert.trade_id == uuid.UUID(trade_id),
        Alert.alert_type == "profit_target",
    )
    r = await db_session.execute(stmt)
    assert len(r.scalars().all()) == 1


async def test_stop_loss_fires(client: AsyncClient, db_session: AsyncSession):
    trade_id = await _create_trade(client)
    # max_profit = 400; stop_loss triggers at pnl <= -800
    await _set_price_and_pnl(db_session, trade_id, current_price=170.0, unrealized_pnl=-850.0)

    await run_alert_engine(db_session)

    stmt = select(Alert).where(
        Alert.trade_id == uuid.UUID(trade_id),
        Alert.alert_type == "stop_loss",
    )
    r = await db_session.execute(stmt)
    assert r.scalar_one_or_none() is not None


async def test_dte_critical_fires_and_not_threshold(client: AsyncClient, db_session: AsyncSession):
    payload = {**TRADE_PAYLOAD, "expiry_date": str(date.today() + timedelta(days=5))}
    resp = await client.post("/api/trades", json=payload)
    trade_id = resp.json()["id"]

    await run_alert_engine(db_session)

    stmt_critical = select(Alert).where(
        Alert.trade_id == uuid.UUID(trade_id),
        Alert.alert_type == "dte_critical",
    )
    r = await db_session.execute(stmt_critical)
    assert r.scalar_one_or_none() is not None

    # dte_threshold must NOT fire when dte <= 7
    stmt_threshold = select(Alert).where(
        Alert.trade_id == uuid.UUID(trade_id),
        Alert.alert_type == "dte_threshold",
    )
    r2 = await db_session.execute(stmt_threshold)
    assert r2.scalar_one_or_none() is None


async def test_dte_threshold_fires(client: AsyncClient, db_session: AsyncSession):
    payload = {**TRADE_PAYLOAD, "expiry_date": str(date.today() + timedelta(days=15))}
    resp = await client.post("/api/trades", json=payload)
    trade_id = resp.json()["id"]

    await run_alert_engine(db_session)

    stmt = select(Alert).where(
        Alert.trade_id == uuid.UUID(trade_id),
        Alert.alert_type == "dte_threshold",
    )
    r = await db_session.execute(stmt)
    assert r.scalar_one_or_none() is not None


async def test_earnings_approaching_fires(client: AsyncClient, db_session: AsyncSession):
    trade_id = await _create_trade(client)

    stmt = select(Rationale).where(Rationale.trade_id == uuid.UUID(trade_id))
    r = await db_session.execute(stmt)
    rationale = r.scalar_one()
    rationale.next_earnings_date = date.today() + timedelta(days=3)
    await db_session.commit()

    await run_alert_engine(db_session)

    stmt = select(Alert).where(
        Alert.trade_id == uuid.UUID(trade_id),
        Alert.alert_type == "earnings_approaching",
    )
    r = await db_session.execute(stmt)
    assert r.scalar_one_or_none() is not None


async def test_assignment_risk_fires(client: AsyncClient, db_session: AsyncSession):
    # Strike 190, current 191.5 → within 2%
    trade_id = await _create_trade(client)
    await _set_price_and_pnl(db_session, trade_id, current_price=191.5)

    await run_alert_engine(db_session)

    stmt = select(Alert).where(
        Alert.trade_id == uuid.UUID(trade_id),
        Alert.alert_type == "assignment_risk",
    )
    r = await db_session.execute(stmt)
    assert r.scalar_one_or_none() is not None


async def test_overdue_review_fires(client: AsyncClient, db_session: AsyncSession):
    trade_id = await _create_trade(client)

    # Age the trade by 6 days
    stmt = select(Trade).where(Trade.id == uuid.UUID(trade_id))
    r = await db_session.execute(stmt)
    trade = r.scalar_one()
    trade.created_at = datetime.now(timezone.utc) - timedelta(days=6)
    await db_session.commit()

    await run_alert_engine(db_session)

    stmt = select(Alert).where(
        Alert.trade_id == uuid.UUID(trade_id),
        Alert.alert_type == "overdue_review",
    )
    r = await db_session.execute(stmt)
    assert r.scalar_one_or_none() is not None


async def test_deep_itm_fires(client: AsyncClient, db_session: AsyncSession):
    payload = {**TRADE_PAYLOAD, "strategy": "CoveredCall", "strike_price": "190.00"}
    resp = await client.post("/api/trades", json=payload)
    trade_id = resp.json()["id"]
    # 202 is 6.3% above strike 190
    await _set_price_and_pnl(db_session, trade_id, current_price=202.0)

    await run_alert_engine(db_session)

    stmt = select(Alert).where(
        Alert.trade_id == uuid.UUID(trade_id),
        Alert.alert_type == "deep_itm",
    )
    r = await db_session.execute(stmt)
    assert r.scalar_one_or_none() is not None


async def test_no_alerts_for_closed_trade(client: AsyncClient, db_session: AsyncSession):
    trade_id = await _create_trade(client)
    await client.post(f"/api/trades/{trade_id}/close")

    result = await run_alert_engine(db_session)

    stmt = select(Alert).where(Alert.trade_id == uuid.UUID(trade_id))
    r = await db_session.execute(stmt)
    assert r.scalars().all() == []
