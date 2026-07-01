import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

from app.services.technicals_fetcher import (
    fetch_technicals,
    _compute_macd_weekly,
    _bollinger_position,
    _infer_sentiment,
)


def _make_daily_df(n: int = 200, base: float = 100.0, step: float = 0.25) -> pd.DataFrame:
    close = [base + i * step for i in range(n)]
    idx = pd.date_range(end=pd.Timestamp.now(tz="UTC"), periods=n, freq="B")
    return pd.DataFrame(
        {"Open": close, "High": close, "Low": close, "Close": close, "Volume": [1_000_000] * n},
        index=idx,
    )


def _make_weekly_df(n: int = 60, base: float = 95.0, step: float = 0.5) -> pd.DataFrame:
    close = [base + i * step for i in range(n)]
    idx = pd.date_range(end=pd.Timestamp.now(tz="UTC"), periods=n, freq="W")
    return pd.DataFrame(
        {"Open": close, "High": close, "Low": close, "Close": close, "Volume": [500_000] * n},
        index=idx,
    )


def _mock_client(daily_df, weekly_df):
    client = MagicMock()
    client.get_price_history.side_effect = [daily_df, weekly_df]
    return client


# --- unit tests for helpers ---

def test_bollinger_above_upper():
    assert _bollinger_position(125.0, 120.0, 100.0, 80.0) == "above_upper"

def test_bollinger_near_upper():
    assert _bollinger_position(116.0, 120.0, 100.0, 80.0) == "near_upper"

def test_bollinger_mid():
    assert _bollinger_position(100.0, 120.0, 100.0, 80.0) == "mid"

def test_bollinger_near_lower():
    assert _bollinger_position(84.0, 120.0, 100.0, 80.0) == "near_lower"

def test_bollinger_below_lower():
    assert _bollinger_position(75.0, 120.0, 100.0, 80.0) == "below_lower"

def test_bollinger_zero_band_returns_mid():
    assert _bollinger_position(100.0, 100.0, 100.0, 100.0) == "mid"


def test_infer_sentiment_bullish():
    assert _infer_sentiment("bullish", 110.0, 100.0, 50.0) == "bullish"

def test_infer_sentiment_bullish_overbought_rsi():
    # RSI > 70 → not bullish
    assert _infer_sentiment("bullish", 110.0, 100.0, 75.0) == "neutral"

def test_infer_sentiment_bearish():
    assert _infer_sentiment("bearish", 90.0, 100.0, 50.0) == "bearish"

def test_infer_sentiment_mixed_neutral():
    assert _infer_sentiment("bullish", 90.0, 100.0, 50.0) == "neutral"

def test_infer_sentiment_no_ma50():
    assert _infer_sentiment("bullish", 110.0, None, 50.0) == "neutral"


def test_macd_weekly_bullish():
    # Rising series → MACD line above signal
    close = pd.Series([100.0 + i for i in range(60)])
    result = _compute_macd_weekly(close)
    assert result["macd_signal"] == "bullish"
    assert result["macd_notes"] == "above 0 line"

def test_macd_weekly_bearish():
    # Falling series
    close = pd.Series([200.0 - i for i in range(60)])
    result = _compute_macd_weekly(close)
    assert result["macd_signal"] == "bearish"

def test_macd_weekly_insufficient_data():
    close = pd.Series([100.0] * 10)
    result = _compute_macd_weekly(close)
    assert result["macd_signal"] == "neutral"


# --- integration: fetch_technicals ---

def test_fetch_technicals_success():
    mock_client = _mock_client(_make_daily_df(200), _make_weekly_df(60))
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client), \
         patch("yfinance.Ticker") as mock_ticker:
        mock_ticker.return_value.calendar = {"Earnings Date": ["2026-08-15"]}
        result = fetch_technicals("AAPL")

    assert result["fetch_status"] == "ok"
    assert result["fetch_error"] is None
    assert result["price_action"] is not None
    assert result["rsi_14"] is not None
    assert result["ma_200d"] is not None
    assert result["ma_50d"] is not None
    assert result["bollinger_upper"] is not None
    assert result["macd_signal"] in ("bullish", "bearish", "neutral")
    assert result["sentiment"] in ("bullish", "bearish", "neutral")
    assert result["next_earnings_date"] == "2026-08-15"
    assert result["day_color"] in ("green", "red")


def test_fetch_technicals_empty_daily_data():
    mock_client = MagicMock()
    mock_client.get_price_history.return_value = pd.DataFrame()
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        result = fetch_technicals("INVALID")

    assert result["fetch_status"] == "error"
    assert result["fetch_error"] is not None


def test_fetch_technicals_insufficient_daily_rows():
    mock_client = _mock_client(_make_daily_df(1), _make_weekly_df(60))
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        result = fetch_technicals("AAPL")

    assert result["fetch_status"] == "error"


def test_fetch_technicals_no_ma200_when_insufficient_history():
    mock_client = _mock_client(_make_daily_df(60), _make_weekly_df(60))
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client), \
         patch("yfinance.Ticker") as mock_ticker:
        mock_ticker.return_value.calendar = {}
        result = fetch_technicals("AAPL")

    assert result["fetch_status"] == "ok"
    assert result["ma_200d"] is None
    assert result["ma_50d"] is not None


def test_fetch_technicals_schwab_error_returns_error():
    from app.services.schwab_client import SchwabAPIError
    mock_client = MagicMock()
    mock_client.get_price_history.side_effect = SchwabAPIError("network error")
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        result = fetch_technicals("AAPL")

    assert result["fetch_status"] == "error"
    assert "network error" in result["fetch_error"]
