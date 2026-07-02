# CC Sell Signal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 0-100 CC sell signal score with Gemini commentary to every slot row on the WHEEL dashboard, computed from 8 weighted factors (IV percentile, RSI, Bollinger, MACD, day color, MA, earnings, momentum).

**Architecture:** A new backend service (`cc_signal.py`) fetches technicals + option chain data from yfinance, scores 8 factors, calls Gemini 2.5 Flash for trader commentary, and caches results for 4 hours. A single endpoint `GET /api/market/cc-signal/{ticker}` serves the score. The frontend fetches per-ticker on dashboard mount and renders a color-coded badge with expandable detail.

**Tech Stack:** FastAPI, yfinance, google-genai (Gemini 2.5 Flash), pandas/numpy, React 19, TypeScript, Tailwind CSS

## Global Constraints

- Python 3.14+, FastAPI, SQLAlchemy 2.0 async patterns
- `google-genai` SDK for Gemini (not `google-generativeai` which is the older SDK)
- `GEMINI_API_KEY` environment variable must be set
- yfinance calls run in executor (blocking I/O)
- No new database tables or migrations
- Existing endpoints unchanged
- Tests use `python -m pytest backend/tests/... -v` from project root

---

### Task 1: Add google-genai dependency + IV percentile + scoring service

**Files:**
- Modify: `backend/pyproject.toml` (add `google-genai` dependency)
- Create: `backend/app/services/cc_signal.py`
- Test: `backend/tests/test_cc_signal.py`

**Interfaces:**
- Consumes: `fetch_technicals(ticker)` from `backend/app/services/technicals_fetcher.py`, `_compute_rsi_14(close)` from `backend/app/services/price_fetcher.py`
- Produces:
  - `compute_cc_signal(ticker: str) -> dict` — full signal result with score, grade, factors, commentary, cached_at
  - `_compute_iv_percentile(daily_closes: pd.Series, ticker: str) -> tuple[float | None, float | None]` — returns (iv_percentile, atm_iv)
  - `_score_factors(technicals: dict, iv_percentile: float | None, atm_iv: float | None, daily_closes: pd.Series) -> tuple[int, str, list[dict]]` — returns (score, grade, factors_list)
  - `_get_llm_commentary(ticker: str, score: int, grade: str, factors: list, technicals: dict, iv_percentile: float | None, spot: float) -> dict` — returns {commentary, strike_hint, caution}

- [ ] **Step 1: Add google-genai to dependencies**

In `backend/pyproject.toml`, add to the `dependencies` list:

```toml
"google-genai>=1.0.0",
```

Run: `cd /Users/bishwajeetpaul/workspace/github/TradeMinder/backend && pip install google-genai`

- [ ] **Step 2: Write failing tests for scoring logic**

```python
# backend/tests/test_cc_signal.py
import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np
from datetime import date


def _make_daily_closes(n=252, base=100.0, volatility=0.02):
    """Generate a synthetic daily close series."""
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
    assert score <= 75


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
    # With IV override (iv_pts=20 >= 20), moderate threshold drops to 40
    # Score should be around 50-55 range, grade should be "moderate" with override
    assert grade in ("strong", "moderate")


def test_earnings_distance_scoring():
    from app.services.cc_signal import _score_factors
    closes = _make_daily_closes()

    # No earnings → 10 pts
    t1 = _make_technicals({"next_earnings_date": None})
    _, _, f1 = _score_factors(t1, 50.0, 0.30, closes)
    earn1 = next(f for f in f1 if f["name"] == "Earnings Distance")
    assert earn1["points"] == 10

    # Earnings in 5 days → 0 pts
    from datetime import timedelta
    near = (date.today() + timedelta(days=5)).isoformat()
    t2 = _make_technicals({"next_earnings_date": near})
    _, _, f2 = _score_factors(t2, 50.0, 0.30, closes)
    earn2 = next(f for f in f2 if f["name"] == "Earnings Distance")
    assert earn2["points"] == 0


def test_momentum_exhaustion_negative_slope():
    from app.services.cc_signal import _score_factors
    # Build closes where RSI would have been high recently then dropped
    # We'll just test the factor directly by checking it exists
    closes = _make_daily_closes()
    technicals = _make_technicals({"rsi_14": 63.0})
    _, _, factors = _score_factors(technicals, 50.0, 0.30, closes)
    momentum = next(f for f in factors if f["name"] == "Momentum Exhaustion")
    assert momentum["max"] == 10
    assert 0 <= momentum["points"] <= 10
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/bishwajeetpaul/workspace/github/TradeMinder && python -m pytest backend/tests/test_cc_signal.py -v`
Expected: FAIL — ModuleNotFoundError for `app.services.cc_signal`

- [ ] **Step 4: Implement cc_signal.py**

```python
# backend/app/services/cc_signal.py
import json
import logging
import math
import os
import time
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

from app.services.price_fetcher import _compute_rsi_14

log = logging.getLogger(__name__)

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
    except Exception as exc:
        log.exception("cc_signal failed for %s", ticker)
        result = {
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

    _cc_signal_cache[ticker] = (result, now)
    return result


def _compute_fresh(ticker: str) -> dict:
    from app.services.technicals_fetcher import fetch_technicals

    technicals = fetch_technicals(ticker)
    if technicals.get("fetch_status") != "ok":
        raise ValueError(f"Technicals fetch failed: {technicals.get('fetch_error')}")

    df_d = yf.download(ticker, period="1y", interval="1d", progress=False, auto_adjust=True)
    if df_d is None or df_d.empty:
        raise ValueError(f"No daily data for {ticker}")
    close_d = df_d["Close"]
    if isinstance(close_d, pd.DataFrame):
        close_d = close_d.iloc[:, 0]
    close_d = close_d.dropna()

    iv_percentile, atm_iv = _compute_iv_percentile(close_d, ticker)
    spot = float(close_d.iloc[-1])
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


def _compute_iv_percentile(daily_closes: pd.Series, ticker: str) -> tuple[float | None, float | None]:
    try:
        log_returns = np.log(daily_closes / daily_closes.shift(1)).dropna()
        if len(log_returns) < 60:
            return None, None
        hv30 = log_returns.rolling(window=30).std() * math.sqrt(252)
        hv30 = hv30.dropna()
        if len(hv30) < 30:
            return None, None

        t = yf.Ticker(ticker)
        expirations = t.options
        if not expirations:
            return None, None

        today = date.today()
        best_exp = None
        best_dist = float("inf")
        for exp_str in expirations:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - today).days
            if dte < 14:
                continue
            dist = abs(dte - 37)
            if dist < best_dist:
                best_dist = dist
                best_exp = exp_str

        if best_exp is None:
            return None, None

        chain = t.option_chain(best_exp)
        calls = chain.calls
        if calls is None or calls.empty:
            return None, None

        spot = float(daily_closes.iloc[-1])
        calls = calls.copy()
        calls["dist"] = (calls["strike"] - spot).abs()
        atm_row = calls.loc[calls["dist"].idxmin()]
        atm_iv = float(atm_row["impliedVolatility"])
        if atm_iv <= 0.01:
            return None, None

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
    bb_labels = {"above_upper": "Above upper band", "near_upper": "Near upper band", "mid": "Mid band", "near_lower": "Near lower band", "below_lower": "Below lower band"}
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
            recent_rsis = rsi_series[:6]
            was_elevated = any(r > 65 for r in recent_rsis)
            if was_elevated:
                current_rsi = recent_rsis[0] if recent_rsis else 0
                oldest_rsi = recent_rsis[-1] if recent_rsis else 0
                if current_rsi < oldest_rsi:
                    mom_pts = 10
                    mom_detail = f"RSI declining from {oldest_rsi:.1f} to {current_rsi:.1f}"
                else:
                    mom_pts = 5
                    mom_detail = f"RSI > 65 recently but not declining"
    factors.append({"name": "Momentum Exhaustion", "points": mom_pts, "max": 10, "detail": mom_detail})

    total = sum(f["points"] for f in factors)

    # IV fallback normalization: if IV was unavailable, scale to 100
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/bishwajeetpaul/workspace/github/TradeMinder && python -m pytest backend/tests/test_cc_signal.py -v`
Expected: All 6 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/app/services/cc_signal.py backend/tests/test_cc_signal.py
git commit -m "feat(cc-signal): add scoring service with IV percentile, 8 factors, Gemini commentary"
```

---

### Task 2: Add endpoint to market router

**Files:**
- Modify: `backend/app/routers/market.py`
- Test: `backend/tests/test_cc_signal_endpoint.py`

**Interfaces:**
- Consumes: `compute_cc_signal(ticker)` from Task 1
- Produces: `GET /api/market/cc-signal/{ticker}` endpoint

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_cc_signal_endpoint.py
import pytest
from unittest.mock import patch
from httpx import AsyncClient


MOCK_SIGNAL = {
    "ticker": "NVDA",
    "score": 78,
    "grade": "strong",
    "iv_percentile": 72.0,
    "atm_iv": 0.42,
    "spot_price": 142.50,
    "factors": [
        {"name": "IV Percentile", "points": 20, "max": 25, "detail": "72nd percentile"},
    ],
    "commentary": "Test commentary",
    "strike_hint": "Test hint",
    "caution": None,
    "cached_at": "2026-06-22T14:30:00+00:00",
    "fetch_status": "ok",
    "fetch_error": None,
}


async def test_cc_signal_endpoint(client: AsyncClient):
    with patch("app.routers.market.compute_cc_signal", return_value=MOCK_SIGNAL):
        resp = await client.get("/api/market/cc-signal/NVDA")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ticker"] == "NVDA"
    assert data["score"] == 78
    assert data["grade"] == "strong"
    assert len(data["factors"]) >= 1


async def test_cc_signal_endpoint_error(client: AsyncClient):
    error_result = {
        "ticker": "FAKE",
        "score": 0,
        "grade": "wait",
        "iv_percentile": None,
        "atm_iv": None,
        "spot_price": None,
        "factors": [],
        "commentary": None,
        "strike_hint": None,
        "caution": None,
        "cached_at": "2026-06-22T14:30:00+00:00",
        "fetch_status": "error",
        "fetch_error": "No daily data",
    }
    with patch("app.routers.market.compute_cc_signal", return_value=error_result):
        resp = await client.get("/api/market/cc-signal/FAKE")
    assert resp.status_code == 200
    assert resp.json()["fetch_status"] == "error"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/bishwajeetpaul/workspace/github/TradeMinder && python -m pytest backend/tests/test_cc_signal_endpoint.py -v`
Expected: FAIL — 404 (route doesn't exist)

- [ ] **Step 3: Add route to market.py**

Add to the imports at the top of `backend/app/routers/market.py`:

```python
from app.services.cc_signal import compute_cc_signal
```

Add the route at the end of the file:

```python
@router.get("/cc-signal/{ticker}")
async def get_cc_signal(ticker: str):
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, compute_cc_signal, ticker.upper())
    return JSONResponse(content=result)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/bishwajeetpaul/workspace/github/TradeMinder && python -m pytest backend/tests/test_cc_signal_endpoint.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /Users/bishwajeetpaul/workspace/github/TradeMinder && python -m pytest backend/tests/test_cc_signal.py backend/tests/test_cc_signal_endpoint.py backend/tests/test_wheel_crud.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/market.py backend/tests/test_cc_signal_endpoint.py
git commit -m "feat(cc-signal): add GET /api/market/cc-signal/{ticker} endpoint"
```

---

### Task 3: Frontend types, API client, and dashboard integration

**Files:**
- Modify: `frontend/src/types/index.ts` (add CCSignal types)
- Modify: `frontend/src/api/wheel.ts` (add ccSignal fetch)
- Modify: `frontend/src/pages/WheelDashboardPage.tsx` (add signal badge + detail popover)

**Interfaces:**
- Consumes: `GET /api/market/cc-signal/{ticker}` from Task 2
- Produces: Signal badge on every slot row, expandable detail on click

- [ ] **Step 1: Add TypeScript types**

Append to `frontend/src/types/index.ts` before the `isStale` function:

```typescript
// ── CC Sell Signal types ────────────────────────────────────────

export interface CCSignalFactor {
  name: string
  points: number
  max: number
  detail: string
}

export interface CCSignalResult {
  ticker: string
  score: number
  grade: string
  iv_percentile: number | null
  atm_iv: number | null
  spot_price: number | null
  factors: CCSignalFactor[]
  commentary: string | null
  strike_hint: string | null
  caution: string | null
  cached_at: string
  fetch_status: string
  fetch_error: string | null
}
```

- [ ] **Step 2: Add API fetch function**

Append to `frontend/src/api/wheel.ts`:

```typescript
import type { CCSignalResult } from '../types'

export const ccSignalApi = {
  get: (ticker: string) =>
    apiFetch<CCSignalResult>(`/market/cc-signal/${encodeURIComponent(ticker)}`),
}
```

Note: `apiFetch` is already imported in this file.

- [ ] **Step 3: Add signal state and fetching to WheelDashboardPage**

In `frontend/src/pages/WheelDashboardPage.tsx`, add imports and state:

```typescript
import type { WheelSessionDetail, WheelSessionSummary, WheelSlotDetail, CCSignalResult } from '../types'
import { ccSignalApi } from '../api/wheel'
```

Add state after existing state declarations:

```typescript
const [signals, setSignals] = useState<Record<string, CCSignalResult | 'loading' | 'error'>>({})
const [signalDetail, setSignalDetail] = useState<string | null>(null) // ticker showing detail
```

Add fetch effect after the `load` effect:

```typescript
useEffect(() => {
  if (sessions.length === 0) return
  const tickers = [...new Set(sessions.map(s => s.ticker))]
  tickers.forEach(ticker => {
    if (signals[ticker]) return
    setSignals(prev => ({ ...prev, [ticker]: 'loading' }))
    ccSignalApi.get(ticker)
      .then(result => setSignals(prev => ({ ...prev, [ticker]: result })))
      .catch(() => setSignals(prev => ({ ...prev, [ticker]: 'error' })))
  })
}, [sessions])
```

- [ ] **Step 4: Add signal badge to the slot row**

In the `renderSlotRow` function, add a new `<td>` after the premium column (before the actions `<td>`):

```tsx
<td className="py-2 pr-3">
  {(() => {
    const sig = signals[ticker]
    if (sig === 'loading') return <span className="text-xs text-gray-400 animate-pulse">...</span>
    if (sig === 'error' || !sig) return <span className="text-xs text-gray-300" title="Signal unavailable">—</span>
    const colors: Record<string, string> = {
      strong: 'bg-green-100 text-green-800 border-green-300',
      moderate: 'bg-amber-100 text-amber-800 border-amber-300',
      weak: 'bg-gray-100 text-gray-600 border-gray-300',
      wait: 'bg-gray-50 text-gray-400 border-gray-200',
    }
    return (
      <button
        onClick={() => setSignalDetail(signalDetail === ticker ? null : ticker)}
        className={`text-xs font-medium px-2 py-0.5 rounded-full border ${colors[sig.grade] ?? colors.wait} hover:opacity-80`}
        title={sig.commentary ?? `Score: ${sig.score}`}
      >
        {sig.grade === 'wait' ? 'Wait' : `${sig.grade.charAt(0).toUpperCase() + sig.grade.slice(1)} ${sig.score}`}
      </button>
    )
  })()}
</td>
```

Also add a matching `<th>` in the `renderSection` table header:

```tsx
<th className="py-2 pr-3 font-normal">Signal</th>
```

- [ ] **Step 5: Add signal detail expansion**

Add a new function `renderSignalDetail` that renders when `signalDetail` matches a ticker. Place it after `renderLegRows`:

```tsx
function renderSignalDetail(ticker: string) {
  if (signalDetail !== ticker) return null
  const sig = signals[ticker]
  if (!sig || sig === 'loading' || sig === 'error') return null

  return (
    <tr key={`${ticker}-signal-detail`}>
      <td colSpan={8} className="py-3 px-4 bg-gray-50 border-t border-gray-200">
        <div className="space-y-2 text-xs">
          <div className="grid grid-cols-2 gap-x-6 gap-y-1">
            {sig.factors.map(f => (
              <div key={f.name} className="flex justify-between">
                <span className="text-gray-500">{f.name}</span>
                <span className="text-gray-700 font-medium">{f.points}/{f.max} <span className="text-gray-400 font-normal">{f.detail}</span></span>
              </div>
            ))}
          </div>
          {sig.commentary && (
            <p className="text-gray-700 pt-1 border-t border-gray-200">{sig.commentary}</p>
          )}
          {sig.strike_hint && (
            <p className="text-blue-700">{sig.strike_hint}</p>
          )}
          {sig.caution && (
            <p className="text-amber-700 font-medium">{sig.caution}</p>
          )}
          <p className="text-gray-400">
            IV Percentile: {sig.iv_percentile != null ? `${sig.iv_percentile}%` : 'N/A'}
            {sig.atm_iv != null && ` · ATM IV: ${(sig.atm_iv * 100).toFixed(1)}%`}
            {sig.spot_price != null && ` · Spot: $${sig.spot_price}`}
            {' · '}Updated: {new Date(sig.cached_at).toLocaleTimeString()}
          </p>
        </div>
      </td>
    </tr>
  )
}
```

Call it inside the per-slot `<tbody>` after `renderLegRows(f)`:

```tsx
{slots.map(f => (
  <tbody key={f.slot.id} className="border-t border-gray-50">
    {renderSlotRow(f)}
    {renderLegRows(f)}
    {renderSignalDetail(f.ticker)}
  </tbody>
))}
```

To avoid rendering the signal detail row multiple times for the same ticker in the same section, deduplicate: only render it on the first slot for that ticker. Change the call to:

```tsx
{slots.map((f, idx) => {
  const isFirstForTicker = slots.findIndex(s => s.ticker === f.ticker) === idx
  return (
    <tbody key={f.slot.id} className="border-t border-gray-50">
      {renderSlotRow(f)}
      {renderLegRows(f)}
      {isFirstForTicker && renderSignalDetail(f.ticker)}
    </tbody>
  )
})}
```

- [ ] **Step 6: Verify frontend compiles**

Run: `cd /Users/bishwajeetpaul/workspace/github/TradeMinder/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 7: Start dev server and test**

Run: `cd /Users/bishwajeetpaul/workspace/github/TradeMinder/frontend && npm run dev`

Test:
1. Open /wheel dashboard
2. Verify signal badges appear on slot rows (loading spinner → colored badge)
3. Click a badge → verify factor breakdown expands
4. Verify Gemini commentary appears (or null fields if GEMINI_API_KEY not set)
5. Verify multiple slots for the same ticker show the same signal

- [ ] **Step 8: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/wheel.ts frontend/src/pages/WheelDashboardPage.tsx
git commit -m "feat(cc-signal): add signal badge and detail popover to wheel dashboard"
```
