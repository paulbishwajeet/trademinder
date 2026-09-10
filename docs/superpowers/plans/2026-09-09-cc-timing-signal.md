# CC Timing Signal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new "CC Timing Signal" (0–100 score + grade + factor breakdown) to the WHEEL dashboard's "AWAITING CC" box, answering a narrower question than the existing CC Signal: *is right now a good moment to sell a covered call that's likely to expire OTM?*

**Architecture:** A new, standalone backend module (`app/services/cc_timing_signal.py`) computes the score from technicals already fetched elsewhere in the app (RSI(D), MACD(W), Bollinger position, day color) plus one new derived factor (distance to a trailing 3-month closing high). It reuses `fetch_technicals()`, `_compute_rsi_14()`, `compute_iv_percentile_from_chain()`, and the existing Gemini commentary helper `_get_llm_commentary()` — all unmodified. A new FastAPI route exposes it, and the frontend adds a "CC Timing" badge column to the AWAITING CC table only, reusing the existing badge/expand-detail UI pattern (`renderSignalBadge` / `renderSignalDetailRow`) and the existing 1-hour client cache (`WheelDashboardPage.tsx`'s `seedFromCache`/`isCacheFresh` machinery).

**Tech Stack:** FastAPI + pandas (backend scoring), React + TypeScript (frontend), existing Schwab REST client, existing Gemini (`google-genai`) commentary helper — no new dependencies.

## Global Constraints

- Do not modify `backend/app/services/cc_signal.py` or `backend/tests/test_cc_signal.py` — the existing CC/SP Signal must be byte-for-byte unchanged. (Note: `test_cc_signal.py` already has 4 pre-existing failing tests unrelated to this work — `test_iv_override_lowers_threshold`, `test_earnings_distance_no_date`, `test_earnings_distance_close`, `test_compute_fresh_calls_schwab_for_quote_and_chain`. Leave them as-is; do not fix or touch them as part of this plan.)
- New signal name everywhere: **"CC Timing Signal"** / badge label **"CC Timing"** / detail-panel heading **"CC Timing breakdown"**.
- Score is 0–100 (never negative, capped at 100 even after the confluence bonus).
- IV Percentile is a **grade-capping gate**, not a scored factor: if IV percentile < 20, cap `grade` at `"moderate"` even if the raw score would be `"strong"`, and append a caution note. It does not add points to the score.
- Only the **AWAITING CC** box on the WHEEL dashboard gets the new column. Do not add it to Awaiting Sold Put, Active, or Needs Action.
- Reuse the `CCSignalResult` TypeScript type as-is for the new signal's response shape — do not create a parallel type.
- Follow the existing 1-hour client-side cache pattern already in `WheelDashboardPage.tsx` (module-level `Record<string, CacheEntry<T>>` + `seedFromCache` + `isCacheFresh`) — do not invent a different caching mechanism on the frontend.
- Backend cache TTL: 4 hours, matching `_CACHE_TTL` in `cc_signal.py` (`14400` seconds), via its own independent module-level cache dict (do not share `_combined_signal_cache`).

---

## File Structure

- **Create:** `backend/app/services/cc_timing_signal.py` — pure scoring function `_score_cc_timing_factors()` + live compute functions `_compute_cc_timing_fresh()` / `compute_cc_timing_signal()` + module-level cache.
- **Create:** `backend/tests/test_cc_timing_signal.py` — unit tests for the scoring function (pure, no network) + one mocked test for the live-compute wrapper.
- **Modify:** `backend/app/routers/market.py` — add `GET /api/market/cc-timing-signal/{ticker}` route.
- **Modify:** `frontend/src/api/wheel.ts` — add `ccTimingSignalApi`.
- **Modify:** `frontend/src/pages/WheelDashboardPage.tsx` — add cache/state/fetch wiring, generalize the badge/detail-row renderers, add the "CC Timing" column to the Awaiting CC table only.

---

## Task 1: Backend — pure scoring function with tests (TDD)

**Files:**
- Create: `backend/app/services/cc_timing_signal.py`
- Test: `backend/tests/test_cc_timing_signal.py`

**Interfaces:**
- Consumes: `_compute_rsi_14(close: pd.Series) -> float | None` from `app.services.price_fetcher` (existing, unmodified).
- Produces: `_score_cc_timing_factors(technicals: dict, daily_closes: pd.Series, live_price: float, prev_close: float) -> tuple[int, str, list[dict]]` — returns `(score, grade, factors)` where each factor dict has keys `name`, `points`, `max`, `detail` (same shape as `cc_signal.py`'s `_score_factors`). Task 2 calls this function by this exact name and signature.

Scoring spec (implement exactly):

1. **RSI(D) Level** (max 20) — piecewise-linear on `technicals["rsi_14"]`:
   - `rsi >= 70` → `20`
   - `50 <= rsi < 70` → `14 + (rsi - 50) * 0.3`
   - `30 <= rsi < 50` → `(rsi - 30) * 0.7`
   - `rsi < 30` → `0`
   - `rsi_14` is `None` → `0`, detail `"N/A"`
   - Round points to 1 decimal. Detail string: `f"RSI {rsi:.1f}"`.

2. **RSI(D) Trend** (max 10) — reuse the exact "rolling over vs. still rising" logic from `cc_signal.py`'s Momentum Exhaustion factor (6-sample trailing RSI series, `was_elevated = any(r > 60 for r in rsi_series)`):
   - Rolling over from an elevated read (`was_elevated and current_rsi < oldest_rsi`) → `10`
   - Elevated but not yet rolling over (`was_elevated and current_rsi >= oldest_rsi`) → `6`
   - Rising strongly from below (`current_rsi > oldest_rsi and current_rsi > 55`) → `1`
   - Otherwise → `3`
   - Fewer than 20 closes or fewer than 2 RSI samples → `0`, detail `"Insufficient data"`.

3. **MACD(W)** (max 25) — on `technicals["macd_signal"]`:
   - `"bearish"` → `25`
   - `"neutral"` → `12`
   - `"bullish"` → `0`
   - anything else → `0`
   - Detail: `f"{macd.capitalize()}, {technicals.get('macd_notes', '')}"`.

4. **Bollinger %B** (max 15) — compute directly from `daily_closes` (do not use `technicals["bollinger_position"]`, which is bucketed too coarsely):
   - `mean = daily_closes.rolling(20).mean().iloc[-1]`, `std = daily_closes.rolling(20).std().iloc[-1]`
   - `upper = mean + 2*std`, `lower = mean - 2*std`
   - `pct_b = (live_price - lower) / (upper - lower)` (guard `std == 0` → factor is `0`, detail `"N/A"`; fewer than 20 closes → same)
   - `0.65 <= pct_b <= 0.85` → `15`
   - `0.5 <= pct_b < 0.65` or `0.85 < pct_b <= 1.0` → `9`
   - `0.3 <= pct_b < 0.5` → `5`
   - else → `0`
   - Detail: `f"%B {pct_b:.2f}"`.

5. **Swing High Distance** (max 15) — trailing 3-month (63 trading day) closing high, same convention as `cc_signal.py`'s Strike Safety factor (`daily_closes.iloc[-63:].max()`):
   - Fewer than 63 closes → `0`, detail `"Insufficient data"`.
   - `live_price > recent_high` (making a new high) → `0`, detail `f"New high (${live_price:.2f} > 3M high ${recent_high:.2f})"`.
   - Else `dist_pct = (recent_high - live_price) / recent_high * 100`:
     - `dist_pct <= 3` → `15`, detail `f"At resistance (-{dist_pct:.1f}% from 3M high ${recent_high:.2f})"`
     - `3 < dist_pct <= 8` → `8`, detail `f"Near resistance (-{dist_pct:.1f}% from 3M high ${recent_high:.2f})"`
     - `dist_pct > 8` → `0`, detail `f"Well below resistance (-{dist_pct:.1f}% from 3M high ${recent_high:.2f})"`

6. **Day Color** (max 15) — `pct_chg = (live_price - prev_close) / prev_close * 100` (guard `prev_close == 0` → `pct_chg = 0`):
   - `pct_chg > 0.5` → `15`, detail `f"Green ({pct_chg:+.1f}%)"`
   - `-0.5 <= pct_chg <= 0.5` → `7`, detail `f"Neutral ({pct_chg:+.1f}%)"`
   - `pct_chg < -0.5` → `0`, detail `f"Red ({pct_chg:+.1f}%)"`

**Confluence bonus:** after summing the six factors, if `rsi_14 is not None and rsi_14 >= 70` AND `technicals.get("macd_signal") == "bearish"` AND day-color `pct_chg > 0.5` (all three literally true, i.e. the "perfect setup"), add `10` to the total, capped at `100`.

**Grade thresholds:** `total >= 80` → `"strong"`, `total >= 60` → `"moderate"`, `total >= 40` → `"weak"`, else `"wait"`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_cc_timing_signal.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_cc_timing_signal.py -v`
Expected: `ModuleNotFoundError: No module named 'app.services.cc_timing_signal'` (all tests fail/error).

- [ ] **Step 3: Implement `_score_cc_timing_factors`**

```python
# backend/app/services/cc_timing_signal.py
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
    macd = technicals.get("macd_signal", "neutral")
    macd_map = {"bearish": 25, "neutral": 12, "bullish": 0}
    macd_pts = macd_map.get(macd, 0)
    macd_notes = technicals.get("macd_notes", "")
    factors.append({"name": "MACD(W)", "points": macd_pts, "max": 25, "detail": f"{macd.capitalize()}, {macd_notes}"})

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_cc_timing_signal.py -v`
Expected: all tests `PASS`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/cc_timing_signal.py backend/tests/test_cc_timing_signal.py
git commit -m "feat(wheel): add CC Timing Signal scoring engine"
```

---

## Task 2: Backend — live compute wrapper with IV gate, commentary, and caching

**Files:**
- Modify: `backend/app/services/cc_timing_signal.py` (append to file created in Task 1)
- Test: `backend/tests/test_cc_timing_signal.py` (append)

**Interfaces:**
- Consumes: `_score_cc_timing_factors(...)` from Task 1 (exact signature above); `fetch_technicals(ticker: str, return_closes: bool = False) -> dict | tuple[dict, pd.Series]` from `app.services.technicals_fetcher`; `compute_iv_percentile_from_chain(daily_closes, chain, ticker, contract_type) -> tuple[float | None, float | None]` from `app.services.technicals_fetcher`; `get_schwab_client()` from `app.services.schwab_client`; `_get_llm_commentary(ticker, score, grade, factors, technicals, iv_percentile, spot) -> dict` from `app.services.cc_signal` (unmodified, reused as-is).
- Produces: `compute_cc_timing_signal(ticker: str, force: bool = False) -> dict` — the function Task 3's router calls. Response dict shape (mirrors `CCSignalResult` in the frontend exactly):
  ```python
  {
      "ticker": str, "score": int, "grade": str,
      "iv_percentile": float | None, "atm_iv": float | None, "spot_price": float | None,
      "factors": list[dict], "commentary": str | None, "strike_hint": str | None,
      "caution": str | None, "cached_at": str, "fetch_status": str, "fetch_error": str | None,
  }
  ```

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_cc_timing_signal.py

def test_compute_fresh_applies_iv_gate_and_calls_schwab():
    from unittest.mock import patch, MagicMock
    from datetime import date, timedelta

    closes = _make_daily_closes(n=100, base=100.0, volatility=0.001, trend=0.0)

    mock_client = MagicMock()
    mock_client.get_quotes.return_value = {"AAPL": {"lastPrice": float(closes.iloc[-1])}}

    exp_date = (date.today() + timedelta(days=37)).strftime("%Y-%m-%d")
    mock_client.get_option_chain.return_value = {
        "underlyingPrice": float(closes.iloc[-1]),
        "callExpDateMap": {
            f"{exp_date}:37": {
                str(round(float(closes.iloc[-1]))): [{"volatility": 5.0}],  # very low IV -> gate triggers
            }
        },
    }

    technicals = {
        "rsi_14": 75.0,
        "macd_signal": "bearish",
        "macd_notes": "below 0 line",
        "fetch_status": "ok",
    }

    with patch("app.services.cc_timing_signal.get_schwab_client", return_value=mock_client), \
         patch("app.services.cc_timing_signal.fetch_technicals", return_value=(technicals, closes)), \
         patch("app.services.cc_timing_signal._get_llm_commentary", return_value={"commentary": None, "strike_hint": None, "caution": None}):
        from app.services.cc_timing_signal import _compute_cc_timing_fresh
        result = _compute_cc_timing_fresh("AAPL")

    assert result["fetch_status"] == "ok"
    assert result["ticker"] == "AAPL"
    mock_client.get_quotes.assert_called_once_with(["AAPL"])
    mock_client.get_option_chain.assert_called_once_with("AAPL", contract_type="CALL", strike_count=30)
    # IV percentile is very low (below the 20th-percentile gate) -> grade capped, caution set
    assert result["grade"] != "strong"
    assert result["caution"] is not None and "premium" in result["caution"].lower()


def test_compute_cc_timing_signal_uses_cache():
    from unittest.mock import patch
    import app.services.cc_timing_signal as mod

    mod._cc_timing_cache.clear()
    call_count = {"n": 0}

    def fake_fresh(ticker):
        call_count["n"] += 1
        return {"ticker": ticker, "score": 50, "grade": "moderate", "iv_percentile": None,
                "atm_iv": None, "spot_price": 100.0, "factors": [], "commentary": None,
                "strike_hint": None, "caution": None, "cached_at": "2026-01-01T00:00:00+00:00",
                "fetch_status": "ok", "fetch_error": None}

    with patch("app.services.cc_timing_signal._compute_cc_timing_fresh", side_effect=fake_fresh):
        mod.compute_cc_timing_signal("AAPL")
        mod.compute_cc_timing_signal("AAPL")  # should hit cache, not call fresh again
    assert call_count["n"] == 1

    with patch("app.services.cc_timing_signal._compute_cc_timing_fresh", side_effect=fake_fresh):
        mod.compute_cc_timing_signal("AAPL", force=True)  # force bypasses cache
    assert call_count["n"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_cc_timing_signal.py -k "compute_fresh or uses_cache" -v`
Expected: FAIL with `ImportError: cannot import name '_compute_cc_timing_fresh'`.

- [ ] **Step 3: Implement the live-compute wrapper**

Append to `backend/app/services/cc_timing_signal.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_cc_timing_signal.py -v`
Expected: all tests `PASS`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/cc_timing_signal.py backend/tests/test_cc_timing_signal.py
git commit -m "feat(wheel): add live compute + IV gate + caching for CC Timing Signal"
```

---

## Task 3: Backend — API route

**Files:**
- Modify: `backend/app/routers/market.py:17` (import line), `backend/app/routers/market.py:112-124` area (add new route near `/cc-signal/{ticker}`)

**Interfaces:**
- Consumes: `compute_cc_timing_signal(ticker: str, force: bool = False) -> dict` from Task 2.
- Produces: `GET /api/market/cc-timing-signal/{ticker}?refresh=true` — same request/response contract as the existing `/cc-signal/{ticker}` route (`market.py:112-116`), which Task 4's frontend API client depends on.

- [ ] **Step 1: Add the import**

In `backend/app/routers/market.py`, change line 17 from:
```python
from app.services.cc_signal import compute_cc_signal, compute_combined_signal, compute_sp_signal, fetch_option_mid
```
to:
```python
from app.services.cc_signal import compute_cc_signal, compute_combined_signal, compute_sp_signal, fetch_option_mid
from app.services.cc_timing_signal import compute_cc_timing_signal
```

- [ ] **Step 2: Add the route**

Immediately after the existing `/cc-signal/{ticker}` route (`backend/app/routers/market.py:112-116`), insert:

```python
@router.get("/cc-timing-signal/{ticker}")
async def get_cc_timing_signal(ticker: str, refresh: bool = False):
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, compute_cc_timing_signal, ticker.upper(), refresh)
    return JSONResponse(content=result)
```

- [ ] **Step 3: Verify the app imports cleanly**

Run: `cd backend && python -c "from app.routers import market"`
Expected: no output, exit code 0 (import succeeds).

- [ ] **Step 4: Verify existing router tests still pass**

Run: `cd backend && python -m pytest tests/ -k "market or wheel" -q`
Expected: same pass/fail counts as before this change (no new failures introduced; pre-existing failures in `test_cc_signal.py` noted in Global Constraints are unaffected since that file wasn't touched).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/market.py
git commit -m "feat(wheel): expose CC Timing Signal via /api/market/cc-timing-signal"
```

---

## Task 4: Frontend — API client

**Files:**
- Modify: `frontend/src/api/wheel.ts:77-87` (add new export after `combinedSignalApi`)

**Interfaces:**
- Consumes: `CCSignalResult` type (already imported at the top of `wheel.ts`); `apiFetch` helper (already imported).
- Produces: `ccTimingSignalApi.get(ticker: string, refresh?: boolean) -> Promise<CCSignalResult>`, called by Task 5.

- [ ] **Step 1: Add the API client export**

In `frontend/src/api/wheel.ts`, immediately after the `combinedSignalApi` block (ends at line 87), insert:

```typescript
export const ccTimingSignalApi = {
  get: (ticker: string, refresh = false) =>
    apiFetch<CCSignalResult>(`/market/cc-timing-signal/${encodeURIComponent(ticker)}${refresh ? '?refresh=true' : ''}`),
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/wheel.ts
git commit -m "feat(wheel): add ccTimingSignalApi client"
```

---

## Task 5: Frontend — wire into WheelDashboardPage state, cache, and fetch loop

**Files:**
- Modify: `frontend/src/pages/WheelDashboardPage.tsx` (multiple locations, listed per step)

**Interfaces:**
- Consumes: `ccTimingSignalApi` from Task 4; existing `CacheEntry<T>`, `seedFromCache`, `isCacheFresh` helpers already defined at `WheelDashboardPage.tsx:44-74`.
- Produces: `ccTimingSignals: Record<string, CCSignalResult | 'loading' | 'error'>` state variable, populated by `loadSignals()`, consumed by Task 6's renderers.

- [ ] **Step 1: Import the new API client**

At `frontend/src/pages/WheelDashboardPage.tsx:4`, change:
```typescript
import { wheelApi, combinedSignalApi, optionPriceApi } from '../api/wheel'
```
to:
```typescript
import { wheelApi, combinedSignalApi, optionPriceApi, ccTimingSignalApi } from '../api/wheel'
```

- [ ] **Step 2: Add a module-level cache**

At `frontend/src/pages/WheelDashboardPage.tsx:61` (immediately after the `optionPricesCache` line), insert:
```typescript
const ccTimingCache: Record<string, CacheEntry<CCSignalResult>> = {}
```

- [ ] **Step 3: Add component state seeded from the cache**

At `frontend/src/pages/WheelDashboardPage.tsx:87` (immediately after the `spSignals` state line), insert:
```typescript
const [ccTimingSignals, setCcTimingSignals] = useState<Record<string, CCSignalResult | 'loading' | 'error'>>(() => seedFromCache(ccTimingCache))
```

- [ ] **Step 4: Add loading-state resets in `loadSignals`**

In the `if (force) { ... }` block at `frontend/src/pages/WheelDashboardPage.tsx:127-134`, add a line after `setSpSignals(prev => ({ ...prev, [ticker]: 'loading' }))`:
```typescript
setCcTimingSignals(prev => ({ ...prev, [ticker]: 'loading' }))
```

In the `else { ... }` block at `frontend/src/pages/WheelDashboardPage.tsx:135-144`, add a line after the `spSignalsCache` freshness check:
```typescript
if (!isCacheFresh(ccTimingCache, ticker)) setCcTimingSignals(prev => ({ ...prev, [ticker]: 'loading' }))
```

- [ ] **Step 5: Add the fetch call to the `Promise.allSettled` batch**

In `frontend/src/pages/WheelDashboardPage.tsx`, immediately after the `combinedSignalApi.get(...)` block (ends at `frontend/src/pages/WheelDashboardPage.tsx:163`, before the `technicalsApi.quote(...)` block), insert:
```typescript
      ...tickersToFetch.map(ticker =>
        ccTimingSignalApi.get(ticker, force)
          .then(result => {
            setCcTimingSignals(prev => ({ ...prev, [ticker]: result }))
            ccTimingCache[ticker] = { data: result, ts: Date.now() }
          })
          .catch(() => setCcTimingSignals(prev => ({ ...prev, [ticker]: 'error' })))
      ),
```

- [ ] **Step 6: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors (state is declared and used, so no unused-variable warnings).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/WheelDashboardPage.tsx
git commit -m "feat(wheel): fetch CC Timing Signal alongside existing signals"
```

---

## Task 6: Frontend — badge, expandable detail row, and AWAITING CC column

**Files:**
- Modify: `frontend/src/pages/WheelDashboardPage.tsx` (renderer functions + Awaiting CC table)

**Interfaces:**
- Consumes: `ccTimingSignals` state from Task 5; `GRADE_COLORS` constant (already defined at `WheelDashboardPage.tsx:40-45`).
- Produces: visible "CC Timing" badge column in the AWAITING CC table, click-to-expand breakdown matching the existing CC/SP Signal UX.

- [ ] **Step 1: Generalize `renderSignalBadge`'s type union**

At `frontend/src/pages/WheelDashboardPage.tsx:356`, change:
```typescript
  function renderSignalBadge(ticker: string, sigMap: Record<string, CCSignalResult | 'loading' | 'error'>, type: 'CC' | 'SP') {
```
to:
```typescript
  function renderSignalBadge(ticker: string, sigMap: Record<string, CCSignalResult | 'loading' | 'error'>, type: 'CC' | 'SP' | 'Timing') {
```
(No other changes needed in this function — it's already generic on `type` for the `detailKey` and title.)

- [ ] **Step 2: Extend `renderSignalDetailRow` to handle the Timing key**

At `frontend/src/pages/WheelDashboardPage.tsx:372-380`, change:
```typescript
  function renderSignalDetailRow(ticker: string, colCount = 11) {
    const ccKey = `${ticker}-CC`
    const spKey = `${ticker}-SP`
    const isCC = signalDetail === ccKey
    const isSP = signalDetail === spKey
    if (!isCC && !isSP) return null
    const sig = isCC ? signals[ticker] : spSignals[ticker]
    const label = isCC ? 'CC Signal' : 'SP Signal'
    if (!sig || sig === 'loading' || sig === 'error') return null
```
to:
```typescript
  function renderSignalDetailRow(ticker: string, colCount = 11) {
    const ccKey = `${ticker}-CC`
    const spKey = `${ticker}-SP`
    const timingKey = `${ticker}-Timing`
    const isCC = signalDetail === ccKey
    const isSP = signalDetail === spKey
    const isTiming = signalDetail === timingKey
    if (!isCC && !isSP && !isTiming) return null
    const sig = isCC ? signals[ticker] : isSP ? spSignals[ticker] : ccTimingSignals[ticker]
    const label = isCC ? 'CC Signal' : isSP ? 'SP Signal' : 'CC Timing'
    if (!sig || sig === 'loading' || sig === 'error') return null
```
The rest of the function (the JSX body rendering `sig.factors`, `sig.commentary`, etc.) is unchanged — it already works generically off `sig` and `label`.

- [ ] **Step 3: Add the badge cell to the Awaiting CC row**

At `frontend/src/pages/WheelDashboardPage.tsx:502`, change:
```typescript
        <td className="py-2 pr-3">{renderSignalBadge(ticker, signals, 'CC')}</td>
```
to:
```typescript
        <td className="py-2 pr-3">{renderSignalBadge(ticker, signals, 'CC')}</td>
        <td className="py-2 pr-3">{renderSignalBadge(ticker, ccTimingSignals, 'Timing')}</td>
```
(This is inside `renderAwaitingCCSlotRow` only — do not change the analogous line in `renderAwaitingSPSlotRow` at `WheelDashboardPage.tsx:609` or in `renderSlotRow` at `WheelDashboardPage.tsx:445-446`.)

- [ ] **Step 4: Add the column header and bump colCount for the Awaiting CC section**

At `frontend/src/pages/WheelDashboardPage.tsx:572` (inside `renderAwaitingCCSection`'s `<thead>`), change:
```typescript
                <th className="py-2 pr-3 font-normal">CC Signal</th>
                <th className="py-2 pr-3 font-normal">% G/L</th>
```
to:
```typescript
                <th className="py-2 pr-3 font-normal">CC Signal</th>
                <th className="py-2 pr-3 font-normal">CC Timing</th>
                <th className="py-2 pr-3 font-normal">% G/L</th>
```

Then, in the same function, at `frontend/src/pages/WheelDashboardPage.tsx:582-583`, change:
```typescript
                  {renderLegRows(f, 11)}
                  {isFirstForTicker && renderSignalDetailRow(f.ticker, 11)}
```
to:
```typescript
                  {renderLegRows(f, 12)}
                  {isFirstForTicker && renderSignalDetailRow(f.ticker, 12)}
```
(Only within `renderAwaitingCCSection` — the Awaiting Sold Put and Active sections keep `colCount = 11`.)

- [ ] **Step 5: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 6: Lint check for regressions**

Run: `cd frontend && npx eslint src/pages/WheelDashboardPage.tsx`
Expected: same findings as before this task (`'WheelSessionSummary' is defined but never used`, two `set-state-in-effect` errors, one `exhaustive-deps` warning — all pre-existing per the WHEEL dashboard's git history, none newly introduced).

- [ ] **Step 7: Manual verification**

Run: `cd frontend && npm run dev` (or the project's existing dev-server invocation), navigate to `/wheel`, confirm:
- The AWAITING CC table shows a new "CC Timing" column between "CC Signal" and "% G/L".
- Clicking the CC Timing badge expands a "CC Timing breakdown" panel listing the 6 factors (RSI(D) Level, RSI(D) Trend, MACD(W), Bollinger %B, Swing High Distance, Day Color) with points/max/detail, plus commentary/caution if present.
- The Awaiting Sold Put and Active boxes are unchanged (no CC Timing column).
- The per-section "Fetch" button on AWAITING CC refreshes the CC Timing badge along with CC Signal.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/WheelDashboardPage.tsx
git commit -m "feat(wheel): show CC Timing Signal badge and breakdown in AWAITING CC"
```

---

## Self-Review Notes

- **Spec coverage:** RSI(D) piecewise curve (Task 1, factor 1) ✓. RSI(D) trend rolling-over (Task 1, factor 2) ✓. MACD(W) bearish-favored scoring, explicitly inverted from `cc_signal.py` (Task 1, factor 3) ✓. Bollinger %B continuous mid-upper zone (Task 1, factor 4) ✓. Swing High Distance (Task 1, factor 5) ✓. Day Color (Task 1, factor 6) ✓. Confluence bonus for the literal "perfect setup" (Task 1) ✓. IV Percentile as a grade-capping gate, not a scored factor (Task 2) ✓. New name "CC Timing Signal" used consistently (badge label, detail heading, commit messages) ✓. Existing CC Signal untouched — new file, no edits to `cc_signal.py` (Global Constraints + Tasks 1–2) ✓. Score/grade/factors/commentary "on-demand explanation" UX matching the existing signal (Task 6) ✓. Scoped to AWAITING CC only (Task 6, Step 3–4 explicitly exclude the other sections) ✓.
- **Deferred from this plan (per prior conversation turns, explicitly out of scope here):** Volume-on-green-day column, Relative-Strength-vs-SPY/sector column, Days-to-earnings gate. None of Tasks 1–6 touch these — confirmed no accidental scope creep.
- **Placeholder scan:** no TBD/TODO, all steps have complete code.
- **Type consistency:** `_score_cc_timing_factors` signature matches between Task 1's definition and Task 2's call site. `compute_cc_timing_signal` / `_compute_cc_timing_fresh` names matches between Task 2's definition and Task 3's router import. `ccTimingSignalApi.get` matches between Task 4's definition and Task 5's call site. `ccTimingSignals` state name matches between Task 5's declaration and Task 6's renderer usage.
