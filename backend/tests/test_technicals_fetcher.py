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
    idx = pd.date_range(end=pd.Timestamp.now(tz="UTC"), periods=n + 1, freq="B")[-n:]
    return pd.DataFrame(
        {"Open": close, "High": close, "Low": close, "Close": close, "Volume": [1_000_000] * n},
        index=idx,
    )


def _make_weekly_df(n: int = 60, base: float = 95.0, step: float = 0.5) -> pd.DataFrame:
    close = [base + i * step for i in range(n)]
    idx = pd.date_range(end=pd.Timestamp.now(tz="UTC"), periods=n + 1, freq="W")[-n:]
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


# --- unit tests for _macd_crossover_state ---

from app.services.technicals_fetcher import _macd_crossover_state


def _make_weekly_close(values: list[float]) -> pd.Series:
    idx = pd.date_range(end=pd.Timestamp("2026-08-03", tz="UTC"), periods=len(values) + 1, freq="W")[-len(values):]
    return pd.Series(values, index=idx)


def test_macd_crossover_insufficient_data_returns_all_none():
    close = _make_weekly_close([100.0] * 10)
    result = _macd_crossover_state(close)
    assert result == {
        "cross_date": None,
        "cross_direction": None,
        "periods_since_cross": None,
        "strength_score": None,
        "trend": None,
    }


def test_macd_crossover_bullish_fading_near_flip():
    # 30 weeks falling, 25 weeks rising sharply (bullish crossover), 5 weeks pulling back (squeeze)
    down = [200.0 - i * 2.0 for i in range(30)]
    up = [down[-1] + i * 3.0 for i in range(1, 26)]
    flat = [up[-1] - i * 0.5 for i in range(1, 6)]
    close = _make_weekly_close(down + up + flat)

    result = _macd_crossover_state(close)

    assert result["cross_date"] == "2026-01-25"
    assert result["cross_direction"] == "bullish"
    assert result["periods_since_cross"] == 27
    assert result["strength_score"] == 12.2
    assert result["trend"] == "fading_near_flip"


def test_macd_crossover_bearish_fading_near_flip():
    # Mirror image of the bullish case: rising, then falling sharply (bearish crossover), then a small bounce
    up = [100.0 + i * 2.0 for i in range(30)]
    down = [up[-1] - i * 3.0 for i in range(1, 26)]
    bounce = [down[-1] + i * 0.5 for i in range(1, 6)]
    close = _make_weekly_close(up + down + bounce)

    result = _macd_crossover_state(close)

    assert result["cross_date"] == "2026-01-25"
    assert result["cross_direction"] == "bearish"
    assert result["periods_since_cross"] == 27
    assert result["strength_score"] == 12.2
    assert result["trend"] == "fading_near_flip"


def test_macd_crossover_squeezing():
    # Steady compounding growth (1% per week) - gap narrows to a mid-range score after the initial ramp
    close = _make_weekly_close([100.0 * (1.01 ** i) for i in range(60)])
    result = _macd_crossover_state(close)

    assert result["cross_direction"] == "bullish"
    assert result["strength_score"] == 42.8
    assert result["trend"] == "squeezing"


def test_macd_crossover_holding_strong():
    close = _make_weekly_close([100.0 * (1.016 ** i) for i in range(60)])
    result = _macd_crossover_state(close)

    assert result["strength_score"] == 75.5
    assert result["trend"] == "holding_strong"


def test_macd_crossover_expanding_at_peak():
    # Strong compounding growth - the gap is still widening at the very last bar
    close = _make_weekly_close([100.0 * (1.02 ** i) for i in range(60)])
    result = _macd_crossover_state(close)

    assert result["strength_score"] == 100.0
    assert result["trend"] == "expanding"


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


def test_fetch_technicals_includes_macd_crossover_fields():
    mock_client = _mock_client(_make_daily_df(200), _make_weekly_df(60))
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client), \
         patch("yfinance.Ticker") as mock_ticker:
        mock_ticker.return_value.calendar = {}
        result = fetch_technicals("AAPL")

    assert result["fetch_status"] == "ok"
    for prefix in ("weekly", "daily"):
        assert f"macd_{prefix}_cross_date" in result
        assert f"macd_{prefix}_cross_direction" in result
        assert f"macd_{prefix}_periods_since_cross" in result
        assert f"macd_{prefix}_strength_score" in result
        assert f"macd_{prefix}_trend" in result


def test_fetch_technicals_schwab_error_returns_error():
    from app.services.schwab_client import SchwabAPIError
    mock_client = MagicMock()
    mock_client.get_price_history.side_effect = SchwabAPIError("network error")
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        result = fetch_technicals("AAPL")

    assert result["fetch_status"] == "error"
    assert "network error" in result["fetch_error"]


# --- fetch_macd_crossover (standalone) ---

from app.services.technicals_fetcher import fetch_macd_crossover


def test_fetch_macd_crossover_success():
    mock_client = MagicMock()
    mock_client.get_price_history.side_effect = [_make_weekly_df(60), _make_daily_df(200)]
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        result = fetch_macd_crossover("AAPL")

    assert result["fetch_status"] == "ok"
    assert result["fetch_error"] is None
    assert set(result["weekly"].keys()) == {"cross_date", "cross_direction", "periods_since_cross", "strength_score", "trend"}
    assert set(result["daily"].keys()) == {"cross_date", "cross_direction", "periods_since_cross", "strength_score", "trend"}
    mock_client.get_price_history.assert_any_call("AAPL", "year", 2, "weekly", 1)
    mock_client.get_price_history.assert_any_call("AAPL", "year", 1, "daily", 1)


def test_fetch_macd_crossover_no_weekly_data_raises_value_error():
    mock_client = MagicMock()
    mock_client.get_price_history.side_effect = [pd.DataFrame(), _make_daily_df(200)]
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        with pytest.raises(ValueError):
            fetch_macd_crossover("INVALID")


def test_fetch_macd_crossover_no_daily_data_raises_value_error():
    mock_client = MagicMock()
    mock_client.get_price_history.side_effect = [_make_weekly_df(60), pd.DataFrame()]
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        with pytest.raises(ValueError):
            fetch_macd_crossover("INVALID")


def test_fetch_macd_crossover_schwab_error_returns_error_status():
    from app.services.schwab_client import SchwabAPIError
    mock_client = MagicMock()
    mock_client.get_price_history.side_effect = SchwabAPIError("network error")
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        result = fetch_macd_crossover("AAPL")

    assert result["fetch_status"] == "error"
    assert "network error" in result["fetch_error"]
    assert result["weekly"]["cross_date"] is None
    assert result["daily"]["cross_date"] is None


def test_fetch_macd_crossover_insufficient_history_returns_ok_with_none_fields():
    mock_client = MagicMock()
    mock_client.get_price_history.side_effect = [_make_weekly_df(10), _make_daily_df(10)]
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        result = fetch_macd_crossover("AAPL")

    assert result["fetch_status"] == "ok"
    assert result["weekly"]["cross_date"] is None
    assert result["daily"]["cross_date"] is None
