import pandas as pd
import numpy as np
from datetime import date


def _make_daily_closes(n=252, base=100.0, volatility=0.01, trend=0.0):
    np.random.seed(11)
    returns = np.random.normal(trend, volatility, n)
    prices = base * np.cumprod(1 + returns)
    idx = pd.date_range(end=date.today(), periods=n, freq="B")
    return pd.Series(prices, index=idx, name="Close")


def _make_technicals(overrides=None):
    base = {
        "rsi_14": 35.0,
        "macd_signal": "bullish",
        "macd_notes": "above 0 line",
    }
    if overrides:
        base.update(overrides)
    return base


def _approx(value, tol=0.01):
    class _Approx:
        def __eq__(self, other):
            return abs(other - value) < tol
    return _Approx()


def test_rsi_level_curve():
    from app.services.sp_timing_signal import _score_sp_timing_factors
    closes = _make_daily_closes()
    live_price = float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2])

    _, _, factors_low = _score_sp_timing_factors(_make_technicals({"rsi_14": 30.0}), closes, live_price, prev_close)
    _, _, factors_mid = _score_sp_timing_factors(_make_technicals({"rsi_14": 50.0}), closes, live_price, prev_close)
    _, _, factors_high = _score_sp_timing_factors(_make_technicals({"rsi_14": 70.0}), closes, live_price, prev_close)

    rsi_low = next(f for f in factors_low if f["name"] == "RSI(D) Level")
    rsi_mid = next(f for f in factors_mid if f["name"] == "RSI(D) Level")
    rsi_high = next(f for f in factors_high if f["name"] == "RSI(D) Level")

    assert rsi_low["points"] == 20
    assert rsi_mid["points"] == _approx(17.0)  # 14 + (60-50)*0.3
    assert rsi_high["points"] == _approx(7.0)   # (80-70)*0.7
    assert rsi_low["max"] == 20


def test_macd_weekly_bullish_scores_max():
    from app.services.sp_timing_signal import _score_sp_timing_factors
    closes = _make_daily_closes()
    live_price = float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2])

    _, _, factors = _score_sp_timing_factors(_make_technicals({"macd_signal": "bullish"}), closes, live_price, prev_close)
    macd = next(f for f in factors if f["name"] == "MACD(W)")
    assert macd["points"] == 25
    assert macd["max"] == 25

    _, _, factors_bear = _score_sp_timing_factors(_make_technicals({"macd_signal": "bearish"}), closes, live_price, prev_close)
    macd_bear = next(f for f in factors_bear if f["name"] == "MACD(W)")
    assert macd_bear["points"] == 0


def test_macd_weekly_bullish_exhaustion_reduces_points():
    from app.services.sp_timing_signal import _score_sp_timing_factors
    closes = _make_daily_closes()
    live_price = float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2])

    _, _, factors_fresh = _score_sp_timing_factors(
        _make_technicals({"macd_signal": "bullish", "macd_weekly_trend": "expanding"}), closes, live_price, prev_close
    )
    _, _, factors_squeeze = _score_sp_timing_factors(
        _make_technicals({"macd_signal": "bullish", "macd_weekly_trend": "squeezing"}), closes, live_price, prev_close
    )
    _, _, factors_fade = _score_sp_timing_factors(
        _make_technicals({"macd_signal": "bullish", "macd_weekly_trend": "fading_near_flip"}), closes, live_price, prev_close
    )

    assert next(f for f in factors_fresh if f["name"] == "MACD(W)")["points"] == 25
    assert next(f for f in factors_squeeze if f["name"] == "MACD(W)")["points"] == 18
    fade_factor = next(f for f in factors_fade if f["name"] == "MACD(W)")
    assert fade_factor["points"] == 12
    assert fade_factor["max"] == 25
    assert "exhaustion" in fade_factor["detail"]


def test_macd_weekly_trend_ignored_when_bearish():
    from app.services.sp_timing_signal import _score_sp_timing_factors
    closes = _make_daily_closes()
    live_price = float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2])

    # Trend should have no effect when macd_signal is already the "bad" direction for SP.
    _, _, factors = _score_sp_timing_factors(
        _make_technicals({"macd_signal": "bearish", "macd_weekly_trend": "fading_near_flip"}), closes, live_price, prev_close
    )
    assert next(f for f in factors if f["name"] == "MACD(W)")["points"] == 0


def test_rsi_trend_bullish_cross_scores_by_freshness():
    from app.services.sp_timing_signal import _score_sp_timing_factors
    closes = _make_daily_closes()
    live_price = float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2])

    _, _, factors_fresh = _score_sp_timing_factors(
        _make_technicals({"rsi_cross_direction": "bullish", "rsi_trend": "expanding"}), closes, live_price, prev_close
    )
    _, _, factors_squeeze = _score_sp_timing_factors(
        _make_technicals({"rsi_cross_direction": "bullish", "rsi_trend": "squeezing"}), closes, live_price, prev_close
    )
    _, _, factors_fade = _score_sp_timing_factors(
        _make_technicals({"rsi_cross_direction": "bullish", "rsi_trend": "fading_near_flip"}), closes, live_price, prev_close
    )

    assert next(f for f in factors_fresh if f["name"] == "RSI(D) Trend")["points"] == 10
    assert next(f for f in factors_squeeze if f["name"] == "RSI(D) Trend")["points"] == 6
    fade_factor = next(f for f in factors_fade if f["name"] == "RSI(D) Trend")
    assert fade_factor["points"] == 3
    assert fade_factor["max"] == 10


def test_rsi_trend_bearish_cross_scores_zero():
    from app.services.sp_timing_signal import _score_sp_timing_factors
    closes = _make_daily_closes()
    live_price = float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2])

    _, _, factors = _score_sp_timing_factors(
        _make_technicals({"rsi_cross_direction": "bearish", "rsi_trend": "expanding"}), closes, live_price, prev_close
    )
    assert next(f for f in factors if f["name"] == "RSI(D) Trend")["points"] == 0


def test_rsi_trend_no_crossover_data_falls_back_to_neutral():
    from app.services.sp_timing_signal import _score_sp_timing_factors
    closes = _make_daily_closes()
    live_price = float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2])

    _, _, factors = _score_sp_timing_factors(
        _make_technicals({"rsi_cross_direction": None, "rsi_trend": None}), closes, live_price, prev_close
    )
    assert next(f for f in factors if f["name"] == "RSI(D) Trend")["points"] == 3


def test_day_color_scoring():
    from app.services.sp_timing_signal import _score_sp_timing_factors
    closes = _make_daily_closes()
    prev_close = 100.0

    _, _, factors_red = _score_sp_timing_factors(_make_technicals(), closes, live_price=99.0, prev_close=prev_close)
    _, _, factors_green = _score_sp_timing_factors(_make_technicals(), closes, live_price=101.0, prev_close=prev_close)

    day_red = next(f for f in factors_red if f["name"] == "Day Color")
    day_green = next(f for f in factors_green if f["name"] == "Day Color")
    assert day_red["points"] == 15
    assert day_green["points"] == 0


def test_swing_low_distance_new_low_scores_zero():
    from app.services.sp_timing_signal import _score_sp_timing_factors
    closes = _make_daily_closes(n=100, base=100.0, volatility=0.001, trend=0.0)
    recent_low = float(closes.iloc[-63:].min())
    live_price = recent_low * 0.98  # below the 3M low

    _, _, factors = _score_sp_timing_factors(_make_technicals(), closes, live_price, prev_close=live_price)
    swing = next(f for f in factors if f["name"] == "Swing Low Distance")
    assert swing["points"] == 0
    assert "New low" in swing["detail"]


def test_swing_low_distance_at_support_scores_max():
    from app.services.sp_timing_signal import _score_sp_timing_factors
    closes = _make_daily_closes(n=100, base=100.0, volatility=0.001, trend=0.0)
    recent_low = float(closes.iloc[-63:].min())
    live_price = recent_low * 1.01  # 1% above the 3M low

    _, _, factors = _score_sp_timing_factors(_make_technicals(), closes, live_price, prev_close=live_price)
    swing = next(f for f in factors if f["name"] == "Swing Low Distance")
    assert swing["points"] == 15


def test_confluence_bonus_applied_for_perfect_setup():
    from app.services.sp_timing_signal import _score_sp_timing_factors
    closes = _make_daily_closes(n=100, base=100.0, volatility=0.001, trend=0.0)
    recent_low = float(closes.iloc[-63:].min())
    live_price = recent_low * 1.01
    prev_close = live_price / 0.99  # >0.5% red day

    technicals = _make_technicals({"rsi_14": 35.0, "macd_signal": "bullish"})
    score, grade, factors = _score_sp_timing_factors(technicals, closes, live_price, prev_close)

    base_total = sum(f["points"] for f in factors)
    assert score == min(100, round(base_total) + 10)
    assert grade == "strong"


def test_confluence_bonus_not_applied_when_macd_bearish():
    from app.services.sp_timing_signal import _score_sp_timing_factors
    closes = _make_daily_closes(n=100, base=100.0, volatility=0.001, trend=0.0)
    recent_low = float(closes.iloc[-63:].min())
    live_price = recent_low * 1.01
    prev_close = live_price / 0.99

    technicals = _make_technicals({"rsi_14": 35.0, "macd_signal": "bearish"})
    score, grade, factors = _score_sp_timing_factors(technicals, closes, live_price, prev_close)

    base_total = sum(f["points"] for f in factors)
    assert score == round(base_total)


def test_grade_thresholds():
    from app.services.sp_timing_signal import _score_sp_timing_factors
    closes = _make_daily_closes(n=100, base=100.0, volatility=0.02, trend=0.0)
    live_price = float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2])

    # Worst-case technicals: overbought, bearish weekly MACD, green day
    technicals = _make_technicals({"rsi_14": 85.0, "macd_signal": "bearish"})
    score, grade, _ = _score_sp_timing_factors(technicals, closes, live_price=prev_close * 1.02, prev_close=prev_close)
    assert grade == "wait"
    assert score < 40


def test_returns_six_factors():
    from app.services.sp_timing_signal import _score_sp_timing_factors
    closes = _make_daily_closes()
    live_price = float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2])
    _, _, factors = _score_sp_timing_factors(_make_technicals(), closes, live_price, prev_close)
    assert len(factors) == 6
    assert all("name" in f and "points" in f and "max" in f and "detail" in f for f in factors)


def test_compute_fresh_uses_put_chain_and_applies_iv_gate():
    from unittest.mock import patch, MagicMock
    from datetime import date, timedelta

    closes = _make_daily_closes(n=100, base=100.0, volatility=0.001, trend=0.0)

    mock_client = MagicMock()
    mock_client.get_quotes.return_value = {"AAPL": {"lastPrice": float(closes.iloc[-1])}}

    exp_date = (date.today() + timedelta(days=37)).strftime("%Y-%m-%d")
    mock_client.get_option_chain.return_value = {
        "underlyingPrice": float(closes.iloc[-1]),
        "putExpDateMap": {
            f"{exp_date}:37": {
                str(round(float(closes.iloc[-1]))): [{"volatility": 1.2}],  # low IV -> gate triggers
            }
        },
    }

    technicals = {
        "rsi_14": 35.0,
        "macd_signal": "bullish",
        "macd_notes": "above 0 line",
        "fetch_status": "ok",
    }

    with patch("app.services.sp_timing_signal.get_schwab_client", return_value=mock_client), \
         patch("app.services.sp_timing_signal.fetch_technicals", return_value=(technicals, closes)), \
         patch("app.services.sp_timing_signal._get_llm_commentary", return_value={"commentary": None, "strike_hint": None, "caution": None}):
        from app.services.sp_timing_signal import _compute_sp_timing_fresh
        result = _compute_sp_timing_fresh("AAPL")

    assert result["fetch_status"] == "ok"
    assert result["ticker"] == "AAPL"
    mock_client.get_quotes.assert_called_once_with(["AAPL"])
    mock_client.get_option_chain.assert_called_once_with("AAPL", contract_type="PUT", strike_count=30)
    assert result["grade"] != "strong"
    assert result["caution"] is not None and "premium" in result["caution"].lower()


def test_compute_sp_timing_signal_uses_cache():
    from unittest.mock import patch
    import app.services.sp_timing_signal as mod

    mod._sp_timing_cache.clear()
    call_count = {"n": 0}

    def fake_fresh(ticker):
        call_count["n"] += 1
        return {"ticker": ticker, "score": 50, "grade": "moderate", "iv_percentile": None,
                "atm_iv": None, "spot_price": 100.0, "factors": [], "commentary": None,
                "strike_hint": None, "caution": None, "cached_at": "2026-01-01T00:00:00+00:00",
                "fetch_status": "ok", "fetch_error": None}

    with patch("app.services.sp_timing_signal._compute_sp_timing_fresh", side_effect=fake_fresh):
        mod.compute_sp_timing_signal("AAPL")
        mod.compute_sp_timing_signal("AAPL")  # should hit cache, not call fresh again
    assert call_count["n"] == 1

    with patch("app.services.sp_timing_signal._compute_sp_timing_fresh", side_effect=fake_fresh):
        mod.compute_sp_timing_signal("AAPL", force=True)  # force bypasses cache
    assert call_count["n"] == 2
