import json
import logging
import math
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from app.services.price_fetcher import _compute_rsi_14
from app.services.schwab_client import get_schwab_client

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


def compute_combined_signal(ticker: str, force: bool = False) -> dict:
    """Fetch technicals + quotes + ALL options chain once; return {"cc": ..., "sp": ...}."""
    ticker = ticker.upper()
    now = time.time()
    cached = _combined_signal_cache.get(ticker)
    if not force and cached and (now - cached[1]) < _CACHE_TTL:
        return cached[0]

    try:
        result = _compute_combined_fresh(ticker)
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


def _compute_combined_fresh(ticker: str) -> dict:
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

    cc_iv_pct, cc_atm_iv = _compute_iv_percentile_from_chain(close_d, call_chain, ticker, contract_type="CALL")
    cc_score, cc_grade, cc_factors = _score_factors(technicals, cc_iv_pct, cc_atm_iv, close_d)
    commentary_data = _get_llm_commentary(ticker, cc_score, cc_grade, cc_factors, technicals, cc_iv_pct, spot)

    sp_iv_pct, sp_atm_iv = _compute_iv_percentile_from_chain(close_d, put_chain, ticker, contract_type="PUT")
    sp_score, sp_grade, sp_factors = _score_sp_factors(technicals, sp_iv_pct, sp_atm_iv, close_d)

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


def _compute_iv_percentile_from_chain(
    daily_closes: pd.Series, chain: dict, ticker: str = "?", contract_type: str = "CALL"
) -> tuple[float | None, float | None]:
    try:
        log_returns = np.log(daily_closes / daily_closes.shift(1)).dropna()
        if len(log_returns) < 60:
            return None, None
        hv30 = log_returns.rolling(window=30).std() * math.sqrt(252)
        hv30 = hv30.dropna()
        if len(hv30) < 30:
            return None, None

        exp_map_key = "putExpDateMap" if contract_type == "PUT" else "callExpDateMap"
        call_exp_map = chain.get(exp_map_key, {})
        if not call_exp_map:
            return None, None

        spot = float(chain.get("underlyingPrice", 0))

        today = date.today()
        best_exp_key = None
        best_dist = float("inf")
        for exp_key in call_exp_map:
            exp_str = exp_key.split(":")[0]
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - today).days
            if dte < 14:
                continue
            dist = abs(dte - 37)
            if dist < best_dist:
                best_dist = dist
                best_exp_key = exp_key

        if best_exp_key is None:
            return None, None

        strikes = call_exp_map[best_exp_key]
        best_strike_key = min(strikes.keys(), key=lambda s: abs(float(s) - spot))
        atm_option = strikes[best_strike_key][0]
        raw_iv = float(atm_option.get("volatility", 0))
        if raw_iv <= 1.0:
            return None, None
        atm_iv = raw_iv / 100.0

        pct = float((hv30 < atm_iv).sum()) / len(hv30) * 100
        return round(pct, 1), atm_iv

    except Exception as exc:
        log.warning("IV percentile failed for %s: %s", ticker, exc)
        return None, None


def _score_factors(
    technicals: dict,
    iv_percentile: float | None,
    atm_iv: float | None,
    daily_closes: pd.Series,
) -> tuple[int, str, list[dict]]:
    factors: list[dict] = []

    # 1. IV Percentile (25 pts)
    iv_pts = 0
    iv_detail = "N/A"
    if iv_percentile is not None:
        if iv_percentile >= 80:
            iv_pts = 25
        elif iv_percentile >= 60:
            iv_pts = 20
        elif iv_percentile >= 50:
            iv_pts = 15
        elif iv_percentile >= 40:
            iv_pts = 10
        elif iv_percentile >= 30:
            iv_pts = 5
        iv_detail = f"{iv_percentile:.0f}th percentile (52-week)"
    factors.append({"name": "IV Percentile", "points": iv_pts, "max": 25, "detail": iv_detail})

    # 2. RSI Zone (15 pts) — CC sweet spot is 45-60: stock is neutral, NOT in a momentum run.
    #    RSI > 70 = squeeze = high probability stock blows through call strike.
    #    RSI 35-45 = dipped = call is very safe OTM (stock pulled back from strike).
    rsi = technicals.get("rsi_14")
    rsi_pts = 0
    rsi_detail = "N/A"
    if rsi is not None:
        rsi = float(rsi)
        if 45 <= rsi <= 60:
            rsi_pts = 15   # sweet spot: neutral, not in a parabolic move
        elif 35 <= rsi < 45:
            rsi_pts = 12   # dipped — call strike is comfortably above current price
        elif 60 < rsi <= 70:
            rsi_pts = 8    # elevated, upward momentum = some risk
        elif rsi < 35:
            rsi_pts = 5    # oversold — call safe but holding a declining stock
        else:              # rsi > 70: momentum run — high risk of being called away
            rsi_pts = 3
        rsi_detail = f"RSI {rsi:.1f}"
    factors.append({"name": "RSI Zone", "points": rsi_pts, "max": 15, "detail": rsi_detail})

    # 3. Bollinger Position (15 pts) — near upper band = natural resistance above your call strike.
    #    Mid band is only OK (stock has room to run toward strike).
    bb_pos = technicals.get("bollinger_position")
    bb_map = {"near_upper": 15, "mid": 8, "above_upper": 5, "near_lower": 3, "below_lower": 0}
    bb_pts = bb_map.get(bb_pos, 0)
    bb_labels = {
        "above_upper": "Above upper band",
        "near_upper": "Near upper band",
        "mid": "Mid band",
        "near_lower": "Near lower band",
        "below_lower": "Below lower band",
    }
    factors.append({"name": "Bollinger Position", "points": bb_pts, "max": 15, "detail": bb_labels.get(bb_pos, str(bb_pos))})

    # 4. MACD Consolidation (10 pts) — neutral weekly MACD = stock is range-bound = call burns safely.
    #    Bullish MACD = uptrend = stock may run through call strike. 0 pts — don't sell CC into momentum.
    #    Bearish MACD = stock declining = call very safe (but holding a loser). Some credit.
    macd = technicals.get("macd_signal", "neutral")
    macd_map = {"neutral": 10, "bearish": 5, "bullish": 0}
    macd_pts = macd_map.get(macd, 0)
    macd_notes = technicals.get("macd_notes", "")
    factors.append({"name": "MACD Consolidation", "points": macd_pts, "max": 10, "detail": f"{macd.capitalize()}, {macd_notes}"})

    # 5. Red Day (5 pts) — stock pulled back today = more buffer before call strike. Green = 0.
    day = technicals.get("day_color", "red")
    day_pts = 5 if day == "red" else 0
    factors.append({"name": "Red Day", "points": day_pts, "max": 5, "detail": day.capitalize()})

    # 6. Price > 50MA (10 pts) — want quality stocks above their long-term trend; give small credit below
    ma50_pos = technicals.get("price_vs_ma50")
    ma50_pts = 10 if ma50_pos == "above" else 2
    price_str = technicals.get("price_action", "?")
    ma50_val = technicals.get("ma_50d", "?")
    factors.append({"name": "Price > 50MA", "points": ma50_pts, "max": 10, "detail": f"${price_str} vs ${ma50_val}"})

    # 7. Earnings Distance (10 pts)
    next_earn = technicals.get("next_earnings_date")
    earn_pts = 10
    earn_detail = "No earnings date found"
    if next_earn:
        try:
            earn_date = date.fromisoformat(str(next_earn)[:10])
            days_to_earn = (earn_date - date.today()).days
            if days_to_earn <= 7:
                earn_pts = 0
            elif days_to_earn <= 14:
                earn_pts = 3
            elif days_to_earn <= 21:
                earn_pts = 7
            else:
                earn_pts = 10
            earn_detail = f"{days_to_earn} days to earnings"
        except (ValueError, TypeError):
            pass
    factors.append({"name": "Earnings Distance", "points": earn_pts, "max": 10, "detail": earn_detail})

    # 8. Momentum Exhaustion (10 pts)
    mom_pts = 0
    mom_detail = "No recent overbought"
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
            was_elevated = any(r > 65 for r in rsi_series)
            if was_elevated:
                current_rsi = rsi_series[0]
                oldest_rsi = rsi_series[-1]
                if current_rsi < oldest_rsi:
                    mom_pts = 10
                    mom_detail = f"RSI declining from {oldest_rsi:.1f} to {current_rsi:.1f}"
                else:
                    mom_pts = 5
                    mom_detail = "RSI > 65 recently but not declining"
    factors.append({"name": "Momentum Exhaustion", "points": mom_pts, "max": 10, "detail": mom_detail})

    total = sum(f["points"] for f in factors)

    # IV fallback normalization
    if iv_percentile is None:
        max_possible = sum(f["max"] for f in factors if f["name"] != "IV Percentile")
        if max_possible > 0:
            total = round(total * 100 / max_possible)

    # IV already contributes 20-25 raw pts — no override needed; use uniform thresholds
    if total >= 75:
        grade = "strong"
    elif total >= 55:
        grade = "moderate"
    elif total >= 35:
        grade = "weak"
    else:
        grade = "wait"

    return total, grade, factors


def _score_sp_factors(
    technicals: dict,
    iv_percentile: float | None,
    atm_iv: float | None,
    daily_closes: pd.Series,
) -> tuple[int, str, list[dict]]:
    factors: list[dict] = []

    # 1. IV Percentile (25 pts) — same as CC: high IV = more premium regardless of direction
    iv_pts = 0
    iv_detail = "N/A"
    if iv_percentile is not None:
        if iv_percentile >= 80:
            iv_pts = 25
        elif iv_percentile >= 60:
            iv_pts = 20
        elif iv_percentile >= 50:
            iv_pts = 15
        elif iv_percentile >= 40:
            iv_pts = 10
        elif iv_percentile >= 30:
            iv_pts = 5
        iv_detail = f"{iv_percentile:.0f}th percentile (52-week)"
    factors.append({"name": "IV Percentile", "points": iv_pts, "max": 25, "detail": iv_detail})

    # 2. RSI Momentum (15 pts) — SP sweet spot is 60-70: stock has upward momentum but not exhausted.
    #    RSI 45-60 = neutral, acceptable but stock has no clear upward bias (put more risk).
    #    RSI < 35 = freefall — put will go ITM.
    rsi = technicals.get("rsi_14")
    rsi_pts = 0
    rsi_detail = "N/A"
    if rsi is not None:
        rsi = float(rsi)
        if 60 <= rsi <= 70:
            rsi_pts = 15   # sweet spot: bullish momentum, stock moving away from put strike
        elif 70 < rsi <= 80:
            rsi_pts = 10   # extended/overbought but put is very safe OTM
        elif 45 <= rsi < 60:
            rsi_pts = 10   # neutral — no clear directional bias, put is OK but not ideal
        elif 35 <= rsi < 45:
            rsi_pts = 5    # dipping — stock declining toward put strike
        else:              # rsi < 35 or rsi > 80
            rsi_pts = 0 if rsi < 35 else 6  # < 35 = freefall; > 80 = extreme overbought
        rsi_detail = f"RSI {rsi:.1f}"
    factors.append({"name": "RSI Momentum", "points": rsi_pts, "max": 15, "detail": rsi_detail})

    # 3. Bollinger Position (15 pts) — mid band is ideal: put is comfortably below current price.
    #    Near upper = stock at resistance, may pull back toward put strike. Far fewer pts.
    bb_pos = technicals.get("bollinger_position")
    bb_map = {"mid": 15, "near_lower": 8, "near_upper": 5, "above_upper": 3, "below_lower": 0}
    bb_pts = bb_map.get(bb_pos, 0)
    bb_labels = {
        "above_upper": "Above upper band",
        "near_upper": "Near upper band",
        "mid": "Mid band",
        "near_lower": "Near lower band",
        "below_lower": "Below lower band",
    }
    factors.append({"name": "Bollinger Position", "points": bb_pts, "max": 15, "detail": bb_labels.get(bb_pos, str(bb_pos))})

    # 4. MACD Trend (10 pts) — only bullish MACD scores: stock needs upward momentum for put to expire OTM.
    #    Neutral = no directional edge = 0 pts. Don't sell puts into a drifting or declining stock.
    macd = technicals.get("macd_signal", "neutral")
    macd_map = {"bullish": 10, "neutral": 0, "bearish": 0}
    macd_pts = macd_map.get(macd, 0)
    macd_notes = technicals.get("macd_notes", "")
    factors.append({"name": "MACD Trend", "points": macd_pts, "max": 10, "detail": f"{macd.capitalize()}, {macd_notes}"})

    # 5. Green Day (5 pts) — stock up today = moving away from put strike = safer. Red day = 0.
    day = technicals.get("day_color", "red")
    day_pts = 5 if day == "green" else 0
    factors.append({"name": "Green Day", "points": day_pts, "max": 5, "detail": day.capitalize()})

    # 6. Price > 50MA (10 pts) — above 50MA = uptrend intact = put much safer OTM (flipped from dip-buying logic)
    ma50_pos = technicals.get("price_vs_ma50")
    ma50_pts = 10 if ma50_pos == "above" else 2
    price_str = technicals.get("price_action", "?")
    ma50_val = technicals.get("ma_50d", "?")
    factors.append({"name": "Price > 50MA", "points": ma50_pts, "max": 10, "detail": f"${price_str} vs ${ma50_val}"})

    # 7. Earnings Distance (10 pts) — same as CC: avoid earnings
    next_earn = technicals.get("next_earnings_date")
    earn_pts = 10
    earn_detail = "No earnings date found"
    if next_earn:
        try:
            earn_date = date.fromisoformat(str(next_earn)[:10])
            days_to_earn = (earn_date - date.today()).days
            if days_to_earn <= 7:
                earn_pts = 0
            elif days_to_earn <= 14:
                earn_pts = 3
            elif days_to_earn <= 21:
                earn_pts = 7
            else:
                earn_pts = 10
            earn_detail = f"{days_to_earn} days to earnings"
        except (ValueError, TypeError):
            pass
    factors.append({"name": "Earnings Distance", "points": earn_pts, "max": 10, "detail": earn_detail})

    # 8. Trend Continuation (10 pts) — RSI has been consistently healthy (≥45) over recent days
    #    = uptrend intact, put likely stays OTM. Confirmed bounce from dip also scores well.
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
            healthy_count = sum(1 for r in rsi_series if r >= 45)
            was_dipping = any(r < 40 for r in rsi_series)

            if healthy_count >= 4 and current_rsi >= 45:
                mom_pts = 10
                mom_detail = f"RSI consistently healthy ({current_rsi:.1f})"
            elif was_dipping and current_rsi > oldest_rsi and current_rsi >= 45:
                mom_pts = 8
                mom_detail = f"RSI bouncing from dip ({oldest_rsi:.1f} → {current_rsi:.1f})"
            elif was_dipping and current_rsi > oldest_rsi and current_rsi >= 40:
                mom_pts = 4   # too small a bounce (still below 45) to count as real recovery
                mom_detail = f"RSI weak bounce ({oldest_rsi:.1f} → {current_rsi:.1f})"
            elif current_rsi >= 40:
                mom_pts = 4
                mom_detail = f"RSI moderate ({current_rsi:.1f})"
            else:
                mom_pts = 0
                mom_detail = f"RSI weakening ({current_rsi:.1f})"
    factors.append({"name": "Trend Continuation", "points": mom_pts, "max": 10, "detail": mom_detail})

    total = sum(f["points"] for f in factors)

    if iv_percentile is None:
        max_possible = sum(f["max"] for f in factors if f["name"] != "IV Percentile")
        if max_possible > 0:
            total = round(total * 100 / max_possible)

    # IV already contributes 20-25 raw pts — no override needed; use uniform thresholds
    if total >= 75:
        grade = "strong"
    elif total >= 55:
        grade = "moderate"
    elif total >= 35:
        grade = "weak"
    else:
        grade = "wait"

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
