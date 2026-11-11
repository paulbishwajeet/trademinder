import asyncio

import pytest
from httpx import AsyncClient
from unittest.mock import patch

MOCK_FETCH_OK = {
    "sector": "Technology", "price": 195.5, "prev_close": 190.0, "change_pct": 2.89,
    "iv_rank": None, "iv_percentile": 45.0, "rsi_14": 55.2,
    "macd_weekly_signal": "bullish", "macd_daily_signal": "bullish",
    "ma_20d": 190.0, "ma_50d": 185.0, "ma_100d": 180.0, "ma_200d": 170.0,
    "bollinger_upper": 200.0, "bollinger_mid": 190.0, "bollinger_lower": 180.0,
    "bollinger_position": "mid", "next_earnings_date": "2026-09-01", "volume_spikes": [],
    "fetch_status": "ok", "fetch_error": None,
}

MOCK_FETCH_ERROR = {"fetch_status": "error", "fetch_error": "No daily data for ZZZZ"}


async def test_add_symbol_direct_mode_fetches_and_persists(client: AsyncClient):
    with patch("app.routers.screener.fetch_screener_row", return_value=MOCK_FETCH_OK) as mock_fn:
        response = await client.post("/api/screener", json={"symbol": "aapl", "category": "Watchlist"})
    assert response.status_code == 201
    data = response.json()
    assert data["symbol"] == "AAPL"
    assert data["category"] == "Watchlist"
    assert data["price"] == "195.50"
    assert data["fetch_status"] == "ok"
    mock_fn.assert_called_once_with("AAPL")


async def test_add_symbol_duplicate_returns_409(client: AsyncClient):
    with patch("app.routers.screener.fetch_screener_row", return_value=MOCK_FETCH_OK):
        await client.post("/api/screener", json={"symbol": "AAPL"})
        response = await client.post("/api/screener", json={"symbol": "AAPL"})
    assert response.status_code == 409


async def test_add_symbol_with_precomputed_skips_fetch(client: AsyncClient):
    with patch("app.routers.screener.fetch_screener_row") as mock_fn:
        response = await client.post("/api/screener", json={"symbol": "MSFT", "precomputed": MOCK_FETCH_OK})
    assert response.status_code == 201
    assert response.json()["price"] == "195.50"
    mock_fn.assert_not_called()


async def test_preview_returns_data_without_persisting(client: AsyncClient):
    with patch("app.routers.screener.fetch_screener_row", return_value=MOCK_FETCH_OK) as mock_fn:
        response = await client.get("/api/screener/preview/tsla")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "TSLA"
    assert data["already_tracked"] is False
    mock_fn.assert_called_once_with("TSLA")

    list_response = await client.get("/api/screener")
    assert list_response.json() == []


async def test_preview_flags_already_tracked(client: AsyncClient):
    with patch("app.routers.screener.fetch_screener_row", return_value=MOCK_FETCH_OK):
        await client.post("/api/screener", json={"symbol": "AAPL"})
        response = await client.get("/api/screener/preview/aapl")
    assert response.json()["already_tracked"] is True


async def test_list_screener_rows(client: AsyncClient):
    with patch("app.routers.screener.fetch_screener_row", return_value=MOCK_FETCH_OK):
        await client.post("/api/screener", json={"symbol": "AAPL"})
        await client.post("/api/screener", json={"symbol": "MSFT"})
    response = await client.get("/api/screener")
    symbols = [r["symbol"] for r in response.json()]
    assert symbols == ["AAPL", "MSFT"]


async def test_fetch_one_updates_existing_row(client: AsyncClient):
    with patch("app.routers.screener.fetch_screener_row", return_value=MOCK_FETCH_OK):
        await client.post("/api/screener", json={"symbol": "AAPL"})
    updated = {**MOCK_FETCH_OK, "price": 200.0}
    with patch("app.routers.screener.fetch_screener_row", return_value=updated):
        response = await client.post("/api/screener/AAPL/fetch")
    assert response.status_code == 200
    assert response.json()["price"] == "200.00"


async def test_fetch_one_404_when_not_tracked(client: AsyncClient):
    response = await client.post("/api/screener/ZZZZ/fetch")
    assert response.status_code == 404


async def test_delete_screener_symbol(client: AsyncClient):
    with patch("app.routers.screener.fetch_screener_row", return_value=MOCK_FETCH_OK):
        await client.post("/api/screener", json={"symbol": "AAPL"})
    response = await client.delete("/api/screener/aapl")
    assert response.status_code == 204
    list_response = await client.get("/api/screener")
    assert list_response.json() == []


async def test_delete_404_when_not_tracked(client: AsyncClient):
    response = await client.delete("/api/screener/ZZZZ")
    assert response.status_code == 404


async def test_patch_sector_and_category(client: AsyncClient):
    with patch("app.routers.screener.fetch_screener_row", return_value=MOCK_FETCH_OK):
        await client.post("/api/screener", json={"symbol": "AAPL"})
    response = await client.patch("/api/screener/AAPL", json={"sector": "Consumer Electronics", "category": "Wheel Candidate"})
    assert response.status_code == 200
    data = response.json()
    assert data["sector"] == "Consumer Electronics"
    assert data["category"] == "Wheel Candidate"


async def test_fetch_all_runs_job_and_updates_rows(client: AsyncClient):
    from tests.conftest import TestSessionLocal

    with patch("app.routers.screener.fetch_screener_row", return_value=MOCK_FETCH_OK):
        await client.post("/api/screener", json={"symbol": "AAPL"})
        await client.post("/api/screener", json={"symbol": "MSFT"})

    updated = {**MOCK_FETCH_OK, "price": 999.0}
    with patch("app.routers.screener.fetch_screener_row", return_value=updated), \
         patch("app.routers.screener.AsyncSessionLocal", TestSessionLocal):
        response = await client.post("/api/screener/fetch-all")
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        assert response.json()["total"] == 2

        for _ in range(50):
            status_response = await client.get(f"/api/screener/jobs/{job_id}")
            status = status_response.json()
            if status["status"] == "done":
                break
            await asyncio.sleep(0.1)
        assert status["status"] == "done"
        assert status["completed"] == 2

    list_response = await client.get("/api/screener")
    prices = {r["symbol"]: r["price"] for r in list_response.json()}
    assert prices == {"AAPL": "999.00", "MSFT": "999.00"}


async def test_fetch_all_records_per_symbol_errors(client: AsyncClient):
    from tests.conftest import TestSessionLocal

    with patch("app.routers.screener.fetch_screener_row", return_value=MOCK_FETCH_OK):
        await client.post("/api/screener", json={"symbol": "AAPL"})

    with patch("app.routers.screener.fetch_screener_row", return_value=MOCK_FETCH_ERROR), \
         patch("app.routers.screener.AsyncSessionLocal", TestSessionLocal):
        response = await client.post("/api/screener/fetch-all")
        job_id = response.json()["job_id"]

        for _ in range(50):
            status_response = await client.get(f"/api/screener/jobs/{job_id}")
            status = status_response.json()
            if status["status"] == "done":
                break
            await asyncio.sleep(0.1)
        assert status["status"] == "done"
        assert status["errors"] == [{"symbol": "AAPL", "error": "No daily data for ZZZZ"}]


async def test_get_job_status_404_for_unknown_job(client: AsyncClient):
    response = await client.get("/api/screener/jobs/does-not-exist")
    assert response.status_code == 404
