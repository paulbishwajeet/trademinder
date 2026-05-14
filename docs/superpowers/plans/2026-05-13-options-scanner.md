# Options Scanner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate stockpile-main's IV-surface options scanner into TradeMinder as a backend API endpoint + React scanner page with trade linking.

**Architecture:** A new `options_scanner.py` service consolidates three stockpile-main modules (chain fetching, IV surface fitting, earnings annotation) into one public `run_scan()` function. The existing `GET /api/market/options/{ticker}` route (currently 501) is wired to call it via `run_in_executor`. The React frontend gains a `/scanner` page and "Scan →" shortcuts on open stock positions.

**Tech Stack:** Python 3.11+, FastAPI, yfinance, numpy, pandas (backend); React 18, TypeScript, Tailwind CSS, React Router (frontend).

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `backend/app/services/options_scanner.py` | Chain fetch, IV surface, earnings, `run_scan()` |
| Create | `backend/tests/test_options_scanner.py` | Unit tests for pure-math helpers + `run_scan` |
| Modify | `backend/app/routers/market.py` | Implement `GET /api/market/options/{ticker}` |
| Modify | `backend/tests/test_market_router_p2.py` | Replace 501 test with real endpoint tests |
| Modify | `backend/pyproject.toml` | Add `numpy` and `pandas` dependencies |
| Modify | `frontend/src/api/client.ts` | Fix `erasableSyntaxOnly` TS6 bug |
| Create | `frontend/src/api/scanner.ts` | `scanOptions()` API function + types |
| Create | `frontend/src/pages/ScannerPage.tsx` | Full scanner UI |
| Modify | `frontend/src/App.tsx` | Add `/scanner` route + nav link |
| Modify | `frontend/src/components/Trades/TradeTable.tsx` | "Scan →" link on open stock rows |
| Modify | `frontend/src/pages/TradeDetailPage.tsx` | "Scan Options" button on open stock trades |

---

## Task 1: Add numpy and pandas to backend dependencies

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Edit pyproject.toml**

In `backend/pyproject.toml`, add `numpy` and `pandas` to the `dependencies` list:

```toml
dependencies = [
    "fastapi>=0.111.0",
    "uvicorn[standard]>=0.29.0",
    "sqlalchemy[asyncio]>=2.0.30",
    "asyncpg>=0.29.0",
    "alembic>=1.13.0",
    "pydantic>=2.7.0",
    "pydantic-settings>=2.2.0",
    "yfinance>=0.2.40",
    "anthropic>=0.26.0",
    "apscheduler>=3.10.4,<4.0",
    "numpy>=1.26.0",
    "pandas>=2.0.0",
]
```

- [ ] **Step 2: Install in the backend venv**

```bash
cd backend && pip install numpy pandas
```

Expected: `Successfully installed` (or `already satisfied` — yfinance pulls them transitively).

- [ ] **Step 3: Verify imports work**

```bash
cd backend && python -c "import numpy; import pandas; print('ok')"
```

Expected output: `ok`

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml
git commit -m "feat: add numpy and pandas to backend deps for options scanner"
```

---

## Task 2: Create options_scanner service — pure-math helpers

**Files:**
- Create: `backend/app/services/options_scanner.py`
- Create: `backend/tests/test_options_scanner.py`

- [ ] **Step 1: Write failing tests for _bs_delta and _compute_iv_excess**

Create `backend/tests/test_options_scanner.py`:

```python
# backend/tests/test_options_scanner.py
import math

import pandas as pd
import pytest

from app.services.options_scanner import _bs_delta, _compute_iv_excess


def test_bs_delta_call_deep_itm():
    delta = _bs_delta(S=200.0, K=100.0, T=1.0, r=0.045, sigma=0.30, opt_type="call")
    assert delta > 0.95


def test_bs_delta_put_deep_otm():
    delta = _bs_delta(S=200.0, K=100.0, T=1.0, r=0.045, sigma=0.30, opt_type="put")
    assert -0.05 < delta <= 0.0


def test_bs_delta_atm_call_near_half():
    delta = _bs_delta(S=100.0, K=100.0, T=1.0, r=0.045, sigma=0.30, opt_type="call")
    assert 0.45 < delta < 0.65


def test_bs_delta_expired_itm_call_returns_one():
    delta = _bs_delta(S=150.0, K=100.0, T=0.0, r=0.045, sigma=0.30, opt_type="call")
    assert delta == 1.0


def test_bs_delta_expired_otm_call_returns_zero():
    delta = _bs_delta(S=100.0, K=150.0, T=0.0, r=0.045, sigma=0.30, opt_type="call")
    assert delta == 0.0


def test_compute_iv_excess_adds_columns():
    rows = [
        {"log_moneyness": math.log(k / 100), "dte": 400, "iv": 0.30 + 0.01 * i}
        for i, k in enumerate([80, 90, 95, 100, 105, 110, 120, 130])
    ]
    df = pd.DataFrame(rows)
    result = _compute_iv_excess(df)
    assert "iv_fitted" in result.columns
    assert "iv_excess" in result.columns
    assert len(result) == len(df)


def test_compute_iv_excess_small_chain_returns_zero_excess():
    df = pd.DataFrame([
        {"log_moneyness": 0.0, "dte": 400, "iv": 0.30},
        {"log_moneyness": 0.1, "dte": 400, "iv": 0.32},
    ])
    result = _compute_iv_excess(df)
    assert (result["iv_excess"] == 0.0).all()


def test_compute_iv_excess_mean_near_zero():
    """Mean IV excess should be close to 0 — the surface goes through the data."""
    rows = [
        {
            "log_moneyness": math.log(k / 100),
            "dte": d,
            "iv": 0.25 + 0.005 * abs(k - 100) / 10 + 0.02 * math.sqrt(d / 365),
        }
        for k in [80, 90, 95, 100, 105, 110, 120]
        for d in [365, 450, 550]
    ]
    df = pd.DataFrame(rows)
    result = _compute_iv_excess(df)
    assert abs(result["iv_excess"].mean()) < 0.02
```

- [ ] **Step 2: Run tests — verify they fail with ImportError**

```bash
cd backend && python -m pytest tests/test_options_scanner.py -v
```

Expected: `ImportError: cannot import name '_bs_delta' from 'app.services.options_scanner'`

- [ ] **Step 3: Create options_scanner.py with _bs_delta and _compute_iv_excess**

Create `backend/app/services/options_scanner.py`:

```python
"""Options scanner service: fetch LEAPS chain, fit IV surface, rank by IV excess."""

import logging
import math
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

_RISK_FREE_RATE = 0.045


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        f = float(val)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        f = float(val)
        return int(f) if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def _norm_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2))


def _bs_delta(
    S: float, K: float, T: float, r: float, sigma: float, opt_type: str
) -> float:
    """Black-Scholes delta for a European call or put."""
    if T <= 0 or sigma < 0.001:
        if opt_type == "call":
            return 1.0 if S > K else 0.0
        return -1.0 if S < K else 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    return _norm_cdf(d1) if opt_type == "call" else _norm_cdf(d1) - 1.0


def _compute_iv_excess(df: pd.DataFrame) -> pd.DataFrame:
    """Add iv_fitted and iv_excess via least-squares 2-D surface fit.

    Surface: IV ≈ a + b·m + c·m² + d·√T + e·m·√T
    where m = log(K/S) and T = DTE/365.
    """
    df = df.copy()
    valid = df[(df["iv"] > 0.02) & (df["dte"] > 0)]
    if len(valid) < 5:
        df["iv_fitted"] = df["iv"]
        df["iv_excess"] = 0.0
        return df

    m = valid["log_moneyness"].values
    sqrt_T = np.sqrt(valid["dte"].values / 365.0)
    iv = valid["iv"].values
    X = np.column_stack([np.ones_like(m), m, m**2, sqrt_T, m * sqrt_T])

    try:
        coeffs, _, _, _ = np.linalg.lstsq(X, iv, rcond=None)
    except np.linalg.LinAlgError:
        df["iv_fitted"] = df["iv"]
        df["iv_excess"] = 0.0
        return df

    m_all = df["log_moneyness"].values
    sqrt_T_all = np.sqrt(df["dte"].values / 365.0)
    X_all = np.column_stack(
        [np.ones_like(m_all), m_all, m_all**2, sqrt_T_all, m_all * sqrt_T_all]
    )
    df["iv_fitted"] = X_all @ coeffs
    df["iv_excess"] = df["iv"] - df["iv_fitted"]
    return df
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd backend && python -m pytest tests/test_options_scanner.py -v
```

Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/options_scanner.py backend/tests/test_options_scanner.py
git commit -m "feat: options_scanner pure-math helpers (BS delta + IV surface)"
```

---

## Task 3: Complete options_scanner — chain fetch, earnings, run_scan

**Files:**
- Modify: `backend/app/services/options_scanner.py` (append functions)
- Modify: `backend/tests/test_options_scanner.py` (append tests)

- [ ] **Step 1: Add imports and append run_scan tests to test_options_scanner.py**

First, add these three imports to the **top** of `backend/tests/test_options_scanner.py` (alongside the existing imports):

```python
from datetime import date, timedelta
from unittest.mock import MagicMock, patch
```

And add this to the existing `from app.services.options_scanner import` line:
```python
from app.services.options_scanner import _bs_delta, _compute_iv_excess, run_scan
```

Then **append** the following tests at the bottom of the file:

```python


def _call_row(strike: float, oi: int = 100) -> dict:
    return {
        "strike": strike,
        "bid": 10.0, "ask": 11.0, "lastPrice": 10.5,
        "impliedVolatility": 0.45,
        "openInterest": oi, "volume": 50,
    }


def _mock_ticker(spot: float, expirations: list, chains: dict) -> MagicMock:
    m = MagicMock()
    m.fast_info.last_price = spot
    m.options = expirations

    def option_chain(exp: str):
        calls_df, puts_df = chains.get(exp, (pd.DataFrame(), pd.DataFrame()))
        r = MagicMock()
        r.calls, r.puts = calls_df, puts_df
        return r

    m.option_chain.side_effect = option_chain
    m.get_earnings_dates.return_value = None
    m.calendar = None
    m.earnings_dates = None
    return m


def test_run_scan_returns_expected_keys():
    today = date.today()
    exp = (today + timedelta(days=400)).strftime("%Y-%m-%d")
    df = pd.DataFrame([_call_row(160.0)])
    with patch("yfinance.Ticker", return_value=_mock_ticker(150.0, [exp], {exp: (df, pd.DataFrame())})):
        result = run_scan("AMD", "calls", 365, 10, 0.90)

    assert result["ticker"] == "AMD"
    assert result["spot"] == 150.0
    assert "lt_close_date" in result
    assert "earnings_dates" in result
    assert isinstance(result["options"], list)
    assert len(result["options"]) == 1
    row = result["options"][0]
    for key in ("type", "strike", "expiration", "dte", "bid", "ask", "mid",
                "iv", "iv_fitted", "iv_excess", "delta", "ann_yield_pct",
                "open_interest", "earnings_count"):
        assert key in row, f"missing key: {key}"


def test_run_scan_filters_low_oi():
    today = date.today()
    exp = (today + timedelta(days=400)).strftime("%Y-%m-%d")
    df = pd.DataFrame([_call_row(160.0, oi=5)])  # OI below min_oi=25
    with patch("yfinance.Ticker", return_value=_mock_ticker(150.0, [exp], {exp: (df, pd.DataFrame())})):
        result = run_scan("AMD", "calls", 365, 25, 0.90)
    assert result["options"] == []


def test_run_scan_sorted_by_iv_excess_descending():
    today = date.today()
    exps = [(today + timedelta(days=d)).strftime("%Y-%m-%d") for d in [380, 410, 440, 470, 500, 530]]
    multi_df = pd.DataFrame([
        {"strike": 150.0, "bid": 8.0, "ask": 9.0, "lastPrice": 8.5,
         "impliedVolatility": 0.60, "openInterest": 200, "volume": 100},
        {"strike": 160.0, "bid": 6.0, "ask": 7.0, "lastPrice": 6.5,
         "impliedVolatility": 0.40, "openInterest": 150, "volume": 80},
    ])
    chains = {e: (multi_df.copy(), pd.DataFrame()) for e in exps}
    with patch("yfinance.Ticker", return_value=_mock_ticker(140.0, exps, chains)):
        result = run_scan("AMD", "calls", 365, 10, 0.90)

    opts = result["options"]
    for i in range(len(opts) - 1):
        assert opts[i]["iv_excess"] >= opts[i + 1]["iv_excess"]


def test_run_scan_raises_for_missing_price():
    with patch("yfinance.Ticker") as mock_cls:
        m = MagicMock()
        m.fast_info.last_price = None
        mock_cls.return_value = m
        with pytest.raises(ValueError, match="live price"):
            run_scan("INVALID", "calls", 365, 25, 0.70)


def test_run_scan_returns_both_types():
    today = date.today()
    exp = (today + timedelta(days=400)).strftime("%Y-%m-%d")
    calls_df = pd.DataFrame([_call_row(160.0)])
    puts_df = pd.DataFrame([_call_row(140.0)])  # same structure, put side
    with patch("yfinance.Ticker", return_value=_mock_ticker(150.0, [exp], {exp: (calls_df, puts_df)})):
        result = run_scan("AMD", "both", 365, 10, 0.90)

    types = {r["type"] for r in result["options"]}
    assert "call" in types
    assert "put" in types
```

- [ ] **Step 2: Run new tests — verify they fail**

```bash
cd backend && python -m pytest tests/test_options_scanner.py::test_run_scan_returns_expected_keys -v
```

Expected: `ImportError` or `AttributeError` — `run_scan` not yet defined.

- [ ] **Step 3: Append chain fetch, earnings, and run_scan to options_scanner.py**

Append to the end of `backend/app/services/options_scanner.py`:

```python

def _fetch_earnings_dates(ticker: str) -> list[date]:
    """Return sorted upcoming earnings dates from yfinance (up to 8 quarters)."""
    import yfinance as yf

    t = yf.Ticker(ticker)
    today = date.today()

    try:
        ed = t.get_earnings_dates(limit=8)
        if ed is not None and not ed.empty:
            future = [
                idx.date() for idx in ed.index
                if hasattr(idx, "date") and idx.date() >= today
            ]
            if future:
                return sorted(future)
    except Exception:
        pass

    try:
        cal = t.calendar
        if cal is not None:
            raw = None
            if isinstance(cal, dict):
                raw = cal.get("Earnings Date")
            elif hasattr(cal, "index") and "Earnings Date" in cal.index:
                raw = cal.loc["Earnings Date"]
            if raw is not None:
                dates = (
                    list(raw)
                    if hasattr(raw, "__iter__") and not isinstance(raw, str)
                    else [raw]
                )
                result = []
                for d in dates:
                    try:
                        d2 = d.date() if hasattr(d, "date") else d
                        if d2 >= today:
                            result.append(d2)
                    except Exception:
                        pass
                if result:
                    return sorted(result)
    except Exception:
        pass

    try:
        ed = t.earnings_dates
        if ed is not None and not ed.empty:
            future = [
                idx.date() for idx in ed.index
                if hasattr(idx, "date") and idx.date() >= today
            ]
            if future:
                return sorted(future)[:8]
    except Exception:
        pass

    return []


def _annotate_earnings(
    df: pd.DataFrame, earnings_dates: list[date]
) -> pd.DataFrame:
    """Add earnings_count: number of earnings events before each expiration."""
    if df.empty:
        return df
    today = date.today()

    def _count(exp_str: str) -> int:
        exp = date.fromisoformat(exp_str)
        return sum(1 for d in earnings_dates if today < d <= exp)

    df = df.copy()
    df["earnings_count"] = df["expiration"].apply(_count)
    return df


def _fetch_chain(
    ticker: str, opt_type: str, min_dte: int
) -> tuple[float, pd.DataFrame]:
    """Fetch LEAPS option chain from yfinance.

    Returns (spot, df). Raises ValueError if spot cannot be fetched.
    """
    import yfinance as yf

    t = yf.Ticker(ticker)
    spot = t.fast_info.last_price
    if not spot:
        raise ValueError(f"Could not fetch live price for {ticker}")
    spot = float(spot)

    today = date.today()
    expirations = [
        e for e in t.options
        if (datetime.strptime(e, "%Y-%m-%d").date() - today).days >= min_dte
    ]

    rows = []
    for exp_str in expirations:
        exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
        dte = (exp_date - today).days
        T = dte / 365.0
        try:
            chain = t.option_chain(exp_str)
        except Exception as exc:
            log.warning("Skipping %s: %s", exp_str, exc)
            continue

        sides: list[tuple[str, pd.DataFrame | None]] = []
        if opt_type in ("both", "calls"):
            sides.append(("call", chain.calls))
        if opt_type in ("both", "puts"):
            sides.append(("put", chain.puts))

        for side, side_df in sides:
            if side_df is None or side_df.empty:
                continue
            for _, row in side_df.iterrows():
                K = _safe_float(row.get("strike"))
                bid = _safe_float(row.get("bid"))
                ask = _safe_float(row.get("ask"))
                last = _safe_float(row.get("lastPrice"))
                iv = _safe_float(row.get("impliedVolatility"))
                oi = _safe_int(row.get("openInterest"))

                if bid <= 0 and ask <= 0:
                    continue
                mid = (bid + ask) / 2 if bid > 0 and ask > 0 else last
                if mid <= 0 or iv < 0.01 or K <= 0:
                    continue

                capital = spot if side == "call" else K
                ann_yield = (mid / capital) * (365.0 / dte) * 100.0

                rows.append({
                    "type": side,
                    "strike": K,
                    "expiration": exp_str,
                    "dte": dte,
                    "log_moneyness": math.log(K / spot),
                    "bid": bid,
                    "ask": ask,
                    "mid": mid,
                    "iv": iv,
                    "iv_fitted": iv,
                    "iv_excess": 0.0,
                    "delta": _bs_delta(spot, K, T, _RISK_FREE_RATE, iv, side),
                    "ann_yield_pct": ann_yield,
                    "open_interest": oi,
                    "earnings_count": 0,
                })

    return spot, pd.DataFrame(rows) if rows else pd.DataFrame()


def run_scan(
    ticker: str,
    opt_type: str = "both",
    min_dte: int = 365,
    min_oi: int = 25,
    max_delta: float = 0.70,
) -> dict:
    """Fetch LEAPS chain → IV surface → earnings → filter → sort.

    Intended to be called via asyncio.run_in_executor.
    Raises ValueError if the ticker price cannot be fetched.
    """
    spot, df = _fetch_chain(ticker, opt_type, min_dte)
    earnings_dates = _fetch_earnings_dates(ticker)

    if not df.empty:
        df = _compute_iv_excess(df)
        df = _annotate_earnings(df, earnings_dates)
        df = df[
            (df["open_interest"] >= min_oi) & (df["delta"].abs() <= max_delta)
        ].copy()
        df = df.sort_values("iv_excess", ascending=False)

    options = []
    for _, row in df.iterrows():
        options.append({
            "type": row["type"],
            "strike": round(float(row["strike"]), 2),
            "expiration": row["expiration"],
            "dte": int(row["dte"]),
            "bid": round(float(row["bid"]), 2),
            "ask": round(float(row["ask"]), 2),
            "mid": round(float(row["mid"]), 2),
            "iv": round(float(row["iv"]), 4),
            "iv_fitted": round(float(row["iv_fitted"]), 4),
            "iv_excess": round(float(row["iv_excess"]), 4),
            "delta": round(float(row["delta"]), 4),
            "ann_yield_pct": round(float(row["ann_yield_pct"]), 2),
            "open_interest": int(row["open_interest"]),
            "earnings_count": int(row["earnings_count"]),
        })

    return {
        "ticker": ticker,
        "spot": round(spot, 2),
        "scan_ts": datetime.utcnow().isoformat() + "Z",
        "lt_close_date": (date.today() + timedelta(days=366)).isoformat(),
        "earnings_dates": [d.isoformat() for d in earnings_dates],
        "options": options,
    }
```

- [ ] **Step 4: Run all options_scanner tests**

```bash
cd backend && python -m pytest tests/test_options_scanner.py -v
```

Expected: `13 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/options_scanner.py backend/tests/test_options_scanner.py
git commit -m "feat: options_scanner chain fetch, earnings, run_scan"
```

---

## Task 4: Implement GET /api/market/options/{ticker} route

**Files:**
- Modify: `backend/app/routers/market.py`
- Modify: `backend/tests/test_market_router_p2.py`

- [ ] **Step 1: Write failing route tests**

In `backend/tests/test_market_router_p2.py`, replace the `test_options_still_501` test with these four tests. (Keep all other existing tests — only remove that one function.)

Find and replace:
```python
async def test_options_still_501(client: AsyncClient):
    response = await client.get("/api/market/options/AAPL")
    assert response.status_code == 501
```

With:
```python
async def test_options_returns_scan_result(client: AsyncClient):
    mock_result = {
        "ticker": "AMD",
        "spot": 142.30,
        "scan_ts": "2026-05-12T10:00:00Z",
        "lt_close_date": "2027-05-13",
        "earnings_dates": [],
        "options": [
            {
                "type": "call", "strike": 150.0, "expiration": "2027-01-15",
                "dte": 400, "bid": 10.0, "ask": 11.0, "mid": 10.5,
                "iv": 0.45, "iv_fitted": 0.42, "iv_excess": 0.03,
                "delta": 0.42, "ann_yield_pct": 12.5,
                "open_interest": 100, "earnings_count": 0,
            }
        ],
    }
    with patch("app.routers.market.run_scan", return_value=mock_result):
        response = await client.get(
            "/api/market/options/AMD?type=calls&min_dte=365&min_oi=25&max_delta=0.70"
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ticker"] == "AMD"
    assert data["spot"] == 142.30
    assert len(data["options"]) == 1


async def test_options_uppercases_ticker(client: AsyncClient):
    mock_result = {
        "ticker": "AMD", "spot": 142.30, "scan_ts": "2026-05-12T10:00:00Z",
        "lt_close_date": "2027-05-13", "earnings_dates": [], "options": [],
    }
    with patch("app.routers.market.run_scan", return_value=mock_result) as mock_fn:
        await client.get("/api/market/options/amd")
    assert mock_fn.call_args[0][0] == "AMD"


async def test_options_returns_404_for_unknown_ticker(client: AsyncClient):
    with patch(
        "app.routers.market.run_scan",
        side_effect=ValueError("Could not fetch live price for INVALID"),
    ):
        response = await client.get("/api/market/options/INVALID")
    assert response.status_code == 404


async def test_options_returns_200_with_empty_options_when_no_leaps(client: AsyncClient):
    mock_result = {
        "ticker": "AMD", "spot": 142.30, "scan_ts": "2026-05-12T10:00:00Z",
        "lt_close_date": "2027-05-13", "earnings_dates": [], "options": [],
    }
    with patch("app.routers.market.run_scan", return_value=mock_result):
        response = await client.get("/api/market/options/AMD")
    assert response.status_code == 200
    assert response.json()["options"] == []
```

- [ ] **Step 2: Run new route tests — verify they fail**

```bash
cd backend && python -m pytest tests/test_market_router_p2.py::test_options_returns_scan_result -v
```

Expected: `AssertionError: assert 501 == 200`

- [ ] **Step 3: Rewrite market.py with the real options endpoint**

Replace the entire content of `backend/app/routers/market.py`:

```python
# backend/app/routers/market.py
import asyncio
from functools import partial
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.alert_engine import run as run_alert_engine
from app.services.options_scanner import run_scan
from app.services.price_fetcher import fetch_quote, fetch_rsi_batch, refresh_open_trades

router = APIRouter(prefix="/api/market", tags=["market"])


class RsiRequest(BaseModel):
    tickers: list[str]


@router.get("/quote/{ticker}")
async def get_quote(ticker: str):
    result = await fetch_quote(ticker.upper())
    if result is None:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker.upper()} not found")
    return result


@router.post("/refresh")
async def refresh_prices(db: AsyncSession = Depends(get_db)):
    price_result = await refresh_open_trades(db)
    alert_result = await run_alert_engine(db)
    return {
        "trades_updated": price_result["trades_updated"],
        "tickers_fetched": price_result["tickers_fetched"],
        "alerts_created": alert_result["alerts_created"],
        "errors": price_result["errors"],
    }


@router.post("/rsi")
async def get_rsi_batch(payload: RsiRequest) -> dict[str, float | None]:
    tickers = [t.upper() for t in payload.tickers if t.strip()]
    if not tickers:
        return {}
    return await fetch_rsi_batch(tickers)


@router.get("/options/{ticker}")
async def get_options(
    ticker: str,
    opt_type: Literal["calls", "puts", "both"] = Query("both", alias="type"),
    min_dte: int = Query(365, ge=1),
    min_oi: int = Query(25, ge=0),
    max_delta: float = Query(0.70, gt=0, le=1.0),
):
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            partial(run_scan, ticker.upper(), opt_type, min_dte, min_oi, max_delta),
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/prefetch/{ticker}")
async def prefetch_indicators(ticker: str):
    return JSONResponse({"detail": "not implemented"}, status_code=501)
```

- [ ] **Step 4: Run all market router tests**

```bash
cd backend && python -m pytest tests/test_market_router_p2.py -v
```

Expected: `7 passed` (the 3 original quote/refresh tests + 4 new options tests, minus the removed 501 test)

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
cd backend && python -m pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/market.py backend/tests/test_market_router_p2.py
git commit -m "feat: implement GET /api/market/options/{ticker} with IV surface scanner"
```

---

## Task 5: Fix client.ts and create scanner.ts API module

**Files:**
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/api/scanner.ts`

- [ ] **Step 1: Fix erasableSyntaxOnly bug in client.ts**

`frontend/src/api/client.ts` currently uses a parameter property shorthand (`constructor(public status: number, ...)`), which is disallowed by `"erasableSyntaxOnly": true` in the tsconfig. Replace the `ApiError` class:

Old:
```typescript
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}
```

New:
```typescript
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}
```

- [ ] **Step 2: Create scanner.ts**

Create `frontend/src/api/scanner.ts`:

```typescript
import { apiFetch } from './client'

export interface ScanParams {
  type?: 'calls' | 'puts' | 'both'
  min_dte?: number
  min_oi?: number
  max_delta?: number
}

export interface OptionRow {
  type: 'call' | 'put'
  strike: number
  expiration: string
  dte: number
  bid: number
  ask: number
  mid: number
  iv: number
  iv_fitted: number
  iv_excess: number
  delta: number
  ann_yield_pct: number
  open_interest: number
  earnings_count: number
}

export interface ScanResult {
  ticker: string
  spot: number
  scan_ts: string
  lt_close_date: string
  earnings_dates: string[]
  options: OptionRow[]
}

export async function scanOptions(
  ticker: string,
  params: ScanParams = {},
): Promise<ScanResult> {
  const query = new URLSearchParams()
  if (params.type) query.set('type', params.type)
  if (params.min_dte !== undefined) query.set('min_dte', String(params.min_dte))
  if (params.min_oi !== undefined) query.set('min_oi', String(params.min_oi))
  if (params.max_delta !== undefined) query.set('max_delta', String(params.max_delta))
  const qs = query.toString()
  return apiFetch<ScanResult>(
    `/market/options/${encodeURIComponent(ticker)}${qs ? `?${qs}` : ''}`,
  )
}
```

- [ ] **Step 3: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/api/scanner.ts
git commit -m "feat: scanner.ts API module + fix client.ts erasableSyntaxOnly"
```

---

## Task 6: Create ScannerPage.tsx

**Files:**
- Create: `frontend/src/pages/ScannerPage.tsx`

- [ ] **Step 1: Create ScannerPage.tsx**

Create `frontend/src/pages/ScannerPage.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { scanOptions } from '../api/scanner'
import type { OptionRow, ScanResult } from '../api/scanner'

type OptType = 'calls' | 'puts' | 'both'
type TabKey = 'calls' | 'puts'

interface FormState {
  ticker: string
  optType: OptType
  minDte: number
  minOi: number
  maxDelta: number
  showAdvanced: boolean
}

type ScanState =
  | { status: 'idle' }
  | { status: 'loading'; ticker: string }
  | { status: 'success'; result: ScanResult; activeTab: TabKey }
  | { status: 'empty'; ticker: string }
  | { status: 'error'; message: string; ticker: string }

function dteClass(dte: number): string {
  if (dte <= 7) return 'text-red-600 font-semibold'
  if (dte <= 21) return 'text-amber-600 font-semibold'
  if (dte <= 60) return 'text-green-600'
  return 'text-blue-600'
}

function fmtExp(expiration: string, earningsCount: number): string {
  const d = new Date(expiration + 'T00:00:00')
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
  const tag = earningsCount > 0 ? ` ${earningsCount}E` : ''
  return `${months[d.getMonth()]} ${d.getDate()} '${String(d.getFullYear()).slice(2)}${tag}`
}

function fmtShortDate(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00')
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
  return `${months[d.getMonth()]} ${d.getDate()} '${String(d.getFullYear()).slice(2)}`
}

function OptionsTable({ rows }: { rows: OptionRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            {['Strike','Expiration','DTE','Bid','Ask','Mid','IV%','IV+pp','Delta','Ann%','OI'].map(h => (
              <th key={h} className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-100">
          {rows.map((r, i) => (
            <tr key={i} className="hover:bg-gray-50">
              <td className="px-3 py-2 font-medium">${r.strike.toFixed(0)}</td>
              <td className="px-3 py-2 whitespace-nowrap">{fmtExp(r.expiration, r.earnings_count)}</td>
              <td className={`px-3 py-2 ${dteClass(r.dte)}`}>{r.dte}</td>
              <td className="px-3 py-2">${r.bid.toFixed(2)}</td>
              <td className="px-3 py-2">${r.ask.toFixed(2)}</td>
              <td className="px-3 py-2 font-medium">${r.mid.toFixed(2)}</td>
              <td className="px-3 py-2">{(r.iv * 100).toFixed(1)}</td>
              <td className={`px-3 py-2 font-medium ${r.iv_excess >= 0 ? 'text-orange-600' : 'text-gray-400'}`}>
                {r.iv_excess >= 0 ? '+' : ''}{(r.iv_excess * 100).toFixed(1)}
              </td>
              <td className="px-3 py-2">{r.delta.toFixed(2)}</td>
              <td className="px-3 py-2">{r.ann_yield_pct.toFixed(1)}%</td>
              <td className="px-3 py-2 text-gray-500">{r.open_interest.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function ScannerPage() {
  const [searchParams] = useSearchParams()
  const [form, setForm] = useState<FormState>({
    ticker: searchParams.get('ticker')?.toUpperCase() ?? '',
    optType: 'both',
    minDte: 365,
    minOi: 25,
    maxDelta: 0.70,
    showAdvanced: false,
  })
  const [scanState, setScanState] = useState<ScanState>({ status: 'idle' })

  const runScan = async (overrideTicker?: string) => {
    const ticker = (overrideTicker ?? form.ticker).trim().toUpperCase()
    if (!ticker) return
    setScanState({ status: 'loading', ticker })
    try {
      const result = await scanOptions(ticker, {
        type: form.optType,
        min_dte: form.minDte,
        min_oi: form.minOi,
        max_delta: form.maxDelta,
      })
      if (result.options.length === 0) {
        setScanState({ status: 'empty', ticker })
      } else {
        const defaultTab: TabKey = form.optType === 'puts' ? 'puts' : 'calls'
        setScanState({ status: 'success', result, activeTab: defaultTab })
      }
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Scan failed. Try again.'
      setScanState({ status: 'error', message, ticker })
    }
  }

  useEffect(() => {
    const ticker = searchParams.get('ticker')
    if (ticker) runScan(ticker.toUpperCase())
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="p-6 max-w-5xl">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Options Scanner</h1>

      {/* Input zone */}
      <div className="bg-white border border-gray-200 rounded-lg p-4 mb-6">
        <div className="flex gap-4 items-end flex-wrap">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Ticker</label>
            <input
              type="text"
              className="border border-gray-300 rounded px-3 py-2 text-sm w-28 uppercase"
              placeholder="e.g. AMD"
              value={form.ticker}
              onChange={e => setForm(f => ({ ...f, ticker: e.target.value.toUpperCase() }))}
              onKeyDown={e => { if (e.key === 'Enter') runScan() }}
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Type</label>
            <div className="flex gap-3">
              {(['calls', 'puts', 'both'] as OptType[]).map(t => (
                <label key={t} className="flex items-center gap-1 text-sm cursor-pointer select-none">
                  <input
                    type="radio"
                    name="optType"
                    value={t}
                    checked={form.optType === t}
                    onChange={() => setForm(f => ({ ...f, optType: t }))}
                  />
                  {t.charAt(0).toUpperCase() + t.slice(1)}
                </label>
              ))}
            </div>
          </div>
          <button
            onClick={() => runScan()}
            disabled={scanState.status === 'loading'}
            className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50"
          >
            {scanState.status === 'loading' ? 'Scanning…' : 'Scan'}
          </button>
        </div>

        <div className="mt-3">
          <button
            type="button"
            className="text-xs text-blue-600 hover:underline"
            onClick={() => setForm(f => ({ ...f, showAdvanced: !f.showAdvanced }))}
          >
            {form.showAdvanced ? '▲ Hide filters' : '▼ Advanced filters'}
          </button>
          {form.showAdvanced && (
            <div className="flex gap-4 mt-2 flex-wrap">
              {(
                [
                  { label: 'Min DTE', key: 'minDte', step: 30, min: 1 },
                  { label: 'Min OI',  key: 'minOi',  step: 5,  min: 0 },
                  { label: 'Max Δ',   key: 'maxDelta', step: 0.05, min: 0.01 },
                ] as { label: string; key: keyof FormState; step: number; min: number }[]
              ).map(({ label, key, step, min }) => (
                <div key={key}>
                  <label className="block text-xs text-gray-500 mb-1">{label}</label>
                  <input
                    type="number"
                    className="border border-gray-300 rounded px-2 py-1 text-sm w-24"
                    value={form[key] as number}
                    step={step}
                    min={min}
                    onChange={e => setForm(f => ({ ...f, [key]: Number(e.target.value) }))}
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* States */}
      {scanState.status === 'idle' && (
        <p className="text-center text-gray-400 py-16 text-sm">
          Enter a ticker and click Scan to find LEAPS options ranked by IV excess.
        </p>
      )}

      {scanState.status === 'loading' && (
        <div className="text-center py-16">
          <div className="animate-spin inline-block w-6 h-6 border-2 border-blue-600 border-t-transparent rounded-full mb-3" />
          <p className="text-gray-500 text-sm">Scanning {scanState.ticker}… this takes ~10s</p>
        </div>
      )}

      {scanState.status === 'error' && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex items-center justify-between">
          <p className="text-sm text-red-700">{scanState.message}</p>
          <button onClick={() => runScan(scanState.ticker)} className="text-sm text-red-600 hover:underline ml-4">
            Retry
          </button>
        </div>
      )}

      {scanState.status === 'empty' && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-sm text-yellow-700">
          No options found for <strong>{scanState.ticker}</strong> — try relaxing the filters (lower Min OI, lower Min DTE, or higher Max Delta).
        </div>
      )}

      {scanState.status === 'success' && (() => {
        const { result, activeTab } = scanState
        const callRows = result.options.filter(o => o.type === 'call')
        const putRows  = result.options.filter(o => o.type === 'put')
        const showTabs = form.optType === 'both'
        const visibleRows = showTabs ? (activeTab === 'calls' ? callRows : putRows) : result.options

        return (
          <>
            <div className="text-xs text-gray-500 mb-4 flex flex-wrap gap-x-4 gap-y-1">
              <span className="font-semibold text-gray-800">{result.ticker}</span>
              <span>spot: ${result.spot.toFixed(2)}</span>
              <span>scanned: {result.scan_ts.slice(0, 10)}</span>
              <span>LT close if opened today: {fmtShortDate(result.lt_close_date)}</span>
              {result.earnings_dates.length > 0 && (
                <span>
                  upcoming earnings: {result.earnings_dates.slice(0, 3).map(fmtShortDate).join(', ')}
                </span>
              )}
            </div>

            {showTabs && (
              <div className="flex gap-1 mb-0 border-b border-gray-200">
                {(['calls', 'puts'] as TabKey[]).map(tab => (
                  <button
                    key={tab}
                    onClick={() =>
                      setScanState(s =>
                        s.status === 'success' ? { ...s, activeTab: tab } : s,
                      )
                    }
                    className={`px-4 py-2 text-sm -mb-px border-b-2 ${
                      activeTab === tab
                        ? 'border-blue-600 text-blue-600 font-medium'
                        : 'border-transparent text-gray-500 hover:text-gray-700'
                    }`}
                  >
                    {tab.charAt(0).toUpperCase() + tab.slice(1)}{' '}
                    <span className="text-xs text-gray-400">
                      ({tab === 'calls' ? callRows.length : putRows.length})
                    </span>
                  </button>
                ))}
              </div>
            )}

            <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
              <OptionsTable rows={visibleRows} />
            </div>

            <div className="mt-3 space-y-1 text-xs text-gray-400">
              <p><strong className="text-gray-500">IV+pp</strong> — percentage points above the fitted IV surface. &gt;3pp = some richness; &gt;5pp = genuine signal.</p>
              <p><strong className="text-gray-500">Delta</strong> — approximate probability of expiring in-the-money. Lower = safer, less premium.</p>
              <p><strong className="text-gray-500">Ann%</strong> — annualized yield on premium collected. Calls: vs. spot; puts: vs. strike.</p>
            </div>
          </>
        )
      })()}
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/ScannerPage.tsx
git commit -m "feat: ScannerPage — IV surface options scanner UI"
```

---

## Task 7: Wire ScannerPage into App.tsx

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Add import, nav link, and route**

In `frontend/src/App.tsx`, make three changes:

**Add import** (after the existing page imports):
```typescript
import { ScannerPage } from './pages/ScannerPage'
```

**Add nav link** (after `<NavItem to="/trades" label="Trades" />`):
```tsx
<NavItem to="/scanner" label="Scanner" />
```

**Add route** (after `<Route path="/trades/:id" element={<TradeDetailPage />} />`):
```tsx
<Route path="/scanner" element={<ScannerPage />} />
```

The complete updated `App.tsx`:

```tsx
// frontend/src/App.tsx
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import { DashboardPage } from './pages/DashboardPage'
import { TradesPage } from './pages/TradesPage'
import { TradeDetailPage } from './pages/TradeDetailPage'
import { ScannerPage } from './pages/ScannerPage'

function NavItem({ to, label }: { to: string; label: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `px-4 py-2 text-sm font-medium rounded ${isActive ? 'bg-blue-600 text-white' : 'text-gray-600 hover:bg-gray-100'}`
      }
    >
      {label}
    </NavLink>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-50">
        <nav className="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-2">
          <span className="font-bold text-gray-900 mr-4">TradeMinder</span>
          <NavItem to="/" label="Dashboard" />
          <NavItem to="/trades" label="Trades" />
          <NavItem to="/scanner" label="Scanner" />
        </nav>
        <main>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/trades" element={<TradesPage />} />
            <Route path="/trades/:id" element={<TradeDetailPage />} />
            <Route path="/scanner" element={<ScannerPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat: add /scanner route and nav link"
```

---

## Task 8: Add Scan links to TradeTable and TradeDetailPage

**Files:**
- Modify: `frontend/src/components/Trades/TradeTable.tsx`
- Modify: `frontend/src/pages/TradeDetailPage.tsx`

The scan link is shown only when `trade.strategy === 'Stock'` and `trade.status === 'open'`. Stock positions benefit from scanning for covered call opportunities.

- [ ] **Step 1: Add "Scan →" link to TradeTable**

In `frontend/src/components/Trades/TradeTable.tsx`, add a `Link` import from `react-router-dom` (it's already imported), then update the actions cell for stock trades.

Replace the last `<td>` in the `<tr>`:
```tsx
<td className="px-4 py-3">
  <button
    onClick={() => onDelete(trade.id)}
    className="text-red-500 hover:text-red-700 text-xs"
  >
    Delete
  </button>
</td>
```

With:
```tsx
<td className="px-4 py-3">
  <div className="flex items-center gap-3">
    {trade.strategy === 'Stock' && trade.status === 'open' && (
      <Link
        to={`/scanner?ticker=${trade.ticker}`}
        className="text-blue-500 hover:text-blue-700 text-xs"
      >
        Scan →
      </Link>
    )}
    <button
      onClick={() => onDelete(trade.id)}
      className="text-red-500 hover:text-red-700 text-xs"
    >
      Delete
    </button>
  </div>
</td>
```

- [ ] **Step 2: Add "Scan Options" button to TradeDetailPage**

In `frontend/src/pages/TradeDetailPage.tsx`, add a `useNavigate` call (it's already imported) and add the button.

After the `← Back to trades` button at the top, find:
```tsx
<div className="flex justify-between items-start mb-6">
```

And within that block, add a "Scan Options" button for open stock trades. Replace:
```tsx
<div className="flex justify-between items-start mb-6">
  <div>
    <h1 className="text-2xl font-bold text-gray-900">{trade.ticker}</h1>
    <p className="text-gray-500">{trade.strategy} · {trade.type} · {trade.category}</p>
  </div>
  <StatusBadge status={trade.status} />
</div>
```

With:
```tsx
<div className="flex justify-between items-start mb-6">
  <div>
    <h1 className="text-2xl font-bold text-gray-900">{trade.ticker}</h1>
    <p className="text-gray-500">{trade.strategy} · {trade.type} · {trade.category}</p>
  </div>
  <div className="flex items-center gap-3">
    {trade.strategy === 'Stock' && trade.status === 'open' && (
      <button
        onClick={() => navigate(`/scanner?ticker=${trade.ticker}`)}
        className="px-3 py-1.5 text-sm border border-blue-300 text-blue-600 rounded hover:bg-blue-50"
      >
        Scan Options
      </button>
    )}
    <StatusBadge status={trade.status} />
  </div>
</div>
```

- [ ] **Step 3: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Trades/TradeTable.tsx frontend/src/pages/TradeDetailPage.tsx
git commit -m "feat: Scan links on open stock positions in TradeTable and TradeDetailPage"
```

---

## Manual smoke test

After all tasks are complete, start the dev server and verify the feature end-to-end.

- [ ] Start backend: `cd backend && uvicorn app.main:app --reload --port 8000`
- [ ] Start frontend: `cd frontend && npm run dev`
- [ ] Open `http://localhost:5173/scanner` — verify the scanner page loads with ticker input + radio buttons
- [ ] Type `AAPL`, select "Calls", click Scan — verify spinner appears then a ranked table loads
- [ ] Confirm IV+pp column is present and rows are sorted highest-to-lowest
- [ ] Confirm earnings annotation (`2E`) appears on expirations that span earnings
- [ ] Confirm metadata bar shows spot price, scan date, LT close date
- [ ] Navigate to `/trades`, find any Stock position with status open — verify "Scan →" link is visible
- [ ] Click "Scan →" — verify it navigates to `/scanner?ticker=TICKER` and auto-scans
- [ ] Navigate to a Stock trade detail — verify "Scan Options" button is visible and works
- [ ] Test empty-result state: scan with `min_dte=9999` — verify the yellow "No options found" message
- [ ] Test error state: scan with a nonsense ticker like `ZZZZZ` — verify the red error message + Retry
