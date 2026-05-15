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


async def test_options_returns_scan_result(client: AsyncClient):
    mock_result = {
        "ticker": "AMD",
        "spot": 142.30,
        "scan_ts": "2026-05-12T10:00:00Z",
        "lt_close_date": "2027-05-13",
        "earnings_dates": [],
        "options": [
            {
                "type": "call", "strike": 150.0, "expiration": "2027-01-15",
                "dte": 400, "bid": 10.0, "ask": 11.0, "mid": 10.5,
                "iv": 0.45, "iv_fitted": 0.42, "iv_excess": 0.03,
                "delta": 0.42, "ann_yield_pct": 12.5,
                "open_interest": 100, "earnings_count": 0,
            }
        ],
    }
    with patch("app.routers.market.run_scan", return_value=mock_result):
        response = await client.get(
            "/api/market/options/AMD?type=calls&min_dte=365&min_oi=25&max_delta=0.70"
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ticker"] == "AMD"
    assert data["spot"] == 142.30
    assert len(data["options"]) == 1


async def test_options_uppercases_ticker(client: AsyncClient):
    mock_result = {
        "ticker": "AMD", "spot": 142.30, "scan_ts": "2026-05-12T10:00:00Z",
        "lt_close_date": "2027-05-13", "earnings_dates": [], "options": [],
    }
    with patch("app.routers.market.run_scan", return_value=mock_result) as mock_fn:
        await client.get("/api/market/options/amd")
    assert mock_fn.call_args[0][0] == "AMD"


async def test_options_returns_404_for_unknown_ticker(client: AsyncClient):
    with patch(
        "app.routers.market.run_scan",
        side_effect=ValueError("Could not fetch live price for INVALID"),
    ):
        response = await client.get("/api/market/options/INVALID")
    assert response.status_code == 404


async def test_options_returns_200_with_empty_options_when_no_leaps(client: AsyncClient):
    mock_result = {
        "ticker": "AMD", "spot": 142.30, "scan_ts": "2026-05-12T10:00:00Z",
        "lt_close_date": "2027-05-13", "earnings_dates": [], "options": [],
    }
    with patch("app.routers.market.run_scan", return_value=mock_result):
        response = await client.get("/api/market/options/AMD")
    assert response.status_code == 200
    assert response.json()["options"] == []


async def test_prefetch_still_501(client: AsyncClient):
    response = await client.post("/api/market/prefetch/AAPL")
    assert response.status_code == 501
