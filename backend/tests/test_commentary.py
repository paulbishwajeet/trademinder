# backend/tests/test_commentary.py
import pytest
from httpx import AsyncClient
from datetime import date


TRADE_PAYLOAD = {
    "type": "Sell",
    "category": "Wheel",
    "strategy": "Put",
    "ticker": "AAPL",
    "open_date": str(date.today()),
    "quantity": 1,
}


async def _create_trade(client: AsyncClient) -> str:
    resp = await client.post("/api/trades", json=TRADE_PAYLOAD)
    return resp.json()["id"]


async def test_add_commentary(client: AsyncClient):
    trade_id = await _create_trade(client)
    response = await client.post(f"/api/trades/{trade_id}/commentary", json={"note": "Watching closely"})
    assert response.status_code == 201
    data = response.json()
    assert data["note"] == "Watching closely"
    assert data["trade_id"] == trade_id


async def test_add_commentary_with_tags(client: AsyncClient):
    trade_id = await _create_trade(client)
    response = await client.post(
        f"/api/trades/{trade_id}/commentary",
        json={"note": "Rolled down", "tags": ["rolled", "adjustment"]},
    )
    assert response.status_code == 201
    assert response.json()["tags"] == ["rolled", "adjustment"]


async def test_list_commentary(client: AsyncClient):
    trade_id = await _create_trade(client)
    await client.post(f"/api/trades/{trade_id}/commentary", json={"note": "First note"})
    await client.post(f"/api/trades/{trade_id}/commentary", json={"note": "Second note"})
    response = await client.get(f"/api/trades/{trade_id}/commentary")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    # Newest first
    assert data[0]["note"] == "Second note"


async def test_list_commentary_for_unknown_trade(client: AsyncClient):
    response = await client.get("/api/trades/00000000-0000-0000-0000-000000000000/commentary")
    assert response.status_code == 200
    assert response.json() == []


async def test_delete_commentary(client: AsyncClient):
    trade_id = await _create_trade(client)
    create_resp = await client.post(f"/api/trades/{trade_id}/commentary", json={"note": "To delete"})
    comment_id = create_resp.json()["id"]
    response = await client.delete(f"/api/commentary/{comment_id}")
    assert response.status_code == 204
    list_resp = await client.get(f"/api/trades/{trade_id}/commentary")
    assert list_resp.json() == []
