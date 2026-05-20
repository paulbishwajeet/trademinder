import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

from app.services.technicals_fetcher import (
    fetch_technicals,
    _compute_macd_weekly,
    _bollinger_position,
    _infer_sentiment,
)


def _daily(n: int = 200, start: float = 100.0, step: float = 0.25) -> pd.DataFrame:
    close = pd.Series([start + i * step for i in range(n)])
    return pd.DataFrame({"Close": close})


def _weekly(n: int = 60, start: float = 95.0, step: float = 0.5) -> pd.DataFrame:
    close = pd.Series([start + i * step for i in range(n)])
    return pd.DataFrame({"Close": close})


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
    mock_calendar = {"Earnings Date": ["2026-08-15"]}

    with patch("app.services.technicals_fetcher.yf.download") as mock_dl, \
         patch("app.services.technicals_fetcher.yf.Ticker") as mock_ticker:
        mock_dl.side_effect = [_daily(200), _weekly(60)]
        mock_ticker.return_value.calendar = mock_calendar

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
    with patch("app.services.technicals_fetcher.yf.download") as mock_dl:
        mock_dl.return_value = pd.DataFrame()
        result = fetch_technicals("INVALID")

    assert result["fetch_status"] == "error"
    assert result["fetch_error"] is not None


def test_fetch_technicals_insufficient_daily_rows():
    with patch("app.services.technicals_fetcher.yf.download") as mock_dl:
        mock_dl.side_effect = [_daily(1), _weekly(60)]
        result = fetch_technicals("AAPL")

    assert result["fetch_status"] == "error"


def test_fetch_technicals_no_ma200_when_insufficient_history():
    with patch("app.services.technicals_fetcher.yf.download") as mock_dl, \
         patch("app.services.technicals_fetcher.yf.Ticker") as mock_ticker:
        mock_dl.side_effect = [_daily(60), _weekly(60)]
        mock_ticker.return_value.calendar = {}
        result = fetch_technicals("AAPL")

    assert result["fetch_status"] == "ok"
    assert result["ma_200d"] is None   # only 60 bars
    assert result["ma_50d"] is not None  # 60 >= 50


def test_fetch_technicals_exception_returns_error():
    with patch("app.services.technicals_fetcher.yf.download", side_effect=RuntimeError("timeout")):
        result = fetch_technicals("AAPL")
    assert result["fetch_status"] == "error"
    assert "timeout" in result["fetch_error"]
