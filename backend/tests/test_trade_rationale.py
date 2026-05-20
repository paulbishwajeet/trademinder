# backend/tests/test_trade_rationale.py
import pytest
from httpx import AsyncClient
from datetime import date

TRADE_PAYLOAD = {
    "type": "Sell",
    "category": "WHEEL",
    "strategy": "Put",
    "ticker": "AAPL",
    "open_date": str(date.today()),
    "quantity": 1,
}

RATIONALE_PAYLOAD = {
    "rsi_14": "45.50",
    "macd_signal": "bullish",
    "macd_notes": "above 0 line",
    "ma_200d": "150.00",
    "ma_50d": "155.00",
    "price_vs_ma200": "above",
    "price_vs_ma50": "above",
    "bollinger_upper": "165.00",
    "bollinger_mid": "157.00",
    "bollinger_lower": "149.00",
    "bollinger_position": "mid",
    "day_color": "green",
    "price_action": "158.50",
    "sentiment": "bullish",
    "notes": "Strong momentum",
}


async def _create_trade(client: AsyncClient) -> str:
    resp = await client.post("/api/trades", json=TRADE_PAYLOAD)
    assert resp.status_code == 201
    return resp.json()["id"]


async def test_upsert_trade_rationale(client: AsyncClient):
    trade_id = await _create_trade(client)
    response = await client.put(f"/api/trades/{trade_id}/rationale", json=RATIONALE_PAYLOAD)
    assert response.status_code == 200
    data = response.json()
    assert float(data["rsi_14"]) == 45.50
    assert data["macd_signal"] == "bullish"
    assert data["fetch_status"] == "ok"
    assert data["commentary_id"] is None


async def test_upsert_trade_rationale_is_idempotent(client: AsyncClient):
    trade_id = await _create_trade(client)
    await client.put(f"/api/trades/{trade_id}/rationale", json=RATIONALE_PAYLOAD)
    # Second upsert updates the same row
    updated = {**RATIONALE_PAYLOAD, "macd_signal": "bearish"}
    response = await client.put(f"/api/trades/{trade_id}/rationale", json=updated)
    assert response.status_code == 200
    assert response.json()["macd_signal"] == "bearish"

    # Verify only one entry-time rationale row exists by checking trade detail
    detail = await client.get(f"/api/trades/{trade_id}")
    assert detail.json()["rationale"]["macd_signal"] == "bearish"


async def test_upsert_rationale_trade_not_found(client: AsyncClient):
    response = await client.put(
        "/api/trades/00000000-0000-0000-0000-000000000000/rationale",
        json=RATIONALE_PAYLOAD,
    )
    assert response.status_code == 404
