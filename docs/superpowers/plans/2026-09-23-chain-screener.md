# Chain Screener Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `/chain` page that screens an options chain for tradeable strike/expiry candidates against a chosen strategy, starting with "Selling Short Puts" — scoring every strike near a target delta on 5 weighted criteria and always surfacing the top N per expiry, never going silently empty.

**Architecture:** New, entirely additive backend slice (`chain_screener.py` service + `chain.py` router) built on the existing `SchwabClient`, plus a new `ChainPage.tsx` frontend page that mirrors the existing `ScannerPage.tsx`'s deep-link (`useSearchParams`) and form patterns. No existing file's behavior changes except two mount points (`main.py`, `App.tsx`).

**Tech Stack:** FastAPI + Pydantic (backend), React + TypeScript + Tailwind (frontend), Schwab REST API via the existing `SchwabClient`, pytest for backend tests (no frontend test suite exists in this project — frontend verification is `tsc`/`eslint` + live manual browser checks).

**Spec:** `docs/superpowers/specs/2026-09-23-chain-screener-design.md`

## Global Constraints

- Reuse these existing functions exactly as they are today, unmodified: `SchwabClient.get_option_chain` (`backend/app/services/schwab_client.py`), `compute_sp_timing_signal` (`backend/app/services/sp_timing_signal.py`), `_fetch_earnings_dates` (`backend/app/services/options_scanner.py`).
- No new third-party dependencies — everything needed already exists in the project.
- Backend sync compute functions that call Schwab must run via `loop.run_in_executor(None, fn, ...)` inside the async route handler — this is the established pattern for every other Schwab-backed endpoint in `backend/app/routers/market.py`.
- Scoring curves must be piecewise/continuous, never a flat cliff at a threshold (matches `cc_timing_signal.py`/`sp_timing_signal.py`'s existing philosophy) — a candidate just below a minimum still gets partial credit.
- The 4 unimplemented strategies (`sell_call`, `buy_call_6_12m`, `buy_call_12_24m`, `sell_put_3_6m`) appear in the frontend dropdown as disabled options only — no backend logic for them in this plan.
- Frontend has no test framework configured — verification is `npx tsc --noEmit`, `npx eslint <file>`, and live manual browser checks against real tickers (NVDA, BE — same ones already spot-checked while designing this feature).

---

## Task 1: Friday expiry selection

**Files:**
- Create: `backend/app/services/chain_screener.py`
- Test: `backend/tests/test_chain_screener.py`

**Interfaces:**
- Produces: `_select_friday_expiries(exp_map: dict, num_expiries: int) -> list[dict]` — each returned dict is `{"exp_key": str, "expiration_date": str (ISO), "dte": int}`, sorted ascending by `dte`, filtered to Friday-only, limited to the first `num_expiries` matches.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_chain_screener.py`:

```python
import pytest
from datetime import date, timedelta


def test_select_friday_expiries_picks_only_fridays_in_order():
    from app.services.chain_screener import _select_friday_expiries
    exp_map = {
        "2026-09-25:2": {},   # Friday
        "2026-09-28:5": {},   # Monday
        "2026-10-02:9": {},   # Friday
        "2026-10-05:12": {},  # Monday
        "2026-10-09:16": {},  # Friday
        "2026-10-16:23": {},  # Friday
    }
    result = _select_friday_expiries(exp_map, num_expiries=3)
    assert [e["expiration_date"] for e in result] == ["2026-09-25", "2026-10-02", "2026-10-09"]
    assert [e["dte"] for e in result] == [2, 9, 16]
    assert result[0]["exp_key"] == "2026-09-25:2"


def test_select_friday_expiries_respects_limit():
    from app.services.chain_screener import _select_friday_expiries
    exp_map = {"2026-09-25:2": {}, "2026-10-02:9": {}, "2026-10-09:16": {}, "2026-10-16:23": {}}
    result = _select_friday_expiries(exp_map, num_expiries=2)
    assert len(result) == 2
    assert [e["expiration_date"] for e in result] == ["2026-09-25", "2026-10-02"]


def test_select_friday_expiries_empty_when_no_fridays():
    from app.services.chain_screener import _select_friday_expiries
    exp_map = {"2026-09-28:5": {}, "2026-10-05:12": {}}
    result = _select_friday_expiries(exp_map, num_expiries=3)
    assert result == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ./venv/bin/pytest tests/test_chain_screener.py -v`
Expected: FAIL — `ModuleNotFoundError` / `ImportError: cannot import name '_select_friday_expiries'` (the module doesn't exist yet).

- [ ] **Step 3: Write the implementation**

Create `backend/app/services/chain_screener.py`:

```python
# backend/app/services/chain_screener.py
from datetime import date


def _select_friday_expiries(exp_map: dict, num_expiries: int) -> list[dict]:
    """Pick the earliest `num_expiries` Friday expirations from a Schwab
    putExpDateMap/callExpDateMap, sorted ascending by days-to-expiration."""
    entries = []
    for exp_key in exp_map:
        exp_str, dte_str = exp_key.split(":")
        exp_date = date.fromisoformat(exp_str)
        if exp_date.weekday() != 4:  # Monday=0 ... Friday=4
            continue
        entries.append({"exp_key": exp_key, "expiration_date": exp_str, "dte": int(dte_str)})
    entries.sort(key=lambda e: e["dte"])
    return entries[:num_expiries]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ./venv/bin/pytest tests/test_chain_screener.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/chain_screener.py backend/tests/test_chain_screener.py
git commit -m "feat(chain): add Friday expiry selection for chain screener"
```

---

## Task 2: Per-candidate scoring

**Files:**
- Modify: `backend/app/services/chain_screener.py`
- Test: `backend/tests/test_chain_screener.py`

**Interfaces:**
- Consumes: none (pure functions)
- Produces:
  - `_score_delta_fit(delta: float, target_delta: float, tolerance: float) -> float`
  - `_score_arr(arr_pct: float, min_arr_pct: float) -> float`
  - `_score_volume(volume: int, min_volume: int) -> float`
  - `_score_oi(oi: int, min_oi: int) -> float`
  - `_score_spread(spread_pct: float) -> float`
  - `_score_candidate(contract: dict, strike: float, dte: int, spot: float, target_delta: float, delta_tolerance: float, min_arr_pct: float, min_volume: int, min_oi: int) -> dict` — returns `{strike, delta, last, bid, ask, spread_pct, volume, open_interest, arr_pct, breakeven, downside_cushion_pct, capital_required, score, factors}` where `factors` is `list[{name, points, max, detail}]` (same shape as the existing `CCSignalFactor` type used elsewhere in this app).

These numbers are checked against the real NVDA/BE data pulled live earlier while designing this feature — not arbitrary synthetic values.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_chain_screener.py`:

```python
def test_score_delta_fit_full_points_at_target():
    from app.services.chain_screener import _score_delta_fit
    assert _score_delta_fit(delta=-0.2, target_delta=0.2, tolerance=0.1) == 25.0


def test_score_delta_fit_zero_at_edge():
    from app.services.chain_screener import _score_delta_fit
    # dist = 0.15 == tolerance * 1.5 -> exactly 0
    assert _score_delta_fit(delta=-0.35, target_delta=0.2, tolerance=0.1) == 0.0


def test_score_delta_fit_partial_credit_matches_live_nvda_data():
    from app.services.chain_screener import _score_delta_fit
    # NVDA 10-02 $220 strike, delta -0.319, target 0.2, tolerance 0.1 (from live spike)
    points = _score_delta_fit(delta=-0.319, target_delta=0.2, tolerance=0.1)
    assert 5.0 <= points <= 5.5


def test_score_arr_no_cliff_below_minimum():
    from app.services.chain_screener import _score_arr
    # NVDA's real 10-02 $215 strike: ARR 22.6%, min 30% -> meaningful partial credit, not 0
    points = _score_arr(arr_pct=22.6, min_arr_pct=30.0)
    assert points == pytest.approx(18.83, abs=0.1)


def test_score_arr_full_points_at_minimum():
    from app.services.chain_screener import _score_arr
    assert _score_arr(arr_pct=30.0, min_arr_pct=30.0) == 25.0


def test_score_arr_capped_above_minimum():
    from app.services.chain_screener import _score_arr
    assert _score_arr(arr_pct=100.0, min_arr_pct=30.0) == 25.0


def test_score_volume_and_oi_scale_to_threshold():
    from app.services.chain_screener import _score_volume, _score_oi
    assert _score_volume(volume=100, min_volume=200) == 7.5
    assert _score_volume(volume=400, min_volume=200) == 15.0  # capped
    assert _score_oi(oi=250, min_oi=500) == 7.5
    assert _score_oi(oi=1000, min_oi=500) == 15.0  # capped


def test_score_spread_full_points_when_tight():
    from app.services.chain_screener import _score_spread
    # NVDA 10-02 $220 strike real spread: (2.32-2.30)/2.31 ~= 0.0087
    assert _score_spread(spread_pct=0.009) == 20.0


def test_score_spread_zero_when_very_wide():
    from app.services.chain_screener import _score_spread
    assert _score_spread(spread_pct=0.30) == 0.0


def test_score_candidate_combines_all_factors_matches_live_nvda_data():
    from app.services.chain_screener import _score_candidate
    contract = {"delta": -0.319, "last": 2.32, "bid": 2.30, "ask": 2.32, "totalVolume": 3751, "openInterest": 11689}
    candidate = _score_candidate(
        contract, strike=220.0, dte=9, spot=224.85,
        target_delta=0.2, delta_tolerance=0.1,
        min_arr_pct=30.0, min_volume=200, min_oi=500,
    )
    assert candidate["strike"] == 220.0
    assert candidate["arr_pct"] == pytest.approx(42.8, abs=0.2)  # matches live NVDA spike output exactly
    assert candidate["breakeven"] == pytest.approx(217.68, abs=0.01)
    assert len(candidate["factors"]) == 5
    assert candidate["score"] == pytest.approx(sum(f["points"] for f in candidate["factors"]))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ./venv/bin/pytest tests/test_chain_screener.py -v`
Expected: FAIL — `ImportError` for each new function name.

- [ ] **Step 3: Write the implementation**

Append to `backend/app/services/chain_screener.py`:

```python
def _score_delta_fit(delta: float, target_delta: float, tolerance: float) -> float:
    dist = abs(abs(delta) - target_delta)
    return round(max(0.0, 25 * (1 - dist / (tolerance * 1.5))), 1)


def _score_arr(arr_pct: float, min_arr_pct: float) -> float:
    if min_arr_pct <= 0:
        return 25.0
    return round(min(25.0, 25 * arr_pct / min_arr_pct), 1)


def _score_volume(volume: int, min_volume: int) -> float:
    if min_volume <= 0:
        return 15.0
    return round(min(15.0, 15 * volume / min_volume), 1)


def _score_oi(oi: int, min_oi: int) -> float:
    if min_oi <= 0:
        return 15.0
    return round(min(15.0, 15 * oi / min_oi), 1)


def _score_spread(spread_pct: float) -> float:
    if spread_pct <= 0.05:
        return 20.0
    return round(max(0.0, 20 * (1 - (spread_pct - 0.05) / 0.25)), 1)


def _score_candidate(
    contract: dict,
    strike: float,
    dte: int,
    spot: float,
    target_delta: float,
    delta_tolerance: float,
    min_arr_pct: float,
    min_volume: int,
    min_oi: int,
) -> dict:
    delta = float(contract.get("delta") or 0.0)
    last = float(contract.get("last") or 0.0)
    bid = float(contract.get("bid") or 0.0)
    ask = float(contract.get("ask") or 0.0)
    volume = int(contract.get("totalVolume") or 0)
    oi = int(contract.get("openInterest") or 0)
    mid = (bid + ask) / 2

    arr_pct = (last / strike) * (365 / dte) * 100 if dte > 0 and strike > 0 else 0.0
    spread_pct = (ask - bid) / mid if mid > 0 else 1.0
    breakeven = strike - last
    downside_cushion_pct = ((spot - breakeven) / spot) * 100 if spot else 0.0
    capital_required = strike * 100

    factors = [
        {"name": "Delta Fit", "points": _score_delta_fit(delta, target_delta, delta_tolerance), "max": 25,
         "detail": f"delta {delta:.3f} vs target {target_delta:.2f}"},
        {"name": "ARR", "points": _score_arr(arr_pct, min_arr_pct), "max": 25,
         "detail": f"{arr_pct:.1f}% (min {min_arr_pct:.0f}%)"},
        {"name": "Volume", "points": _score_volume(volume, min_volume), "max": 15,
         "detail": f"{volume} (min {min_volume})"},
        {"name": "Open Interest", "points": _score_oi(oi, min_oi), "max": 15,
         "detail": f"{oi} (min {min_oi})"},
        {"name": "Spread Tightness", "points": _score_spread(spread_pct), "max": 20,
         "detail": f"{spread_pct * 100:.1f}% of mid"},
    ]
    score = round(sum(f["points"] for f in factors), 1)

    return {
        "strike": strike, "delta": delta, "last": last, "bid": bid, "ask": ask,
        "spread_pct": round(spread_pct, 4), "volume": volume, "open_interest": oi,
        "arr_pct": round(arr_pct, 1), "breakeven": round(breakeven, 2),
        "downside_cushion_pct": round(downside_cushion_pct, 2),
        "capital_required": round(capital_required, 2),
        "score": score, "factors": factors,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ./venv/bin/pytest tests/test_chain_screener.py -v`
Expected: 12 passed (3 from Task 1 + 9 new)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/chain_screener.py backend/tests/test_chain_screener.py
git commit -m "feat(chain): add per-candidate scoring (delta fit, ARR, volume, OI, spread)"
```

---

## Task 3: Full screen compute pipeline

**Files:**
- Modify: `backend/app/services/chain_screener.py`
- Test: `backend/tests/test_chain_screener.py`

**Interfaces:**
- Consumes: `_select_friday_expiries` (Task 1), `_score_candidate` (Task 2), `SchwabClient.get_option_chain(ticker, contract_type, from_date, to_date) -> dict` (`backend/app/services/schwab_client.py`, exact signature confirmed — unchanged), `compute_sp_timing_signal(ticker: str, force: bool = False) -> dict` (`backend/app/services/sp_timing_signal.py`, returns `{ticker, score, grade, iv_percentile, atm_iv, spot_price, factors, commentary, strike_hint, caution, cached_at, fetch_status, fetch_error}`), `_fetch_earnings_dates(ticker: str) -> list[date]` (`backend/app/services/options_scanner.py`).
- Produces: `compute_chain_screen(ticker: str, strategy: str = "sell_put", num_expiries: int = 3, candidates_per_expiry: int = 3, target_delta: float = 0.2, delta_tolerance: float = 0.1, min_arr_pct: float = 30.0, min_volume: int = 200, min_oi: int = 500) -> dict` — raises `ValueError` for any `strategy` other than `"sell_put"`. Returns `{ticker, spot, strategy, sp_timing_signal, iv_percentile, fetched_at, expiries}` matching the spec's JSON shape.

Note: `compute_sp_timing_signal`'s result already includes both `spot_price` and `iv_percentile` (confirmed by reading its implementation) — this avoids a second Schwab call just for IV percentile, and doubles as the page-level SP Timing Signal context the spec calls for.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_chain_screener.py`:

```python
from datetime import timedelta
from unittest.mock import patch, MagicMock


def _next_fridays(n: int, start: date) -> list[date]:
    d = start
    fridays = []
    while len(fridays) < n:
        d += timedelta(days=1)
        if d.weekday() == 4:
            fridays.append(d)
    return fridays


def test_compute_chain_screen_full_pipeline():
    from app.services.chain_screener import compute_chain_screen

    today = date.today()
    fridays = _next_fridays(3, today)
    exp_map = {}
    for f in fridays:
        dte = (f - today).days
        exp_map[f"{f.isoformat()}:{dte}"] = {
            "220.0": [{"delta": -0.20, "last": 2.5, "bid": 2.45, "ask": 2.50,
                       "totalVolume": 1000, "openInterest": 2000}],
        }

    mock_client = MagicMock()
    mock_client.get_option_chain.return_value = {"underlyingPrice": 225.0, "putExpDateMap": exp_map}

    mock_timing = {
        "ticker": "NVDA", "score": 62, "grade": "moderate", "iv_percentile": 41.2, "atm_iv": 0.35,
        "spot_price": 225.0, "factors": [], "commentary": None, "strike_hint": None, "caution": None,
        "cached_at": "2026-09-23T14:00:00+00:00", "fetch_status": "ok", "fetch_error": None,
    }

    with patch("app.services.chain_screener.get_schwab_client", return_value=mock_client), \
         patch("app.services.chain_screener.compute_sp_timing_signal", return_value=mock_timing), \
         patch("app.services.chain_screener._fetch_earnings_dates", return_value=[]):
        result = compute_chain_screen("NVDA", strategy="sell_put", num_expiries=3, candidates_per_expiry=3)

    assert result["ticker"] == "NVDA"
    assert result["spot"] == 225.0
    assert result["sp_timing_signal"]["score"] == 62
    assert result["iv_percentile"] == 41.2
    assert len(result["expiries"]) == 3
    for expiry in result["expiries"]:
        assert len(expiry["candidates"]) == 1
        assert expiry["candidates"][0]["strike"] == 220.0
        assert expiry["candidates"][0]["score"] > 0


def test_compute_chain_screen_rejects_unsupported_strategy():
    from app.services.chain_screener import compute_chain_screen
    with pytest.raises(ValueError, match="not yet implemented"):
        compute_chain_screen("NVDA", strategy="sell_call")


def test_compute_chain_screen_flags_earnings_in_window():
    from app.services.chain_screener import compute_chain_screen

    today = date.today()
    friday = _next_fridays(1, today)[0]
    dte = (friday - today).days
    exp_map = {
        f"{friday.isoformat()}:{dte}": {
            "220.0": [{"delta": -0.20, "last": 2.5, "bid": 2.45, "ask": 2.50,
                       "totalVolume": 1000, "openInterest": 2000}],
        },
    }
    mock_client = MagicMock()
    mock_client.get_option_chain.return_value = {"underlyingPrice": 225.0, "putExpDateMap": exp_map}
    mock_timing = {
        "ticker": "NVDA", "score": 62, "grade": "moderate", "iv_percentile": 41.2, "atm_iv": 0.35,
        "spot_price": 225.0, "factors": [], "commentary": None, "strike_hint": None, "caution": None,
        "cached_at": "2026-09-23T14:00:00+00:00", "fetch_status": "ok", "fetch_error": None,
    }
    earnings_date = today + timedelta(days=3)
    with patch("app.services.chain_screener.get_schwab_client", return_value=mock_client), \
         patch("app.services.chain_screener.compute_sp_timing_signal", return_value=mock_timing), \
         patch("app.services.chain_screener._fetch_earnings_dates", return_value=[earnings_date]):
        result = compute_chain_screen("NVDA", strategy="sell_put", num_expiries=1)

    assert result["expiries"][0]["earnings_in_window"] is True
    assert result["expiries"][0]["earnings_date"] == earnings_date.isoformat()


def test_compute_chain_screen_empty_band_reports_no_candidates():
    from app.services.chain_screener import compute_chain_screen

    today = date.today()
    friday = _next_fridays(1, today)[0]
    dte = (friday - today).days
    exp_map = {
        f"{friday.isoformat()}:{dte}": {
            # delta way outside the target 0.2 +/- 0.15 band
            "300.0": [{"delta": -0.90, "last": 2.5, "bid": 2.45, "ask": 2.50,
                       "totalVolume": 1000, "openInterest": 2000}],
        },
    }
    mock_client = MagicMock()
    mock_client.get_option_chain.return_value = {"underlyingPrice": 225.0, "putExpDateMap": exp_map}
    mock_timing = {
        "ticker": "NVDA", "score": 62, "grade": "moderate", "iv_percentile": 41.2, "atm_iv": 0.35,
        "spot_price": 225.0, "factors": [], "commentary": None, "strike_hint": None, "caution": None,
        "cached_at": "2026-09-23T14:00:00+00:00", "fetch_status": "ok", "fetch_error": None,
    }
    with patch("app.services.chain_screener.get_schwab_client", return_value=mock_client), \
         patch("app.services.chain_screener.compute_sp_timing_signal", return_value=mock_timing), \
         patch("app.services.chain_screener._fetch_earnings_dates", return_value=[]):
        result = compute_chain_screen("NVDA", strategy="sell_put", num_expiries=1)

    assert result["expiries"][0]["candidates"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ./venv/bin/pytest tests/test_chain_screener.py -v`
Expected: FAIL — `ImportError: cannot import name 'compute_chain_screen'`

- [ ] **Step 3: Write the implementation**

Append to `backend/app/services/chain_screener.py` (and add the new imports at the top of the file):

```python
# add near the top of backend/app/services/chain_screener.py, alongside the existing `from datetime import date`
from datetime import date, datetime, timedelta, timezone

from app.services.schwab_client import get_schwab_client
from app.services.sp_timing_signal import compute_sp_timing_signal
from app.services.options_scanner import _fetch_earnings_dates

STRATEGY_CONTRACT_TYPE = {"sell_put": "PUT"}
```

```python
def compute_chain_screen(
    ticker: str,
    strategy: str = "sell_put",
    num_expiries: int = 3,
    candidates_per_expiry: int = 3,
    target_delta: float = 0.2,
    delta_tolerance: float = 0.1,
    min_arr_pct: float = 30.0,
    min_volume: int = 200,
    min_oi: int = 500,
) -> dict:
    if strategy not in STRATEGY_CONTRACT_TYPE:
        raise ValueError(f"Strategy '{strategy}' not yet implemented")

    ticker = ticker.upper()
    contract_type = STRATEGY_CONTRACT_TYPE[strategy]

    timing = compute_sp_timing_signal(ticker)
    spot = timing.get("spot_price")
    iv_percentile = timing.get("iv_percentile")

    client = get_schwab_client()
    to_date = (date.today() + timedelta(days=num_expiries * 7 + 10)).isoformat()
    chain = client.get_option_chain(
        ticker, contract_type=contract_type,
        from_date=date.today().isoformat(), to_date=to_date,
    )
    if spot is None:
        spot = chain.get("underlyingPrice")

    exp_map_key = "putExpDateMap" if contract_type == "PUT" else "callExpDateMap"
    exp_map = chain.get(exp_map_key, {})
    selected_expiries = _select_friday_expiries(exp_map, num_expiries)

    earnings_dates = _fetch_earnings_dates(ticker)
    today = date.today()

    band_lo = target_delta - delta_tolerance * 1.5
    band_hi = target_delta + delta_tolerance * 1.5

    expiries_out = []
    for entry in selected_expiries:
        exp_date = date.fromisoformat(entry["expiration_date"])
        window_earnings = [ed for ed in earnings_dates if today <= ed <= exp_date]
        earnings_in_window = len(window_earnings) > 0
        earnings_date = window_earnings[0].isoformat() if window_earnings else None

        strikes = exp_map.get(entry["exp_key"], {})
        scored = []
        for strike_str, contracts in strikes.items():
            contract = contracts[0]
            delta = contract.get("delta")
            if delta is None:
                continue
            if not (band_lo <= abs(float(delta)) <= band_hi):
                continue
            scored.append(_score_candidate(
                contract, float(strike_str), entry["dte"], spot,
                target_delta, delta_tolerance, min_arr_pct, min_volume, min_oi,
            ))
        scored.sort(key=lambda c: c["score"], reverse=True)

        expiries_out.append({
            "expiration_date": entry["expiration_date"],
            "dte": entry["dte"],
            "day_of_week": "Friday",
            "earnings_in_window": earnings_in_window,
            "earnings_date": earnings_date,
            "candidates": scored[:candidates_per_expiry],
        })

    return {
        "ticker": ticker,
        "spot": spot,
        "strategy": strategy,
        "sp_timing_signal": timing if timing.get("fetch_status") == "ok" else None,
        "iv_percentile": iv_percentile,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "expiries": expiries_out,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ./venv/bin/pytest tests/test_chain_screener.py -v`
Expected: 16 passed (12 from Tasks 1-2 + 4 new)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/chain_screener.py backend/tests/test_chain_screener.py
git commit -m "feat(chain): add compute_chain_screen full pipeline (expiries, earnings, scoring)"
```

---

## Task 4: API endpoint

**Files:**
- Create: `backend/app/schemas/chain.py`
- Create: `backend/app/routers/chain.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_chain_screener.py`

**Interfaces:**
- Consumes: `compute_chain_screen` (Task 3)
- Produces: `GET /api/chain/{ticker}` — query params `strategy` (required, default `sell_put`), `num_expiries`, `candidates_per_expiry`, `target_delta`, `delta_tolerance`, `min_arr_pct`, `min_volume`, `min_oi` (all optional, defaults matching Task 3). Returns 400 for any unsupported `strategy`, 502 if the underlying compute raises.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_chain_screener.py`:

```python
async def test_get_chain_screen_returns_result(client):
    mock_result = {
        "ticker": "NVDA", "spot": 224.85, "strategy": "sell_put",
        "sp_timing_signal": None, "iv_percentile": None,
        "fetched_at": "2026-09-23T14:00:00+00:00", "expiries": [],
    }
    with patch("app.routers.chain.compute_chain_screen", return_value=mock_result):
        response = await client.get("/api/chain/NVDA?strategy=sell_put")
    assert response.status_code == 200
    assert response.json()["ticker"] == "NVDA"


async def test_get_chain_screen_rejects_unsupported_strategy(client):
    response = await client.get("/api/chain/NVDA?strategy=sell_call")
    assert response.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ./venv/bin/pytest tests/test_chain_screener.py -v`
Expected: FAIL — connection/route errors (`/api/chain/NVDA` doesn't exist: 404, not 200/400)

- [ ] **Step 3: Write the implementation**

Create `backend/app/schemas/chain.py`:

```python
# backend/app/schemas/chain.py
from typing import Optional
from pydantic import BaseModel


class ChainFactor(BaseModel):
    name: str
    points: float
    max: float
    detail: str


class ChainCandidate(BaseModel):
    strike: float
    delta: float
    last: float
    bid: float
    ask: float
    spread_pct: float
    volume: int
    open_interest: int
    arr_pct: float
    breakeven: float
    downside_cushion_pct: float
    capital_required: float
    score: float
    factors: list[ChainFactor]


class ChainExpiry(BaseModel):
    expiration_date: str
    dte: int
    day_of_week: str
    earnings_in_window: bool
    earnings_date: Optional[str] = None
    candidates: list[ChainCandidate]


class SpTimingSignalSummary(BaseModel):
    ticker: str
    score: float
    grade: str
    iv_percentile: Optional[float] = None
    atm_iv: Optional[float] = None
    spot_price: Optional[float] = None
    factors: list[dict] = []
    commentary: Optional[str] = None
    strike_hint: Optional[str] = None
    caution: Optional[str] = None
    cached_at: str
    fetch_status: str
    fetch_error: Optional[str] = None


class ChainScreenResponse(BaseModel):
    ticker: str
    spot: Optional[float] = None
    strategy: str
    sp_timing_signal: Optional[SpTimingSignalSummary] = None
    iv_percentile: Optional[float] = None
    fetched_at: str
    expiries: list[ChainExpiry]
```

Create `backend/app/routers/chain.py`:

```python
# backend/app/routers/chain.py
import asyncio
from fastapi import APIRouter, HTTPException, Query
from app.services.chain_screener import compute_chain_screen
from app.schemas.chain import ChainScreenResponse

router = APIRouter(prefix="/api/chain", tags=["chain"])

SUPPORTED_STRATEGIES = {"sell_put"}


@router.get("/{ticker}", response_model=ChainScreenResponse)
async def get_chain_screen(
    ticker: str,
    strategy: str = Query("sell_put"),
    num_expiries: int = Query(3, ge=1, le=8),
    candidates_per_expiry: int = Query(3, ge=1, le=10),
    target_delta: float = Query(0.2, gt=0, lt=1),
    delta_tolerance: float = Query(0.1, gt=0, lt=1),
    min_arr_pct: float = Query(30.0, ge=0),
    min_volume: int = Query(200, ge=0),
    min_oi: int = Query(500, ge=0),
):
    if strategy not in SUPPORTED_STRATEGIES:
        raise HTTPException(status_code=400, detail=f"Strategy '{strategy}' not yet implemented")
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: compute_chain_screen(
                ticker, strategy, num_expiries, candidates_per_expiry,
                target_delta, delta_tolerance, min_arr_pct, min_volume, min_oi,
            ),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to screen chain: {exc}")
    return result
```

Modify `backend/app/main.py` — add `chain` to the router import and mount it:

```python
# change this line:
from app.routers import trades, commentary, alerts, market, briefing, categories, positions, signals, sessions, wheel, screener
# to:
from app.routers import trades, commentary, alerts, market, briefing, categories, positions, signals, sessions, wheel, screener, chain
```

```python
# add alongside the other app.include_router(...) calls:
app.include_router(chain.router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ./venv/bin/pytest tests/test_chain_screener.py -v`
Expected: 18 passed (16 from Tasks 1-3 + 2 new)

- [ ] **Step 5: Run the full backend suite to confirm nothing else broke**

Run: `cd backend && ./venv/bin/pytest tests/ -q`
Expected: same pre-existing 6 unrelated failures as always (`test_cc_signal.py` x4, `test_market_router_p2.py::test_prefetch_still_501`, `test_schwab_client.py::test_schwab_alias_maps_spx`), all Chain tests passing, no new failures.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/chain.py backend/app/routers/chain.py backend/app/main.py backend/tests/test_chain_screener.py
git commit -m "feat(chain): add GET /api/chain/{ticker} endpoint"
```

---

## Task 5: Frontend API client

**Files:**
- Create: `frontend/src/api/chain.ts`

**Interfaces:**
- Consumes: `apiFetch<T>(path, options?) -> Promise<T>` (`frontend/src/api/client.ts`, existing, unchanged)
- Produces: `screenChain(ticker: string, params: ChainScreenParams) -> Promise<ChainScreenResult>`, plus exported types `ChainFactor`, `ChainCandidate`, `ChainExpiry`, `SpTimingSignalSummary`, `ChainScreenResult`, `ChainScreenParams`.

- [ ] **Step 1: Write the implementation**

Create `frontend/src/api/chain.ts`:

```typescript
// frontend/src/api/chain.ts
import { apiFetch } from './client'

export interface ChainFactor {
  name: string
  points: number
  max: number
  detail: string
}

export interface ChainCandidate {
  strike: number
  delta: number
  last: number
  bid: number
  ask: number
  spread_pct: number
  volume: number
  open_interest: number
  arr_pct: number
  breakeven: number
  downside_cushion_pct: number
  capital_required: number
  score: number
  factors: ChainFactor[]
}

export interface ChainExpiry {
  expiration_date: string
  dte: number
  day_of_week: string
  earnings_in_window: boolean
  earnings_date: string | null
  candidates: ChainCandidate[]
}

export interface SpTimingSignalSummary {
  ticker: string
  score: number
  grade: string
  iv_percentile: number | null
  atm_iv: number | null
  spot_price: number | null
  factors: ChainFactor[]
  commentary: string | null
  strike_hint: string | null
  caution: string | null
  cached_at: string
  fetch_status: string
  fetch_error: string | null
}

export interface ChainScreenResult {
  ticker: string
  spot: number | null
  strategy: string
  sp_timing_signal: SpTimingSignalSummary | null
  iv_percentile: number | null
  fetched_at: string
  expiries: ChainExpiry[]
}

export interface ChainScreenParams {
  strategy: string
  num_expiries?: number
  candidates_per_expiry?: number
  target_delta?: number
  delta_tolerance?: number
  min_arr_pct?: number
  min_volume?: number
  min_oi?: number
}

export async function screenChain(ticker: string, params: ChainScreenParams): Promise<ChainScreenResult> {
  const query = new URLSearchParams()
  query.set('strategy', params.strategy)
  if (params.num_expiries != null) query.set('num_expiries', String(params.num_expiries))
  if (params.candidates_per_expiry != null) query.set('candidates_per_expiry', String(params.candidates_per_expiry))
  if (params.target_delta != null) query.set('target_delta', String(params.target_delta))
  if (params.delta_tolerance != null) query.set('delta_tolerance', String(params.delta_tolerance))
  if (params.min_arr_pct != null) query.set('min_arr_pct', String(params.min_arr_pct))
  if (params.min_volume != null) query.set('min_volume', String(params.min_volume))
  if (params.min_oi != null) query.set('min_oi', String(params.min_oi))
  return apiFetch<ChainScreenResult>(`/chain/${encodeURIComponent(ticker)}?${query.toString()}`)
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npx tsc --noEmit -p .`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/chain.ts
git commit -m "feat(chain): add frontend api client for chain screener"
```

---

## Task 6: Chain page shell — form, deep-link, nav/route wiring

**Files:**
- Create: `frontend/src/pages/ChainPage.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `screenChain`, `ChainScreenParams`, `ChainScreenResult` (Task 5); `ApiError` (`frontend/src/api/client.ts`, existing)
- Produces: page reachable at `/chain`, deep-linkable via `?symbol=&strategy=`. Results render as raw JSON in this task (Task 7 replaces that with the styled per-expiry layout) — this task's deliverable is: form works, deep-link auto-runs, a real network call fires and result data reaches the page.

- [ ] **Step 1: Write the implementation**

Create `frontend/src/pages/ChainPage.tsx`:

```tsx
// frontend/src/pages/ChainPage.tsx
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { screenChain } from '../api/chain'
import type { ChainScreenResult } from '../api/chain'

const STRATEGIES = [
  { value: 'sell_put', label: 'Selling Short Puts' },
  { value: 'sell_call', label: 'Selling Short Calls (coming soon)' },
  { value: 'buy_call_6_12m', label: 'Buying 6-12mo Calls (coming soon)' },
  { value: 'buy_call_12_24m', label: 'Buying 12-24mo Calls (coming soon)' },
  { value: 'sell_put_3_6m', label: 'Selling 3-6mo Puts (coming soon)' },
]

interface FormState {
  ticker: string
  strategy: string
  numExpiries: number
  candidatesPerExpiry: number
  targetDelta: number
  deltaTolerance: number
  minArrPct: number
  minVolume: number
  minOi: number
  showAdvanced: boolean
}

type ScreenState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'success'; result: ChainScreenResult }
  | { status: 'error'; message: string }

export function ChainPage() {
  const [searchParams] = useSearchParams()
  const [form, setForm] = useState<FormState>({
    ticker: searchParams.get('symbol')?.toUpperCase() ?? '',
    strategy: searchParams.get('strategy') ?? 'sell_put',
    numExpiries: 3,
    candidatesPerExpiry: 3,
    targetDelta: 0.2,
    deltaTolerance: 0.1,
    minArrPct: 30,
    minVolume: 200,
    minOi: 500,
    showAdvanced: false,
  })
  const [screenState, setScreenState] = useState<ScreenState>({ status: 'idle' })

  const runScreen = async (overrideTicker?: string) => {
    const ticker = (overrideTicker ?? form.ticker).trim().toUpperCase()
    if (!ticker) return
    setScreenState({ status: 'loading' })
    try {
      const result = await screenChain(ticker, {
        strategy: form.strategy,
        num_expiries: form.numExpiries,
        candidates_per_expiry: form.candidatesPerExpiry,
        target_delta: form.targetDelta,
        delta_tolerance: form.deltaTolerance,
        min_arr_pct: form.minArrPct,
        min_volume: form.minVolume,
        min_oi: form.minOi,
      })
      setScreenState({ status: 'success', result })
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Screen failed. Try again.'
      setScreenState({ status: 'error', message })
    }
  }

  useEffect(() => {
    const symbol = searchParams.get('symbol')
    if (symbol) runScreen(symbol.toUpperCase())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Chain Screener</h1>

      <div className="bg-white border border-gray-200 rounded-lg p-4 mb-6">
        <div className="flex gap-4 items-end flex-wrap">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Symbol</label>
            <input
              value={form.ticker}
              onChange={e => setForm(f => ({ ...f, ticker: e.target.value.toUpperCase() }))}
              onKeyDown={e => { if (e.key === 'Enter') runScreen() }}
              className="border border-gray-300 rounded px-3 py-2 text-sm w-32"
              placeholder="NVDA"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Strategy</label>
            <select
              value={form.strategy}
              onChange={e => setForm(f => ({ ...f, strategy: e.target.value }))}
              className="border border-gray-300 rounded px-3 py-2 text-sm"
            >
              {STRATEGIES.map(s => (
                <option key={s.value} value={s.value} disabled={s.value !== 'sell_put'}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
          <button
            onClick={() => runScreen()}
            disabled={screenState.status === 'loading'}
            className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50"
          >
            {screenState.status === 'loading' ? 'Screening…' : 'Screen'}
          </button>
        </div>

        <button
          type="button"
          onClick={() => setForm(f => ({ ...f, showAdvanced: !f.showAdvanced }))}
          className="text-xs text-indigo-600 hover:underline mt-3"
        >
          {form.showAdvanced ? '▲ Hide Advanced' : '▼ Advanced Filters'}
        </button>
        {form.showAdvanced && (
          <div className="grid grid-cols-4 gap-3 mt-3">
            <div>
              <label className="block text-xs text-gray-500 mb-1"># Fridays</label>
              <input type="number" min={1} max={8} value={form.numExpiries}
                onChange={e => setForm(f => ({ ...f, numExpiries: Number(e.target.value) }))}
                className="border border-gray-300 rounded px-2 py-1 text-sm w-full" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Candidates/Expiry</label>
              <input type="number" min={1} max={10} value={form.candidatesPerExpiry}
                onChange={e => setForm(f => ({ ...f, candidatesPerExpiry: Number(e.target.value) }))}
                className="border border-gray-300 rounded px-2 py-1 text-sm w-full" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Target Delta</label>
              <input type="number" step={0.01} min={0} max={1} value={form.targetDelta}
                onChange={e => setForm(f => ({ ...f, targetDelta: Number(e.target.value) }))}
                className="border border-gray-300 rounded px-2 py-1 text-sm w-full" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Delta Tolerance</label>
              <input type="number" step={0.01} min={0} max={1} value={form.deltaTolerance}
                onChange={e => setForm(f => ({ ...f, deltaTolerance: Number(e.target.value) }))}
                className="border border-gray-300 rounded px-2 py-1 text-sm w-full" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Min ARR%</label>
              <input type="number" min={0} value={form.minArrPct}
                onChange={e => setForm(f => ({ ...f, minArrPct: Number(e.target.value) }))}
                className="border border-gray-300 rounded px-2 py-1 text-sm w-full" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Min Volume</label>
              <input type="number" min={0} value={form.minVolume}
                onChange={e => setForm(f => ({ ...f, minVolume: Number(e.target.value) }))}
                className="border border-gray-300 rounded px-2 py-1 text-sm w-full" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Min OI</label>
              <input type="number" min={0} value={form.minOi}
                onChange={e => setForm(f => ({ ...f, minOi: Number(e.target.value) }))}
                className="border border-gray-300 rounded px-2 py-1 text-sm w-full" />
            </div>
          </div>
        )}
      </div>

      {screenState.status === 'error' && (
        <p className="text-red-600 text-sm mb-4">{screenState.message}</p>
      )}
      {screenState.status === 'success' && (
        <pre className="text-xs bg-gray-50 border border-gray-200 rounded p-4 overflow-x-auto">
          {JSON.stringify(screenState.result, null, 2)}
        </pre>
      )}
    </div>
  )
}
```

Modify `frontend/src/App.tsx`:

```tsx
// add this import alongside the other page imports:
import { ChainPage } from './pages/ChainPage'
```

```tsx
// add this nav item, after the Screener NavItem:
<NavItem to="/chain" label="Chain" />
```

```tsx
// add this route, after the /screener route:
<Route path="/chain" element={<ChainPage />} />
```

- [ ] **Step 2: Typecheck and lint**

Run: `cd frontend && npx tsc --noEmit -p . && npx eslint src/pages/ChainPage.tsx src/App.tsx`
Expected: no errors (the two pre-existing unrelated lint issues in other files, if surfaced by a broader lint run, are not from these files)

- [ ] **Step 3: Verify live in a browser**

Start the backend (`cd backend && ./venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 5431`) and frontend (`cd frontend && npm run dev`) if not already running. Navigate to `http://localhost:<port>/chain`, enter `NVDA`, click Screen, confirm a raw JSON blob renders with `ticker`, `spot`, `sp_timing_signal`, `expiries` fields populated. Then navigate to `http://localhost:<port>/chain?symbol=NVDA&strategy=sell_put` directly and confirm it auto-runs without clicking Screen.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/ChainPage.tsx frontend/src/App.tsx
git commit -m "feat(chain): add Chain page shell with form, deep-link, and nav/route"
```

---

## Task 7: Chain page results rendering

**Files:**
- Modify: `frontend/src/pages/ChainPage.tsx`

**Interfaces:**
- Consumes: `ChainCandidate`, `ChainExpiry`, `ChainScreenResult` (Task 5)
- Produces: replaces the raw `<pre>` JSON dump from Task 6 with the full visual layout from the spec — page-level signal strip, one box per expiry with earnings badge, candidate cards with per-factor pass/fail pills and a highlighted top candidate.

- [ ] **Step 1: Write the implementation**

In `frontend/src/pages/ChainPage.tsx`, first change the top-of-file import line (added in Task 6) from:

```tsx
import type { ChainScreenResult } from '../api/chain'
```

to:

```tsx
import type { ChainScreenResult, ChainCandidate, ChainExpiry } from '../api/chain'
```

Then add these three functions above the `ChainPage` component (after the `STRATEGIES` constant):

```tsx
function factorPillClass(points: number, max: number): string {
  const pct = max > 0 ? points / max : 0
  if (pct >= 0.7) return 'bg-green-100 text-green-700'
  if (pct >= 0.4) return 'bg-amber-100 text-amber-700'
  return 'bg-red-100 text-red-700'
}

function CandidateCard({ candidate, isBest }: { candidate: ChainCandidate; isBest: boolean }) {
  return (
    <div className={`border rounded-lg p-3 ${isBest ? 'border-blue-400 bg-blue-50' : 'border-gray-200 bg-white'}`}>
      <div className="flex items-center justify-between">
        <span className="font-bold text-gray-900">${candidate.strike.toFixed(2)}</span>
        <span className="text-xs text-gray-400">Score {candidate.score.toFixed(1)}</span>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 mt-2 text-xs">
        <div><span className="text-gray-400">Delta: </span><span className="text-gray-700">{candidate.delta.toFixed(3)}</span></div>
        <div><span className="text-gray-400">ARR: </span><span className="text-gray-700">{candidate.arr_pct.toFixed(1)}%</span></div>
        <div><span className="text-gray-400">Bid/Ask: </span><span className="text-gray-700">${candidate.bid.toFixed(2)}/${candidate.ask.toFixed(2)} ({(candidate.spread_pct * 100).toFixed(1)}%)</span></div>
        <div><span className="text-gray-400">Last: </span><span className="text-gray-700">${candidate.last.toFixed(2)}</span></div>
        <div><span className="text-gray-400">Volume: </span><span className="text-gray-700">{candidate.volume}</span></div>
        <div><span className="text-gray-400">OI: </span><span className="text-gray-700">{candidate.open_interest}</span></div>
        <div><span className="text-gray-400">Breakeven: </span><span className="text-gray-700">${candidate.breakeven.toFixed(2)}</span></div>
        <div><span className="text-gray-400">Cushion: </span><span className="text-gray-700">{candidate.downside_cushion_pct.toFixed(1)}%</span></div>
        <div className="col-span-2"><span className="text-gray-400">Capital: </span><span className="text-gray-700">${candidate.capital_required.toLocaleString()}</span></div>
      </div>
      <div className="flex flex-wrap gap-1 mt-2">
        {candidate.factors.map(f => (
          <span key={f.name} title={f.detail} className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${factorPillClass(f.points, f.max)}`}>
            {f.name} {f.points}/{f.max}
          </span>
        ))}
      </div>
    </div>
  )
}

function ExpiryBox({ expiry }: { expiry: ChainExpiry }) {
  return (
    <section className="mb-5">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-sm font-bold text-gray-700">{expiry.expiration_date} ({expiry.day_of_week}, {expiry.dte}d)</span>
        {expiry.earnings_in_window && (
          <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-red-100 text-red-800 border border-red-300">
            Earnings {expiry.earnings_date}
          </span>
        )}
      </div>
      {expiry.candidates.length === 0 ? (
        <p className="text-sm text-gray-400 italic">No strikes in target delta band for this expiry.</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {expiry.candidates.map((c, i) => (
            <CandidateCard key={c.strike} candidate={c} isBest={i === 0} />
          ))}
        </div>
      )}
    </section>
  )
}
```

Add this function alongside the ones above (it needs `ChainScreenResult`, already imported at the top of the file):

```tsx
function SignalStrip({ result }: { result: ChainScreenResult }) {
  const timing = result.sp_timing_signal
  return (
    <div className="flex items-center gap-4 mb-6 text-sm">
      <span className="text-gray-700">Spot: <span className="font-bold">${result.spot?.toFixed(2) ?? '—'}</span></span>
      {timing && (
        <span className="text-gray-700">
          SP Timing: <span className="font-medium px-2 py-0.5 rounded-full bg-amber-100 text-amber-800">{timing.grade} {timing.score}</span>
        </span>
      )}
      <span className="text-gray-700">IV Percentile: <span className="font-bold">{result.iv_percentile != null ? `${result.iv_percentile}%` : '—'}</span></span>
    </div>
  )
}
```

Replace the Task 6 placeholder block:

```tsx
{screenState.status === 'success' && (
  <pre className="text-xs bg-gray-50 border border-gray-200 rounded p-4 overflow-x-auto">
    {JSON.stringify(screenState.result, null, 2)}
  </pre>
)}
```

with:

```tsx
{screenState.status === 'success' && (
  <>
    <SignalStrip result={screenState.result} />
    {screenState.result.expiries.map(e => <ExpiryBox key={e.expiration_date} expiry={e} />)}
  </>
)}
```

- [ ] **Step 2: Typecheck and lint**

Run: `cd frontend && npx tsc --noEmit -p . && npx eslint src/pages/ChainPage.tsx`
Expected: no errors

- [ ] **Step 3: Verify live in a browser against real data**

With backend and frontend running, navigate to `/chain?symbol=NVDA&strategy=sell_put`. Confirm:
- The signal strip shows a spot price, SP Timing grade/score, and IV Percentile.
- Three expiry boxes render (this Friday, next Friday, following Friday from today), each with up to 3 candidate cards.
- Each candidate card shows 5 factor pills; hovering one shows its `detail` tooltip.
- The 10-02 (or equivalent 9-DTE) expiry's $220-strike-equivalent candidate is present and its ARR roughly matches the 42.8% figure found in this session's earlier live NVDA spike.

Then navigate to `/chain?symbol=BE&strategy=sell_put` and confirm the $250 strike (or nearest match) at the 9-DTE expiry shows a high score (delta ~0.22, ARR ~73%, strong volume/OI) consistent with this session's earlier live BE spike.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/ChainPage.tsx
git commit -m "feat(chain): render per-expiry candidate cards with factor highlight pills"
```

---

## Self-Review Notes

- **Spec coverage:** every in-scope spec item maps to a task — Friday expiry selection (Task 1), 5-criteria scoring with continuous curves (Task 2), full pipeline incl. SP Timing Signal reuse + IV Percentile + earnings awareness (Task 3), API shape incl. 400 for unsupported strategies (Task 4), typed frontend client (Task 5), deep-link + adjustable thresholds + nav (Task 6), visual highlighting (Task 7).
- **No placeholders:** every step has real, complete code; the one intentionally interim state (Task 6's raw JSON output) is explicitly called out as interim and is itself fully functional, not a stub.
- **Type consistency:** `ChainCandidate`/`ChainExpiry`/`ChainScreenResult` (frontend, Task 5) match `ChainCandidate`/`ChainExpiry`/`ChainScreenResponse` (backend, Task 4) field-for-field; `_score_candidate`'s returned dict keys (Task 2) match the Pydantic `ChainCandidate` schema fields (Task 4) exactly; `compute_chain_screen`'s returned dict keys (Task 3) match `ChainScreenResponse` exactly.
