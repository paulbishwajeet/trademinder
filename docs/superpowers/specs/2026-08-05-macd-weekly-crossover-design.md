# Spec: Weekly MACD Crossover Detection + Strength Score

**Date:** 2026-08-05
**Feature:** Technicals Capture (context/feature-technicals-capture.md)
**Status:** Approved, ready for implementation plan

## Problem

`fetch_technicals(ticker)` (`backend/app/services/technicals_fetcher.py`) already computes a weekly MACD signal (`macd_signal`: bullish/bearish/neutral, based only on the *current* bar), but gives no sense of *when* the MACD line last crossed the signal line, in which direction, or how much conviction remains behind that crossover. A user wheeling a ticker wants to know at a glance: "we've been bullish for 14 weeks, but momentum is fading and a flip is close" vs. "we just crossed and the gap is still widening."

## Goal

1. Detect the most recent weekly MACD/signal crossover for a ticker: date and direction (bullish/bearish).
2. Compute a numeric strength score reflecting how much of the crossover's peak momentum remains, so declining scores signal an approaching reversal.
3. Expose this both as new fields on the existing `fetch_technicals` response and as a standalone endpoint for fetching just this data.

## Non-Goals

- No crossover history list (just the latest crossover) — decided during brainstorming to keep the response flat, matching the rest of `fetch_technicals`.
- No frontend changes — `TechnicalsPanel` and other UI are untouched. API/backend only for now.
- No change to lookback window handling beyond the existing 2-year weekly history already fetched (`period_type="year", period=2, frequency_type="weekly"`). If no crossover exists in that window, the new fields return `None` — this is an accepted limitation, not an error.
- No change to the existing `macd_signal`/`macd_notes` fields — they remain as-is; the new fields are additive.

## Computation Logic (validated against live AAPL data during brainstorming)

Given the weekly close series already used for the existing MACD calc (12/26 EMA → MACD line, 9-EMA of that → signal line):

1. `diff = macd_line - signal_line`
2. Find the most recent sign flip in `diff` (compare each value's sign to the previous bar's sign) → this is the last crossover. Its date and direction (`bullish` if diff flipped positive, `bearish` if negative) are `macd_cross_date` / `macd_cross_direction`.
3. `macd_weeks_since_cross` = number of weekly bars from the crossover bar (exclusive) to the latest bar.
4. Slice `diff` from the crossover date to the latest bar (`since`). `peak_gap` = `since.max()` for a bullish crossover, `since.min()` for bearish — the most extreme (strongest) value reached since the flip.
5. `strength_score = round(since.iloc[-1] / peak_gap * 100, 1)` — current gap magnitude as a percentage of peak gap magnitude reached since the crossover. A score near 100 means still near peak conviction; a score near 0 means the gap has nearly closed and a reversal may be imminent.
6. `macd_trend` label, derived from `strength_score` and whether the current bar *is* the peak:
   - `"expanding"` — current bar is the peak (score would be exactly 100, still climbing)
   - `"holding_strong"` — score ≥ 70
   - `"squeezing"` — 30 ≤ score < 70
   - `"fading_near_flip"` — score < 30

**Insufficient data:** if fewer than ~35 weekly bars are available (enough for a stable 26-EMA + 9-EMA signal) or no sign flip exists anywhere in the available weekly series, all five new fields are `None`. This is not an error — `fetch_status` stays `"ok"` for the rest of the response.

## Backend Changes

**`backend/app/services/technicals_fetcher.py`**
- New private function `_macd_weekly_crossover_state(close_w: pd.Series) -> dict` implementing the logic above. Returns a dict with keys `macd_cross_date` (str `YYYY-MM-DD` or `None`), `macd_cross_direction` (`"bullish"`/`"bearish"`/`None`), `macd_weeks_since_cross` (int or `None`), `macd_strength_score` (float or `None`), `macd_trend` (str or `None`).
- `fetch_technicals()` calls this helper using the `close_w` series it already fetches (no extra Schwab call) and merges the result into its returned dict.

**`backend/app/routers/market.py`**
- New endpoint `GET /api/market/macd-crossover/{ticker}`. Follows the same pattern as the existing `GET /api/market/technicals/{ticker}`: runs in a thread executor, fetches weekly history via `get_schwab_client().get_price_history(ticker, "year", 2, "weekly", 1)`, calls `_macd_weekly_crossover_state`, and returns the 5 fields plus `fetch_status`/`fetch_error`. 404 if no weekly data at all for the ticker; `fetch_status: "error"` (200 response) if data exists but is insufficient for MACD (matches existing error-shape convention in `fetch_technicals`).

**Not changed:** `RationaleCreate`/`RationaleResponse` in `backend/app/schemas/trade.py` and the `rationale` table. `GET /api/market/technicals/{ticker}` has no `response_model` today — it returns the raw dict from `fetch_technicals` directly, so the 5 new fields flow through automatically. Persisting them (via the rationale save flow) would need a schema change and DB migration, which is out of scope — this spec is compute/API only, matching the "backend only for now" decision from brainstorming.

## Testing

- Unit tests for `_macd_weekly_crossover_state` covering: normal bullish crossover with clear peak-then-squeeze pattern, bearish equivalent, insufficient history (< 35 bars) returns all `None`, and the edge case where the current bar is the new peak (`"expanding"`).
- Extend `backend/tests/test_market_technicals.py` with a case asserting the 5 new fields appear in the `/technicals/{ticker}` response.
- New test file (or extend the same) for `GET /api/market/macd-crossover/{ticker}`: happy path, 404 on no data, `fetch_status: "error"` on insufficient history.

## Open Questions

None outstanding — lookback window, response shape, and frontend scope were all settled during brainstorming.
