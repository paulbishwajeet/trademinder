# Margin Assignment Confidence Design

## Goal

Add a probability-of-assignment layer to the margin dashboard. Each short put gets a Black-Scholes-derived assignment probability; the UI shows a confidence-adjusted obligation total alongside the existing raw obligation, giving a realistic view of how much capital is actually at risk.

## Architecture

Pure client-side calculation after a single backend batch call. No new pages, no new routes in the router beyond extending an existing endpoint. All BS math lives in the frontend as pure TypeScript functions with no external dependencies.

**Data sources per position:**
| Field | Source |
|---|---|
| Strike, DTE, IV, entryPremium, pnl, obligation | CSV (already parsed) |
| Current stock price | Backend `/api/market/rsi` (extended) |
| RSI | Backend `/api/market/rsi` (already returned) |

---

## Backend Change

**File:** `backend/app/services/price_fetcher.py`

`_fetch_one_rsi` already downloads 45 days of history. Change the return tuple from `(ticker, rsi)` to `(ticker, {"rsi": rsi, "price": price})`, where `price = float(df["Close"].iloc[-1])` from the same download.

```python
# before
def _fetch_one_rsi(ticker: str) -> tuple[str, float | None]:
    ...
    return ticker, _compute_rsi_14(close)

# after
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

`fetch_rsi_batch` return type changes from `dict[str, float | None]` to `dict[str, dict | None]`.

**File:** `backend/app/routers/market.py`

Update the return type annotation on `get_rsi_batch`:
```python
@router.post("/rsi")
async def get_rsi_batch(payload: RsiRequest) -> dict[str, dict | None]:
```

**New response shape:**
```json
{
  "AAPL": { "rsi": 52.3, "price": 213.40 },
  "NVDA": { "rsi": 71.1, "price": 134.20 },
  "BADTICKER": null
}
```

---

## Extension Fix

**File:** `extension/content.js`, function `fetchRsiForAll`

The extension reads the RSI response as `data[ticker]` (a number). Update to read `data[ticker]?.rsi`:

```js
// before
Object.entries(data).forEach(([ticker, rsi]) => {
  rsiCache.set(ticker, typeof rsi === 'number' ? rsi : null);
});

// after
Object.entries(data).forEach(([ticker, val]) => {
  const rsi = val && typeof val === 'object' ? val.rsi : null;
  rsiCache.set(ticker, typeof rsi === 'number' ? rsi : null);
});
```

---

## Frontend: Math

**File:** `frontend/src/pages/MarginDashboardPage.tsx`

Two pure functions added at the top of the file (no imports needed):

```ts
/** Abramowitz & Stegun rational approximation — accurate to ~7 decimal places */
function normalCDF(x: number): number {
  const a1 =  0.254829592, a2 = -0.284496736, a3 =  1.421413741
  const a4 = -1.453152027, a5 =  1.061405429, p  =  0.3275911
  const sign = x < 0 ? -1 : 1
  const t = 1 / (1 + p * Math.abs(x) / Math.SQRT2)
  const poly = t * (a1 + t * (a2 + t * (a3 + t * (a4 + t * a5))))
  return 0.5 * (1 + sign * (1 - poly * Math.exp(-x * x / 2)))
}

/** Black-Scholes put delta (absolute value = probability of assignment).
 *  Returns null if any input is missing or invalid. */
function bsPutAssignmentProb(
  S: number,   // current stock price
  K: number,   // strike
  T: number,   // time to expiry in years (DTE / 365)
  sigma: number, // implied volatility as decimal (e.g. 0.35)
  r = 0.045    // risk-free rate
): number | null {
  if (!S || !K || T <= 0 || sigma <= 0) return null
  const d1 = (Math.log(S / K) + (r + sigma * sigma / 2) * T) / (sigma * Math.sqrt(T))
  return normalCDF(-d1)
}
```

---

## Frontend: Types & State

Updated `ShortPut` interface:
```ts
interface ShortPut {
  // ... existing fields unchanged ...
  gainPct: number           // pnl / |entryPremium|, clamped 0-1
  stockPrice: number | null // from backend, null until loaded
  rsi: number | null        // from backend, null until loaded
  assignmentProb: number | null  // bsPutAssignmentProb result, null if data missing
  weightedObligation: number     // obligation × (assignmentProb ?? 1) — falls back to full obligation
}
```

New `MarketData` interface:
```ts
interface MarketData {
  price: number | null
  rsi: number | null
}
```

New state in `MarginDashboardPage`:
```ts
const [marketData, setMarketData] = useState<Record<string, MarketData>>({})
const [marketLoading, setMarketLoading] = useState(false)
const [marketError, setMarketError] = useState(false)
```

`gainPct` is computed during CSV parse (no backend needed):
```ts
const absEntry = Math.abs(entryPremium)
const gainPct = absEntry > 0 ? Math.min(Math.max(pnl / absEntry, 0), 1) : 0
```

`assignmentProb` and `weightedObligation` are computed in a derived memo after market data loads:
```ts
const enrichedPuts: ShortPut[] = useMemo(() => {
  return shortPuts.map(p => {
    const md = marketData[p.ticker]
    const stockPrice = md?.price ?? null
    const rsi = md?.rsi ?? null
    const ivDecimal = p.iv !== '--' ? parseFloat(p.iv) / 100 : null
    const T = p.dte / 365
    const prob = stockPrice && ivDecimal
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
}, [shortPuts, marketData])
```

`prob ?? 1` means: if market data is unavailable, the position counts as 100% risk (conservative fallback — raw obligation).

---

## Frontend: Market Data Fetch

Triggered in the `reader.onload` callback after CSV parse completes. Uses the existing `/api/market/rsi` endpoint.

```ts
async function fetchMarketData(tickers: string[]) {
  setMarketLoading(true)
  setMarketError(false)
  try {
    const resp = await fetch(`${API_URL}/api/market/rsi`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tickers }),
    })
    if (!resp.ok) throw new Error()
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
}
```

`API_URL` = `'http://localhost:3001'` (same as the extension; can extract to a constant).

---

## Frontend: UI Changes

### Summary Cards

Fifth card added to the existing row (grid becomes `grid-cols-2 lg:grid-cols-5`):

```
┌─────────────────────┐
│ Confidence-Adjusted │
│ Obligation          │
│                     │
│  $XX,XXX            │
│  X% of raw          │
└─────────────────────┘
```

Accent color: `border-t-violet-500` when loaded, `border-t-gray-300` while loading.

The existing **Liquid Coverage** card adds a second line beneath the existing sub-text:
```
sub: "Sufficient liquid coverage"
sub2: "Adj. coverage: 340%" ← new, based on adjustedCoverage
```

Loading state: cards show `"—"` while `marketLoading` is true. Error state: cards show `"—"` with no error message (the table-level notice covers it).

### Loading / Error Notice

Small dismissible banner just below the header, visible only while `marketLoading` or `marketError` is true:

- Loading: `"Fetching market data…"` (gray, spinner icon)
- Error: `"Market data unavailable — probabilities not shown"` (amber, dismissible)

### Position Table

Four new columns appended after **IV**:

| Column | Content | Color coding |
|---|---|---|
| Gain % | `gainPct` as % | ≥ 70% green · 40–69% amber · < 40% red |
| RSI | Colored pill | < 30 green · 30–40 light green · 40–60 gray · 60–70 amber · > 70 red |
| Assign. Prob | `assignmentProb` as % | < 15% green · 15–35% amber · > 35% red |
| Wtd. Obligation | `weightedObligation` in dollars | same style as existing Obligation column |

While loading, all four columns show `"—"`. If IV is `"--"` for a position (prob cannot be computed), Assign. Prob shows `"—"`.

### Expiry Breakdown Table

New **Wtd. Obligation** column added after the existing **Obligation** column. Values are summed from `enrichedPuts` by expiry group. Footer total shows `totalWeightedObligation`.

---

## Computed Aggregates

```ts
const totalWeightedObligation = enrichedPuts.reduce((s, p) => s + p.weightedObligation, 0)
const adjustedCoverage = totalWeightedObligation > 0
  ? (liquidBuffer / totalWeightedObligation) * 100
  : 0
```

---

## Error / Edge Cases

| Scenario | Behaviour |
|---|---|
| Backend not running | `marketError = true`; all prob columns show `"—"`; raw obligations unaffected |
| Ticker not found by yfinance | `price: null` → prob `null` → falls back to full obligation (conservative) |
| IV missing (`"--"`) | BS cannot run → prob `null` → same fallback |
| DTE ≤ 0 (already expired) | `T ≤ 0` → `bsPutAssignmentProb` returns `null` → full obligation fallback |
| gainPct > 1 (data anomaly) | Clamped to 1 during parse; does not affect BS calc |
