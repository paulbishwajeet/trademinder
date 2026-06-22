# CC Sell Signal — Design Spec

## Goal

Add a quantitative + AI-enhanced "CC Sell Signal" to the WHEEL dashboard that tells the user how favorable current conditions are for selling a covered call on each ticker. Displayed as a color-coded score badge on every slot row, with an expandable factor breakdown and LLM-generated trader commentary.

## Architecture

A new backend service computes a 0-100 score from 8 weighted factors (technicals + IV percentile), then passes the result to Gemini 2.5 Flash for a 1-2 sentence "trader's take." The score, factor breakdown, and commentary are cached in-memory for 4 hours per ticker. The frontend fetches on-demand per ticker when the dashboard loads.

## Endpoint

`GET /api/market/cc-signal/{ticker}`

Returns cached result if available (4hr TTL), otherwise computes fresh.

### Response Shape

```json
{
  "ticker": "NVDA",
  "score": 78,
  "grade": "strong",
  "iv_percentile": 72,
  "atm_iv": 0.42,
  "spot_price": 142.50,
  "factors": [
    { "name": "IV Percentile", "points": 20, "max": 25, "detail": "72nd percentile (52-week)" },
    { "name": "RSI Overbought", "points": 12, "max": 15, "detail": "RSI 71.3" },
    { "name": "Bollinger Position", "points": 12, "max": 15, "detail": "Near upper band" },
    { "name": "MACD Bullish", "points": 10, "max": 10, "detail": "Bullish, above 0 line" },
    { "name": "Green Day", "points": 5, "max": 5, "detail": "+1.2%" },
    { "name": "Price > 50MA", "points": 10, "max": 10, "detail": "$142.50 vs $131.20" },
    { "name": "Earnings Distance", "points": 7, "max": 10, "detail": "18 days to earnings" },
    { "name": "Momentum Exhaustion", "points": 5, "max": 10, "detail": "RSI > 65 but slope flat" }
  ],
  "commentary": "NVDA is extended after a 3-week run with IV in the 72nd pct — rich premium. RSI starting to roll over. Sell into strength.",
  "strike_hint": "Consider 5-10% OTM given elevated IV",
  "caution": "Earnings in 18 days — if selling monthlies, the CC will span the event",
  "cached_at": "2026-06-22T14:30:00Z",
  "fetch_status": "ok",
  "fetch_error": null
}
```

## Scoring Algorithm

### Factors (100 total points)

**1. IV Percentile (25 pts)**
- Fetch the nearest option expiration with 30-45 DTE (or closest to 30 if none in range)
- Find the ATM call option (strike closest to spot price)
- Extract its `impliedVolatility` → this is the current ATM IV
- Compute 30-day historical volatility (HV30) from daily closes, rolling over the past 252 trading days
- IV percentile = percentage of past 252 HV30 values that are below the current ATM IV
- Scoring: `>= 80 → 25`, `>= 60 → 20`, `>= 50 → 15`, `>= 40 → 10`, `>= 30 → 5`, `< 30 → 0`

**2. RSI Overbought (15 pts)**
- Use RSI-14 from daily closes (already computed by `fetch_technicals`)
- Scoring: `>= 75 → 15`, `>= 70 → 12`, `>= 65 → 8`, `>= 60 → 4`, `< 60 → 0`

**3. Bollinger Position (15 pts)**
- Use 20-day Bollinger band position (already computed by `fetch_technicals`)
- Scoring: `above_upper → 15`, `near_upper → 12`, `mid → 5`, `near_lower → 0`, `below_lower → 0`

**4. MACD Bullish (10 pts)**
- Use weekly MACD signal (already computed by `fetch_technicals`)
- Scoring: `bullish → 10`, `neutral → 5`, `bearish → 0`

**5. Green Day (5 pts)**
- Use day color (already computed by `fetch_technicals`)
- Scoring: `green → 5`, `red → 0`

**6. Price > 50MA (10 pts)**
- Use price vs 50-day MA (already computed by `fetch_technicals`)
- Scoring: `above → 10`, `below → 0`

**7. Earnings Distance (10 pts)**
- Use next earnings date (already fetched by `fetch_technicals`)
- Days until earnings: `> 21 → 10`, `> 14 → 7`, `> 7 → 3`, `<= 7 → 0`
- No earnings date found → 10 (assume safe)

**8. Momentum Exhaustion (10 pts)**
- Compute RSI-14 for each of the last 5 trading days from the daily close series
- If any of the last 5 RSI values was > 65 AND the current RSI is lower than the 5-day-ago RSI (negative slope): `10`
- If any of the last 5 RSI values was > 65 but slope is flat/positive: `5`
- Otherwise: `0`

### IV Override Rule

If the IV Percentile factor scores >= 20 points (IV pct >= 60th percentile), the grade thresholds shift down by 10 points. Premium is rich enough that a less-than-perfect technical setup is still worth selling into.

### Grade Thresholds

| Grade | Default Threshold | With IV Override (IV pts >= 20) |
|-------|------------------|---------------------------------|
| **Strong** | score >= 70 | score >= 60 |
| **Moderate** | score >= 50 | score >= 40 |
| **Weak** | score >= 30 | score >= 20 |
| **Wait** | score < 30 | score < 20 |

## IV Percentile Computation

**Data source:** yfinance

**Steps:**
1. `yf.download(ticker, period="1y", interval="1d")` → daily closes (already fetched for technicals — reuse)
2. Compute rolling 30-day HV: `std(log_returns, window=30) * sqrt(252)` for each day over the past year
3. This gives ~222 HV30 data points
4. `yf.Ticker(ticker).options` → find expiration closest to 30-45 DTE
5. `yf.Ticker(ticker).option_chain(expiration)` → find call with strike closest to spot → `impliedVolatility`
6. IV percentile = `(count of HV30 values < ATM IV) / total HV30 values * 100`

**Fallback:** If option chain fetch fails (ticker has no options, yfinance error), IV percentile = `None`, IV factor scores 0, and the score is computed from the remaining 75 points (normalized: `score * 100/75` to keep 0-100 scale).

## LLM Commentary (Gemini 2.5 Flash)

**SDK:** `google-genai` Python package
**API Key:** `GEMINI_API_KEY` environment variable
**Model:** `gemini-2.5-flash`

**When called:** After the quantitative score is computed, before caching.

**System prompt:**
```
You are a senior options trader reviewing technical data for covered call selling opportunities. Given the scoring factors and raw technicals for a ticker, provide:
1. "commentary" — 1-2 sentences explaining the setup in plain trader language. Be direct and opinionated. Reference specific numbers.
2. "strike_hint" — One sentence suggesting strike selection approach based on IV and technical picture. If conditions are poor, say "Wait for a better setup."
3. "caution" — One sentence warning if there's a risk factor (earnings proximity, bearish divergence, etc.), or null if no concerns.

Respond in JSON format with keys: commentary, strike_hint, caution.
Do not include any explanation outside the JSON.
```

**User prompt:** The full factor scores, raw technicals snapshot (RSI, MACD, Bollinger values, MAs, price, earnings date), IV percentile, ATM IV, and spot price.

**Timeout:** 5 seconds. If Gemini fails or times out, return null for all three commentary fields. The quantitative score always returns regardless.

**Cost:** ~19 Gemini Flash calls per 4 hours at most. Negligible.

## Caching

- In-memory Python dict: `_cc_signal_cache: dict[str, tuple[dict, float]]` — key is ticker, value is `(result, timestamp_epoch)`
- TTL: 4 hours (14400 seconds)
- Cache is per-process (resets on backend restart) — acceptable for a personal tool
- No database persistence needed

## Backend Service Structure

**New file:** `backend/app/services/cc_signal.py`

Contains:
- `compute_cc_signal(ticker: str) -> dict` — orchestrates the full flow
- `_compute_iv_percentile(daily_closes: pd.Series, ticker: str) -> tuple[float|None, float|None]` — returns (iv_percentile, atm_iv)
- `_score_factors(technicals: dict, iv_percentile: float|None, atm_iv: float|None, daily_closes: pd.Series) -> tuple[int, str, list[dict]]` — returns (score, grade, factors)
- `_get_llm_commentary(ticker: str, score: int, grade: str, factors: list, technicals: dict, iv_percentile: float|None, spot: float) -> dict` — calls Gemini, returns {commentary, strike_hint, caution}
- `_cc_signal_cache` — module-level cache dict

**Router addition:** New route in `backend/app/routers/market.py`:
```python
@router.get("/cc-signal/{ticker}")
async def get_cc_signal(ticker: str): ...
```

## Frontend Display

### Dashboard Table Row (compact)

Each row in all four sections gets a signal badge after the premium column:

```
NVDA  1x100  Awaiting CC  $150 exp 07/18  R1  $3.50  [Strong 78]
```

Badge colors:
- **Strong:** green background (`bg-green-100 text-green-800`)
- **Moderate:** amber background (`bg-amber-100 text-amber-800`)
- **Weak:** gray background (`bg-gray-100 text-gray-600`)
- **Wait:** no badge shown (or faint "Wait" in light gray)
- **Loading:** spinner while fetching

### Expanded Detail (on badge click)

A popover or inline expansion showing:
- Factor breakdown: each factor as a row with name, points/max, and detail text
- LLM commentary (if available)
- Strike hint (if available)
- Caution warning (if available, highlighted in amber)
- "Last updated: {cached_at}" timestamp

### Fetch Behavior

- On dashboard mount, fire `GET /api/market/cc-signal/{ticker}` for each unique ticker across all slots
- Deduplicate: if NVDA has 3 slots, fetch once, show same badge on all 3
- Fetch in parallel (all tickers at once)
- Show spinner per row while loading
- On error: show "—" with tooltip "Signal unavailable"

## Future: Sold Put Signal

The same architecture supports `GET /api/market/put-signal/{ticker}` with inverted factor scoring:
- RSI oversold (< 35) instead of overbought
- Bollinger near/below lower band instead of upper
- Bearish MACD as favorable (stock pulled back = good put entry)
- Momentum exhaustion inverted (RSI was < 35, now rising)

The endpoint parameter approach (`?strategy=cc` vs `?strategy=put`) is also viable but separate endpoints are cleaner.

## Dependencies

- `google-genai` — added to backend Python dependencies
- `GEMINI_API_KEY` — environment variable (already added by user)
- No new database tables or migrations
- No changes to existing endpoints
