# Spec: RSI/RSI-MA Crossover Detection + Exact RSI-14

**Date:** 2026-08-05
**Feature:** Technicals Capture (context/feature-technicals-capture.md)
**Status:** Approved, ready for implementation plan

## Problem

`fetch_technicals` already returns the exact daily RSI-14 value (`rsi_14`) and a threshold-based label (`rsi_result`: oversold/overbought/None). It has no sense of RSI *momentum* — a trader wants to know whether RSI is trending up or down relative to its own recent behavior, similar to how the MACD crossover work (see `context/feature-technicals-capture.md`, MACD crossover specs from 2026-08-05) surfaces when the MACD line last crossed its signal line and how much conviction remains.

## Goal

1. Track RSI-14 against a 14-period moving average of RSI itself (the "RSI-MA" line) — the RSI equivalent of MACD's line-vs-signal relationship.
2. Detect the most recent crossover between RSI and RSI-MA: date, direction (bullish/bearish), and a strength score reflecting how much of the post-crossover peak momentum remains — same peak-based scoring approach as the MACD crossover work.
3. Continue to surface the exact current RSI-14 value alongside this crossover state.
4. Expose this as new fields on `fetch_technicals` and via a standalone endpoint, daily interval only.

## Non-Goals

- **No refactor of `_macd_crossover_state`.** Per explicit direction, the RSI crossover logic is implemented as its own independent, self-contained function (`_rsi_crossover_state`) rather than extracting a shared helper. Some duplication of the sign-flip/peak/strength-score/trend logic between `_macd_crossover_state` and `_rsi_crossover_state` is accepted.
- No weekly interval — RSI crossover is daily-only, per decision during brainstorming (RSI is conventionally read on daily bars; weekly adds complexity not asked for here).
- No frontend changes — backend/API only, consistent with the MACD crossover work.
- No change to the existing `rsi_14`/`rsi_result` fields already in `fetch_technicals` — these are unchanged; the new fields are additive.

## Design

### RSI-MA line and crossover detection

Given the daily close series `close_d` (already fetched by `fetch_technicals`, or fetched fresh by the standalone endpoint):

1. Compute the full RSI-14 series (not just the latest value) using the same Wilder's-smoothing math as the existing `_compute_rsi_14` in `price_fetcher.py`, but keeping every bar's RSI instead of only the last one:
   - `delta = close.diff()`, `gain = delta.clip(lower=0)`, `loss = (-delta).clip(lower=0)`
   - `avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()`, same for `avg_loss`
   - `rs = avg_gain / avg_loss` (with `avg_loss == 0` handled as RSI = 100)
   - `rsi = 100 - (100 / (1 + rs))`
2. `rsi_ma = rsi.rolling(14).mean()` — 14-period SMA of the RSI series itself.
3. `diff = (rsi - rsi_ma).dropna()` — drop the leading `NaN`s from the rolling window warm-up.
4. Same crossover algorithm as MACD (independently implemented, not shared): find the most recent sign flip in `diff`, compute `periods_since_cross`, find the peak `diff` magnitude since that crossover, and `strength_score = round(current / peak * 100, 1)`. Same `trend` labels: `expanding` / `holding_strong` (≥70) / `squeezing` (30–69) / `fading_near_flip` (<30). Same 35-bar minimum on the `diff` series before attempting detection — below that, all crossover fields are `None`.

Validated against live AAPL data during brainstorming: RSI-14 = 44.68 (matches the value `fetch_technicals` already returns — confirms the full-series computation agrees with the existing single-value one), RSI-MA-14 = 60.73, last crossover 2026-07-30 bearish, 3 days ago, strength score 72.6 ("holding_strong").

### Backend changes

**`backend/app/services/technicals_fetcher.py`**
- New function `_rsi_crossover_state(close: pd.Series) -> dict`, fully self-contained (does not call or share code with `_macd_crossover_state`). Returns `cross_date`, `cross_direction`, `periods_since_cross`, `strength_score`, `trend` (`None` if fewer than 35 valid `diff` bars), plus `rsi_14` (latest RSI value, rounded to 2dp) and `rsi_ma_14` (latest RSI-MA value, rounded to 2dp) computed as part of the same pass.
- `fetch_technicals()` calls `_rsi_crossover_state(close_d)` (reusing the `close_d` series it already fetches — no extra Schwab call) and merges `rsi_ma_14`, `rsi_cross_date`, `rsi_cross_direction`, `rsi_periods_since_cross`, `rsi_strength_score`, `rsi_trend` into its flat response. (`rsi_14` is already a top-level field from the existing `_compute_rsi_14` call — unchanged, not duplicated.)
- New public function `fetch_rsi_signal(ticker: str) -> dict` — standalone, daily-only (`period_type="year", period=1, frequency_type="daily"`), mirrors `fetch_macd_crossover`'s error handling: `SchwabAPIError` → `fetch_status: "error"` with all crossover fields `None`; empty daily data → raises `ValueError` (404 at the router). Returns a **flat** shape (no weekly/daily nesting needed since this is daily-only):
  ```json
  {"rsi_14": 44.68, "rsi_ma_14": 60.73, "cross_date": "2026-07-30", "cross_direction": "bearish", "periods_since_cross": 3, "strength_score": 72.6, "trend": "holding_strong", "fetch_status": "ok", "fetch_error": null}
  ```

**`backend/app/routers/market.py`**
- New endpoint `GET /api/market/rsi-crossover/{ticker}`, same thread-executor + `ValueError`→404 pattern as `macd-crossover`.

## Testing

- Unit tests for `_rsi_crossover_state`: insufficient data (<35 valid diff bars) → all `None` fields but `rsi_14`/`rsi_ma_14` still computed if available; bullish/bearish crossover with peak-then-squeeze pattern (same synthetic-series technique as the MACD tests); `holding_strong`/`squeezing`/`expanding` trend branches.
- `fetch_technicals` integration test: assert the 6 new `rsi_*` fields are present alongside the existing `rsi_14`/`rsi_result`.
- `fetch_rsi_signal` unit tests: success path, `SchwabAPIError` → error status, empty data → `ValueError`, insufficient history → `ok` with `None` crossover fields but a real `rsi_14` if enough bars exist for RSI itself even without enough for the crossover.
- Router tests for `GET /api/market/rsi-crossover/{ticker}`: success, 404, ticker uppercasing — same shape as the `macd-crossover` router tests.

## Open Questions

None — interval scope, MA period, and the no-refactor decision were all settled during brainstorming.
