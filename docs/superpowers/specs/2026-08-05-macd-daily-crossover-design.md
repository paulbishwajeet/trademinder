# Spec: Daily-Interval MACD Crossover Support

**Date:** 2026-08-05
**Feature:** Technicals Capture (context/feature-technicals-capture.md)
**Status:** Approved, ready for implementation plan

## Problem

`feature/macd-weekly-crossover` (not yet merged to `develop`) added weekly-only MACD crossover detection: last crossover date/direction and a strength score, as flat `macd_cross_*` fields on `fetch_technicals` and a matching standalone endpoint. A trader also wants the same signal on the daily timeframe — daily MACD reacts much faster than weekly and catches shorter-term reversals weekly would miss for weeks.

## Goal

1. Generalize the crossover-detection helper so it works for any bar interval (weekly or daily), not just weekly.
2. Add daily-interval crossover detection alongside the existing weekly one, in both `fetch_technicals` and the standalone endpoint.
3. Rename the weekly-only fields added in the prior (unmerged) branch to a `weekly_`-prefixed scheme, matching the new `daily_`-prefixed fields, before this ships.

## Non-Goals

- No other intervals (monthly, 4-hour, etc.) — daily and weekly only, per this and the prior spec.
- No frontend changes — still backend/API only.
- No change to the 2-year weekly lookback window (unchanged from the prior spec).
- No extra Schwab call for the daily side in `fetch_technicals` — it reuses the `close_d` series that function already fetches (1 year of daily bars) for RSI/MA200/Bollinger.

## Design

### 1. Generalized helper

Rename `_macd_weekly_crossover_state(close_w)` → `_macd_crossover_state(close: pd.Series) -> dict` in `backend/app/services/technicals_fetcher.py`. Same logic as before (12/26/9 EMA MACD, most recent sign flip, peak-since-crossover strength score, 35-bar minimum), but with periodicity-neutral key names:

- `cross_date` (str `YYYY-MM-DD` or `None`)
- `cross_direction` (`"bullish"`/`"bearish"`/`None`)
- `periods_since_cross` (int or `None`) — renamed from `weeks_since_cross`; represents bars of whatever interval was passed in (weeks or trading days)
- `strength_score` (float or `None`)
- `trend` (`"expanding"`/`"holding_strong"`/`"squeezing"`/`"fading_near_flip"`/`None`)

The 35-bar minimum and scoring math are periodicity-agnostic — no changes needed to the thresholds themselves, confirmed by running the logic against live daily Schwab data during brainstorming (AAPL: last daily crossover 2026-07-31, bearish, 2 days ago, strength score 100.0, "expanding").

### 2. `fetch_technicals` — merged with prefixes

`fetch_technicals` already computes both `close_d` (1yr daily) and `close_w` (2yr weekly). It now calls `_macd_crossover_state` on each and merges both results into the flat response, prefixed:

`macd_weekly_cross_date`, `macd_weekly_cross_direction`, `macd_weekly_periods_since_cross`, `macd_weekly_strength_score`, `macd_weekly_trend`, and the `macd_daily_*` equivalents. This replaces the unprefixed `macd_cross_*`/`macd_weeks_since_cross`/`macd_strength_score`/`macd_trend` fields from the prior branch (safe to rename — unmerged, unshipped, no consumers).

### 3. `fetch_macd_crossover(ticker)` — nested weekly/daily response

The standalone function now fetches **both** weekly (`period_type="year", period=2, frequency_type="weekly"`) and daily (`period_type="year", period=1, frequency_type="daily"`) history from Schwab — two calls, mirroring the pattern `fetch_technicals` already uses internally. Returns:

```json
{
  "weekly": {"cross_date": ..., "cross_direction": ..., "periods_since_cross": ..., "strength_score": ..., "trend": ...},
  "daily":  {"cross_date": ..., "cross_direction": ..., "periods_since_cross": ..., "strength_score": ..., "trend": ...},
  "fetch_status": "ok",
  "fetch_error": null
}
```

**Error handling:**
- If either the weekly or the daily history fetch returns empty data, raise `ValueError` (router turns this into a 404) — a real ticker should have both; if either is missing, treat it as "ticker not found" rather than partially degrading.
- If a `SchwabAPIError` occurs on either fetch, return `{"weekly": <all-None dict>, "daily": <all-None dict>, "fetch_status": "error", "fetch_error": str(exc)}`.
- Insufficient history for one or both intervals (fewer than 35 bars) is not an error — that interval's 5 fields come back `None` inside its sub-object, `fetch_status` stays `"ok"`.

### 4. Endpoint

`GET /api/market/macd-crossover/{ticker}` — same route, same thread-executor pattern, new nested response shape described above.

## Testing

- Unit tests for `_macd_crossover_state` (renamed from the weekly-specific tests, same coverage: insufficient data, bullish/bearish fading, squeezing, holding_strong, expanding) — the function itself doesn't know or care which interval it's given, so no new interval-specific unit tests are needed here beyond a sanity check that it works identically regardless of what bars are passed in.
- `fetch_technicals` integration test updated to assert both `macd_weekly_*` and `macd_daily_*` keys are present.
- `fetch_macd_crossover` tests updated/added: success returns both `weekly` and `daily` sub-objects; `SchwabAPIError` on either fetch returns the all-`None` error shape for both; empty weekly or empty daily data raises `ValueError`; insufficient history in one interval only nulls out that interval's sub-object.
- Router tests updated to the new nested mock shape.

## Open Questions

None — lookback windows, error handling, and field naming were all settled during brainstorming.
