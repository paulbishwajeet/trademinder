# Margin Assignment Confidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Black-Scholes assignment probability to each short put on the margin dashboard, producing a confidence-adjusted obligation total alongside the existing worst-case figure.

**Architecture:** Extend the existing `/api/market/rsi` backend endpoint to also return current price (free — same yfinance call). The frontend fires one batch request on CSV load, computes BS put delta per position in a `useMemo`, and renders four new columns in the position table plus a fifth summary card. The extension's RSI fetch is updated to read the new response shape. All BS math is pure TypeScript with no external dependencies.

**Tech Stack:** FastAPI + yfinance (backend), React 19 + TypeScript + Tailwind (frontend), Chrome MV3 content script (extension)

---

## File Map

| File | Change |
|---|---|
| `backend/app/services/price_fetcher.py` | `_fetch_one_rsi` returns `dict{rsi, price}` instead of bare float; update type annotations on `_fetch_rsi_from_yfinance` and `fetch_rsi_batch` |
| `backend/app/routers/market.py` | Update return type annotation on `get_rsi_batch` |
| `backend/tests/test_price_fetcher.py` | Add four tests for the new `_fetch_one_rsi` shape |
| `extension/content.js` | `fetchRsiForAll` reads `val.rsi` instead of `val` (lines 677–678) |
| `frontend/src/pages/MarginDashboardPage.tsx` | All remaining changes — math functions, types, state, fetch, UI |

---

## Task 1: Backend — `_fetch_one_rsi` returns `{rsi, price}`

**Files:**
- Modify: `backend/app/services/price_fetcher.py:82–104`
- Modify: `backend/app/routers/market.py:38`
- Modify: `backend/tests/test_price_fetcher.py` (add tests after line 194)

- [ ] **Step 1: Add four failing tests to `backend/tests/test_price_fetcher.py`**

Append after the last test in the file:

```python
# --- _fetch_one_rsi returns {rsi, price} dict ---

import pandas as pd as _pd

def _make_close_df(n: int = 30, start: float = 100.0) -> _pd.DataFrame:
    """Minimal DataFrame mimicking yfinance single-ticker output (enough rows for RSI-14)."""
    prices = [start + i * 0.5 for i in range(n)]
    return _pd.DataFrame({"Close": prices, "Volume": [1_000_000] * n})


def test_fetch_one_rsi_returns_dict_shape():
    """Return must be (ticker, dict) with exactly {rsi, price}."""
    from app.services.price_fetcher import _fetch_one_rsi
    with patch("app.services.price_fetcher.yf.download", return_value=_make_close_df(30)):
        ticker, result = _fetch_one_rsi("AAPL")
    assert ticker == "AAPL"
    assert isinstance(result, dict)
    assert set(result.keys()) == {"rsi", "price"}


def test_fetch_one_rsi_price_is_last_close():
    from app.services.price_fetcher import _fetch_one_rsi
    df = _make_close_df(30)
    with patch("app.services.price_fetcher.yf.download", return_value=df):
        _, result = _fetch_one_rsi("AAPL")
    assert result["price"] == round(float(df["Close"].iloc[-1]), 2)


def test_fetch_one_rsi_rsi_type():
    from app.services.price_fetcher import _fetch_one_rsi
    with patch("app.services.price_fetcher.yf.download", return_value=_make_close_df(30)):
        _, result = _fetch_one_rsi("AAPL")
    assert result["rsi"] is None or isinstance(result["rsi"], float)


def test_fetch_one_rsi_empty_df_returns_none():
    from app.services.price_fetcher import _fetch_one_rsi
    with patch("app.services.price_fetcher.yf.download", return_value=_pd.DataFrame()):
        ticker, result = _fetch_one_rsi("BADTICKER")
    assert ticker == "BADTICKER"
    assert result is None
```

- [ ] **Step 2: Run tests — expect 4 failures**

```bash
cd backend && python -m pytest tests/test_price_fetcher.py -k "fetch_one_rsi" -v
```

Expected: 4 FAILED (AttributeError or AssertionError — `result` is currently a float, not a dict)

- [ ] **Step 3: Update `_fetch_one_rsi` in `backend/app/services/price_fetcher.py`**

Replace lines 82–93 (the entire `_fetch_one_rsi` function):

```python
def _fetch_one_rsi(ticker: str) -> tuple[str, dict | None]:
    try:
        df = yf.download(ticker, period="45d", interval="1d", progress=False, auto_adjust=True)
        if df is None or df.empty:
            return ticker, None
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        price = round(float(close.iloc[-1]), 2)
        rsi = _compute_rsi_14(close)
        return ticker, {"rsi": rsi, "price": price}
    except Exception:
        return ticker, None
```

- [ ] **Step 4: Update type annotations for `_fetch_rsi_from_yfinance` and `fetch_rsi_batch`**

Replace lines 95–104:

```python
def _fetch_rsi_from_yfinance(tickers: list[str]) -> dict[str, dict | None]:
    """Parallel RSI fetch — 5 workers keeps yfinance from throttling."""
    with ThreadPoolExecutor(max_workers=5) as ex:
        return dict(ex.map(_fetch_one_rsi, tickers))


async def fetch_rsi_batch(tickers: list[str]) -> dict[str, dict | None]:
    """Async wrapper so the event loop is not blocked."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_rsi_from_yfinance, tickers)
```

- [ ] **Step 5: Update return type annotation in `backend/app/routers/market.py`**

Find the `get_rsi_batch` route (currently `-> dict[str, float | None]`) and change it:

```python
@router.post("/rsi")
async def get_rsi_batch(payload: RsiRequest) -> dict[str, dict | None]:
    tickers = [t.upper() for t in payload.tickers if t.strip()]
    if not tickers:
        return {}
    return await fetch_rsi_batch(tickers)
```

- [ ] **Step 6: Run tests — expect 4 passes**

```bash
cd backend && python -m pytest tests/test_price_fetcher.py -k "fetch_one_rsi" -v
```

Expected: 4 PASSED

- [ ] **Step 7: Run the full test suite to check for regressions**

```bash
cd backend && python -m pytest tests/ -v --ignore=tests/test_market_router_p2.py
```

Expected: all previously passing tests still pass. (`test_market_router_p2.py` may require a live DB — skip it.)

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/price_fetcher.py backend/app/routers/market.py backend/tests/test_price_fetcher.py
git commit -m "feat: extend /api/market/rsi to return {rsi, price} per ticker"
```

---

## Task 2: Extension — update `fetchRsiForAll` to read new response shape

**Files:**
- Modify: `extension/content.js:677–678`

- [ ] **Step 1: Replace the `Object.entries` block inside `fetchRsiForAll`**

Find this block (currently around lines 677–678):

```js
      Object.entries(data).forEach(([ticker, rsi]) => {
        rsiCache.set(ticker, typeof rsi === 'number' ? rsi : null);
      });
```

Replace with:

```js
      Object.entries(data).forEach(([ticker, val]) => {
        const rsi = val && typeof val === 'object' ? val.rsi : null;
        rsiCache.set(ticker, typeof rsi === 'number' ? rsi : null);
      });
```

- [ ] **Step 2: Manual smoke test**

Load the extension on the E*TRADE positions page. Click "📊 Fetch RSI". Confirm RSI pills appear on rows. Open DevTools Network tab — the `/api/market/rsi` response should now be `{"AAPL": {"rsi": 52.3, "price": 213.4}, ...}` (object of objects, not flat numbers). RSI pills should render correctly.

- [ ] **Step 3: Commit**

```bash
git add extension/content.js
git commit -m "fix: update extension fetchRsiForAll to read new {rsi, price} response shape"
```

---

## Task 3: Frontend — `normalCDF` and `bsPutAssignmentProb` math functions

**Files:**
- Modify: `frontend/src/pages/MarginDashboardPage.tsx` — add two functions in the `// ─── Helpers` section

- [ ] **Step 1: Add `normalCDF` and `bsPutAssignmentProb` after the existing helper functions**

After `fmtPct`, add:

```ts
/** Abramowitz & Stegun rational approximation — accurate to ~7 decimal places. */
function normalCDF(x: number): number {
  const a1 =  0.254829592, a2 = -0.284496736, a3 =  1.421413741
  const a4 = -1.453152027, a5 =  1.061405429, p  =  0.3275911
  const sign = x < 0 ? -1 : 1
  const t = 1 / (1 + p * Math.abs(x) / Math.SQRT2)
  const poly = t * (a1 + t * (a2 + t * (a3 + t * (a4 + t * a5))))
  return 0.5 * (1 + sign * (1 - poly * Math.exp(-x * x / 2)))
}

/**
 * Black-Scholes put delta (absolute value) = probability of assignment.
 * Returns null when any required input is missing or invalid.
 */
function bsPutAssignmentProb(
  S: number,        // current stock price
  K: number,        // strike price
  T: number,        // time to expiry in years (DTE / 365)
  sigma: number,    // implied volatility as decimal (e.g. 0.35 for 35%)
  r = 0.045,        // risk-free rate (approx T-bill rate)
): number | null {
  if (!S || !K || T <= 0 || sigma <= 0) return null
  const d1 = (Math.log(S / K) + (r + (sigma * sigma) / 2) * T) / (sigma * Math.sqrt(T))
  return normalCDF(-d1)
}
```

- [ ] **Step 2: Add three color-coding helpers after `bsPutAssignmentProb`**

```ts
function gainClass(pct: number): string {
  if (pct >= 0.70) return 'text-green-600 font-medium'
  if (pct >= 0.40) return 'text-amber-600 font-medium'
  return 'text-red-600 font-medium'
}

function probClass(prob: number): string {
  if (prob < 0.15) return 'text-green-600 font-medium'
  if (prob < 0.35) return 'text-amber-600 font-medium'
  return 'text-red-600 font-medium'
}

function rsiPillClass(rsi: number): string {
  if (rsi < 30)  return 'bg-green-100 text-green-700 border border-green-300'
  if (rsi < 40)  return 'bg-emerald-100 text-emerald-700 border border-emerald-300'
  if (rsi <= 60) return 'bg-gray-100 text-gray-600 border border-gray-200'
  if (rsi <= 70) return 'bg-amber-100 text-amber-700 border border-amber-300'
  return 'bg-red-100 text-red-700 border border-red-300'
}
```

- [ ] **Step 3: Verify the file still compiles**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

Expected: no TypeScript errors. (The new functions are unused at this point — that's fine; TS does not error on unused functions.)

- [ ] **Step 4: Manual smoke test for BS math (open browser console on any page)**

```ts
// ATM put: S=K=100, 30d, IV=30% → should be ~0.50
console.log(bsPutAssignmentProb(100, 100, 30/365, 0.30))   // expect ~0.49–0.51
// Deep OTM: stock 20% above strike → should be low
console.log(bsPutAssignmentProb(120, 100, 30/365, 0.30))   // expect < 0.10
// Null cases
console.log(bsPutAssignmentProb(0, 100, 30/365, 0.30))     // expect null
console.log(bsPutAssignmentProb(100, 100, 0, 0.30))        // expect null
console.log(bsPutAssignmentProb(100, 100, 30/365, 0))      // expect null
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/MarginDashboardPage.tsx
git commit -m "feat: add normalCDF, bsPutAssignmentProb, and color-coding helpers"
```

---

## Task 4: Frontend — update types, CSV parser, and `groupByExpiry`

**Files:**
- Modify: `frontend/src/pages/MarginDashboardPage.tsx`

This task adds the new fields to the `ShortPut` and `ExpiryGroup` interfaces, computes `gainPct` and default `weightedObligation` during CSV parse, and updates `groupByExpiry` to sum `weightedObligation`.

- [ ] **Step 1: Update the `ShortPut` interface**

Replace the existing `ShortPut` interface (lines 6–19) with:

```ts
interface ShortPut {
  symbol: string
  ticker: string
  expiry: Date
  expiryLabel: string
  strike: number
  qty: number
  obligation: number
  entryPremium: number
  closeValue: number
  pnl: number
  dte: number
  iv: string
  gainPct: number            // pnl / |entryPremium|, clamped 0–1; computed in parsePortfolioCSV
  stockPrice: number | null  // current price from backend; null until loaded
  rsi: number | null         // RSI-14 from backend; null until loaded
  assignmentProb: number | null  // BS put delta; null if stockPrice or IV unavailable
  weightedObligation: number     // obligation × (assignmentProb ?? 1); defaults to full obligation
}
```

- [ ] **Step 2: Update the `ExpiryGroup` interface**

Replace the existing `ExpiryGroup` interface (lines 27–33) with:

```ts
interface ExpiryGroup {
  label: string
  expiry: Date
  dte: number
  count: number
  obligation: number
  weightedObligation: number
}
```

- [ ] **Step 3: Add `MarketData` interface** (add after `ExpiryGroup`):

```ts
interface MarketData {
  price: number | null
  rsi: number | null
}
```

- [ ] **Step 4: Update `parsePortfolioCSV` to compute `gainPct` and default `weightedObligation`**

Inside `parsePortfolioCSV`, find the `shortPuts.push({...})` call. Add three lines before the push, and add the new fields to the object:

Before:
```ts
    shortPuts.push({
      symbol,
      ticker,
      expiry,
      expiryLabel,
      strike,
      qty,
      obligation: strike * absQty * 100,
      entryPremium: pricePaid * absQty * 100,
      closeValue: Math.abs(value),
      pnl: totalGain,
      dte: getDte(expiry),
      iv,
    })
```

After:
```ts
    const obligation = strike * absQty * 100
    const entryPremium = pricePaid * absQty * 100
    const absEntry = Math.abs(entryPremium)
    const gainPct = absEntry > 0 ? Math.min(Math.max(totalGain / absEntry, 0), 1) : 0

    shortPuts.push({
      symbol,
      ticker,
      expiry,
      expiryLabel,
      strike,
      qty,
      obligation,
      entryPremium,
      closeValue: Math.abs(value),
      pnl: totalGain,
      dte: getDte(expiry),
      iv,
      gainPct,
      stockPrice: null,
      rsi: null,
      assignmentProb: null,
      weightedObligation: obligation,   // conservative default: 100% risk until market data loads
    })
```

- [ ] **Step 5: Update `groupByExpiry` to accumulate `weightedObligation`**

Replace the existing `groupByExpiry` function with:

```ts
function groupByExpiry(positions: ShortPut[]): ExpiryGroup[] {
  const map = new Map<string, ExpiryGroup>()
  for (const p of positions) {
    if (!map.has(p.expiryLabel)) {
      map.set(p.expiryLabel, {
        label: p.expiryLabel,
        expiry: p.expiry,
        dte: p.dte,
        count: 0,
        obligation: 0,
        weightedObligation: 0,
      })
    }
    const g = map.get(p.expiryLabel)!
    g.count++
    g.obligation += p.obligation
    g.weightedObligation += p.weightedObligation
  }
  return Array.from(map.values()).sort((a, b) => a.dte - b.dte)
}
```

- [ ] **Step 6: Verify the file compiles**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

Expected: no TypeScript errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/MarginDashboardPage.tsx
git commit -m "feat: add gainPct and weightedObligation to ShortPut type and CSV parser"
```

---

## Task 5: Frontend — market data state, `fetchMarketData`, and `enrichedPuts`

**Files:**
- Modify: `frontend/src/pages/MarginDashboardPage.tsx`

- [ ] **Step 1: Add `useMemo` to the React import and add `API_URL` constant**

Change the top import line from:
```ts
import { useState, useCallback, useRef, type DragEvent, type ChangeEvent } from 'react'
```
to:
```ts
import { useState, useCallback, useMemo, useRef, type DragEvent, type ChangeEvent } from 'react'
```

Add this constant immediately after the import (before the interfaces):
```ts
const API_URL = 'http://localhost:3001'
```

- [ ] **Step 2: Add three new state variables inside `MarginDashboardPage`**

Add after the existing `const [dragOver, setDragOver] = useState(false)`:

```ts
  const [marketData, setMarketData] = useState<Record<string, MarketData>>({})
  const [marketLoading, setMarketLoading] = useState(false)
  const [marketError, setMarketError] = useState(false)
```

- [ ] **Step 3: Add `fetchMarketData` callback**

Add after the state declarations, before `loadFile`:

```ts
  const fetchMarketData = useCallback(async (tickers: string[]) => {
    setMarketLoading(true)
    setMarketError(false)
    try {
      const resp = await fetch(`${API_URL}/api/market/rsi`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tickers }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const raw: Record<string, { rsi: number | null; price: number | null } | null> = await resp.json()
      const out: Record<string, MarketData> = {}
      for (const [ticker, val] of Object.entries(raw)) {
        out[ticker] = { price: val?.price ?? null, rsi: val?.rsi ?? null }
      }
      setMarketData(out)
    } catch {
      setMarketError(true)
    } finally {
      setMarketLoading(false)
    }
  }, [])
```

- [ ] **Step 4: Update `loadFile` to call `fetchMarketData` and reset market state on new file**

Replace the existing `loadFile` with:

```ts
  const loadFile = useCallback((file: File) => {
    if (!file.name.toLowerCase().endsWith('.csv')) {
      alert('Please upload a .csv file exported from E*TRADE.')
      return
    }
    setFileName(file.name)
    setMarketData({})
    setMarketError(false)
    const reader = new FileReader()
    reader.onload = (e) => {
      const text = e.target?.result as string
      const data = parsePortfolioCSV(text)
      setParsed(data)
      const tickers = [...new Set(data.shortPuts.map(p => p.ticker))]
      if (tickers.length > 0) fetchMarketData(tickers)
    }
    reader.readAsText(file)
  }, [fetchMarketData])
```

- [ ] **Step 5: Add `enrichedPuts` memo**

Add this immediately after the `loadFile` definition (still before the `if (!parsed)` guard — hooks must come before any early return):

```ts
  const enrichedPuts = useMemo((): ShortPut[] => {
    return (parsed?.shortPuts ?? []).map(p => {
      const md = marketData[p.ticker]
      const stockPrice = md?.price ?? null
      const rsi = md?.rsi ?? null
      const ivDecimal = p.iv !== '--' ? parseFloat(p.iv) / 100 : null
      const T = p.dte / 365
      const prob = stockPrice !== null && ivDecimal !== null
        ? bsPutAssignmentProb(stockPrice, p.strike, T, ivDecimal)
        : null
      return {
        ...p,
        stockPrice,
        rsi,
        assignmentProb: prob,
        weightedObligation: p.obligation * (prob ?? 1),
      }
    })
  }, [parsed, marketData])
```

- [ ] **Step 6: Update the "Upload New File" button to also reset market state**

Find the onClick for the "Upload New File" button (currently `onClick={() => { setParsed(null); setFileName('') }}`). Replace it with:

```tsx
onClick={() => { setParsed(null); setFileName(''); setMarketData({}); setMarketError(false) }}
```

- [ ] **Step 7: Verify the file compiles**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

Expected: no TypeScript errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/MarginDashboardPage.tsx
git commit -m "feat: add market data fetch and enrichedPuts memo to margin dashboard"
```

---

## Task 6: Frontend — summary cards and loading/error banner

**Files:**
- Modify: `frontend/src/pages/MarginDashboardPage.tsx`

- [ ] **Step 1: Add weighted aggregate computed values in the dashboard section**

Find this block in the dashboard section (after `const expiryGroups = groupByExpiry(shortPuts)`):

```ts
  const expiryGroups = groupByExpiry(shortPuts)
```

Replace with:

```ts
  const expiryGroups = groupByExpiry(enrichedPuts)
  const totalWeightedObligation = enrichedPuts.reduce((s, p) => s + p.weightedObligation, 0)
  const adjustedCoverage = totalWeightedObligation > 0
    ? (liquidBuffer / totalWeightedObligation) * 100
    : 0
```

- [ ] **Step 2: Update the summary cards grid from 4 to 5 columns**

Change:
```tsx
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
```
To:
```tsx
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mb-6">
```

- [ ] **Step 3: Update the Liquid Coverage card to show adjusted coverage as sub-text**

Find the Liquid Coverage `SummaryCard`:
```tsx
        <SummaryCard
          label="Liquid Coverage"
          value={fmtPct(coveragePct)}
          sub={coveragePct >= 100 ? 'Sufficient liquid coverage' : 'Below 1:1 liquid coverage'}
          accentClass={coveragePct >= 100 ? 'border-t-green-500' : coveragePct >= 75 ? 'border-t-amber-500' : 'border-t-red-500'}
        />
```

Replace with:
```tsx
        <SummaryCard
          label="Liquid Coverage"
          value={fmtPct(coveragePct)}
          sub={marketLoading
            ? 'Adj. coverage: loading…'
            : `Adj. coverage: ${fmtPct(adjustedCoverage)}`}
          accentClass={coveragePct >= 100 ? 'border-t-green-500' : coveragePct >= 75 ? 'border-t-amber-500' : 'border-t-red-500'}
        />
```

- [ ] **Step 4: Add the fifth summary card after the Near-Term card**

Add after the Near-Term `SummaryCard` closing tag (still inside the grid div):

```tsx
        <SummaryCard
          label="Confidence-Adjusted Obligation"
          value={marketLoading ? '—' : fmt$(totalWeightedObligation)}
          sub={marketLoading
            ? 'Fetching market data…'
            : marketError
            ? 'Market data unavailable'
            : `${fmtPct(totalWeightedObligation > 0 ? (totalWeightedObligation / totalObligation) * 100 : 0)} of worst-case`}
          accentClass={marketLoading || marketError ? 'border-t-gray-300' : 'border-t-violet-500'}
        />
```

- [ ] **Step 5: Add the loading/error banner just below the header `<div>`**

Find the block that ends with `</div>` closing the header section (the flex row with the h1 and "Upload New File" button). Add the banner immediately after that closing `</div>`:

```tsx
      {/* Market data status banner */}
      {(marketLoading || marketError) && (
        <div className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm mb-4 ${
          marketLoading
            ? 'bg-gray-50 border border-gray-200 text-gray-500'
            : 'bg-amber-50 border border-amber-200 text-amber-700'
        }`}>
          {marketLoading
            ? <><span className="animate-spin">⏳</span> Fetching market data…</>
            : <><span>⚠️</span> Market data unavailable — probability columns not shown</>}
        </div>
      )}
```

- [ ] **Step 6: Verify the file compiles and the page renders correctly**

```bash
cd frontend && npm run dev
```

Load a CSV. Confirm:
- The summary row shows 5 cards
- The Confidence-Adjusted Obligation card shows "—" while loading, then a dollar value
- The Liquid Coverage card's sub-text shows "Adj. coverage: X%"
- The loading banner appears briefly after CSV upload, then disappears
- If backend is down: the amber "Market data unavailable" banner persists

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/MarginDashboardPage.tsx
git commit -m "feat: add confidence-adjusted obligation summary card and market data banner"
```

---

## Task 7: Frontend — position table new columns

**Files:**
- Modify: `frontend/src/pages/MarginDashboardPage.tsx`

- [ ] **Step 1: Add four column headers to the position table `<thead>`**

Find the position table header row. After the existing `<th>` for **IV**, add:

```tsx
                <th className="px-4 py-2.5 text-right font-medium">Gain %</th>
                <th className="px-4 py-2.5 text-center font-medium">RSI</th>
                <th className="px-4 py-2.5 text-right font-medium">Assign. Prob</th>
                <th className="px-4 py-2.5 text-right font-medium">Wtd. Obligation</th>
```

- [ ] **Step 2: Switch the position table `tbody` to iterate `enrichedPuts` instead of `shortPuts`**

Find:
```tsx
              {shortPuts.map((p, i) => (
```

Replace with:
```tsx
              {enrichedPuts.map((p, i) => (
```

- [ ] **Step 3: Add four data cells to each position row**

Find the closing of the last existing `<td>` in the position row (the IV cell):
```tsx
                  <td className="px-4 py-2.5 text-right text-gray-500">
                    {p.iv !== '--' ? p.iv + '%' : '—'}
                  </td>
```

After that `</td>`, add:

```tsx
                  <td className={`px-4 py-2.5 text-right ${gainClass(p.gainPct)}`}>
                    {fmtPct(p.gainPct * 100)}
                  </td>
                  <td className="px-4 py-2.5 text-center">
                    {p.rsi != null
                      ? <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${rsiPillClass(p.rsi)}`}>{p.rsi.toFixed(1)}</span>
                      : <span className="text-gray-300">—</span>}
                  </td>
                  <td className={`px-4 py-2.5 text-right ${p.assignmentProb != null ? probClass(p.assignmentProb) : 'text-gray-300'}`}>
                    {p.assignmentProb != null ? fmtPct(p.assignmentProb * 100) : '—'}
                  </td>
                  <td className="px-4 py-2.5 text-right font-medium text-gray-800">
                    {p.assignmentProb != null ? fmt$(p.weightedObligation) : '—'}
                  </td>
```

- [ ] **Step 4: Verify the file compiles and position table looks correct**

```bash
cd frontend && npm run dev
```

Load a CSV. Confirm:
- Position table has four new columns: Gain %, RSI, Assign. Prob, Wtd. Obligation
- While backend loads: Gain % shows immediately (from CSV), RSI/Assign. Prob/Wtd. Obligation show "—"
- After load: RSI shows colored pills, Assign. Prob shows green/amber/red %, Wtd. Obligation shows dollar amount
- For any position with IV = "--": Assign. Prob and Wtd. Obligation both show "—"

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/MarginDashboardPage.tsx
git commit -m "feat: add Gain%, RSI, assignment probability, and weighted obligation columns to position table"
```

---

## Task 8: Frontend — expiry breakdown table weighted obligation column

**Files:**
- Modify: `frontend/src/pages/MarginDashboardPage.tsx`

- [ ] **Step 1: Add Wtd. Obligation column header to the expiry table**

Find the expiry table `<thead>`. After the `% of Total` header, add:

```tsx
                <th className="px-4 py-2 text-right font-medium">Wtd. Obligation</th>
```

- [ ] **Step 2: Add Wtd. Obligation data cell to each expiry row**

Find the expiry row `<td>` for `% of Total`:
```tsx
                  <td className="px-4 py-2.5 text-right text-gray-500">
                    {fmtPct(totalObligation > 0 ? (g.obligation / totalObligation) * 100 : 0)}
                  </td>
```

After that `</td>`, add:
```tsx
                  <td className="px-4 py-2.5 text-right text-gray-600">
                    {marketLoading ? '—' : fmt$(g.weightedObligation)}
                  </td>
```

- [ ] **Step 3: Add Wtd. Obligation cell to the expiry table footer**

Find the `<tfoot>` row in the expiry table. After the `100%` total cell, add:
```tsx
                <td className="px-4 py-2.5 text-right text-gray-700">
                  {marketLoading ? '—' : fmt$(totalWeightedObligation)}
                </td>
```

- [ ] **Step 4: Final compile + full manual test**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

Expected: zero TypeScript errors.

Start dev server and run through the full flow:

```bash
cd frontend && npm run dev
```

Upload a real E*TRADE CSV export. Verify:

1. **Loading state**: Immediately after upload, the banner shows "⏳ Fetching market data…", the 5th summary card shows "—", position table probability columns show "—", expiry table Wtd. Obligation shows "—"

2. **Loaded state**: Banner disappears, 5th summary card shows a dollar amount (smaller than Total Assignment Obligation), Liquid Coverage card shows "Adj. coverage: X%"

3. **Position table**: Each row shows Gain % (colored), RSI pill (colored), Assign. Prob % (colored), Wtd. Obligation ($)

4. **Expiry table**: New column shows confidence-weighted obligation per expiry bucket; footer shows `totalWeightedObligation`

5. **Backend down**: Kill the backend, upload a CSV — amber banner appears, all probability columns show "—", raw obligations still display correctly

6. **Upload New File**: Click "Upload New File", upload a second CSV — market state resets, fresh fetch fires

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/MarginDashboardPage.tsx
git commit -m "feat: add weighted obligation column to expiry breakdown table"
```

---

## Self-Review

**Spec coverage check:**
- ✅ Backend extends `/api/market/rsi` to return `{rsi, price}` — Task 1
- ✅ Extension updated for new response shape — Task 2
- ✅ `normalCDF` + `bsPutAssignmentProb` pure functions — Task 3
- ✅ `gainPct` computed in CSV parser — Task 4
- ✅ `weightedObligation` defaults to full obligation — Task 4
- ✅ `MarketData` interface — Task 4
- ✅ `groupByExpiry` sums `weightedObligation` — Task 4
- ✅ `enrichedPuts` memo with `prob ?? 1` fallback — Task 5
- ✅ Market data fetch triggered on CSV load — Task 5
- ✅ Market state reset on "Upload New File" — Task 5
- ✅ 5th summary card (Confidence-Adjusted Obligation) — Task 6
- ✅ Liquid Coverage card shows adjusted coverage sub-text — Task 6
- ✅ Loading/error banner — Task 6
- ✅ Four new position table columns — Task 7
- ✅ Expiry table weighted obligation column — Task 8
- ✅ All edge cases: backend down, IV missing, DTE ≤ 0, gainPct > 1 — handled via `prob ?? 1` fallback and null guards

**Placeholder scan:** None found.

**Type consistency:**
- `ShortPut.weightedObligation: number` — set in Task 4 CSV parser, overwritten in Task 5 `enrichedPuts` memo ✅
- `groupByExpiry` receives `enrichedPuts` (Task 6) which always has `weightedObligation` set ✅
- `totalWeightedObligation` used in Task 6 (card), Task 7 (table) — both read from same `enrichedPuts.reduce(...)` ✅
- `rsiPillClass`, `gainClass`, `probClass` defined in Task 3, used in Task 7 ✅
