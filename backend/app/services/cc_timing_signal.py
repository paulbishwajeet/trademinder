"""Standalone 'CC Timing Signal' — scores how good a moment it is to sell a covered
call likely to expire OTM (mean-reversion entry timing), independent of the existing
CC/SP Signal in cc_signal.py, which optimizes for overall wheel P&L instead."""
import logging
import time
from datetime import datetime, timezone

import pandas as pd

from app.services.price_fetcher import _compute_rsi_14
from app.services.schwab_client import get_schwab_client
from app.services.technicals_fetcher import compute_iv_percentile_from_chain, fetch_technicals
from app.services.cc_signal import _get_llm_commentary

log = logging.getLogger(__name__)

_cc_timing_cache: dict[str, tuple[dict, float]] = {}
_CACHE_TTL = 14400  # 4 hours


def _score_cc_timing_factors(
    technicals: dict,
    daily_closes: pd.Series,
    live_price: float,
    prev_close: float,
) -> tuple[int, str, list[dict]]:
    factors: list[dict] = []

    # 1. RSI(D) Level (20 pts) — piecewise: gentle slope 50-70, steep slope 30-50.
    rsi = technicals.get("rsi_14")
    rsi_pts = 0.0
    rsi_detail = "N/A"
    if rsi is not None:
        rsi = float(rsi)
        if rsi >= 70:
            rsi_pts = 20.0
        elif rsi >= 50:
            rsi_pts = 14.0 + (rsi - 50) * 0.3
        elif rsi >= 30:
            rsi_pts = (rsi - 30) * 0.7
        else:
            rsi_pts = 0.0
        rsi_pts = round(rsi_pts, 1)
        rsi_detail = f"RSI {rsi:.1f}"
    factors.append({"name": "RSI(D) Level", "points": rsi_pts, "max": 20, "detail": rsi_detail})

    # 2. RSI(D) Trend (10 pts) — rolling over from an elevated read = ideal.
    trend_pts = 0
    trend_detail = "Insufficient data"
    if len(daily_closes) >= 20:
        rsi_series = []
        for i in range(6):
            offset = len(daily_closes) - 1 - i
            if offset < 14:
                break
            sub = daily_closes.iloc[: offset + 1]
            rsi_val = _compute_rsi_14(sub)
            if rsi_val is not None:
                rsi_series.append(rsi_val)
        if len(rsi_series) >= 2:
            current_rsi = rsi_series[0]
            oldest_rsi = rsi_series[-1]
            was_elevated = any(r > 60 for r in rsi_series)
            if was_elevated and current_rsi < oldest_rsi:
                trend_pts = 10
                trend_detail = f"Rolling over: {oldest_rsi:.1f} → {current_rsi:.1f}"
            elif was_elevated and current_rsi >= oldest_rsi:
                trend_pts = 6
                trend_detail = f"Elevated ({current_rsi:.1f}), not yet rolling over"
            elif current_rsi > oldest_rsi and current_rsi > 55:
                trend_pts = 1
                trend_detail = f"Rising strongly: {oldest_rsi:.1f} → {current_rsi:.1f}"
            else:
                trend_pts = 3
                trend_detail = f"Neutral/weak ({current_rsi:.1f})"
    factors.append({"name": "RSI(D) Trend", "points": trend_pts, "max": 10, "detail": trend_detail})

    # 3. MACD(W) (25 pts) — bearish weekly = overhead pressure, confirms the fade thesis.
    #    The crossover's trend matters too: a bearish read that's "fading_near_flip"
    #    (exhausted, reversal risk) is worth less than a fresh or sustained one.
    macd = technicals.get("macd_signal", "neutral")
    macd_trend = technicals.get("macd_weekly_trend")
    macd_map = {"bearish": 25, "neutral": 12, "bullish": 0}
    macd_pts = macd_map.get(macd, 0)
    trend_note = ""
    if macd == "bearish" and macd_trend == "squeezing":
        macd_pts = 18
        trend_note = ", squeezing"
    elif macd == "bearish" and macd_trend == "fading_near_flip":
        macd_pts = 12
        trend_note = ", fading (bearish exhaustion)"
    macd_notes = technicals.get("macd_notes", "")
    factors.append({"name": "MACD(W)", "points": macd_pts, "max": 25, "detail": f"{macd.capitalize()}, {macd_notes}{trend_note}"})

    # 4. Bollinger %B (15 pts) — continuous position within the bands; sweet spot is
    #    mid-to-upper without touching the extremes (overextended but not parabolic).
    bb_pts = 0
    bb_detail = "N/A"
    if len(daily_closes) >= 20:
        mean = float(daily_closes.rolling(20).mean().iloc[-1])
        std = float(daily_closes.rolling(20).std().iloc[-1])
        if std > 0:
            upper = mean + 2 * std
            lower = mean - 2 * std
            pct_b = (live_price - lower) / (upper - lower)
            if 0.65 <= pct_b <= 0.85:
                bb_pts = 15
            elif 0.5 <= pct_b < 0.65 or 0.85 < pct_b <= 1.0:
                bb_pts = 9
            elif 0.3 <= pct_b < 0.5:
                bb_pts = 5
            else:
                bb_pts = 0
            bb_detail = f"%B {pct_b:.2f}"
    factors.append({"name": "Bollinger %B", "points": bb_pts, "max": 15, "detail": bb_detail})

    # 5. Swing High Distance (15 pts) — trailing 3-month CLOSING high as resistance,
    #    same convention as cc_signal.py's Strike Safety factor.
    swing_pts = 0
    swing_detail = "Insufficient data"
    if len(daily_closes) >= 63:
        recent_high = float(daily_closes.iloc[-63:].max())
        if recent_high > 0:
            if live_price > recent_high:
                swing_pts = 0
                swing_detail = f"New high (${live_price:.2f} > 3M high ${recent_high:.2f})"
            else:
                dist_pct = (recent_high - live_price) / recent_high * 100
                if dist_pct <= 3:
                    swing_pts = 15
                    swing_detail = f"At resistance (-{dist_pct:.1f}% from 3M high ${recent_high:.2f})"
                elif dist_pct <= 8:
                    swing_pts = 8
                    swing_detail = f"Near resistance (-{dist_pct:.1f}% from 3M high ${recent_high:.2f})"
                else:
                    swing_pts = 0
                    swing_detail = f"Well below resistance (-{dist_pct:.1f}% from 3M high ${recent_high:.2f})"
    factors.append({"name": "Swing High Distance", "points": swing_pts, "max": 15, "detail": swing_detail})

    # 6. Day Color (15 pts) — green day = capturing richer premium on the pop.
    pct_chg = (live_price - prev_close) / prev_close * 100 if prev_close else 0.0
    if pct_chg > 0.5:
        day_pts = 15
        day_detail = f"Green ({pct_chg:+.1f}%)"
    elif pct_chg >= -0.5:
        day_pts = 7
        day_detail = f"Neutral ({pct_chg:+.1f}%)"
    else:
        day_pts = 0
        day_detail = f"Red ({pct_chg:+.1f}%)"
    factors.append({"name": "Day Color", "points": day_pts, "max": 15, "detail": day_detail})

    total = round(sum(f["points"] for f in factors))

    # Confluence bonus — reward the literal "perfect setup" beyond additive luck.
    is_perfect_setup = (
        rsi is not None and rsi >= 70
        and macd == "bearish"
        and pct_chg > 0.5
    )
    if is_perfect_setup:
        total = min(100, total + 10)

    if total >= 80:
        grade = "strong"
    elif total >= 60:
        grade = "moderate"
    elif total >= 40:
        grade = "weak"
    else:
        grade = "wait"

    return total, grade, factors


def _make_error_signal(ticker: str, exc: Exception) -> dict:
    return {
        "ticker": ticker, "score": 0, "grade": "wait",
        "iv_percentile": None, "atm_iv": None, "spot_price": None,
        "factors": [], "commentary": None, "strike_hint": None, "caution": None,
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "fetch_status": "error", "fetch_error": str(exc),
    }


def _compute_cc_timing_fresh(ticker: str) -> dict:
    technicals, close_d = fetch_technicals(ticker, return_closes=True)
    if technicals.get("fetch_status") != "ok":
        raise ValueError(f"Technicals fetch failed: {technicals.get('fetch_error')}")
    if close_d.empty:
        raise ValueError(f"No daily data for {ticker}")

    client = get_schwab_client()
    quotes = client.get_quotes([ticker])
    quote = quotes.get(ticker, {})
    try:
        live_price = float(quote.get("lastPrice", close_d.iloc[-1]))
    except Exception:
        live_price = float(close_d.iloc[-1])
    prev_close = float(close_d.iloc[-1])

    call_chain = client.get_option_chain(ticker, contract_type="CALL", strike_count=30)
    iv_percentile, atm_iv = compute_iv_percentile_from_chain(close_d, call_chain, ticker, contract_type="CALL")

    score, grade, factors = _score_cc_timing_factors(technicals, close_d, live_price, prev_close)

    commentary_data = _get_llm_commentary(ticker, score, grade, factors, technicals, iv_percentile, live_price)
    caution = commentary_data.get("caution")

    # Weekly MACD exhaustion — bearish confirmation that's fading is a reversal risk, not part of the score.
    if technicals.get("macd_signal") == "bearish" and technicals.get("macd_weekly_trend") == "fading_near_flip":
        periods = technicals.get("macd_weekly_periods_since_cross")
        periods_note = f" ({periods} weeks since the last cross)" if periods is not None else ""
        exhaustion_note = f"Weekly MACD is bearish but fading{periods_note} — reversal risk."
        caution = f"{caution} {exhaustion_note}" if caution else exhaustion_note

    # IV Percentile gate — caps the grade and flags thin premium; not part of the score.
    if iv_percentile is not None and iv_percentile < 20:
        if grade == "strong":
            grade = "moderate"
        gate_note = "Premium is thin (low IV percentile) — a technical setup alone might not be worth trading."
        caution = f"{caution} {gate_note}" if caution else gate_note

    return {
        "ticker": ticker,
        "score": score,
        "grade": grade,
        "iv_percentile": iv_percentile,
        "atm_iv": atm_iv,
        "spot_price": round(live_price, 2),
        "factors": factors,
        "commentary": commentary_data.get("commentary"),
        "strike_hint": commentary_data.get("strike_hint"),
        "caution": caution,
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "fetch_status": "ok",
        "fetch_error": None,
    }


def compute_cc_timing_signal(ticker: str, force: bool = False) -> dict:
    ticker = ticker.upper()
    now = time.time()
    cached = _cc_timing_cache.get(ticker)
    if not force and cached and (now - cached[1]) < _CACHE_TTL:
        return cached[0]

    try:
        result = _compute_cc_timing_fresh(ticker)
        _cc_timing_cache[ticker] = (result, now)
        return result
    except Exception as exc:
        log.exception("cc_timing_signal failed for %s", ticker)
        return _make_error_signal(ticker, exc)
