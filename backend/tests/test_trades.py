# backend/tests/test_trades.py
import pytest
from httpx import AsyncClient
from datetime import date


TRADE_PAYLOAD = {
    "type": "Sell",
    "category": "Wheel",
    "strategy": "Put",
    "ticker": "AAPL",
    "open_date": str(date.today()),
    "expiry_date": "2026-06-20",
    "strike_price": "180.00",
    "quantity": 1,
    "premium": "3.50",
    "collateral": "18000.00",
    "exit_strategy": "Close at 50% profit or 21 DTE",
    "signal_action": "Hold",
}


async def test_create_trade(client: AsyncClient):
    response = await client.post("/api/trades", json=TRADE_PAYLOAD)
    assert response.status_code == 201
    data = response.json()
    assert data["ticker"] == "AAPL"
    assert data["status"] == "open"
    assert data["strategy"] == "Put"
    assert "id" in data


async def test_list_trades_empty(client: AsyncClient):
    response = await client.get("/api/trades")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_trades(client: AsyncClient):
    await client.post("/api/trades", json=TRADE_PAYLOAD)
    response = await client.get("/api/trades")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["ticker"] == "AAPL"


async def test_get_trade_detail(client: AsyncClient):
    create_resp = await client.post("/api/trades", json=TRADE_PAYLOAD)
    trade_id = create_resp.json()["id"]
    response = await client.get(f"/api/trades/{trade_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == trade_id
    assert data["exit_strategy"] == "Close at 50% profit or 21 DTE"


async def test_get_trade_not_found(client: AsyncClient):
    response = await client.get("/api/trades/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


async def test_patch_trade(client: AsyncClient):
    create_resp = await client.post("/api/trades", json=TRADE_PAYLOAD)
    trade_id = create_resp.json()["id"]
    response = await client.patch(f"/api/trades/{trade_id}", json={"signal_action": "Close — 52% profit"})
    assert response.status_code == 200
    assert response.json()["signal_action"] == "Close — 52% profit"


async def test_close_trade(client: AsyncClient):
    create_resp = await client.post("/api/trades", json=TRADE_PAYLOAD)
    trade_id = create_resp.json()["id"]
    response = await client.post(f"/api/trades/{trade_id}/close", json={"closed_date": str(date.today())})
    assert response.status_code == 200
    assert response.json()["status"] == "closed"
    assert response.json()["closed_date"] is not None


async def test_delete_trade(client: AsyncClient):
    create_resp = await client.post("/api/trades", json=TRADE_PAYLOAD)
    trade_id = create_resp.json()["id"]
    response = await client.delete(f"/api/trades/{trade_id}")
    assert response.status_code == 204
    get_resp = await client.get(f"/api/trades/{trade_id}")
    assert get_resp.status_code == 404


async def test_filter_trades_by_status(client: AsyncClient):
    await client.post("/api/trades", json=TRADE_PAYLOAD)
    response = await client.get("/api/trades?status=open")
    assert response.status_code == 200
    assert all(t["status"] == "open" for t in response.json())


async def test_filter_trades_by_ticker(client: AsyncClient):
    await client.post("/api/trades", json=TRADE_PAYLOAD)
    response = await client.get("/api/trades?ticker=TSLA")
    assert response.status_code == 200
    assert response.json() == []
