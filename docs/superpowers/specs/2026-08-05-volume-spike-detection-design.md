# Spec: Unusual Volume Spike Detection

**Date:** 2026-08-05
**Feature:** Technicals Capture (context/feature-technicals-capture.md)
**Status:** Approved, ready for implementation plan

## Problem

Trading volume is already fetched (as part of the daily OHLCV bars from Schwab) but never surfaced. A trader wants to know if a stock had an unusually high-volume day recently — often a sign of news, earnings, or institutional activity — without manually eyeballing a volume chart.

## Goal

1. Detect days in the recent past where daily volume was unusually high relative to its own recent baseline.
2. Expose the list of spike days (date, volume, baseline average, ratio) on `fetch_technicals` and via a standalone endpoint.

## Non-Goals

- No weekly volume spike detection — daily only, consistent with the RSI crossover work's scope decision.
- No frontend changes — backend/API only.
- No configurable thresholds via the API (lookback/baseline/multiplier are fixed constants for now, not query parameters) — YAGNI until there's a concrete need to tune them per-call.

## Design

### Spike detection algorithm

Given a daily volume series (from the same `df_d` daily price history `fetch_technicals` and the standalone endpoint already fetch — 1 year, `period_type="year", period=1, frequency_type="daily"`):

For each of the **last 10 trading days**, compare that day's volume to the **trailing 20-day average volume immediately preceding it** (the 20 days before that day, not including it — so the average isn't inflated by the spike itself). If `day_volume / baseline_avg >= 2.0`, it's a spike.

Validated against live AAPL data during brainstorming: one spike found — **2026-07-31, volume 132,489,137 vs a trailing 20-day baseline average of 50,812,793 (ratio 2.61)**.

Constants: `lookback_days = 10`, `baseline_days = 20`, `threshold_multiple = 2.0`. If there isn't enough history to compute a full 20-day baseline for a given day within the lookback window, that day is skipped (not flagged, not an error).

### Backend changes

**`backend/app/services/technicals_fetcher.py`**
- New function `_detect_volume_spikes(volume: pd.Series, lookback_days: int = 10, baseline_days: int = 20, threshold: float = 2.0) -> list[dict]`. For each day in the last `lookback_days` (in chronological order), if a full `baseline_days`-day trailing window exists before it, compute `avg_volume` and `ratio = round(day_volume / avg_volume, 2)`; include `{"date": "YYYY-MM-DD", "volume": int, "avg_volume": int, "ratio": float}` in the returned list when `ratio >= threshold`. Returns `[]` if no spikes found or insufficient history — never `None`, since "no spikes" is a normal, valid result, not an error state.
- `fetch_technicals()` currently only keeps `df_d["Close"]` (`close_d`) from the daily fetch — it needs the `Volume` column too. Add `volume_d = df_d["Volume"].dropna()` alongside the existing `close_d = df_d["Close"].dropna()`, and call `_detect_volume_spikes(volume_d)`, merging the result into the response as a new field `volume_spikes` (a list, unlike every other field in this response which is a scalar — the first non-scalar field in `fetch_technicals`, but the natural shape for "zero or more spike days").
- New public function `fetch_volume_spikes(ticker: str) -> dict` — standalone, daily-only, same error-handling shape as `fetch_rsi_signal`/`fetch_macd_crossover` (`SchwabAPIError` → `fetch_status: "error"` with `spikes: []`; empty daily data → `ValueError` → 404). Returns:
  ```json
  {"spikes": [{"date": "2026-07-31", "volume": 132489137, "avg_volume": 50812793, "ratio": 2.61}], "lookback_days": 10, "baseline_days": 20, "threshold_multiple": 2.0, "fetch_status": "ok", "fetch_error": null}
  ```

**`backend/app/routers/market.py`**
- New endpoint `GET /api/market/volume-spikes/{ticker}`, same thread-executor + `ValueError`→404 pattern as the other technicals endpoints.

## Testing

- Unit tests for `_detect_volume_spikes`: no spikes in a flat/steady volume series; a single clear spike detected with correct `ratio`; multiple spikes in the lookback window; insufficient history (fewer than `baseline_days + 1` bars total) returns `[]`; a spike exactly at the boundary (below vs at/above `threshold_multiple`) is classified correctly.
- `fetch_technicals` integration test: assert `volume_spikes` key is present and is a list.
- `fetch_volume_spikes` unit tests: success path (list present, could be empty or populated depending on mock data), `SchwabAPIError` → error status, empty data → `ValueError`.
- Router tests for `GET /api/market/volume-spikes/{ticker}`: success, 404, ticker uppercasing — same shape as the other technicals router tests.

## Open Questions

None — threshold, baseline, and lookback window were all settled during brainstorming and validated against live data.
