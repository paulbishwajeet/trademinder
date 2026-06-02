import pytest
from datetime import date, datetime, timezone, timedelta
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

STOCK_TRADE = {
    "type": "Buy",
    "category": "WHEEL",
    "strategy": "Stock",
    "ticker": "AAPL",
    "open_date": str(date.today()),
    "quantity": 100,
}

PUT_TRADE = {
    "type": "Sell",
    "category": "WHEEL",
    "strategy": "Put",
    "ticker": "NVDA",
    "open_date": str(date.today()),
    "expiry_date": "2026-09-19",
    "strike_price": "120.00",
    "quantity": 1,
    "premium": "3.00",
}

RECONCILE_URL = "/api/positions/reconcile"


async def test_reconcile_returns_unmatched_position(client: AsyncClient):
    """Position in E*TRADE with no backend trade appears in unmatched_etrade."""
    await client.post("/api/trades", json=STOCK_TRADE)  # AAPL in backend

    resp = await client.post(RECONCILE_URL, json={
        "positions": [
            {"ticker": "TSLA", "full_symbol": None, "type": "Stock"},  # not in backend
        ]
    })
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["unmatched_etrade"]) == 1
    assert data["unmatched_etrade"][0]["ticker"] == "TSLA"
    assert data["stale_backend"] == []


async def test_reconcile_matched_trade_gets_last_etrade_seen(
    client: AsyncClient, db_session: AsyncSession
):
    """Matched trade has last_etrade_seen set to a recent timestamp."""
    from sqlalchemy import select
    from app.models.trade import Trade

    create_resp = await client.post("/api/trades", json=STOCK_TRADE)
    trade_id = create_resp.json()["id"]

    resp = await client.post(RECONCILE_URL, json={
        "positions": [{"ticker": "AAPL", "full_symbol": None, "type": "Stock"}]
    })
    assert resp.status_code == 200

    result = await db_session.execute(select(Trade).where(Trade.id == trade_id))
    trade = result.scalar_one()
    await db_session.refresh(trade)
    assert trade.last_etrade_seen is not None
    assert trade.last_etrade_seen > datetime.now(timezone.utc) - timedelta(minutes=1)


async def test_reconcile_stale_trade_in_stale_backend(
    client: AsyncClient, db_session: AsyncSession
):
    """Open trade with last_etrade_seen > 1 day ago that's absent from snapshot → stale_backend."""
    from sqlalchemy import select
    from app.models.trade import Trade

    create_resp = await client.post("/api/trades", json=STOCK_TRADE)
    trade_id = create_resp.json()["id"]

    # Backdate last_etrade_seen to 2 days ago
    result = await db_session.execute(select(Trade).where(Trade.id == trade_id))
    trade = result.scalar_one()
    trade.last_etrade_seen = datetime.now(timezone.utc) - timedelta(days=2)
    await db_session.commit()

    # Reconcile without AAPL in snapshot
    resp = await client.post(RECONCILE_URL, json={
        "positions": [{"ticker": "TSLA", "full_symbol": None, "type": "Stock"}]
    })
    assert resp.status_code == 200
    data = resp.json()
    stale_ids = [item["id"] for item in data["stale_backend"]]
    assert trade_id in stale_ids


async def test_reconcile_recently_seen_not_stale(
    client: AsyncClient, db_session: AsyncSession
):
    """Trade seen within the last hour is not stale even if absent from snapshot."""
    from sqlalchemy import select
    from app.models.trade import Trade

    create_resp = await client.post("/api/trades", json=STOCK_TRADE)
    trade_id = create_resp.json()["id"]

    result = await db_session.execute(select(Trade).where(Trade.id == trade_id))
    trade = result.scalar_one()
    trade.last_etrade_seen = datetime.now(timezone.utc) - timedelta(hours=1)
    await db_session.commit()

    resp = await client.post(RECONCILE_URL, json={
        "positions": [{"ticker": "TSLA", "full_symbol": None, "type": "Stock"}]
    })
    assert resp.status_code == 200
    data = resp.json()
    stale_ids = [item["id"] for item in data["stale_backend"]]
    assert trade_id not in stale_ids


async def test_reconcile_never_seen_not_stale(client: AsyncClient):
    """Trade with null last_etrade_seen is never flagged stale."""
    create_resp = await client.post("/api/trades", json=STOCK_TRADE)
    trade_id = create_resp.json()["id"]

    resp = await client.post(RECONCILE_URL, json={
        "positions": [{"ticker": "TSLA", "full_symbol": None, "type": "Stock"}]
    })
    assert resp.status_code == 200
    stale_ids = [item["id"] for item in resp.json()["stale_backend"]]
    assert trade_id not in stale_ids


async def test_reconcile_option_matched_by_strike_and_expiry(
    client: AsyncClient, db_session: AsyncSession
):
    """Option position matched by strike+expiry sets last_etrade_seen."""
    from sqlalchemy import select
    from app.models.trade import Trade

    create_resp = await client.post("/api/trades", json=PUT_TRADE)
    trade_id = create_resp.json()["id"]

    resp = await client.post(RECONCILE_URL, json={
        "positions": [{
            "ticker": "NVDA",
            "full_symbol": "NVDA--260919P00120000",
            "type": "Put",
            "strike": 120.0,
            "expiry": "2026-09-19",
        }]
    })
    assert resp.status_code == 200
    assert resp.json()["unmatched_etrade"] == []

    result = await db_session.execute(select(Trade).where(Trade.id == trade_id))
    trade = result.scalar_one()
    await db_session.refresh(trade)
    assert trade.last_etrade_seen is not None


async def test_list_trades_stale_filter(client: AsyncClient, db_session: AsyncSession):
    """GET /api/trades?stale=true returns only trades with old last_etrade_seen."""
    from sqlalchemy import select
    from app.models.trade import Trade

    # Create two trades
    r1 = await client.post("/api/trades", json=STOCK_TRADE)
    r2 = await client.post("/api/trades", json={**STOCK_TRADE, "ticker": "MSFT"})
    stale_id = r1.json()["id"]
    fresh_id = r2.json()["id"]

    # Backdate one
    result = await db_session.execute(select(Trade).where(Trade.id == stale_id))
    t = result.scalar_one()
    t.last_etrade_seen = datetime.now(timezone.utc) - timedelta(days=2)
    await db_session.commit()

    # MSFT has null last_etrade_seen — should not appear
    resp = await client.get("/api/trades?stale=true")
    assert resp.status_code == 200
    ids = [item["id"] for item in resp.json()]
    assert stale_id in ids
    assert fresh_id not in ids
