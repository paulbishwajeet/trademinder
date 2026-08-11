import pytest
from httpx import AsyncClient
from unittest.mock import patch

MOCK_FETCH_OK = {
    "sector": None, "price": 100.0, "prev_close": 99.0, "change_pct": 1.01,
    "iv_rank": None, "iv_percentile": None, "rsi_14": None,
    "macd_weekly_signal": None, "macd_daily_signal": None,
    "ma_20d": None, "ma_50d": None, "ma_100d": None, "ma_200d": None,
    "bollinger_upper": None, "bollinger_mid": None, "bollinger_lower": None,
    "bollinger_position": None, "next_earnings_date": None, "volume_spikes": [],
    "fetch_status": "ok", "fetch_error": None,
}


async def _add_symbol(client: AsyncClient, symbol: str = "AAPL") -> None:
    with patch("app.routers.screener.fetch_screener_row", return_value=MOCK_FETCH_OK):
        await client.post("/api/screener", json={"symbol": symbol})


async def test_add_and_list_commentary(client: AsyncClient):
    await _add_symbol(client)
    response = await client.post("/api/screener/AAPL/commentary", json={"note": "Watching for a breakout", "tags": ["breakout"]})
    assert response.status_code == 201
    data = response.json()
    assert data["note"] == "Watching for a breakout"
    assert data["updated_at"] is None

    list_response = await client.get("/api/screener/AAPL/commentary")
    assert len(list_response.json()) == 1


async def test_add_commentary_404_when_symbol_not_tracked(client: AsyncClient):
    response = await client.post("/api/screener/ZZZZ/commentary", json={"note": "note"})
    assert response.status_code == 404


async def test_update_commentary_sets_updated_at(client: AsyncClient):
    await _add_symbol(client)
    add_response = await client.post("/api/screener/AAPL/commentary", json={"note": "original"})
    comment_id = add_response.json()["id"]

    response = await client.put(f"/api/screener/commentary/{comment_id}", json={"note": "edited note"})
    assert response.status_code == 200
    data = response.json()
    assert data["note"] == "edited note"
    assert data["updated_at"] is not None


async def test_update_commentary_404_when_missing(client: AsyncClient):
    import uuid
    response = await client.put(f"/api/screener/commentary/{uuid.uuid4()}", json={"note": "x"})
    assert response.status_code == 404


async def test_delete_commentary(client: AsyncClient):
    await _add_symbol(client)
    add_response = await client.post("/api/screener/AAPL/commentary", json={"note": "delete me"})
    comment_id = add_response.json()["id"]

    response = await client.delete(f"/api/screener/commentary/{comment_id}")
    assert response.status_code == 204

    list_response = await client.get("/api/screener/AAPL/commentary")
    assert list_response.json() == []


async def test_delete_commentary_404_when_missing(client: AsyncClient):
    import uuid
    response = await client.delete(f"/api/screener/commentary/{uuid.uuid4()}")
    assert response.status_code == 404
