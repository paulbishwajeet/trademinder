import pandas as pd
import numpy as np
from datetime import date


def _make_daily_closes(n=252, base=100.0, volatility=0.01, trend=0.0):
    """trend > 0 drifts price up over the series (used to place price near/above recent highs)."""
    np.random.seed(7)
    returns = np.random.normal(trend, volatility, n)
    prices = base * np.cumprod(1 + returns)
    idx = pd.date_range(end=date.today(), periods=n, freq="B")
    return pd.Series(prices, index=idx, name="Close")


def _make_technicals(overrides=None):
    base = {
        "rsi_14": 72.0,
        "macd_signal": "bearish",
        "macd_notes": "below 0 line",
    }
    if overrides:
        base.update(overrides)
    return base


def test_rsi_level_curve():
    from app.services.cc_timing_signal import _score_cc_timing_factors
    closes = _make_daily_closes()
    live_price = float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2])

    _, _, factors_high = _score_cc_timing_factors(_make_technicals({"rsi_14": 75.0}), closes, live_price, prev_close)
    _, _, factors_mid = _score_cc_timing_factors(_make_technicals({"rsi_14": 60.0}), closes, live_price, prev_close)
    _, _, factors_low = _score_cc_timing_factors(_make_technicals({"rsi_14": 40.0}), closes, live_price, prev_close)

    rsi_high = next(f for f in factors_high if f["name"] == "RSI(D) Level")
    rsi_mid = next(f for f in factors_mid if f["name"] == "RSI(D) Level")
    rsi_low = next(f for f in factors_low if f["name"] == "RSI(D) Level")

    assert rsi_high["points"] == 20
    assert rsi_mid["points"] == pytest_approx(17.0)  # 14 + (60-50)*0.3
    assert rsi_low["points"] == pytest_approx(7.0)    # (40-30)*0.7
    assert rsi_high["max"] == 20


def pytest_approx(value, tol=0.01):
    class _Approx:
        def __eq__(self, other):
            return abs(other - value) < tol
    return _Approx()


def test_macd_weekly_bearish_scores_max():
    from app.services.cc_timing_signal import _score_cc_timing_factors
    closes = _make_daily_closes()
    live_price = float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2])

    _, _, factors = _score_cc_timing_factors(_make_technicals({"macd_signal": "bearish"}), closes, live_price, prev_close)
    macd = next(f for f in factors if f["name"] == "MACD(W)")
    assert macd["points"] == 25
    assert macd["max"] == 25

    _, _, factors_bull = _score_cc_timing_factors(_make_technicals({"macd_signal": "bullish"}), closes, live_price, prev_close)
    macd_bull = next(f for f in factors_bull if f["name"] == "MACD(W)")
    assert macd_bull["points"] == 0


def test_day_color_scoring():
    from app.services.cc_timing_signal import _score_cc_timing_factors
    closes = _make_daily_closes()
    prev_close = 100.0

    _, _, factors_green = _score_cc_timing_factors(_make_technicals(), closes, live_price=101.0, prev_close=prev_close)
    _, _, factors_red = _score_cc_timing_factors(_make_technicals(), closes, live_price=99.0, prev_close=prev_close)

    day_green = next(f for f in factors_green if f["name"] == "Day Color")
    day_red = next(f for f in factors_red if f["name"] == "Day Color")
    assert day_green["points"] == 15
    assert day_red["points"] == 0


def test_swing_high_distance_new_high_scores_zero():
    from app.services.cc_timing_signal import _score_cc_timing_factors
    closes = _make_daily_closes(n=100, base=100.0, volatility=0.001, trend=0.0)
    recent_high = float(closes.iloc[-63:].max())
    live_price = recent_high * 1.02  # above the 3M high

    _, _, factors = _score_cc_timing_factors(_make_technicals(), closes, live_price, prev_close=live_price)
    swing = next(f for f in factors if f["name"] == "Swing High Distance")
    assert swing["points"] == 0
    assert "New high" in swing["detail"]


def test_swing_high_distance_at_resistance_scores_max():
    from app.services.cc_timing_signal import _score_cc_timing_factors
    closes = _make_daily_closes(n=100, base=100.0, volatility=0.001, trend=0.0)
    recent_high = float(closes.iloc[-63:].max())
    live_price = recent_high * 0.99  # 1% below the 3M high

    _, _, factors = _score_cc_timing_factors(_make_technicals(), closes, live_price, prev_close=live_price)
    swing = next(f for f in factors if f["name"] == "Swing High Distance")
    assert swing["points"] == 15


def test_confluence_bonus_applied_for_perfect_setup():
    from app.services.cc_timing_signal import _score_cc_timing_factors
    closes = _make_daily_closes(n=100, base=100.0, volatility=0.001, trend=0.0)
    recent_high = float(closes.iloc[-63:].max())
    live_price = recent_high * 0.99
    prev_close = live_price / 1.01  # >0.5% green day

    technicals = _make_technicals({"rsi_14": 75.0, "macd_signal": "bearish"})
    score, grade, factors = _score_cc_timing_factors(technicals, closes, live_price, prev_close)

    base_total = sum(f["points"] for f in factors)
    assert score == min(100, round(base_total) + 10)
    assert grade == "strong"


def test_confluence_bonus_not_applied_when_macd_bullish():
    from app.services.cc_timing_signal import _score_cc_timing_factors
    closes = _make_daily_closes(n=100, base=100.0, volatility=0.001, trend=0.0)
    recent_high = float(closes.iloc[-63:].max())
    live_price = recent_high * 0.99
    prev_close = live_price / 1.01

    technicals = _make_technicals({"rsi_14": 75.0, "macd_signal": "bullish"})
    score, grade, factors = _score_cc_timing_factors(technicals, closes, live_price, prev_close)

    base_total = sum(f["points"] for f in factors)
    assert score == round(base_total)


def test_grade_thresholds():
    from app.services.cc_timing_signal import _score_cc_timing_factors
    closes = _make_daily_closes(n=100, base=100.0, volatility=0.02, trend=0.0)
    live_price = float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2])

    # Worst-case technicals: oversold, bullish weekly MACD, red day
    technicals = _make_technicals({"rsi_14": 20.0, "macd_signal": "bullish"})
    score, grade, _ = _score_cc_timing_factors(technicals, closes, live_price=prev_close * 0.98, prev_close=prev_close)
    assert grade == "wait"
    assert score < 40


def test_returns_seven_factors():
    from app.services.cc_timing_signal import _score_cc_timing_factors
    closes = _make_daily_closes()
    live_price = float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2])
    _, _, factors = _score_cc_timing_factors(_make_technicals(), closes, live_price, prev_close)
    assert len(factors) == 6
    assert all("name" in f and "points" in f and "max" in f and "detail" in f for f in factors)
