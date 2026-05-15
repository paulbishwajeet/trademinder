# Options Scanner — Design Spec
**Date:** 2026-05-12  
**Status:** Approved

## Overview

Integrate the options scanner from `stockpile-main` into TradeMinder as a first-class feature. The scanner fetches a LEAPS option chain for a given ticker, fits a 2-D implied volatility surface, and ranks options by IV excess (how far each option's IV sits above the fitted surface). High IV-excess options are rich premium candidates worth selling (covered calls, cash-secured puts).

---

## Scope

**In scope:**
- Single-ticker scan with IV surface analysis
- Standalone `/scanner` page in the React frontend
- "Scan Options" shortcut on open stock positions in the Trades list and Trade Detail page
- User-selectable option type (Calls / Puts / Both)
- Adjustable filter controls (min DTE, min OI, max delta)

**Out of scope (future):**
- Portfolio scanner (CSV upload, scan all positions)
- Roll analysis (net credit calculation)
- Cost-basis charts
- Google Sheets sync

---

## Backend

### New service: `backend/app/services/options_scanner.py`

Consolidates three modules from `stockpile-main/options-scanner/src/` with no new external dependencies beyond `numpy`:

| Source module | Responsibility |
|---|---|
| `chain.py` | Fetch option chain via yfinance; compute Black-Scholes delta and annualized yield per row |
| `iv_surface.py` | Fit 2-D IV surface `IV ≈ f(log-moneyness, √T)` using least-squares; compute `iv_excess = iv − iv_fitted` per option |
| `earnings.py` | Fetch upcoming earnings dates; annotate each option with count of earnings events before its expiration |

Public function signature:
```python
def run_scan(
    ticker: str,
    opt_type: str,        # "calls" | "puts" | "both"
    min_dte: int,         # default 365
    min_oi: int,          # default 25
    max_delta: float,     # default 0.70
) -> dict
```

Returns:
```python
{
    "ticker": str,
    "spot": float,
    "scan_ts": str,           # ISO-8601 UTC
    "lt_close_date": str,     # YYYY-MM-DD, 366 days from today
    "earnings_dates": list[str],
    "options": list[dict],    # see response shape below
}
```

Each option row:
```python
{
    "type": "call" | "put",
    "strike": float,
    "expiration": str,        # YYYY-MM-DD
    "dte": int,
    "bid": float,
    "ask": float,
    "mid": float,
    "iv": float,
    "iv_fitted": float,
    "iv_excess": float,       # key ranking column
    "delta": float,
    "ann_yield_pct": float,
    "open_interest": int,
    "earnings_count": int,
}
```

Rows sorted by `iv_excess` descending (richest premium first) before returning.

### New dependency

Add `numpy` to `backend/requirements.txt`. No other new packages needed — `yfinance` and `pandas` are already present.

### Route update: `backend/app/routers/market.py`

The existing `GET /api/market/options/{ticker}` currently returns `NOT_IMPLEMENTED (501)`. Replace with a real handler:

```
GET /api/market/options/{ticker}
  ?type=both          # calls | puts | both
  &min_dte=365
  &min_oi=25
  &max_delta=0.70
```

The handler runs the scan in a thread pool via `loop.run_in_executor(None, run_scan, ...)` — the same pattern used by `fetch_rsi_batch` in `price_fetcher.py` — so the async event loop is not blocked.

**Error responses:**
- `404` — ticker not found / yfinance returns no price
- `422` — invalid query param values (Pydantic validation)
- `500` — unexpected error during scan
- `200` with `options: []` — scan succeeded but no options survived the filters

---

## Frontend

### New page: `frontend/src/pages/ScannerPage.tsx`

Route: `/scanner`  
Nav link: "Scanner" added to the top nav in `App.tsx`

#### URL parameter
`/scanner?ticker=AMD` — when navigated from a trade link, the ticker input is pre-filled and the scan fires automatically.

#### Input zone

- Ticker text input (uppercased on change, Enter triggers scan)
- Calls / Puts / Both radio group (default: Both)
- Collapsible "Advanced" section:
  - Min DTE: number input, default 365
  - Min OI: number input, default 25
  - Max Delta: number input, default 0.70
- "Scan" button

#### Metadata bar (shown after successful scan)

Single subdued line: `AMD  ·  spot: $142.30  ·  Scanned: 2026-05-12  ·  LT close if opened today: May 13 '27  ·  Upcoming earnings: Jul 29`

#### Results table

- When type = Both: two tabs, Calls and Puts
- When type = Calls or Puts: single table, no tabs

Columns:

| Column | Notes |
|---|---|
| Strike | `$150` |
| Expiration | `Jan 15 '27` + ` 2E` suffix if `earnings_count > 0` |
| DTE | Color-coded: red ≤7, amber ≤21, green ≤60, blue >60 |
| Bid / Ask / Mid | Dollar values |
| IV% | `iv × 100`, one decimal |
| IV+pp | `iv_excess × 100` with sign, one decimal — **primary sort column** |
| Delta | Two decimals |
| Ann% | One decimal |
| OI | Integer, comma-formatted |

Legend below table (static text):
- **IV+pp** — how many percentage points above the fitted surface. >3pp = some richness; >5pp = genuine signal.
- **Delta** — approximate probability of expiring in the money. Lower = safer, less premium.
- **Ann%** — annualized yield on premium collected (calls: vs. spot; puts: vs. strike).

#### States

- **Idle** — empty state with prompt to enter a ticker
- **Loading** — full-table spinner, "Scanning AMD…"
- **Success** — metadata bar + table
- **Empty** — "No options found — try relaxing the filters (lower Min OI, lower Min DTE, or higher Max Delta)"
- **Error** — message + Retry button

### New API module: `frontend/src/api/scanner.ts`

```typescript
export interface ScanParams {
  type?: 'calls' | 'puts' | 'both'
  min_dte?: number
  min_oi?: number
  max_delta?: number
}

export interface OptionRow {
  type: 'call' | 'put'
  strike: number
  expiration: string   // YYYY-MM-DD
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

export async function scanOptions(ticker: string, params: ScanParams): Promise<ScanResult>
```

### Trade links

**`TradesPage.tsx`** — For rows where `type === 'Stock'` and `status === 'open'`, add a small "Scan →" link that navigates to `/scanner?ticker={ticker}`.

**`TradeDetailPage.tsx`** — For open stock trades, add a "Scan Options" button in the action area that navigates to `/scanner?ticker={ticker}`.

---

## Data Flow

```
User submits ticker + params
  → GET /api/market/options/{ticker}?type=both&min_dte=365&min_oi=25&max_delta=0.70
  → FastAPI validates query params (Pydantic)
  → run_in_executor → run_scan() in thread
      → fetch_chain(): yfinance option chain + BS delta + ann yield
      → compute_iv_excess(): least-squares surface fit, iv_excess per row
      → fetch_earnings_dates(): yfinance calendar lookup (3 fallback approaches)
      → annotate_earnings(): earnings_count per option
      → filter: open_interest >= min_oi, abs(delta) <= max_delta
      → sort by iv_excess desc
      → return dict
  → JSON response
  → Frontend renders metadata bar + ranked table
```

No database reads or writes. Results are transient — re-scanning fetches fresh live data.

---

## Error Handling

| Scenario | Backend response | Frontend display |
|---|---|---|
| Ticker not found | 404 | "Ticker not found." |
| No options survive filters | 200, `options: []` | "No options found — try relaxing the filters" |
| yfinance network error | 500 | Error message + Retry button |
| Invalid params | 422 | Inline form validation message |
| Scan > 30s (edge case) | 504 (gateway timeout) | Timeout message + Retry button |

---

## Files Changed

**New:**
- `backend/app/services/options_scanner.py`
- `frontend/src/pages/ScannerPage.tsx`
- `frontend/src/api/scanner.ts`

**Modified:**
- `backend/app/routers/market.py` — implement `GET /api/market/options/{ticker}`
- `backend/requirements.txt` — add `numpy`
- `frontend/src/App.tsx` — add `/scanner` route + nav link
- `frontend/src/pages/TradesPage.tsx` — add "Scan →" link on open stock rows
- `frontend/src/pages/TradeDetailPage.tsx` — add "Scan Options" button on open stock trades
