import pytest
from httpx import AsyncClient
from unittest.mock import patch

MOCK_TECHNICALS = {
    "macd_signal": "bullish",
    "macd_notes": "above 0 line",
    "rsi_14": 45.5,
    "rsi_result": None,
    "ma_200d": 150.0,
    "ma_50d": 155.0,
    "price_vs_ma200": "above",
    "price_vs_ma50": "above",
    "bollinger_upper": 165.0,
    "bollinger_mid": 157.0,
    "bollinger_lower": 149.0,
    "bollinger_position": "mid",
    "day_color": "green",
    "price_action": "158.50",
    "sentiment": "bullish",
    "next_earnings_date": "2026-08-15",
    "fetch_status": "ok",
    "fetch_error": None,
    "notes": None,
}


async def test_get_technicals_success(client: AsyncClient):
    with patch("app.routers.market.fetch_technicals", return_value=MOCK_TECHNICALS):
        response = await client.get("/api/market/technicals/AAPL")
    assert response.status_code == 200
    data = response.json()
    assert data["macd_signal"] == "bullish"
    assert data["fetch_status"] == "ok"
    assert data["price_action"] == "158.50"


async def test_get_technicals_fetch_error_returns_200_with_error_status(client: AsyncClient):
    error_result = {"fetch_status": "error", "fetch_error": "No data"}
    with patch("app.routers.market.fetch_technicals", return_value=error_result):
        response = await client.get("/api/market/technicals/INVALID")
    assert response.status_code == 200
    assert response.json()["fetch_status"] == "error"


async def test_get_technicals_ticker_uppercased(client: AsyncClient):
    with patch("app.routers.market.fetch_technicals", return_value=MOCK_TECHNICALS) as mock_fn:
        await client.get("/api/market/technicals/aapl")
    mock_fn.assert_called_once_with("AAPL")
