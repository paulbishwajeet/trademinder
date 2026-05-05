# backend/tests/test_alerts.py
import pytest
from httpx import AsyncClient
from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.alert import Alert
from app.models.trade import Trade
import uuid


TRADE_PAYLOAD = {
    "type": "Sell",
    "category": "Wheel",
    "strategy": "Put",
    "ticker": "AAPL",
    "open_date": str(date.today()),
    "quantity": 1,
}


async def _create_trade_and_alert(client: AsyncClient, db_session: AsyncSession) -> tuple[str, str]:
    trade_resp = await client.post("/api/trades", json=TRADE_PAYLOAD)
    trade_id = trade_resp.json()["id"]

    alert = Alert(
        trade_id=uuid.UUID(trade_id),
        alert_type="profit_target",
        severity="warning",
        title="Profit target reached",
        message="Position at 52% of max profit",
    )
    db_session.add(alert)
    await db_session.commit()
    await db_session.refresh(alert)
    return trade_id, str(alert.id)


async def test_list_alerts_empty(client: AsyncClient):
    response = await client.get("/api/alerts")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_alerts(client: AsyncClient, db_session: AsyncSession):
    _, _ = await _create_trade_and_alert(client, db_session)
    response = await client.get("/api/alerts")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["alert_type"] == "profit_target"
    assert data[0]["is_read"] is False


async def test_mark_alert_read(client: AsyncClient, db_session: AsyncSession):
    _, alert_id = await _create_trade_and_alert(client, db_session)
    response = await client.post(f"/api/alerts/{alert_id}/read")
    assert response.status_code == 200
    assert response.json()["is_read"] is True


async def test_dismiss_alert(client: AsyncClient, db_session: AsyncSession):
    _, alert_id = await _create_trade_and_alert(client, db_session)
    response = await client.post(f"/api/alerts/{alert_id}/dismiss")
    assert response.status_code == 200
    assert response.json()["is_dismissed"] is True
    # dismissed alerts don't appear in main list
    list_resp = await client.get("/api/alerts")
    assert list_resp.json() == []


async def test_get_alerts_for_trade(client: AsyncClient, db_session: AsyncSession):
    trade_id, _ = await _create_trade_and_alert(client, db_session)
    response = await client.get(f"/api/alerts/trade/{trade_id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["trade_id"] == trade_id


async def test_stub_market_returns_501(client: AsyncClient):
    response = await client.get("/api/market/quote/AAPL")
    assert response.status_code == 501


async def test_stub_briefing_returns_501(client: AsyncClient):
    response = await client.get("/api/briefing/today")
    assert response.status_code == 501
