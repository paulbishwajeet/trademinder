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

RATIONALE_SNIPPET = {
    "rsi_14": "35.20",
    "macd_signal": "bullish",
    "sentiment": "bullish",
}


async def _create_trade(client: AsyncClient) -> str:
    resp = await client.post("/api/trades", json=TRADE_PAYLOAD)
    return resp.json()["id"]


async def test_add_commentary_with_rationale(client: AsyncClient):
    trade_id = await _create_trade(client)
    response = await client.post(
        f"/api/trades/{trade_id}/commentary",
        json={"note": "RSI looks good", "rationale": RATIONALE_SNIPPET},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["note"] == "RSI looks good"
    assert data["rationale"] is not None
    assert float(data["rationale"]["rsi_14"]) == 35.20
    assert data["rationale"]["macd_signal"] == "bullish"
    assert data["rationale"]["commentary_id"] == data["id"]


async def test_add_commentary_without_rationale(client: AsyncClient):
    trade_id = await _create_trade(client)
    response = await client.post(
        f"/api/trades/{trade_id}/commentary",
        json={"note": "Just watching"},
    )
    assert response.status_code == 201
    assert response.json()["rationale"] is None


async def test_list_commentary_includes_rationale(client: AsyncClient):
    trade_id = await _create_trade(client)
    await client.post(
        f"/api/trades/{trade_id}/commentary",
        json={"note": "With technicals", "rationale": RATIONALE_SNIPPET},
    )
    await client.post(
        f"/api/trades/{trade_id}/commentary",
        json={"note": "Without technicals"},
    )
    response = await client.get(f"/api/trades/{trade_id}/commentary")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    with_rat = next(d for d in data if d["note"] == "With technicals")
    without_rat = next(d for d in data if d["note"] == "Without technicals")
    assert with_rat["rationale"] is not None
    assert without_rat["rationale"] is None


async def test_commentary_rationale_deleted_with_commentary(client: AsyncClient):
    """Deleting a comment must cascade-delete its rationale."""
    trade_id = await _create_trade(client)
    create_resp = await client.post(
        f"/api/trades/{trade_id}/commentary",
        json={"note": "To delete", "rationale": RATIONALE_SNIPPET},
    )
    comment_id = create_resp.json()["id"]
    del_resp = await client.delete(f"/api/commentary/{comment_id}")
    assert del_resp.status_code == 204

    list_resp = await client.get(f"/api/trades/{trade_id}/commentary")
    assert list_resp.json() == []
