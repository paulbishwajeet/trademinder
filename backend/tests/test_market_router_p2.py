# backend/tests/test_market_router_p2.py
from unittest.mock import patch
from httpx import AsyncClient


async def test_quote_returns_price(client: AsyncClient):
    mock_result = {
        "ticker": "AAPL",
        "price": 192.43,
        "change_pct": -0.82,
        "last_updated": "2026-05-05T14:32:00Z",
    }
    with patch("app.routers.market.fetch_quote", return_value=mock_result):
        response = await client.get("/api/market/quote/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["ticker"] == "AAPL"
    assert data["price"] == 192.43


async def test_quote_lowercases_ticker(client: AsyncClient):
    mock_result = {
        "ticker": "AAPL",
        "price": 192.43,
        "change_pct": -0.82,
        "last_updated": "2026-05-05T14:32:00Z",
    }
    with patch("app.routers.market.fetch_quote", return_value=mock_result) as mock_fn:
        await client.get("/api/market/quote/aapl")
    # Verify it was called with uppercase
    mock_fn.assert_called_once_with("AAPL")


async def test_quote_returns_404_for_unknown_ticker(client: AsyncClient):
    with patch("app.routers.market.fetch_quote", return_value=None):
        response = await client.get("/api/market/quote/INVALID")
    assert response.status_code == 404


async def test_refresh_triggers_price_and_alert_engine(client: AsyncClient):
    price_result = {"trades_updated": 3, "tickers_fetched": 2, "errors": []}
    alert_result = {"alerts_created": 1, "trades_evaluated": 3}

    with patch("app.routers.market.refresh_open_trades", return_value=price_result), \
         patch("app.routers.market.run_alert_engine", return_value=alert_result):
        response = await client.post("/api/market/refresh")

    assert response.status_code == 200
    data = response.json()
    assert data["trades_updated"] == 3
    assert data["alerts_created"] == 1
    assert data["tickers_fetched"] == 2
    assert data["errors"] == []


async def test_options_still_501(client: AsyncClient):
    response = await client.get("/api/market/options/AAPL")
    assert response.status_code == 501


async def test_prefetch_still_501(client: AsyncClient):
    response = await client.post("/api/market/prefetch/AAPL")
    assert response.status_code == 501
