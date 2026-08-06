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


MOCK_CROSSOVER = {
    "weekly": {
        "cross_date": "2026-04-27",
        "cross_direction": "bullish",
        "periods_since_cross": 14,
        "strength_score": 19.1,
        "trend": "fading_near_flip",
    },
    "daily": {
        "cross_date": "2026-07-31",
        "cross_direction": "bearish",
        "periods_since_cross": 2,
        "strength_score": 100.0,
        "trend": "expanding",
    },
    "fetch_status": "ok",
    "fetch_error": None,
}


async def test_get_macd_crossover_success(client: AsyncClient):
    with patch("app.routers.market.fetch_macd_crossover", return_value=MOCK_CROSSOVER):
        response = await client.get("/api/market/macd-crossover/AAPL")
    assert response.status_code == 200
    data = response.json()
    assert data["weekly"]["cross_direction"] == "bullish"
    assert data["weekly"]["strength_score"] == 19.1
    assert data["daily"]["cross_direction"] == "bearish"
    assert data["daily"]["strength_score"] == 100.0


async def test_get_macd_crossover_no_data_returns_404(client: AsyncClient):
    with patch("app.routers.market.fetch_macd_crossover", side_effect=ValueError("No weekly data for INVALID")):
        response = await client.get("/api/market/macd-crossover/INVALID")
    assert response.status_code == 404


async def test_get_macd_crossover_ticker_uppercased(client: AsyncClient):
    with patch("app.routers.market.fetch_macd_crossover", return_value=MOCK_CROSSOVER) as mock_fn:
        await client.get("/api/market/macd-crossover/aapl")
    mock_fn.assert_called_once_with("AAPL")


MOCK_RSI_SIGNAL = {
    "rsi_14": 44.68,
    "rsi_ma_14": 60.73,
    "cross_date": "2026-07-30",
    "cross_direction": "bearish",
    "periods_since_cross": 3,
    "strength_score": 72.6,
    "trend": "holding_strong",
    "fetch_status": "ok",
    "fetch_error": None,
}


async def test_get_rsi_crossover_success(client: AsyncClient):
    with patch("app.routers.market.fetch_rsi_signal", return_value=MOCK_RSI_SIGNAL):
        response = await client.get("/api/market/rsi-crossover/AAPL")
    assert response.status_code == 200
    data = response.json()
    assert data["rsi_14"] == 44.68
    assert data["cross_direction"] == "bearish"
    assert data["strength_score"] == 72.6


async def test_get_rsi_crossover_no_data_returns_404(client: AsyncClient):
    with patch("app.routers.market.fetch_rsi_signal", side_effect=ValueError("No daily data for INVALID")):
        response = await client.get("/api/market/rsi-crossover/INVALID")
    assert response.status_code == 404


async def test_get_rsi_crossover_ticker_uppercased(client: AsyncClient):
    with patch("app.routers.market.fetch_rsi_signal", return_value=MOCK_RSI_SIGNAL) as mock_fn:
        await client.get("/api/market/rsi-crossover/aapl")
    mock_fn.assert_called_once_with("AAPL")
