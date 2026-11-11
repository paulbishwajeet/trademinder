# SP Timing Signal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new "SP Timing Signal" (0–100 score + grade + factor breakdown) to the WHEEL dashboard's "AWAITING SOLD PUT" box — a mirror of the existing "CC Timing Signal" (`backend/app/services/cc_timing_signal.py`), answering the inverse question: *is right now a good moment to sell a cash-secured put that's likely to expire OTM (worthless)?*

**Architecture:** A new, standalone backend module (`app/services/sp_timing_signal.py`) mirrors `cc_timing_signal.py`'s structure exactly, with every directional factor inverted for the "expects the stock to hold or rise" thesis (bullish weekly MACD, oversold daily RSI, red day, lower-band Bollinger position, proximity to a trailing swing **low** instead of high). It reuses the same shared helpers (`fetch_technicals()`, `_compute_rsi_14()`, `compute_iv_percentile_from_chain()`, `_get_llm_commentary()`) already used by `cc_timing_signal.py`, but computes IV percentile from the **PUT** chain (matching how `cc_signal.py` already distinguishes CC/SP IV percentile by option type) rather than reusing CC Timing's CALL-chain calculation. A new FastAPI route exposes it, and the frontend adds an "SP Timing" badge column to the AWAITING SOLD PUT table only, reusing the same badge/expand-detail UI pattern and the existing 1-hour client cache. As part of this, the existing 'Timing' badge-type string is renamed to 'CCTiming' to disambiguate from the new 'SPTiming' — without the rename, a ticker with both an awaiting-CC slot and an awaiting-sold-put slot open simultaneously would collide on the same `${ticker}-Timing` detail-row key across two different sections.

**Tech Stack:** FastAPI + pandas (backend scoring), React + TypeScript (frontend), existing Schwab REST client, existing Gemini (`google-genai`) commentary helper — no new dependencies.

## Global Constraints

- Do not modify `backend/app/services/cc_signal.py`, `backend/tests/test_cc_signal.py`, or `backend/app/services/cc_timing_signal.py`'s scoring/compute logic. `cc_timing_signal.py` gets ONE change only: none — it is not touched at all by this plan (the frontend rename of 'Timing'→'CCTiming' lives in `WheelDashboardPage.tsx`, not in the backend module).
- New signal name everywhere: **"SP Timing Signal"** / badge label **"SP Timing"** / detail-panel heading **"SP Timing breakdown"**.
- Score is 0–100 (never negative, capped at 100 even after the confluence bonus).
- IV Percentile is a **grade-capping gate**, not a scored factor — identical logic to CC Timing: if IV percentile < 20, cap `grade` at `"moderate"` even if the raw score would be `"strong"`, and append a caution note. Computed from the **PUT** option chain (not CALL).
- Only the **AWAITING SOLD PUT** box on the WHEEL dashboard gets the new column. Do not add it to Awaiting CC, Active, or Needs Action.
- Reuse the `CCSignalResult` TypeScript type as-is for the new signal's response shape — do not create a parallel type.
- Follow the existing 1-hour client-side cache pattern already in `WheelDashboardPage.tsx` (module-level `Record<string, CacheEntry<T>>` + `seedFromCache` + `isCacheFresh`).
- Backend cache TTL: 4 hours (`_CACHE_TTL = 14400` seconds), via its own independent module-level cache dict — do not share `_cc_timing_cache`.
- The existing badge-type string `'Timing'` (used for CC Timing) must be renamed to `'CCTiming'` throughout `WheelDashboardPage.tsx`, and the new signal uses `'SPTiming'`. This is required to avoid a same-ticker cross-section key collision (see Architecture above) — it is not optional polish.

---

## File Structure

- **Create:** `backend/app/services/sp_timing_signal.py` — pure scoring function `_score_sp_timing_factors()` + live compute functions `_compute_sp_timing_fresh()` / `compute_sp_timing_signal()` + module-level cache. Structurally mirrors `cc_timing_signal.py`.
- **Create:** `backend/tests/test_sp_timing_signal.py` — unit tests for the scoring function (pure, no network) + one mocked test for the live-compute wrapper.
- **Modify:** `backend/app/routers/market.py` — add `GET /api/market/sp-timing-signal/{ticker}` route.
- **Modify:** `frontend/src/api/wheel.ts` — add `spTimingSignalApi`.
- **Modify:** `frontend/src/pages/WheelDashboardPage.tsx` — add cache/state/fetch wiring, rename `'Timing'`→`'CCTiming'` and add `'SPTiming'` to the badge/detail-row renderers, add the "SP Timing" column to the Awaiting Sold Put table only.

---

## Task 1: Backend — pure scoring function with tests (TDD)

**Files:**
- Create: `backend/app/services/sp_timing_signal.py`
- Test: `backend/tests/test_sp_timing_signal.py`

**Interfaces:**
- Consumes: `_compute_rsi_14(close: pd.Series) -> float | None` from `app.services.price_fetcher` (existing, unmodified).
- Produces: `_score_sp_timing_factors(technicals: dict, daily_closes: pd.Series, live_price: float, prev_close: float) -> tuple[int, str, list[dict]]` — returns `(score, grade, factors)`, same shape as `cc_timing_signal.py`'s `_score_cc_timing_factors`. Task 2 calls this function by this exact name and signature.

Scoring spec — every factor here is the directional mirror of `cc_timing_signal.py`'s `_score_cc_timing_factors` (implement exactly):

1. **RSI(D) Level** (max 20) — ideal cutoff at RSI ≤ 40 (oversold), mirrored curve shape (gentle taper immediately above the ideal zone, steep taper further away, matching the same 20-point-wide gentle/steep segment structure as CC Timing's curve, just re-centered so the ideal edge sits at 40 instead of 70):
   ```
   rsi <= 40:          20
   40 < rsi <= 60:      14 + (60 - rsi) * 0.3
   60 < rsi <= 80:      (80 - rsi) * 0.7
   rsi > 80:            0
   ```
   `rsi_14` is `None` → `0`, detail `"N/A"`. Round points to 1 decimal. Detail string: `f"RSI {rsi:.1f}"`.

2. **RSI(D) Trend** (max 10) — "bottoming out from a depressed read" is ideal (mirror of CC Timing's "rolling over from an elevated read"). Reuse the same 6-sample trailing RSI series logic, but with `was_depressed = any(r < 40 for r in rsi_series)` (mirrors CC Timing's `was_elevated = any(r > 60 ...)`):
   - Turning up from a depressed read (`was_depressed and current_rsi > oldest_rsi`) → `10`, detail `f"Bottoming out: {oldest_rsi:.1f} → {current_rsi:.1f}"`
   - Depressed but not yet turning up (`was_depressed and current_rsi <= oldest_rsi`) → `6`, detail `f"Depressed ({current_rsi:.1f}), not yet bottoming out"`
   - Falling strongly from above (`current_rsi < oldest_rsi and current_rsi < 45`) → `1`, detail `f"Falling strongly: {oldest_rsi:.1f} → {current_rsi:.1f}"`
   - Otherwise → `3`, detail `f"Neutral/weak ({current_rsi:.1f})"`
   - Fewer than 20 closes or fewer than 2 RSI samples → `0`, detail `"Insufficient data"`.

3. **MACD(W)** (max 25) — on `technicals["macd_signal"]`, exact inverse of CC Timing:
   - `"bullish"` → `25`
   - `"neutral"` → `12`
   - `"bearish"` → `0`
   - anything else → `0`
   - Detail: `f"{macd.capitalize()}, {technicals.get('macd_notes', '')}"`.

4. **Bollinger %B** (max 15) — compute directly from `daily_closes`, same `%B` formula as CC Timing, but the ideal zone is the lower-mid band (mirror reflection of CC Timing's zones about the 0.5 midpoint):
   - `0.15 <= pct_b <= 0.35` → `15`
   - `0.0 <= pct_b < 0.15` or `0.35 < pct_b <= 0.5` → `9`
   - `0.5 < pct_b <= 0.7` → `5`
   - else (i.e. `pct_b < 0` or `pct_b > 0.7`) → `0`
   - Fewer than 20 closes, or `std == 0` → `0`, detail `"N/A"`.
   - Detail: `f"%B {pct_b:.2f}"`.

5. **Swing Low Distance** (max 15) — trailing 3-month (63 trading day) closing **low** as a support level (mirror of CC Timing's Swing High Distance, which uses the closing high as resistance):
   - Fewer than 63 closes → `0`, detail `"Insufficient data"`.
   - `live_price < recent_low` (making a new low) → `0`, detail `f"New low (${live_price:.2f} < 3M low ${recent_low:.2f})"`.
   - Else `dist_pct = (live_price - recent_low) / recent_low * 100`:
     - `dist_pct <= 3` → `15`, detail `f"At support (+{dist_pct:.1f}% above 3M low ${recent_low:.2f})"`
     - `3 < dist_pct <= 8` → `8`, detail `f"Near support (+{dist_pct:.1f}% above 3M low ${recent_low:.2f})"`
     - `dist_pct > 8` → `0`, detail `f"Well above support (+{dist_pct:.1f}% above 3M low ${recent_low:.2f})"`

6. **Day Color** (max 15) — `pct_chg = (live_price - prev_close) / prev_close * 100` (guard `prev_close == 0` → `pct_chg = 0`), exact inverse of CC Timing:
   - `pct_chg < -0.5` → `15`, detail `f"Red ({pct_chg:+.1f}%)"`
   - `-0.5 <= pct_chg <= 0.5` → `7`, detail `f"Neutral ({pct_chg:+.1f}%)"`
   - `pct_chg > 0.5` → `0`, detail `f"Green ({pct_chg:+.1f}%)"`

**Confluence bonus:** after summing the six factors, if `rsi_14 is not None and rsi_14 <= 40` AND `technicals.get("macd_signal") == "bullish"` AND day-color `pct_chg < -0.5` (all three literally true — the mirrored "perfect setup"), add `10` to the total, capped at `100`.

**Grade thresholds:** identical to CC Timing — `total >= 80` → `"strong"`, `total >= 60` → `"moderate"`, `total >= 40` → `"weak"`, else `"wait"`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_sp_timing_signal.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_sp_timing_signal.py -v`
Expected: `ModuleNotFoundError: No module named 'app.services.sp_timing_signal'` (all tests fail/error).

- [ ] **Step 3: Implement `_score_sp_timing_factors`**

```python
# backend/app/services/sp_timing_signal.py
"""Standalone 'SP Timing Signal' — scores how good a moment it is to sell a cash-secured
put likely to expire OTM (mean-reversion entry timing), mirroring cc_timing_signal.py's
architecture with every directional factor inverted for the 'stock holds or rises' thesis.
Independent of the existing CC/SP Signal in cc_signal.py, which optimizes for overall
wheel P&L instead."""
import logging
import time
from datetime import datetime, timezone

import pandas as pd

from app.services.price_fetcher import _compute_rsi_14
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

    # 2. RSI(D) Trend (10 pts) — bottoming out from a depressed read = ideal.
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
            was_depressed = any(r < 40 for r in rsi_series)
            if was_depressed and current_rsi > oldest_rsi:
                trend_pts = 10
                trend_detail = f"Bottoming out: {oldest_rsi:.1f} → {current_rsi:.1f}"
            elif was_depressed and current_rsi <= oldest_rsi:
                trend_pts = 6
                trend_detail = f"Depressed ({current_rsi:.1f}), not yet bottoming out"
            elif current_rsi < oldest_rsi and current_rsi < 45:
                trend_pts = 1
                trend_detail = f"Falling strongly: {oldest_rsi:.1f} → {current_rsi:.1f}"
            else:
                trend_pts = 3
                trend_detail = f"Neutral/weak ({current_rsi:.1f})"
    factors.append({"name": "RSI(D) Trend", "points": trend_pts, "max": 10, "detail": trend_detail})

    # 3. MACD(W) (25 pts) — bullish weekly = tailwind, confirms the "holds or rises" thesis.
    macd = technicals.get("macd_signal", "neutral")
    macd_map = {"bullish": 25, "neutral": 12, "bearish": 0}
    macd_pts = macd_map.get(macd, 0)
    macd_notes = technicals.get("macd_notes", "")
    factors.append({"name": "MACD(W)", "points": macd_pts, "max": 25, "detail": f"{macd.capitalize()}, {macd_notes}"})

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_sp_timing_signal.py -v`
Expected: all tests `PASS`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sp_timing_signal.py backend/tests/test_sp_timing_signal.py
git commit -m "feat(wheel): add SP Timing Signal scoring engine"
```

---

## Task 2: Backend — live compute wrapper with IV gate (PUT chain), commentary, and caching

**Files:**
- Modify: `backend/app/services/sp_timing_signal.py` (append to file created in Task 1)
- Test: `backend/tests/test_sp_timing_signal.py` (append)

**Interfaces:**
- Consumes: `_score_sp_timing_factors(...)` from Task 1 (exact signature above); `fetch_technicals(ticker: str, return_closes: bool = False) -> dict | tuple[dict, pd.Series]` from `app.services.technicals_fetcher`; `compute_iv_percentile_from_chain(daily_closes, chain, ticker, contract_type) -> tuple[float | None, float | None]` from `app.services.technicals_fetcher`; `get_schwab_client()` from `app.services.schwab_client`; `_get_llm_commentary(ticker, score, grade, factors, technicals, iv_percentile, spot) -> dict` from `app.services.cc_signal` (unmodified, reused as-is).
- Produces: `compute_sp_timing_signal(ticker: str, force: bool = False) -> dict` — the function Task 3's router calls. Response dict shape mirrors `CCSignalResult` exactly (identical field set to `compute_cc_timing_signal`'s return value).

The only structural difference from `cc_timing_signal.py`'s Task 2 (`_compute_cc_timing_fresh`) is that the option chain fetched for the IV-percentile gate is the **PUT** chain, not CALL — matching how `cc_signal.py`'s `_compute_combined_fresh` already computes `sp_iv_pct` from a PUT chain for the existing SP Signal.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_sp_timing_signal.py

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_sp_timing_signal.py -k "compute_fresh or uses_cache" -v`
Expected: FAIL with `ImportError: cannot import name '_compute_sp_timing_fresh'`.

- [ ] **Step 3: Implement the live-compute wrapper**

Append to `backend/app/services/sp_timing_signal.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_sp_timing_signal.py -v`
Expected: all tests `PASS`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sp_timing_signal.py backend/tests/test_sp_timing_signal.py
git commit -m "feat(wheel): add live compute + IV gate (PUT chain) + caching for SP Timing Signal"
```

---

## Task 3: Backend — API route

**Files:**
- Modify: `backend/app/routers/market.py:18` (import line area), `backend/app/routers/market.py:120-124` area (add new route immediately after `/cc-timing-signal/{ticker}`)

**Interfaces:**
- Consumes: `compute_sp_timing_signal(ticker: str, force: bool = False) -> dict` from Task 2.
- Produces: `GET /api/market/sp-timing-signal/{ticker}?refresh=true` — same request/response contract as `/cc-timing-signal/{ticker}` (`market.py:120-124`), which Task 4's frontend API client depends on.

- [ ] **Step 1: Add the import**

In `backend/app/routers/market.py`, immediately after the line:
```python
from app.services.cc_timing_signal import compute_cc_timing_signal
```
add:
```python
from app.services.sp_timing_signal import compute_sp_timing_signal
```

- [ ] **Step 2: Add the route**

Immediately after the existing `/cc-timing-signal/{ticker}` route, insert:

```python
@router.get("/sp-timing-signal/{ticker}")
async def get_sp_timing_signal(ticker: str, refresh: bool = False):
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, compute_sp_timing_signal, ticker.upper(), refresh)
    return JSONResponse(content=result)
```

- [ ] **Step 3: Verify the app imports cleanly**

Run: `cd backend && python -c "from app.routers import market"`
Expected: no output, exit code 0.

- [ ] **Step 4: Verify existing tests still pass**

Run: `cd backend && python -m pytest -q`
Expected: same pass/fail counts as before this change plus the new `test_sp_timing_signal.py` tests (no new failures introduced; pre-existing failures unrelated to this work are unaffected — verify by comparing counts against a run before this task).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/market.py
git commit -m "feat(wheel): expose SP Timing Signal via /api/market/sp-timing-signal"
```

---

## Task 4: Frontend — API client

**Files:**
- Modify: `frontend/src/api/wheel.ts` (add new export immediately after `ccTimingSignalApi`)

**Interfaces:**
- Consumes: `CCSignalResult` type (already imported at the top of `wheel.ts`); `apiFetch` helper (already imported).
- Produces: `spTimingSignalApi.get(ticker: string, refresh?: boolean) -> Promise<CCSignalResult>`, called by Task 5.

- [ ] **Step 1: Add the API client export**

In `frontend/src/api/wheel.ts`, immediately after the `ccTimingSignalApi` block, insert:

```typescript
export const spTimingSignalApi = {
  get: (ticker: string, refresh = false) =>
    apiFetch<CCSignalResult>(`/market/sp-timing-signal/${encodeURIComponent(ticker)}${refresh ? '?refresh=true' : ''}`),
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/wheel.ts
git commit -m "feat(wheel): add spTimingSignalApi client"
```

---

## Task 5: Frontend — wire into WheelDashboardPage state, cache, and fetch loop

**Files:**
- Modify: `frontend/src/pages/WheelDashboardPage.tsx` (multiple locations, listed per step)

**Interfaces:**
- Consumes: `spTimingSignalApi` from Task 4; existing `CacheEntry<T>`, `seedFromCache`, `isCacheFresh` helpers already in the file.
- Produces: `spTimingSignals: Record<string, CCSignalResult | 'loading' | 'error'>` state variable, populated by `loadSignals()`, consumed by Task 6's renderers.

The file already has this exact pattern implemented three times (`signals`/`spSignals`/`ccTimingSignals`) — locate each by matching the surrounding code shown below (current line numbers may have shifted; anchor on the text, not the number).

- [ ] **Step 1: Import the new API client**

Change:
```typescript
import { wheelApi, combinedSignalApi, optionPriceApi, ccTimingSignalApi } from '../api/wheel'
```
to:
```typescript
import { wheelApi, combinedSignalApi, optionPriceApi, ccTimingSignalApi, spTimingSignalApi } from '../api/wheel'
```

- [ ] **Step 2: Add a module-level cache**

Immediately after the line:
```typescript
const ccTimingCache: Record<string, CacheEntry<CCSignalResult>> = {}
```
insert:
```typescript
const spTimingCache: Record<string, CacheEntry<CCSignalResult>> = {}
```

- [ ] **Step 3: Add component state seeded from the cache**

Immediately after the line:
```typescript
const [ccTimingSignals, setCcTimingSignals] = useState<Record<string, CCSignalResult | 'loading' | 'error'>>(() => seedFromCache(ccTimingCache))
```
insert:
```typescript
const [spTimingSignals, setSpTimingSignals] = useState<Record<string, CCSignalResult | 'loading' | 'error'>>(() => seedFromCache(spTimingCache))
```

- [ ] **Step 4: Add loading-state resets in `loadSignals`**

In the `if (force) { ... }` block, immediately after the line:
```typescript
setCcTimingSignals(prev => ({ ...prev, [ticker]: 'loading' }))
```
insert:
```typescript
setSpTimingSignals(prev => ({ ...prev, [ticker]: 'loading' }))
```

In the `else { ... }` block, immediately after the line:
```typescript
if (!isCacheFresh(ccTimingCache, ticker)) setCcTimingSignals(prev => ({ ...prev, [ticker]: 'loading' }))
```
insert:
```typescript
if (!isCacheFresh(spTimingCache, ticker)) setSpTimingSignals(prev => ({ ...prev, [ticker]: 'loading' }))
```

- [ ] **Step 5: Add the fetch call to the `Promise.allSettled` batch**

Immediately after the `ccTimingSignalApi.get(...)` block inside the `Promise.allSettled([...])` array (identifiable by its `.then()` writing to `setCcTimingSignals` and `ccTimingCache`), insert:
```typescript
      ...tickersToFetch.map(ticker =>
        spTimingSignalApi.get(ticker, force)
          .then(result => {
            setSpTimingSignals(prev => ({ ...prev, [ticker]: result }))
            spTimingCache[ticker] = { data: result, ts: Date.now() }
          })
          .catch(() => setSpTimingSignals(prev => ({ ...prev, [ticker]: 'error' })))
      ),
```

- [ ] **Step 6: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 7: Expected interim lint state (do not try to fix in this task)**

Run: `cd frontend && npx eslint src/pages/WheelDashboardPage.tsx` — expect ONE new `'spTimingSignals' is assigned a value but never used` finding on top of the pre-existing baseline (currently 3 problems: `no-unused-vars` on `WheelSessionSummary`, one `react-hooks/set-state-in-effect` error, one `exhaustive-deps` warning). This is expected and intentional — `spTimingSignals` has no JSX consumer until Task 6. It resolves automatically once Task 6 lands.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/WheelDashboardPage.tsx
git commit -m "feat(wheel): fetch SP Timing Signal alongside existing signals"
```

---

## Task 6: Frontend — rename 'Timing'→'CCTiming', add 'SPTiming' badge, and AWAITING SOLD PUT column

**Files:**
- Modify: `frontend/src/pages/WheelDashboardPage.tsx` (renderer functions + Awaiting Sold Put table)

**Interfaces:**
- Consumes: `spTimingSignals` state from Task 5; `GRADE_COLORS` constant (already defined in the file).
- Produces: visible "SP Timing" badge column in the AWAITING SOLD PUT table, click-to-expand breakdown matching the existing CC/SP/CC-Timing UX. Also disambiguates the CC Timing badge type from `'Timing'` to `'CCTiming'` to prevent a same-ticker cross-section key collision (a ticker can simultaneously have a slot in AWAITING CC and a different slot in AWAITING SOLD PUT; both currently would have collided on `${ticker}-Timing`).

- [ ] **Step 1: Rename the badge type union and disambiguate keys**

Locate `renderSignalBadge`'s signature:
```typescript
  function renderSignalBadge(ticker: string, sigMap: Record<string, CCSignalResult | 'loading' | 'error'>, type: 'CC' | 'SP' | 'Timing') {
```
Change to:
```typescript
  function renderSignalBadge(ticker: string, sigMap: Record<string, CCSignalResult | 'loading' | 'error'>, type: 'CC' | 'SP' | 'CCTiming' | 'SPTiming') {
```
(No other change needed inside this function — `detailKey` is already built generically as `` `${ticker}-${type}` ``.)

- [ ] **Step 2: Update the badge invocation for CC Timing**

Find the existing call inside `renderAwaitingCCSlotRow`:
```typescript
        <td className="py-2 pr-3">{renderSignalBadge(ticker, ccTimingSignals, 'Timing')}</td>
```
Change the type argument only:
```typescript
        <td className="py-2 pr-3">{renderSignalBadge(ticker, ccTimingSignals, 'CCTiming')}</td>
```

- [ ] **Step 3: Extend `renderSignalDetailRow` for both Timing variants**

Locate:
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
Replace with:
```typescript
  function renderSignalDetailRow(ticker: string, colCount = 11) {
    const ccKey = `${ticker}-CC`
    const spKey = `${ticker}-SP`
    const ccTimingKey = `${ticker}-CCTiming`
    const spTimingKey = `${ticker}-SPTiming`
    const isCC = signalDetail === ccKey
    const isSP = signalDetail === spKey
    const isCCTiming = signalDetail === ccTimingKey
    const isSPTiming = signalDetail === spTimingKey
    if (!isCC && !isSP && !isCCTiming && !isSPTiming) return null
    const sig = isCC ? signals[ticker] : isSP ? spSignals[ticker] : isCCTiming ? ccTimingSignals[ticker] : spTimingSignals[ticker]
    const label = isCC ? 'CC Signal' : isSP ? 'SP Signal' : isCCTiming ? 'CC Timing' : 'SP Timing'
    if (!sig || sig === 'loading' || sig === 'error') return null
```
The rest of the function (the JSX body rendering `sig.factors`, `sig.commentary`, etc.) is unchanged.

- [ ] **Step 4: Add the badge cell to the Awaiting Sold Put row**

Locate, inside `renderAwaitingSPSlotRow` specifically (NOT `renderSlotRow`, which is the generic row used by Active/NeedsAction):
```typescript
        <td className="py-2 pr-3">{renderSignalBadge(ticker, spSignals, 'SP')}</td>
```
(this exact line appears in multiple functions — confirm you are inside `renderAwaitingSPSlotRow` by checking it is immediately preceded by `{renderMacdCell(ticker)}` and followed by `{renderGainLossCell(f)}` with no `renderPnlCell` call anywhere in the same function body). Change to:
```typescript
        <td className="py-2 pr-3">{renderSignalBadge(ticker, spSignals, 'SP')}</td>
        <td className="py-2 pr-3">{renderSignalBadge(ticker, spTimingSignals, 'SPTiming')}</td>
```

- [ ] **Step 5: Add the column header and bump colCount for the Awaiting Sold Put section**

Inside `renderAwaitingSPSection`'s `<thead>`, locate:
```typescript
                <th className="py-2 pr-3 font-normal">SP Signal</th>
                <th className="py-2 pr-3 font-normal">% G/L</th>
```
Change to:
```typescript
                <th className="py-2 pr-3 font-normal">SP Signal</th>
                <th className="py-2 pr-3 font-normal">SP Timing</th>
                <th className="py-2 pr-3 font-normal">% G/L</th>
```

Then, still within `renderAwaitingSPSection`, locate:
```typescript
                  {renderAwaitingSPSlotRow(f)}
                  {renderLegRows(f, 11)}
                  {isFirstForTicker && renderSignalDetailRow(f.ticker, 11)}
```
Change to:
```typescript
                  {renderAwaitingSPSlotRow(f)}
                  {renderLegRows(f, 12)}
                  {isFirstForTicker && renderSignalDetailRow(f.ticker, 12)}
```
(Only within `renderAwaitingSPSection` — do not touch `renderAwaitingCCSection`'s `colCount = 12` calls, which are a separate, already-correct instance of this same pattern.)

- [ ] **Step 6: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 7: Lint check — confirm both interim issues are resolved**

Run: `cd frontend && npx eslint src/pages/WheelDashboardPage.tsx`
Expected: back to the 3-problem baseline (no `spTimingSignals` unused-var finding — it's now consumed by this task's JSX). If it's still 4, something is wrong — investigate before proceeding.

- [ ] **Step 8: Manual verification**

Run: `cd frontend && npm run dev`, navigate to `/wheel`, confirm:
- The AWAITING SOLD PUT table shows a new "SP Timing" column between "SP Signal" and "% G/L".
- Clicking the SP Timing badge expands an "SP Timing breakdown" panel listing the 6 factors (RSI(D) Level, RSI(D) Trend, MACD(W), Bollinger %B, Swing Low Distance, Day Color).
- The AWAITING CC box's "CC Timing" badge still works identically to before (verifying the rename didn't break it).
- If a ticker happens to have slots in both AWAITING CC and AWAITING SOLD PUT simultaneously, opening one signal's detail panel and then the other's does not show stale or duplicated data (verifies the key-collision fix).
- The Active and Needs Action boxes are unchanged.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/pages/WheelDashboardPage.tsx
git commit -m "feat(wheel): show SP Timing Signal badge and breakdown in AWAITING SOLD PUT"
```

---

## Self-Review Notes

- **Spec coverage:** RSI(D) Level mirrored curve with ideal cutoff at ≤40 per user's explicit choice (Task 1, factor 1) ✓. RSI(D) Trend bottoming-out mirror (Task 1, factor 2) ✓. MACD(W) bullish-favored, exact inverse of CC Timing (Task 1, factor 3) ✓. Bollinger %B lower-mid zone, mirror reflection about 0.5 (Task 1, factor 4) ✓. Swing Low Distance mirroring Swing High Distance (Task 1, factor 5) ✓. Day Color red-favored, exact inverse (Task 1, factor 6) ✓. Confluence bonus mirrored (Task 1) ✓. IV Percentile gate identical logic but PUT chain (Task 2) ✓. New name "SP Timing Signal" used consistently ✓. `cc_signal.py` and `cc_timing_signal.py` untouched — new file only (Global Constraints + Tasks 1–2) ✓. Scoped to AWAITING SOLD PUT only (Task 6, Steps 4–5 explicitly exclude other sections) ✓. Badge-type collision fix via CCTiming/SPTiming rename (Task 6, Steps 1–3) ✓.
- **Placeholder scan:** no TBD/TODO, all steps have complete code.
- **Type consistency:** `_score_sp_timing_factors` signature matches between Task 1's definition and Task 2's call site. `compute_sp_timing_signal` / `_compute_sp_timing_fresh` names match between Task 2's definition and Task 3's router import. `spTimingSignalApi.get` matches between Task 4's definition and Task 5's call site. `spTimingSignals` state name matches between Task 5's declaration and Task 6's renderer usage. `'CCTiming'`/`'SPTiming'` string literals match between Task 6's `renderSignalBadge` type union, its two call sites, and `renderSignalDetailRow`'s key construction.
