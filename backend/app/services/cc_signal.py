import json
import logging
import math
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from typing import Optional

from app.services.price_fetcher import _compute_rsi_14
from app.services.schwab_client import get_schwab_client
from app.services.technicals_fetcher import compute_iv_percentile_from_chain


def _bollinger_pos_from_closes(closes: pd.Series, window: int) -> Optional[str]:
    """Compute Bollinger position using the same zone logic as technicals_fetcher."""
    if len(closes) < window:
        return None
    mean = float(closes.rolling(window).mean().iloc[-1])
    std = float(closes.rolling(window).std().iloc[-1])
    if std == 0:
        return "mid"
    upper = mean + 2 * std
    lower = mean - 2 * std
    price = float(closes.iloc[-1])
    band_width = upper - lower
    upper_zone = mean + band_width * 0.25
    lower_zone = mean - band_width * 0.25
    if price > upper:
        return "above_upper"
    if price > upper_zone:
        return "near_upper"
    if price < lower:
        return "below_lower"
    if price < lower_zone:
        return "near_lower"
    return "mid"


def _standard_strike_otm_pct(
    chain: dict,
    spot: float,
    target_delta: float = 0.30,
    contract_type: str = "CALL",
) -> Optional[float]:
    """Find the ~0.30 delta option in the nearest 14-60 DTE expiry; return OTM% (positive = OTM).

    Used for the Strike Safety factor: how far OTM is a "standard" income-selling contract?
    """
    exp_map_key = "callExpDateMap" if contract_type.upper() == "CALL" else "putExpDateMap"
    exp_map = chain.get(exp_map_key, {})
    if not exp_map:
        return None

    today = date.today()
    best_key = None
    best_dte_diff = float("inf")
    for k in exp_map:
        try:
            k_date = date.fromisoformat(k.split(":")[0])
            dte = (k_date - today).days
            if dte < 14:
                continue
            diff = abs(dte - 30)
            if diff < best_dte_diff:
                best_dte_diff = diff
                best_key = k
        except (ValueError, IndexError):
            continue

    if not best_key:
        return None

    best_otm_pct: Optional[float] = None
    best_delta_diff = float("inf")
    for strike_str, options in exp_map[best_key].items():
        if not options:
            continue
        delta = options[0].get("delta")
        if delta is None:
            continue
        abs_delta = abs(float(delta))
        diff = abs(abs_delta - target_delta)
        if diff < best_delta_diff:
            best_delta_diff = diff
            strike = float(strike_str)
            best_otm_pct = ((strike - spot) / spot * 100 if contract_type.upper() == "CALL"
                            else (spot - strike) / spot * 100)

    return best_otm_pct if best_delta_diff <= 0.15 else None

log = logging.getLogger(__name__)

_combined_signal_cache: dict[str, tuple[dict, float]] = {}
_option_chain_cache: dict[str, tuple[dict, float]] = {}
_CACHE_TTL = 14400       # 4 hours
_OPTION_CHAIN_TTL = 300  # 5 minutes


def fetch_option_mid(ticker: str, strike: float, expiry_str: str, contract_type: str) -> dict:
    """Return current bid/ask/mid for a specific option contract.

    expiry_str is the date stored in the trade (may be Thursday when Schwab uses Friday).
    We find the closest expiry key within ±3 days to handle that convention difference.
    """
    cache_key = f"{ticker}-{contract_type.upper()}"
    now = time.time()
    cached = _option_chain_cache.get(cache_key)
    if cached and (now - cached[1]) < _OPTION_CHAIN_TTL:
        chain = cached[0]
    else:
        client = get_schwab_client()
        to_date = (date.today() + timedelta(days=90)).isoformat()
        chain = client.get_option_chain(
            ticker,
            contract_type=contract_type.upper(),
            to_date=to_date,
            strike_count=60,
        )
        _option_chain_cache[cache_key] = (chain, now)

    exp_map_key = "putExpDateMap" if contract_type.upper() == "PUT" else "callExpDateMap"
    exp_map = chain.get(exp_map_key, {})

    # Find the closest expiry key within ±3 days — handles Thu vs Fri convention
    target = date.fromisoformat(expiry_str)
    matching_key = None
    best_delta = float("inf")
    for k in exp_map:
        k_date = date.fromisoformat(k.split(":")[0])
        delta = abs((k_date - target).days)
        if delta <= 3 and delta < best_delta:
            best_delta = delta
            matching_key = k

    if not matching_key:
        log.warning("option_price %s: no expiry near %s (available: %s)", ticker, expiry_str, [k.split(":")[0] for k in exp_map.keys()])
        return {"fetch_status": "error", "fetch_error": f"No chain data for expiry {expiry_str}"}

    strikes = exp_map[matching_key]
    if not strikes:
        log.warning("option_price %s: empty strikes at %s", ticker, matching_key)
        return {"fetch_status": "error", "fetch_error": "Empty strikes in chain"}

    strike_key = min(strikes.keys(), key=lambda s: abs(float(s) - strike))
    if abs(float(strike_key) - strike) > 2.0:
        log.warning("option_price %s: strike %.2f not found near %s (closest=%.2f)", ticker, strike, matching_key, float(strike_key))
        return {"fetch_status": "error", "fetch_error": f"No option found near strike {strike}"}

    option = strikes[strike_key][0]
    bid = float(option.get("bid", 0))
    ask = float(option.get("ask", 0))
    mid = round((bid + ask) / 2, 4)
    return {"bid": bid, "ask": ask, "mid": mid, "fetch_status": "ok", "fetch_error": None}


def _make_error_signal(ticker: str, exc: Exception) -> dict:
    return {
        "ticker": ticker,
        "score": 0,
        "grade": "wait",
        "iv_percentile": None,
        "atm_iv": None,
        "spot_price": None,
        "factors": [],
        "commentary": None,
        "strike_hint": None,
        "caution": None,
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "fetch_status": "error",
        "fetch_error": str(exc),
    }


def compute_combined_signal(ticker: str, force: bool = False, dte: Optional[int] = None) -> dict:
    """Fetch technicals + quotes + ALL options chain once; return {"cc": ..., "sp": ...}.

    dte: contract days-to-expiry, used to pick Bollinger lookback (≤10 → 20-day; >10 → 50-day).
    When dte is provided the cache is bypassed so the DTE-adjusted score is always fresh.
    """
    ticker = ticker.upper()
    now = time.time()
    cached = _combined_signal_cache.get(ticker)
    if dte is None and not force and cached and (now - cached[1]) < _CACHE_TTL:
        return cached[0]

    try:
        result = _compute_combined_fresh(ticker, dte=dte)
        if dte is None:
            _combined_signal_cache[ticker] = (result, now)
        return result
    except Exception as exc:
        log.exception("combined_signal failed for %s", ticker)
        err = _make_error_signal(ticker, exc)
        return {"cc": err, "sp": err}


def compute_cc_signal(ticker: str, force: bool = False) -> dict:
    return compute_combined_signal(ticker, force)["cc"]


def compute_sp_signal(ticker: str, force: bool = False) -> dict:
    return compute_combined_signal(ticker, force)["sp"]


def _compute_combined_fresh(ticker: str, dte: Optional[int] = None) -> dict:
    from app.services.technicals_fetcher import fetch_technicals

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

    # Two focused calls with strikeCount avoids 502 overflow on large ETFs (QQQ etc.)
    call_chain = client.get_option_chain(ticker, contract_type="CALL", strike_count=30)
    put_chain = client.get_option_chain(ticker, contract_type="PUT", strike_count=30)

    prev_close = float(close_d.iloc[-1])
    technicals = dict(technicals)
    technicals["day_color"] = "green" if live_price > prev_close else "red"
    technicals["price_action"] = str(round(live_price, 2))
    spot = live_price
    cached_at = datetime.now(timezone.utc).isoformat()

    # OTM% of the ~0.30 delta option at nearest monthly expiry — feeds Strike Safety factor
    cc_strike_otm_pct = _standard_strike_otm_pct(call_chain, spot, target_delta=0.30, contract_type="CALL")
    sp_strike_otm_pct = _standard_strike_otm_pct(put_chain, spot, target_delta=0.30, contract_type="PUT")

    cc_iv_pct, cc_atm_iv = compute_iv_percentile_from_chain(close_d, call_chain, ticker, contract_type="CALL")
    cc_score, cc_grade, cc_factors = _score_factors(technicals, cc_iv_pct, cc_atm_iv, close_d, dte=dte, strike_otm_pct=cc_strike_otm_pct)
    commentary_data = _get_llm_commentary(ticker, cc_score, cc_grade, cc_factors, technicals, cc_iv_pct, spot)

    sp_iv_pct, sp_atm_iv = compute_iv_percentile_from_chain(close_d, put_chain, ticker, contract_type="PUT")
    sp_score, sp_grade, sp_factors = _score_sp_factors(technicals, sp_iv_pct, sp_atm_iv, close_d, dte=dte, strike_otm_pct=sp_strike_otm_pct)

    return {
        "cc": {
            "ticker": ticker,
            "score": cc_score,
            "grade": cc_grade,
            "iv_percentile": round(cc_iv_pct, 1) if cc_iv_pct is not None else None,
            "atm_iv": round(cc_atm_iv, 4) if cc_atm_iv is not None else None,
            "spot_price": round(spot, 2),
            "factors": cc_factors,
            "commentary": commentary_data.get("commentary"),
            "strike_hint": commentary_data.get("strike_hint"),
            "caution": commentary_data.get("caution"),
            "cached_at": cached_at,
            "fetch_status": "ok",
            "fetch_error": None,
        },
        "sp": {
            "ticker": ticker,
            "score": sp_score,
            "grade": sp_grade,
            "iv_percentile": round(sp_iv_pct, 1) if sp_iv_pct is not None else None,
            "atm_iv": round(sp_atm_iv, 4) if sp_atm_iv is not None else None,
            "spot_price": round(spot, 2),
            "factors": sp_factors,
            "commentary": None,
            "strike_hint": None,
            "caution": None,
            "cached_at": cached_at,
            "fetch_status": "ok",
            "fetch_error": None,
        },
    }


def _score_factors(
    technicals: dict,
    iv_percentile: float | None,
    atm_iv: float | None,
    daily_closes: pd.Series,
    dte: Optional[int] = None,
    strike_otm_pct: Optional[float] = None,
) -> tuple[int, str, list[dict]]:
    factors: list[dict] = []

    # 1. IV Percentile (25 pts) — bell curve for CC: sweet spot 40-70th percentile.
    #    Very high IV (>80) signals chaos/event-driven moves → elevated assignment risk.
    #    Very low IV (<20) → thin premium not worth selling.
    #    40-70th percentile: rich premium with manageable assignment risk (tastytrade/Sheridan consensus).
    iv_pts = 0
    iv_detail = "N/A"
    if iv_percentile is not None:
        if 40 <= iv_percentile <= 70:
            iv_pts = 25   # sweet spot — premium rich, volatility manageable
        elif iv_percentile < 40 and iv_percentile >= 20:
            iv_pts = 10   # thin premium but low assignment risk
        elif iv_percentile > 70 and iv_percentile < 80:
            iv_pts = 18   # elevated, acceptable — but assignment risk rising
        elif iv_percentile >= 80:
            iv_pts = 10   # chaos zone — fat premium but assignment/runaway risk high
        else:
            iv_pts = 3    # <20: near-zero premium
        iv_detail = f"{iv_percentile:.0f}th percentile (52-week)"
    factors.append({"name": "IV Percentile", "points": iv_pts, "max": 25, "detail": iv_detail})

    # 2. Daily RSI Momentum (15 pts) — overbought / high-momentum = ideal CC entry.
    #    High RSI = elevated premium + mean reversion potential = call likely expires OTM.
    #    Low RSI = stock may rally sharply from here = assignment risk or weak premium.
    rsi = technicals.get("rsi_14")
    rsi_pts = 0
    rsi_detail = "N/A"
    if rsi is not None:
        rsi = float(rsi)
        if rsi >= 65:
            rsi_pts = 15   # overbought — mean reversion likely, call expires OTM
        elif rsi >= 55:
            rsi_pts = 10   # strong momentum but not overextended
        elif rsi >= 45:
            rsi_pts = 6    # neutral — decent premium, no clear directional edge
        else:              # <45: oversold/weak — stock may rally hard
            rsi_pts = 1
        rsi_detail = f"RSI {rsi:.1f}"
    factors.append({"name": "RSI Momentum", "points": rsi_pts, "max": 15, "detail": rsi_detail})

    # 3. Bollinger Bands Position (15 pts) — at/near/above upper band = stock overextended,
    #    pullback likely = call expires OTM. Near lower band = upward momentum risk.
    #    Lookback: 20-day for weekly (DTE ≤ 10), 50-day for monthly (DTE > 10, default).
    bb_window = 20 if (dte is not None and dte <= 10) else 50
    bb_pos = _bollinger_pos_from_closes(daily_closes, bb_window) or technicals.get("bollinger_position")
    bb_map = {
        "above_upper": 15,  # above upper band — extended, pullback very likely
        "near_upper": 15,   # near upper band — same signal
        "mid": 6,           # at middle band — neutral
        "near_lower": 2,    # near lower band — upward momentum risk
        "below_lower": 0,   # below lower band — avoid (likely to bounce hard)
    }
    bb_pts = bb_map.get(bb_pos, 0)
    bb_labels = {
        "above_upper": "Above upper band",
        "near_upper": "Near upper band",
        "mid": "Mid band",
        "near_lower": "Near lower band",
        "below_lower": "Below lower band",
    }
    bb_label = bb_labels.get(bb_pos, str(bb_pos))
    factors.append({"name": "Bollinger Position", "points": bb_pts, "max": 15, "detail": f"{bb_label} ({bb_window}d)"})

    # 4. Weekly MACD Trend (10 pts) — mildly bullish or neutral is ideal for CC:
    #    stock has some premium but isn't in a runaway uptrend that would blow through the call.
    #    Strongly bullish = assignment risk. Bearish = call safe but holding a declining stock.
    macd = technicals.get("macd_signal", "neutral")
    macd_map = {"bullish": 10, "neutral": 7, "bearish": 2}
    macd_pts = macd_map.get(macd, 0)
    macd_notes = technicals.get("macd_notes", "")
    factors.append({"name": "MACD Trend", "points": macd_pts, "max": 10, "detail": f"{macd.capitalize()}, {macd_notes}"})

    # 5. Day Color (5 pts) — sell calls into strength: green day = elevated call premium,
    #    stock above previous close = call strike further from current price on entry.
    #    Red day = stock falling, call premium deflated, assignment risk unclear.
    #    Use % change from prev close: >+0.5% green, ±0.5% neutral, <-0.5% red.
    day_pts = 3  # default neutral
    day_detail = "N/A"
    try:
        live_price = float(technicals.get("price_action") or 0)
        prev_close = float(daily_closes.iloc[-1]) if not daily_closes.empty else 0
        pct_chg = (live_price - prev_close) / prev_close * 100 if prev_close else 0
        if pct_chg > 0.5:
            day_pts = 5
            day_detail = f"Green ({pct_chg:+.1f}%)"
        elif pct_chg >= -0.5:
            day_pts = 3
            day_detail = f"Neutral ({pct_chg:+.1f}%)"
        else:
            day_pts = 1
            day_detail = f"Red ({pct_chg:+.1f}%)"
    except (ValueError, TypeError):
        day_detail = technicals.get("day_color", "N/A").capitalize()
    factors.append({"name": "Day Color", "points": day_pts, "max": 5, "detail": day_detail})

    # 6. Price Action + Key Moving Averages (15 pts) — above both MAs with overextension = ideal:
    #    stock is stretched, natural ceiling near call strike. Clean uptrend = assignment risk.
    ma50_pos = technicals.get("price_vs_ma50")
    ma200_pos = technicals.get("price_vs_ma200")
    price_str = technicals.get("price_action", "?")
    ma50_val = technicals.get("ma_50d", "?")
    ma200_val = technicals.get("ma_200d", "?")
    if ma50_pos == "above" and ma200_pos == "above":
        ma_pts = 15
        ma_detail = f"${price_str} above 50MA (${ma50_val}) + 200MA (${ma200_val})"
    elif ma50_pos == "above" or ma200_pos == "above":
        ma_pts = 10
        above_which = "50MA" if ma50_pos == "above" else "200MA"
        ma_detail = f"${price_str} above {above_which}, near other"
    else:
        ma_pts = 2
        ma_detail = f"${price_str} below 50MA (${ma50_val}) + 200MA (${ma200_val})"
    factors.append({"name": "Price vs MAs", "points": ma_pts, "max": 15, "detail": ma_detail})

    # 7. Momentum Exhaustion (10 pts) — RSI rolling over from highs = momentum fading,
    #    call very likely expires OTM. Strong continued upside = stock may run through strike.
    mom_pts = 0
    mom_detail = "Insufficient data"
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
                # Rolling over from highs — momentum fading, ideal CC setup
                mom_pts = 10
                mom_detail = f"RSI rolling over: {oldest_rsi:.1f} → {current_rsi:.1f}"
            elif was_elevated and current_rsi >= oldest_rsi:
                # Elevated but not yet declining — early signs of slowing
                mom_pts = 6
                mom_detail = f"RSI elevated ({current_rsi:.1f}), not yet rolling over"
            elif current_rsi > oldest_rsi and current_rsi > 55:
                # Rising strongly from lower levels — assignment risk
                mom_pts = 1
                mom_detail = f"RSI rising strongly: {oldest_rsi:.1f} → {current_rsi:.1f}"
            else:
                # Weak / neutral momentum — call safe but stock not ideal for wheel
                mom_pts = 3
                mom_detail = f"RSI neutral/weak ({current_rsi:.1f})"
    factors.append({"name": "Momentum Exhaustion", "points": mom_pts, "max": 10, "detail": mom_detail})

    # 8. Strike Safety / Resistance (10 pts) — OTM% of ~0.30 delta call.
    #    Bonus if call strike is near the 3-month high (natural resistance = stock stalled there before).
    ss_pts = 0
    ss_detail = "No chain data"
    if strike_otm_pct is not None:
        call_strike_approx = float(technicals.get("price_action") or 0) * (1 + strike_otm_pct / 100)
        three_month_high = float(daily_closes.iloc[-63:].max()) if len(daily_closes) >= 63 else None
        # Resistance present = call strike at or below the recent 3M high (stock has stalled there)
        has_resistance = (
            three_month_high is not None
            and call_strike_approx > 0
            and call_strike_approx <= three_month_high * 1.03
        )

        if strike_otm_pct >= 5 and has_resistance:
            ss_pts = 10
            ss_detail = f"0.30δ call {strike_otm_pct:.1f}% OTM, resistance at ${three_month_high:.0f} ✓"
        elif strike_otm_pct >= 5:
            ss_pts = 8
            ss_detail = f"0.30δ call {strike_otm_pct:.1f}% OTM (no recent resistance)"
        elif strike_otm_pct >= 3:
            res_note = f", resistance at ${three_month_high:.0f}" if three_month_high else ""
            ss_pts = 7
            ss_detail = f"0.30δ call {strike_otm_pct:.1f}% OTM{res_note}"
        elif strike_otm_pct >= 0:
            ss_pts = 3
            ss_detail = f"0.30δ call {strike_otm_pct:.1f}% OTM (low cushion)"
        else:
            ss_pts = 0
            ss_detail = f"0.30δ call is ITM ({strike_otm_pct:.1f}%)"
    factors.append({"name": "Strike Safety", "points": ss_pts, "max": 10, "detail": ss_detail})

    total = sum(f["points"] for f in factors)

    # IV fallback normalization: if IV unavailable, scale non-IV/non-Strike score to 100
    if iv_percentile is None:
        max_possible = sum(f["max"] for f in factors if f["name"] not in ("IV Percentile", "Strike Safety"))
        if max_possible > 0:
            total = round(total * 100 / max_possible)

    # Grade thresholds (factor weights sum to 105; thresholds target ~80/70/60%)
    if total >= 80:
        grade = "strong"    # excellent — high conviction
    elif total >= 70:
        grade = "moderate"  # good — proceed with smaller size
    elif total >= 60:
        grade = "weak"      # marginal — only with high IV or other strong factors
    else:
        grade = "wait"      # avoid

    return total, grade, factors


def _score_sp_factors(
    technicals: dict,
    iv_percentile: float | None,
    atm_iv: float | None,
    daily_closes: pd.Series,
    dte: Optional[int] = None,
    strike_otm_pct: Optional[float] = None,
) -> tuple[int, str, list[dict]]:
    factors: list[dict] = []

    # 1. IV Percentile (25 pts) — high IV = richer premiums; avoid thin-premium environments (<20%).
    iv_pts = 0
    iv_detail = "N/A"
    if iv_percentile is not None:
        if iv_percentile >= 80:
            iv_pts = 25
        elif iv_percentile >= 60:
            iv_pts = 20
        elif iv_percentile >= 40:
            iv_pts = 12
        elif iv_percentile >= 20:
            iv_pts = 5
        # <20%: 0 pts — thin premiums, avoid for wheel income
        iv_detail = f"{iv_percentile:.0f}th percentile (52-week)"
    factors.append({"name": "IV Percentile", "points": iv_pts, "max": 25, "detail": iv_detail})

    # 2. Daily RSI Momentum (15 pts) — oversold/neutral with potential bounce is the SP sweet spot.
    #    RSI 25-45: stock pulled back (richer put premium), potential bounce keeps put OTM.
    #    RSI >70 or <25: overbought reversal risk / extreme downtrend — avoid.
    #    Bonus: +2 pts if RSI is rising (3-day trend), capped at 15.
    rsi = technicals.get("rsi_14")
    rsi_pts = 0
    rsi_detail = "N/A"
    rsi_rising = False
    if rsi is not None:
        rsi = float(rsi)
        if 25 <= rsi <= 45:
            rsi_pts = 15   # oversold, potential bounce — ideal put-selling zone
        elif 45 < rsi <= 55:
            rsi_pts = 10   # neutral, building momentum
        elif 55 < rsi <= 70:
            rsi_pts = 5    # uptrending, put is safely OTM but less premium
        else:              # >70 or <25: overbought reversal / extreme downtrend
            rsi_pts = 2
        rsi_detail = f"RSI {rsi:.1f}"

        # Rising RSI bonus (+2, capped at max)
        if len(daily_closes) >= 17:
            rsi_3d_ago = _compute_rsi_14(daily_closes.iloc[:-3])
            if rsi_3d_ago is not None and rsi > rsi_3d_ago:
                rsi_rising = True
                rsi_pts = min(15, rsi_pts + 2)
                rsi_detail += " (↑ rising +2)"
    factors.append({"name": "RSI Momentum", "points": rsi_pts, "max": 15, "detail": rsi_detail})

    # 3. Bollinger Bands Position (15 pts) — price near/below lower band signals oversold /
    #    mean-reversion potential: stock bounces, put expires OTM.
    #    Near upper band = pullback risk toward put strike.
    #    Lookback: 20-day for weekly (DTE ≤ 10), 50-day for monthly (DTE > 10, default).
    bb_window = 20 if (dte is not None and dte <= 10) else 50
    bb_pos = _bollinger_pos_from_closes(daily_closes, bb_window) or technicals.get("bollinger_position")
    bb_map = {
        "below_lower": 15,  # at/below lower band — oversold, high bounce potential
        "near_lower": 15,   # near lower band — same signal
        "mid": 7,           # at middle band — neutral
        "near_upper": 2,    # near upper band — pullback risk toward put
        "above_upper": 0,   # extended above upper band — avoid
    }
    bb_pts = bb_map.get(bb_pos, 0)
    bb_labels = {
        "above_upper": "Above upper band",
        "near_upper": "Near upper band",
        "mid": "Mid band",
        "near_lower": "Near lower band",
        "below_lower": "Below lower band",
    }
    bb_label = bb_labels.get(bb_pos, str(bb_pos))
    factors.append({"name": "Bollinger Position", "points": bb_pts, "max": 15, "detail": f"{bb_label} ({bb_window}d)"})

    # 4. Weekly MACD Trend (10 pts) — higher-timeframe confirmation.
    #    Bullish/expanding = uptrend support = put safer. Neutral = range-bound = acceptable.
    #    Bearish = downtrend = high assignment risk.
    macd = technicals.get("macd_signal", "neutral")
    macd_map = {"bullish": 10, "neutral": 6, "bearish": 1}
    macd_pts = macd_map.get(macd, 0)
    macd_notes = technicals.get("macd_notes", "")
    factors.append({"name": "MACD Trend", "points": macd_pts, "max": 10, "detail": f"{macd.capitalize()}, {macd_notes}"})

    # 5. Day Color (5 pts) — sell puts into weakness: red day = fear premium spikes,
    #    stock pulls back = richer put premium + oversold bounce potential.
    #    Green day = put premium deflated, less edge for the seller.
    #    Use % change from prev close: <-0.5% red, ±0.5% neutral, >+0.5% green.
    day_pts = 3  # default neutral
    day_detail = "N/A"
    try:
        live_price = float(technicals.get("price_action") or 0)
        prev_close = float(daily_closes.iloc[-1]) if not daily_closes.empty else 0
        pct_chg = (live_price - prev_close) / prev_close * 100 if prev_close else 0
        if pct_chg < -0.5:
            day_pts = 5
            day_detail = f"Red ({pct_chg:+.1f}%)"
        elif pct_chg <= 0.5:
            day_pts = 3
            day_detail = f"Neutral ({pct_chg:+.1f}%)"
        else:
            day_pts = 1
            day_detail = f"Green ({pct_chg:+.1f}%)"
    except (ValueError, TypeError):
        day_detail = technicals.get("day_color", "N/A").capitalize()
    factors.append({"name": "Day Color", "points": day_pts, "max": 5, "detail": day_detail})

    # 6. Price Action + Key Moving Averages (15 pts) — bullish structure above 50MA + 200MA
    #    = uptrend intact = put safely OTM. Below key MAs = downtrend = assignment risk.
    ma50_pos = technicals.get("price_vs_ma50")
    ma200_pos = technicals.get("price_vs_ma200")
    price_str = technicals.get("price_action", "?")
    ma50_val = technicals.get("ma_50d", "?")
    ma200_val = technicals.get("ma_200d", "?")
    if ma50_pos == "above" and ma200_pos == "above":
        ma_pts = 15
        ma_detail = f"${price_str} above 50MA (${ma50_val}) + 200MA (${ma200_val})"
    elif ma50_pos == "above" or ma200_pos == "above":
        ma_pts = 10
        above_which = "50MA" if ma50_pos == "above" else "200MA"
        ma_detail = f"${price_str} above {above_which}, testing other"
    else:
        ma_pts = 3
        ma_detail = f"${price_str} below 50MA (${ma50_val}) + 200MA (${ma200_val})"
    factors.append({"name": "Price vs MAs", "points": ma_pts, "max": 15, "detail": ma_detail})

    # 7. Momentum Initiation (10 pts) — RSI crossing above 45 from below with persistence.
    #    Signals uptrend beginning = put very likely stays OTM.
    #    "Always above" (no recent dip below 45 in window) treated as borderline without confirmation.
    mom_pts = 0
    mom_detail = "Insufficient data"
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
            was_below_45 = any(r < 45 for r in rsi_series[1:])

            consecutive_above = 0
            for r in rsi_series:
                if r >= 45:
                    consecutive_above += 1
                else:
                    break

            if consecutive_above >= 2 and was_below_45:
                # Confirmed cross with persistence — clear initiation signal
                mom_pts = 10
                mom_detail = f"RSI initiation confirmed (held {consecutive_above} days, {current_rsi:.1f})"
            elif consecutive_above >= 5:
                # Sustained well above 45 — established uptrend
                mom_pts = 10
                mom_detail = f"RSI sustained ≥45 ({consecutive_above} days, {current_rsi:.1f})"
            elif consecutive_above >= 1:
                # Fresh cross or always-above without recent confirmation: borderline
                mom_pts = 6
                mom_detail = f"RSI borderline / early cross ({current_rsi:.1f})"
            else:
                mom_pts = 0
                mom_detail = f"RSI below 45 or fading ({current_rsi:.1f})"
    factors.append({"name": "Momentum Initiation", "points": mom_pts, "max": 10, "detail": mom_detail})

    # 8. Strike Safety / Support (10 pts) — OTM distance of ~0.30 delta put + historical support.
    #    "Recently tested" = put strike above 3-month low (stock traded near strike lately).
    ss_pts = 0
    ss_detail = "No chain data"
    if strike_otm_pct is not None:
        put_strike_approx = float(technicals.get("price_action") or 0) * (1 - strike_otm_pct / 100)
        three_month_low = float(daily_closes.iloc[-63:].min()) if len(daily_closes) >= 63 else None
        recently_tested = (
            three_month_low is not None
            and put_strike_approx > 0
            and put_strike_approx > three_month_low
        )

        if strike_otm_pct >= 10 and not recently_tested:
            ss_pts = 10
            lbl = f"${three_month_low:.0f}" if three_month_low else "N/A"
            ss_detail = f"0.30δ put {strike_otm_pct:.1f}% OTM, below 3M low ${lbl} ✓"
        elif strike_otm_pct >= 10:
            ss_pts = 7
            ss_detail = f"0.30δ put {strike_otm_pct:.1f}% OTM (3M low ${three_month_low:.0f} caution)"
        elif strike_otm_pct >= 5:
            ss_pts = 7 if not recently_tested else 4
            if recently_tested:
                ss_detail = f"0.30δ put {strike_otm_pct:.1f}% OTM (recently tested)"
            else:
                ss_detail = f"0.30δ put {strike_otm_pct:.1f}% OTM + support"
        else:
            ss_pts = 3
            ss_detail = f"0.30δ put {strike_otm_pct:.1f}% OTM (tight, assignment risk)"
    factors.append({"name": "Strike Safety", "points": ss_pts, "max": 10, "detail": ss_detail})

    total = sum(f["points"] for f in factors)

    # IV fallback normalization: if IV unavailable, scale non-IV/non-Strike score to 100
    if iv_percentile is None:
        max_possible = sum(f["max"] for f in factors if f["name"] not in ("IV Percentile", "Strike Safety"))
        if max_possible > 0:
            total = round(total * 100 / max_possible)

    # Grade thresholds per scoring guide (factor weights sum to 105; thresholds target ~80/70/60%)
    if total >= 80:
        grade = "strong"    # excellent — high conviction
    elif total >= 70:
        grade = "moderate"  # good — proceed with smaller size
    elif total >= 60:
        grade = "weak"      # marginal — only with high IV or other strong factors
    else:
        grade = "wait"      # avoid

    return total, grade, factors


def _get_llm_commentary(
    ticker: str,
    score: int,
    grade: str,
    factors: list[dict],
    technicals: dict,
    iv_percentile: float | None,
    spot: float,
) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"commentary": None, "strike_hint": None, "caution": None}

    try:
        from google import genai

        client = genai.Client(api_key=api_key)

        system_prompt = (
            "You are a senior options trader reviewing technical data for covered call selling opportunities. "
            "Given the scoring factors and raw technicals for a ticker, provide:\n"
            '1. "commentary" — 1-2 sentences explaining the setup in plain trader language. Be direct and opinionated. Reference specific numbers.\n'
            '2. "strike_hint" — One sentence suggesting strike selection approach based on IV and technical picture. If conditions are poor, say "Wait for a better setup."\n'
            '3. "caution" — One sentence warning if there\'s a risk factor (earnings proximity, bearish divergence, etc.), or null if no concerns.\n\n'
            "Respond in JSON format with keys: commentary, strike_hint, caution.\n"
            "Do not include any explanation outside the JSON."
        )

        user_data = {
            "ticker": ticker,
            "spot_price": spot,
            "score": score,
            "grade": grade,
            "iv_percentile": iv_percentile,
            "factors": factors,
            "technicals_snapshot": {
                "rsi_14": technicals.get("rsi_14"),
                "macd_signal": technicals.get("macd_signal"),
                "macd_notes": technicals.get("macd_notes"),
                "bollinger_position": technicals.get("bollinger_position"),
                "day_color": technicals.get("day_color"),
                "price_vs_ma50": technicals.get("price_vs_ma50"),
                "price_vs_ma200": technicals.get("price_vs_ma200"),
                "ma_50d": technicals.get("ma_50d"),
                "ma_200d": technicals.get("ma_200d"),
                "sentiment": technicals.get("sentiment"),
                "next_earnings_date": technicals.get("next_earnings_date"),
            },
        }

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=json.dumps(user_data),
            config={
                "system_instruction": system_prompt,
                "temperature": 0.3,
                "max_output_tokens": 300,
                "response_mime_type": "application/json",
            },
        )

        text = response.text.strip()
        parsed = json.loads(text)
        return {
            "commentary": parsed.get("commentary"),
            "strike_hint": parsed.get("strike_hint"),
            "caution": parsed.get("caution"),
        }

    except Exception as exc:
        log.warning("Gemini commentary failed for %s: %s", ticker, exc)
        return {"commentary": None, "strike_hint": None, "caution": None}
