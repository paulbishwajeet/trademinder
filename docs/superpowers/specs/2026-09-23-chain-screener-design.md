# Chain Screener ("Chain" page) — Design

**Date:** 2026-09-23
**Branch:** develop
**Status:** Approved, ready for planning

## Goal

A new "Chain" page that screens an options chain for tradeable strike/expiry candidates against a chosen strategy, starting with **Selling Short Puts**. Replaces manual spot-checking (as done live in this session for NVDA and BE) with a repeatable, tunable, visually scannable tool — and is deep-linkable so other pages can eventually jump straight into a pre-filled screen.

## Scope

**In scope (v1):**
- New `/chain` page: symbol input, strategy dropdown (5 options — only "Selling Short Puts" implemented, other 4 visible but disabled), adjustable thresholds, results grouped by expiry.
- New backend endpoint that pulls N Friday expiries via Schwab, scores every strike near the target delta on 5 weighted criteria, returns the top N candidates per expiry (never empty — always ranks what's available).
- Page-level context: spot price, existing SP Timing Signal (grade + score, reused as-is), IV Percentile (reused as-is).
- Earnings-date awareness: flag any expiry whose window contains an earnings date (reusing the existing yfinance-based fetcher).
- Deep-link receiving side: `?symbol=&strategy=` (and optionally the threshold params) populate and auto-run on load, mirroring the existing Scanner page's `useSearchParams` pattern.

**Out of scope (v1, explicitly deferred):**
- The other 4 strategies (Sell Calls, Buy 6-12mo Calls, Buy 12-24mo Calls, Sell 3-6mo Puts) — dropdown entries exist and are disabled, no logic.
- Any deep-link *source* wiring (e.g., a clickable ticker on the Wheels dashboard that lands here) — only the receiving side is built now.
- Non-earnings market events (dividends, macro calendar, etc.) — no such data source exists in the codebase today.
- Automated/scheduled screening, alerts, or persistence of past screens — this is a live, on-demand tool, nothing is saved.

## Architecture

```
ChainPage.tsx (new)
  │  useSearchParams() reads ?symbol=&strategy=... on mount (matches ScannerPage.tsx pattern)
  │  Symbol input + strategy dropdown + Advanced thresholds + Fetch button
  ▼
api/chain.ts (new)
  │  GET /api/chain/{ticker}?strategy=sell_put&...
  ▼
routers/chain.py (new)
  │  strategy dispatch — only "sell_put" implemented, else 400
  ▼
services/chain_screener.py (new)
  ├──▶ schwab_client.get_option_chain(ticker, "PUT", from_date, to_date)
  ├──▶ schwab_client.get_price_history(...)  → technicals_fetcher.compute_iv_percentile_from_chain (reused, unchanged)
  ├──▶ sp_timing_signal.compute_sp_timing_signal(ticker)  (reused, unchanged)
  └──▶ options_scanner._fetch_earnings_dates(ticker)  (reused, unchanged)
```

No existing file is modified except a new router being mounted in `main.py` and a new nav entry in `App.tsx`. Everything else is additive.

## Scoring

Per candidate strike, 5 weighted criteria (100 pts total), same `{name, points, max, detail}` shape as `CCSignalFactor` (existing type, reused on the frontend). Curves are piecewise/continuous, not flat cutoffs — consistent with how `cc_timing_signal.py`/`sp_timing_signal.py` already score RSI/MACD, avoiding an arbitrary cliff at the threshold edge.

| Criterion | Max | Formula | Notes |
|---|---|---|---|
| Delta fit | 25 | `25 × max(0, 1 − dist / (tolerance × 1.5))` where `dist = abs(abs(delta) − target_delta)` | Full points at exact target, tapers to 0 at 1.5× the tolerance band |
| ARR | 25 | `min(25, 25 × arr_pct / min_arr_pct)` | Full points *at* the minimum, partial credit below it (no cliff — this is exactly what the NVDA run needed: 22.6% ARR should score ~20/25, not 0) |
| Volume | 15 | `min(15, 15 × volume / min_volume)` | |
| Open Interest | 15 | `min(15, 15 × oi / min_oi)` | |
| Spread tightness | 20 | `20` if `spread_pct ≤ 0.05`, else `max(0, 20 × (1 − (spread_pct − 0.05) / 0.25))` | `spread_pct = (ask − bid) / mid` |

**Candidate gathering:** for each target expiry, every strike with `abs(delta)` inside `[target_delta − tolerance×1.5, target_delta + tolerance×1.5]` is scored; the top `candidates_per_expiry` by total score are kept, sorted descending. If zero strikes fall in that band (e.g. a very short DTE with sparse deltas), the expiry renders an explicit "no strikes in target delta band" message — never a silent/blank box.

**Page-level context (not scored per-candidate):** SP Timing Signal (badge, click-to-expand factor breakdown — reuse the existing render pattern from `WheelDashboardPage.tsx`, adapted locally, not extracted into a shared component yet — YAGNI), IV Percentile (single number, ticker-level), spot price.

**Informational fields per candidate (not scored):** breakeven price (`strike − last`), downside cushion (`(spot − breakeven) / spot`), capital required (`strike × 100`).

**Earnings awareness:** each expiry block checks `options_scanner._fetch_earnings_dates(ticker)` for any date falling between today and that expiry's date; if found, shows a warning badge with the earnings date. Fetch failure degrades gracefully (badge omitted, not a page error) — matches the `fetch_status` degrade pattern used everywhere else in this codebase.

## API

```
GET /api/chain/{ticker}
  ?strategy=sell_put              (required; anything else → 400 "not yet implemented")
  &num_expiries=3                 (default 3 — number of Friday expiries to pull)
  &candidates_per_expiry=3        (default 3)
  &target_delta=0.2               (default 0.2)
  &delta_tolerance=0.1            (default 0.1)
  &min_arr_pct=30                 (default 30)
  &min_volume=200                 (default 200)
  &min_oi=500                     (default 500)
```

Response:
```jsonc
{
  "ticker": "NVDA",
  "spot": 224.85,
  "strategy": "sell_put",
  "sp_timing_signal": { "grade": "moderate", "score": 62, "factors": [...] } | null,
  "iv_percentile": 41.2 | null,
  "fetched_at": "2026-09-23T14:00:00Z",
  "expiries": [
    {
      "expiration_date": "2026-10-02",
      "dte": 9,
      "day_of_week": "Friday",
      "earnings_in_window": false,
      "earnings_date": null,
      "candidates": [
        {
          "strike": 220.0, "delta": -0.319, "last": 2.32, "bid": 2.30, "ask": 2.32,
          "spread_pct": 0.009, "volume": 3751, "open_interest": 11689,
          "arr_pct": 42.8, "breakeven": 217.68, "downside_cushion_pct": 3.19,
          "capital_required": 22000.0, "score": 87.4,
          "factors": [ { "name": "Delta Fit", "points": 5.2, "max": 25, "detail": "Δ -0.319 vs target 0.20" }, ... ]
        }
      ]
    }
  ]
}
```

## Frontend

- New nav item "Chain" → `/chain`, placed after "Screener" in `App.tsx`.
- Layout mirrors the Wheels dashboard's visual language (one bordered box per expiry, colored status header, pill-based highlights) so it feels native to the app rather than a bolted-on tool.
- Symbol input + strategy `<select>` (5 options, `disabled` on the 4 unimplemented ones with a "(coming soon)" suffix) + a collapsible "Advanced" section exposing all 7 threshold params as inputs, pre-filled with the defaults above.
- `useSearchParams()` reads `?symbol=` and `?strategy=` (and, if present, any of the threshold params) on mount; if `symbol` is present, auto-fires the fetch — identical mechanism to `ScannerPage.tsx`.
- Each expiry box: header (date, DTE, day-of-week, earnings badge if applicable), then one card/row per candidate showing strike, delta, bid/ask + spread%, volume, OI, ARR%, breakeven + cushion, capital required, and a compact row of 5 pass/fail pills (green ≥ 70% of max points, amber 40-70%, red < 40% — avoids a binary pass/fail that would hide the "how close" signal that mattered for NVDA) plus the total score. The top-scored candidate in each expiry box gets a distinct highlight (border/background), not just a numeric rank.
- Page-level strip above the expiry boxes: spot price, SP Timing Signal badge (click-to-expand), IV Percentile.

## Error Handling

- Unknown/invalid ticker or Schwab chain failure → inline error message on the page (same `ApiError` → message-string pattern already used for commentary/note failures), not a crash.
- Fewer than `num_expiries` Friday expiries available in the near-term chain → render only what's found, with a note.
- Earnings-date fetch failure → omit the badge silently (matches existing degrade-gracefully conventions), never fails the whole request.
- IV Percentile / SP Timing Signal fetch failure → omit that page-level field (`null`), rest of the response still returns.
- Zero candidates in an expiry's delta band → explicit "no strikes in target delta band" message for that expiry box, not blank/missing.

## Testing

- Backend: pure unit tests for the 5 scoring formulas (synthetic inputs, assert point values at boundary conditions — 0, threshold, 1.5×threshold), a unit test for Friday-expiry selection from a synthetic `putExpDateMap`, and one mocked live-compute test for the full endpoint (pattern matches `test_cc_timing_signal.py`).
- Frontend: `tsc --noEmit` + `eslint`, then live manual verification in a real browser against NVDA and BE (same tickers already spot-checked this session) to confirm the results match today's manual spike output.
