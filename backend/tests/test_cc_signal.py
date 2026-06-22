import pytest
import pandas as pd
import numpy as np
from datetime import date, timedelta


def _make_daily_closes(n=252, base=100.0, volatility=0.02):
    np.random.seed(42)
    returns = np.random.normal(0.0005, volatility, n)
    prices = base * np.cumprod(1 + returns)
    idx = pd.date_range(end=date.today(), periods=n, freq="B")
    return pd.Series(prices, index=idx, name="Close")


def _make_technicals(overrides=None):
    base = {
        "rsi_14": 72.0,
        "rsi_result": "rsi_overbought",
        "bollinger_position": "near_upper",
        "macd_signal": "bullish",
        "macd_notes": "above 0 line",
        "day_color": "green",
        "price_vs_ma50": "above",
        "price_vs_ma200": "above",
        "ma_50d": 130.0,
        "ma_200d": 120.0,
        "price_action": "142.50",
        "next_earnings_date": None,
        "bollinger_upper": 145.0,
        "bollinger_mid": 135.0,
        "bollinger_lower": 125.0,
        "sentiment": "bullish",
        "fetch_status": "ok",
        "fetch_error": None,
        "notes": None,
    }
    if overrides:
        base.update(overrides)
    return base


def test_score_factors_bullish_setup():
    from app.services.cc_signal import _score_factors
    closes = _make_daily_closes()
    technicals = _make_technicals()
    score, grade, factors = _score_factors(technicals, iv_percentile=72.0, atm_iv=0.42, daily_closes=closes)
    assert 60 <= score <= 100
    assert grade in ("strong", "moderate")
    assert len(factors) == 8
    assert all("name" in f and "points" in f and "max" in f and "detail" in f for f in factors)


def test_score_factors_bearish_setup():
    from app.services.cc_signal import _score_factors
    closes = _make_daily_closes(volatility=0.01)
    technicals = _make_technicals({
        "rsi_14": 45.0,
        "rsi_result": None,
        "bollinger_position": "near_lower",
        "macd_signal": "bearish",
        "day_color": "red",
        "price_vs_ma50": "below",
    })
    score, grade, factors = _score_factors(technicals, iv_percentile=20.0, atm_iv=0.18, daily_closes=closes)
    assert score < 40
    assert grade in ("weak", "wait")


def test_score_factors_no_iv():
    from app.services.cc_signal import _score_factors
    closes = _make_daily_closes()
    technicals = _make_technicals()
    score, grade, factors = _score_factors(technicals, iv_percentile=None, atm_iv=None, daily_closes=closes)
    iv_factor = next(f for f in factors if f["name"] == "IV Percentile")
    assert iv_factor["points"] == 0


def test_iv_override_lowers_threshold():
    from app.services.cc_signal import _score_factors
    closes = _make_daily_closes()
    technicals = _make_technicals({
        "rsi_14": 62.0,
        "rsi_result": None,
        "bollinger_position": "mid",
        "macd_signal": "neutral",
        "day_color": "red",
        "price_vs_ma50": "above",
    })
    score, grade, factors = _score_factors(technicals, iv_percentile=75.0, atm_iv=0.50, daily_closes=closes)
    assert grade in ("strong", "moderate")


def test_earnings_distance_no_date():
    from app.services.cc_signal import _score_factors
    closes = _make_daily_closes()
    t = _make_technicals({"next_earnings_date": None})
    _, _, factors = _score_factors(t, 50.0, 0.30, closes)
    earn = next(f for f in factors if f["name"] == "Earnings Distance")
    assert earn["points"] == 10


def test_earnings_distance_close():
    from app.services.cc_signal import _score_factors
    closes = _make_daily_closes()
    near = (date.today() + timedelta(days=5)).isoformat()
    t = _make_technicals({"next_earnings_date": near})
    _, _, factors = _score_factors(t, 50.0, 0.30, closes)
    earn = next(f for f in factors if f["name"] == "Earnings Distance")
    assert earn["points"] == 0


def test_momentum_exhaustion_factor_exists():
    from app.services.cc_signal import _score_factors
    closes = _make_daily_closes()
    technicals = _make_technicals({"rsi_14": 63.0})
    _, _, factors = _score_factors(technicals, 50.0, 0.30, closes)
    momentum = next(f for f in factors if f["name"] == "Momentum Exhaustion")
    assert momentum["max"] == 10
    assert 0 <= momentum["points"] <= 10
