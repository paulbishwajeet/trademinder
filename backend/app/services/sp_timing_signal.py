"""Standalone 'SP Timing Signal' — scores how good a moment it is to sell a cash-secured
put likely to expire OTM (mean-reversion entry timing), mirroring cc_timing_signal.py's
architecture with every directional factor inverted for the 'stock holds or rises' thesis.
Independent of the existing CC/SP Signal in cc_signal.py, which optimizes for overall
wheel P&L instead."""
import logging
import time
from datetime import datetime, timezone

import pandas as pd

from app.services.schwab_client import get_schwab_client
from app.services.technicals_fetcher import compute_iv_percentile_from_chain, fetch_technicals
from app.services.cc_signal import _get_llm_commentary

log = logging.getLogger(__name__)

_sp_timing_cache: dict[str, tuple[dict, float]] = {}
_CACHE_TTL = 14400  # 4 hours


def _score_sp_timing_factors(
    technicals: dict,
    daily_closes: pd.Series,
    live_price: float,
    prev_close: float,
) -> tuple[int, str, list[dict]]:
    factors: list[dict] = []

    # 1. RSI(D) Level (20 pts) — ideal at <=40 (oversold), mirrored curve re-centered
    #    so the ideal edge sits at 40 instead of CC Timing's 70.
    rsi = technicals.get("rsi_14")
    rsi_pts = 0.0
    rsi_detail = "N/A"
    if rsi is not None:
        rsi = float(rsi)
        if rsi <= 40:
            rsi_pts = 20.0
        elif rsi <= 60:
            rsi_pts = 14.0 + (60 - rsi) * 0.3
        elif rsi <= 80:
            rsi_pts = (80 - rsi) * 0.7
        else:
            rsi_pts = 0.0
        rsi_pts = round(rsi_pts, 1)
        rsi_detail = f"RSI {rsi:.1f}"
    factors.append({"name": "RSI(D) Level", "points": rsi_pts, "max": 20, "detail": rsi_detail})

    # 2. RSI(D) Trend (10 pts) — direction of RSI vs its own 14-period signal line
    #    (rsi_ma_14). A bullish cross (RSI turning up) is ideal for SP; the
    #    freshness of that cross (rsi_trend) scales the points — exact mirror of
    #    cc_timing_signal.py's RSI(D) Trend factor.
    rsi_cross_direction = technicals.get("rsi_cross_direction")
    rsi_trend = technicals.get("rsi_trend")
    if rsi_cross_direction == "bullish":
        if rsi_trend in ("expanding", "holding_strong"):
            trend_pts = 10
            trend_detail = f"Bullish cross, {rsi_trend}"
        elif rsi_trend == "squeezing":
            trend_pts = 6
            trend_detail = "Bullish cross, squeezing"
        elif rsi_trend == "fading_near_flip":
            trend_pts = 3
            trend_detail = "Bullish cross, fading (near flip)"
        else:
            trend_pts = 3
            trend_detail = "Bullish cross"
    elif rsi_cross_direction == "bearish":
        trend_pts = 0
        trend_detail = f"Bearish cross ({rsi_trend or 'n/a'})"
    else:
        trend_pts = 3
        trend_detail = "No RSI crossover data"
    factors.append({"name": "RSI(D) Trend", "points": trend_pts, "max": 10, "detail": trend_detail})

    # 3. MACD(W) (25 pts) — bullish weekly = tailwind, confirms the "holds or rises" thesis.
    #    The crossover's trend matters too: a bullish read that's "fading_near_flip"
    #    (exhausted, reversal risk) is worth less than a fresh or sustained one.
    macd = technicals.get("macd_signal", "neutral")
    macd_trend = technicals.get("macd_weekly_trend")
    macd_map = {"bullish": 25, "neutral": 12, "bearish": 0}
    macd_pts = macd_map.get(macd, 0)
    trend_note = ""
    if macd == "bullish" and macd_trend == "squeezing":
        macd_pts = 18
        trend_note = ", squeezing"
    elif macd == "bullish" and macd_trend == "fading_near_flip":
        macd_pts = 12
        trend_note = ", fading (bullish exhaustion)"
    macd_notes = technicals.get("macd_notes", "")
    factors.append({"name": "MACD(W)", "points": macd_pts, "max": 25, "detail": f"{macd.capitalize()}, {macd_notes}{trend_note}"})

    # 4. Bollinger %B (15 pts) — sweet spot is lower-mid without touching the extremes
    #    (oversold but not in freefall) — mirror reflection of CC Timing's zones about 0.5.
    bb_pts = 0
    bb_detail = "N/A"
    if len(daily_closes) >= 20:
        mean = float(daily_closes.rolling(20).mean().iloc[-1])
        std = float(daily_closes.rolling(20).std().iloc[-1])
        if std > 0:
            upper = mean + 2 * std
            lower = mean - 2 * std
            pct_b = (live_price - lower) / (upper - lower)
            if 0.15 <= pct_b <= 0.35:
                bb_pts = 15
            elif 0.0 <= pct_b < 0.15 or 0.35 < pct_b <= 0.5:
                bb_pts = 9
            elif 0.5 < pct_b <= 0.7:
                bb_pts = 5
            else:
                bb_pts = 0
            bb_detail = f"%B {pct_b:.2f}"
    factors.append({"name": "Bollinger %B", "points": bb_pts, "max": 15, "detail": bb_detail})

    # 5. Swing Low Distance (15 pts) — trailing 3-month CLOSING low as support,
    #    mirror of cc_timing_signal.py's Swing High Distance.
    swing_pts = 0
    swing_detail = "Insufficient data"
    if len(daily_closes) >= 63:
        recent_low = float(daily_closes.iloc[-63:].min())
        if recent_low > 0:
            if live_price < recent_low:
                swing_pts = 0
                swing_detail = f"New low (${live_price:.2f} < 3M low ${recent_low:.2f})"
            else:
                dist_pct = (live_price - recent_low) / recent_low * 100
                if dist_pct <= 3:
                    swing_pts = 15
                    swing_detail = f"At support (+{dist_pct:.1f}% above 3M low ${recent_low:.2f})"
                elif dist_pct <= 8:
                    swing_pts = 8
                    swing_detail = f"Near support (+{dist_pct:.1f}% above 3M low ${recent_low:.2f})"
                else:
                    swing_pts = 0
                    swing_detail = f"Well above support (+{dist_pct:.1f}% above 3M low ${recent_low:.2f})"
    factors.append({"name": "Swing Low Distance", "points": swing_pts, "max": 15, "detail": swing_detail})

    # 6. Day Color (15 pts) — red day = capturing richer put premium on the dip.
    pct_chg = (live_price - prev_close) / prev_close * 100 if prev_close else 0.0
    if pct_chg < -0.5:
        day_pts = 15
        day_detail = f"Red ({pct_chg:+.1f}%)"
    elif pct_chg <= 0.5:
        day_pts = 7
        day_detail = f"Neutral ({pct_chg:+.1f}%)"
    else:
        day_pts = 0
        day_detail = f"Green ({pct_chg:+.1f}%)"
    factors.append({"name": "Day Color", "points": day_pts, "max": 15, "detail": day_detail})

    total = round(sum(f["points"] for f in factors))

    # Confluence bonus — reward the literal mirrored "perfect setup" beyond additive luck.
    is_perfect_setup = (
        rsi is not None and rsi <= 40
        and macd == "bullish"
        and pct_chg < -0.5
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


def _compute_sp_timing_fresh(ticker: str) -> dict:
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

    put_chain = client.get_option_chain(ticker, contract_type="PUT", strike_count=30)
    iv_percentile, atm_iv = compute_iv_percentile_from_chain(close_d, put_chain, ticker, contract_type="PUT")

    score, grade, factors = _score_sp_timing_factors(technicals, close_d, live_price, prev_close)

    commentary_data = _get_llm_commentary(ticker, score, grade, factors, technicals, iv_percentile, live_price)
    caution = commentary_data.get("caution")

    # Weekly MACD exhaustion — bullish confirmation that's fading is a reversal risk, not part of the score.
    if technicals.get("macd_signal") == "bullish" and technicals.get("macd_weekly_trend") == "fading_near_flip":
        periods = technicals.get("macd_weekly_periods_since_cross")
        periods_note = f" ({periods} weeks since the last cross)" if periods is not None else ""
        exhaustion_note = f"Weekly MACD is bullish but fading{periods_note} — reversal risk."
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


def compute_sp_timing_signal(ticker: str, force: bool = False) -> dict:
    ticker = ticker.upper()
    now = time.time()
    cached = _sp_timing_cache.get(ticker)
    if not force and cached and (now - cached[1]) < _CACHE_TTL:
        return cached[0]

    try:
        result = _compute_sp_timing_fresh(ticker)
        _sp_timing_cache[ticker] = (result, now)
        return result
    except Exception as exc:
        log.exception("sp_timing_signal failed for %s", ticker)
        return _make_error_signal(ticker, exc)
