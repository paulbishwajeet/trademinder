import json
import logging
import math
import os
import time
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from app.services.price_fetcher import _compute_rsi_14
from app.services.schwab_client import get_schwab_client

log = logging.getLogger(__name__)

# fetch_technicals is imported lazily inside _compute_fresh to avoid circular
# imports, but we declare it here at module level so unit tests can patch it via
# patch("app.services.cc_signal.fetch_technicals").
fetch_technicals = None  # populated on first call or overridden by tests

_cc_signal_cache: dict[str, tuple[dict, float]] = {}
_CACHE_TTL = 14400  # 4 hours


def compute_cc_signal(ticker: str) -> dict:
    ticker = ticker.upper()
    now = time.time()
    cached = _cc_signal_cache.get(ticker)
    if cached and (now - cached[1]) < _CACHE_TTL:
        return cached[0]

    try:
        result = _compute_fresh(ticker)
        _cc_signal_cache[ticker] = (result, now)
        return result
    except Exception as exc:
        log.exception("cc_signal failed for %s", ticker)
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


def _compute_fresh(ticker: str) -> dict:
    import sys as _sys
    # Check if fetch_technicals has been injected into this module's namespace
    # (e.g. by a test mock via patch("app.services.cc_signal.fetch_technicals")).
    # Fall back to a lazy import to avoid circular imports at module load time.
    _ft = getattr(_sys.modules[__name__], "fetch_technicals", None)
    if _ft is None:
        from app.services.technicals_fetcher import fetch_technicals as _ft
    fetch_technicals = _ft

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

    chain = client.get_option_chain(ticker, contract_type="CALL")
    iv_percentile, atm_iv = _compute_iv_percentile_from_chain(close_d, chain, ticker)

    prev_close = float(close_d.iloc[-1])
    technicals = dict(technicals)
    technicals["day_color"] = "green" if live_price > prev_close else "red"
    technicals["price_action"] = str(round(live_price, 2))
    spot = live_price
    score, grade, factors = _score_factors(technicals, iv_percentile, atm_iv, close_d)
    commentary_data = _get_llm_commentary(ticker, score, grade, factors, technicals, iv_percentile, spot)

    return {
        "ticker": ticker,
        "score": score,
        "grade": grade,
        "iv_percentile": round(iv_percentile, 1) if iv_percentile is not None else None,
        "atm_iv": round(atm_iv, 4) if atm_iv is not None else None,
        "spot_price": round(spot, 2),
        "factors": factors,
        "commentary": commentary_data.get("commentary"),
        "strike_hint": commentary_data.get("strike_hint"),
        "caution": commentary_data.get("caution"),
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "fetch_status": "ok",
        "fetch_error": None,
    }


def _compute_iv_percentile_from_chain(
    daily_closes: pd.Series, chain: dict, ticker: str = "?"
) -> tuple[float | None, float | None]:
    try:
        log_returns = np.log(daily_closes / daily_closes.shift(1)).dropna()
        if len(log_returns) < 60:
            return None, None
        hv30 = log_returns.rolling(window=30).std() * math.sqrt(252)
        hv30 = hv30.dropna()
        if len(hv30) < 30:
            return None, None

        call_exp_map = chain.get("callExpDateMap", {})
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

    # 2. RSI Overbought (15 pts)
    rsi = technicals.get("rsi_14")
    rsi_pts = 0
    rsi_detail = "N/A"
    if rsi is not None:
        rsi = float(rsi)
        if rsi >= 75:
            rsi_pts = 15
        elif rsi >= 70:
            rsi_pts = 12
        elif rsi >= 65:
            rsi_pts = 8
        elif rsi >= 60:
            rsi_pts = 4
        rsi_detail = f"RSI {rsi:.1f}"
    factors.append({"name": "RSI Overbought", "points": rsi_pts, "max": 15, "detail": rsi_detail})

    # 3. Bollinger Position (15 pts)
    bb_pos = technicals.get("bollinger_position")
    bb_map = {"above_upper": 15, "near_upper": 12, "mid": 5, "near_lower": 0, "below_lower": 0}
    bb_pts = bb_map.get(bb_pos, 0)
    bb_labels = {
        "above_upper": "Above upper band",
        "near_upper": "Near upper band",
        "mid": "Mid band",
        "near_lower": "Near lower band",
        "below_lower": "Below lower band",
    }
    factors.append({"name": "Bollinger Position", "points": bb_pts, "max": 15, "detail": bb_labels.get(bb_pos, str(bb_pos))})

    # 4. MACD Bullish (10 pts)
    macd = technicals.get("macd_signal", "neutral")
    macd_map = {"bullish": 10, "neutral": 5, "bearish": 0}
    macd_pts = macd_map.get(macd, 0)
    macd_notes = technicals.get("macd_notes", "")
    factors.append({"name": "MACD Bullish", "points": macd_pts, "max": 10, "detail": f"{macd.capitalize()}, {macd_notes}"})

    # 5. Green Day (5 pts)
    day = technicals.get("day_color", "red")
    day_pts = 5 if day == "green" else 0
    factors.append({"name": "Green Day", "points": day_pts, "max": 5, "detail": day.capitalize()})

    # 6. Price > 50MA (10 pts)
    ma50_pos = technicals.get("price_vs_ma50")
    ma50_pts = 10 if ma50_pos == "above" else 0
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

    # Grade with IV override
    iv_override = iv_pts >= 20
    if iv_override:
        if total >= 60:
            grade = "strong"
        elif total >= 40:
            grade = "moderate"
        elif total >= 20:
            grade = "weak"
        else:
            grade = "wait"
    else:
        if total >= 70:
            grade = "strong"
        elif total >= 50:
            grade = "moderate"
        elif total >= 30:
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
