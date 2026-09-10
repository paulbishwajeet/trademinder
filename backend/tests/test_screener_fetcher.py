import pandas as pd
from unittest.mock import MagicMock, patch

from app.services.screener_fetcher import fetch_screener_row
from app.services.schwab_client import SchwabAPIError

MOCK_TECHNICALS = {
    "fetch_status": "ok",
    "rsi_14": 55.2,
    "macd_signal": "bullish",
    "macd_daily_cross_direction": "bullish",
    "ma_20d": 190.0, "ma_50d": 185.0, "ma_100d": 180.0, "ma_200d": 170.0,
    "bollinger_upper": 200.0, "bollinger_mid": 190.0, "bollinger_lower": 180.0,
    "bollinger_position": "mid",
    "next_earnings_date": "2026-09-01",
    "volume_spikes": [],
}


def test_fetch_screener_row_success():
    close_d = pd.Series([190.0] * 100)
    mock_client = MagicMock()
    mock_client.get_quotes.return_value = {"AAPL": {"lastPrice": 195.5, "closePrice": 190.0}}
    mock_client.get_option_chain.return_value = {"underlyingPrice": 195.5, "callExpDateMap": {}}
    mock_client.get_instrument_fundamentals.return_value = {"sector": "Technology"}

    with patch("app.services.screener_fetcher.fetch_technicals", return_value=(MOCK_TECHNICALS, close_d)), \
         patch("app.services.screener_fetcher.get_schwab_client", return_value=mock_client), \
         patch("app.services.screener_fetcher.compute_iv_percentile_from_chain", return_value=(45.0, 0.25)):
        result = fetch_screener_row("AAPL")

    assert result["fetch_status"] == "ok"
    assert result["price"] == 195.5
    assert result["prev_close"] == 190.0
    assert result["change_pct"] == round((195.5 - 190.0) / 190.0 * 100, 2)
    assert result["iv_percentile"] == 45.0
    assert result["rsi_14"] == 55.2
    assert result["macd_weekly_signal"] == "bullish"
    assert result["macd_daily_signal"] == "bullish"
    assert result["ma_20d"] == 190.0
    assert result["sector"] == "Technology"


def test_fetch_screener_row_propagates_technicals_error():
    with patch(
        "app.services.screener_fetcher.fetch_technicals",
        return_value=({"fetch_status": "error", "fetch_error": "No daily data for ZZZZ"}, pd.Series(dtype=float)),
    ):
        result = fetch_screener_row("ZZZZ")

    assert result == {"fetch_status": "error", "fetch_error": "No daily data for ZZZZ"}


def test_fetch_screener_row_handles_schwab_api_error():
    with patch("app.services.screener_fetcher.fetch_technicals", side_effect=SchwabAPIError("rate limited")):
        result = fetch_screener_row("AAPL")

    assert result["fetch_status"] == "error"
    assert "rate limited" in result["fetch_error"]


def test_fetch_screener_row_sector_lookup_failure_falls_back_to_existing():
    close_d = pd.Series([190.0] * 100)
    mock_client = MagicMock()
    mock_client.get_quotes.return_value = {"AAPL": {"lastPrice": 195.5, "closePrice": 190.0}}
    mock_client.get_option_chain.return_value = {"underlyingPrice": 195.5, "callExpDateMap": {}}
    mock_client.get_instrument_fundamentals.side_effect = Exception("no fundamentals endpoint")

    with patch("app.services.screener_fetcher.fetch_technicals", return_value=(MOCK_TECHNICALS, close_d)), \
         patch("app.services.screener_fetcher.get_schwab_client", return_value=mock_client), \
         patch("app.services.screener_fetcher.compute_iv_percentile_from_chain", return_value=(None, None)):
        result = fetch_screener_row("AAPL", existing_sector="Manually Set Sector")

    assert result["fetch_status"] == "ok"
    assert result["sector"] == "Manually Set Sector"
