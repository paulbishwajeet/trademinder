# Spec: Screener Page

**Date:** 2026-08-10
**Feature:** New — Screener (watchlist-style stock screener)
**Status:** Approved, ready for implementation plan

## Problem

Trader wants a persistent watchlist of tickers with a compact, at-a-glance technical snapshot per symbol (price, IV rank, RSI, MACD, moving averages, Bollinger position), plus a running commentary thread per symbol — separate from the trade-centric Commentary already attached to `trades`. Currently there's no way to track "symbols I'm watching but haven't traded yet" with persisted technicals that survive between sessions.

## Goal

1. A `/screener` page with a grid of watched symbols, each row showing: Symbol, Price, Change%, IV Rank/Percentile, RSI(d), MACD(w), 20ma/50ma/100ma/200ma (color-coded vs price), Bollinger position, "fetched X ago", and a commentary entry point.
2. Rows are backed by a new `screener` DB table — populated by an explicit fetch action, not live on every page load. Page load reads persisted data instantly.
3. Add new symbols to the watchlist, either directly (symbol + category → instant add+fetch) or via a lookup-first flow (punch in a symbol, click Fetch to preview its data, then decide whether to add it).
4. Fetch technicals for one symbol on demand, or all symbols at once (sequential background job with progress polling).
5. Expandable rows reveal a fuller technical breakdown (Bollinger bands, MACD daily+weekly crossover trend, RSI trend, next earnings, volume spikes).
6. Per-symbol commentary thread with add/edit/delete (a new `screener_commentary` table, many-to-one to `screener`).

## Non-Goals

- No automatic/scheduled background refresh (e.g. APScheduler cron) — all fetches are user-triggered. Can be added later.
- No sector/category as a hard-required field — best-effort auto-fetch from Schwab, manually editable, can be null.
- No alerting/threshold rules tied to screener rows (that's the existing `alert_engine` for trades — out of scope here).
- No sparkline charts or historical price charts in v1.
- No CSV import/bulk-add — one symbol at a time via the add form.

## Design

### Data model

**`backend/app/models/screener.py`** — new table `screener`:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `symbol` | String, unique, not null | uppercased on write |
| `sector` | String, nullable | best-effort from Schwab, manually editable |
| `category` | String, nullable | user-defined free text (e.g. "Wheel Candidate", "Watchlist") |
| `price` | Numeric, nullable | |
| `prev_close` | Numeric, nullable | |
| `change_pct` | Numeric, nullable | |
| `iv_rank` | Numeric, nullable | reserved; Schwab doesn't give this directly, see IV section below |
| `iv_percentile` | Numeric, nullable | from `_compute_iv_percentile_from_chain` |
| `rsi_14` | Numeric, nullable | |
| `macd_weekly_signal` | String, nullable | `bullish`/`neutral`/`bearish` |
| `macd_daily_signal` | String, nullable | for expanded view |
| `ma_20d` | Numeric, nullable | |
| `ma_50d` | Numeric, nullable | |
| `ma_100d` | Numeric, nullable | |
| `ma_200d` | Numeric, nullable | |
| `bollinger_upper` | Numeric, nullable | |
| `bollinger_mid` | Numeric, nullable | |
| `bollinger_lower` | Numeric, nullable | |
| `bollinger_position` | String, nullable | `above_upper`/`near_upper`/`mid`/`near_lower`/`below_lower` (reuse `_bollinger_position` labels) |
| `next_earnings_date` | Date, nullable | |
| `volume_spikes` | JSON, nullable | list of `{date, volume, avg_volume, ratio}` |
| `last_fetched_at` | DateTime(tz), nullable | drives "fetched X ago"; null = never fetched |
| `fetch_status` | String, nullable | `ok`/`error` |
| `fetch_error` | Text, nullable | |
| `created_at` | DateTime(tz), server default now | |

**`backend/app/models/screener_commentary.py`** — new table `screener_commentary`, many-to-one to `screener`:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `screener_id` | UUID, FK → `screener.id` ON DELETE CASCADE | |
| `note` | Text, not null | |
| `tags` | ARRAY(String), nullable | mirrors `commentary.tags` |
| `created_at` | DateTime(tz), server default now | |
| `updated_at` | DateTime(tz), nullable | set on edit; null until first edit |

This mirrors `commentary.py`'s structure but adds `updated_at` since screener commentary supports editing (trade commentary currently doesn't).

**Migration:** new Alembic revision creating both tables, `idx_screener_symbol` unique index, `idx_screener_commentary_screener` index on `screener_commentary.screener_id`.

### Backend: shared technicals extension

**`backend/app/services/technicals_fetcher.py`**
- Add `ma_20d` and `ma_100d` computation alongside the existing `ma_50d`/`ma_200d` (same `close_d.rolling(N).mean()` pattern), and `price_vs_ma20`/`price_vs_ma100` alongside the existing `price_vs_ma50`/`price_vs_ma200`. Included in `fetch_technicals()`'s return dict. This benefits trade rationale too (already has a UI slot for arbitrary technicals fields).

### Backend: IV percentile de-duplication

`_compute_iv_percentile_from_chain` currently lives in `cc_signal.py` as a "private" (underscore-prefixed) function. Move it to `technicals_fetcher.py` as a public `compute_iv_percentile_from_chain` (drop the underscore), and update `cc_signal.py` to import it from there instead of defining it locally. No behavior change — pure relocation so the screener fetcher can use the same logic without duplicating it or importing a private name cross-module.

### Backend: screener fetcher

**`backend/app/services/screener_fetcher.py`** — new file, `fetch_screener_row(ticker: str) -> dict`:

1. Call `fetch_technicals(ticker, return_closes=True)` → technicals dict + `close_d` series. If `fetch_status == "error"`, return `{"fetch_status": "error", "fetch_error": ...}` immediately (matches existing error-propagation pattern).
2. Call `client.get_quotes([ticker])` for live price/prev close/change% (same as `_compute_combined_fresh` does in `cc_signal.py`).
3. Call `client.get_option_chain(ticker, contract_type="CALL", strike_count=30)` and `compute_iv_percentile_from_chain(close_d, chain, ticker)` for `iv_percentile`. `iv_rank` stays `None` for now (Schwab's chain response doesn't directly provide a 52-week IV rank the way some other data vendors do — flagged as an open question below, not blocking).
4. Best-effort sector/category: attempt `GET /marketdata/v1/instruments?symbol={ticker}&projection=fundamental` via a new `SchwabClient.get_fundamentals(ticker)` method. If the response has no sector-like field (Schwab's fundamental payload is uncertain to include GICS sector — needs live verification during implementation), leave `sector` as whatever was already stored (don't overwrite a manually-entered value with `None`).
5. Assemble and return the full row dict matching the `screener` table columns (mapping `fetch_technicals`' field names to the table's, e.g. `bollinger_upper` ← `bollinger_upper`, `macd_weekly_signal` ← `macd_signal`, `macd_daily_signal` ← derived from `macd_daily_cross_direction`/existing daily crossover state).

Error handling: any `SchwabAPIError` or exception → `{"fetch_status": "error", "fetch_error": str(exc)}`, consistent with the rest of the fetcher module.

### Backend: router

**`backend/app/routers/screener.py`** — new router, `prefix="/api/screener"`:

- `GET /api/screener` → list all rows from DB, ordered by `symbol`. Pure read, no external calls.
- `GET /api/screener/preview/{ticker}` → read-only lookup, does **not** write to the DB. Runs `fetch_screener_row(ticker)` via thread executor and returns the same field shape as `ScreenerRowResponse` minus `id`/`created_at`, plus `already_tracked: bool` (true if a row for that symbol already exists, so the UI can warn instead of silently allowing a duplicate). Powers the "punch in a symbol → Fetch → review → Add" flow described below. No 404 on missing history — same error shape as other fetch endpoints (`fetch_status: "error"`), since the user is actively probing an arbitrary ticker and a hard error response is worse UX than an inline error state.
- `POST /api/screener` (body: `{symbol, category?, precomputed?}`) → uppercase symbol, reject if already exists (409). Two modes:
  - **Direct add** (`precomputed` omitted): create row, run `fetch_screener_row` synchronously via thread executor (single-ticker fetch, a few seconds), persist result including `last_fetched_at = now()`, return the row. If the fetch itself errors, the row is still created with `fetch_status="error"` (user sees the symbol added but can retry fetch).
  - **Commit from preview** (`precomputed` provided, shaped like the `GET /preview` response): skip re-fetching entirely — persist the already-fetched field values directly with `last_fetched_at = now()`. Avoids a redundant round of Schwab calls when the user already previewed the data seconds earlier.
- `POST /api/screener/{symbol}/fetch` → re-run `fetch_screener_row` for one existing row, update it, return it. 404 if symbol not tracked.
- `POST /api/screener/fetch-all` → for every tracked symbol, spawn an in-memory sequential background job (see below), return `{"job_id": ...}`.
- `GET /api/screener/jobs/{job_id}` → `{"status": "running"|"done", "total": N, "completed": N, "errors": [{"symbol": ..., "error": ...}]}`. 404 for unknown job_id.
- `DELETE /api/screener/{symbol}` → remove row (cascades to commentary). 404 if not found.
- `PATCH /api/screener/{symbol}` (body: `{category?, sector?}`) → manual edit of the two free-text fields (covers the case where auto-fetched sector is wrong/missing).
- `GET /api/screener/{symbol}/commentary` → list, ordered `created_at DESC`.
- `POST /api/screener/{symbol}/commentary` (body: `{note, tags?}`) → create.
- `PUT /api/screener/commentary/{id}` (body: `{note, tags?}`) → update `note`/`tags`, set `updated_at = now()`.
- `DELETE /api/screener/commentary/{id}` → delete.

**Background job mechanics:** module-level `_screener_jobs: dict[str, dict]` (same pattern as `commentary.py`'s `_summary_cache` in-memory dict — single-user local app, no need for a real task queue). `POST /fetch-all` creates a `job_id = uuid4()`, seeds `_screener_jobs[job_id] = {"status": "running", "total": N, "completed": 0, "errors": []}`, and starts an `asyncio.create_task` that loops through symbols **sequentially** (not parallel — avoids hammering Schwab's rate limits, consistent with why IV percentile fetching is already the slow path), calling `fetch_screener_row` via thread executor for each, updating the job dict's `completed` count and `errors` list as it goes, and persisting each row's result to the DB as soon as that ticker finishes (so a page refresh mid-job shows partial progress). Sets `status: "done"` when finished. No job persistence across server restarts — acceptable since this is a manually-triggered, short-lived (~seconds-to-low-minutes for a realistic watchlist size) operation.

### Backend: schemas

**`backend/app/schemas/screener.py`** — new file: `ScreenerRowCreate` (`symbol`, `category?`, `precomputed: ScreenerPreviewData?`), `ScreenerRowResponse` (full table shape), `ScreenerPreviewData` (same fields as `ScreenerRowResponse` minus `id`/`created_at`, used both as the `GET /preview` response shape — with `already_tracked` added — and as the `precomputed` input shape on `POST /api/screener`), `ScreenerRowPatch` (sector/category only), `ScreenerCommentaryCreate`, `ScreenerCommentaryUpdate`, `ScreenerCommentaryResponse`, `ScreenerJobStatus`.

### Frontend

**Route:** `/screener` added to `App.tsx` routes and nav (`<NavItem to="/screener" label="Screener" />`).

**`frontend/src/pages/ScreenerPage.tsx`** — loads `GET /api/screener` on mount, renders `AddSymbolForm` + `ScreenerTable`. Holds `fetchAll` state (job polling) and a `refresh()` callback passed down.

**`frontend/src/components/Screener/ScreenerTable.tsx`** — one `<tr>` per row plus a conditional detail `<tr>` when expanded (same two-row expand pattern used elsewhere via local `expanded` state per row, chevron rotate like `WheelSlotCard.tsx`). Columns: Symbol, Price, Change%, IV Rank/Pctl, RSI(d), MACD(w) (badge colored by signal), 20/50/100/200ma (each cell red if `price < ma`, green if `price >= ma`, dash if ma is null), BB (text label), fetched-time-ago (computed client-side from `last_fetched_at` via a small `timeAgo()` helper — "5 mins ago" / "2 hours ago" / "1 day ago" / "3 days ago"), Commentary (opens `ScreenerCommentaryCell`), and a per-row "Fetch" button + a "Fetch All" button in the table header.

**`frontend/src/components/Screener/ScreenerDetailRow.tsx`** — expanded content: Bollinger upper/mid/lower values, MACD daily + weekly crossover trend/strength (`macd_daily_*`/`macd_weekly_*` fields already computed by `fetch_technicals`), RSI trend, next earnings date, volume spike list (date/ratio).

**`frontend/src/components/Screener/AddSymbolForm.tsx`** — ticker input (+ optional category text input) → `POST /api/screener` (direct-add mode, no `precomputed`), shows inline loading state during the synchronous fetch, appends result to the table on success, surfaces `fetch_status: "error"` inline without blocking the add.

**`frontend/src/components/Screener/SymbolLookup.tsx`** — separate "quick lookup" section on the page, alongside `AddSymbolForm`: a symbol input + **Fetch** button calling `GET /api/screener/preview/{ticker}`. While loading, shows a spinner; on success, renders a preview card using the same column layout/labels as the main grid row (price, change%, IV pctl, RSI, MACD, MAs, BB, etc.) plus an **Add to Screener** button. If `already_tracked` is true, the button is replaced with a disabled "Already tracked" state (or relabeled to jump to that row) instead of allowing a duplicate. Clicking **Add to Screener** calls `POST /api/screener` with `{symbol, precomputed: <the previewed data>}` — committing without re-fetching — then appends/updates the row in the grid and clears the lookup form. This is independent of `AddSymbolForm`; both write through the same `POST /api/screener` endpoint, just with different payload shapes.

**`frontend/src/components/Screener/ScreenerCommentaryCell.tsx`** — same Radix `Dialog` pattern as `CommentaryCell.tsx`, backed by a new `ScreenerCommentaryThread.tsx` (adapted from `CommentaryThread.tsx`) that additionally supports inline edit (click note → textarea + Save/Cancel) since screener commentary is editable, unlike trade commentary.

**`frontend/src/api/screener.ts`** — typed wrappers: `list()`, `preview(ticker)`, `add()`, `fetchOne(symbol)`, `fetchAll()`, `getJobStatus(jobId)`, `remove(symbol)`, `patch(symbol, {sector?, category?})`, `commentary.{list,add,update,remove}`.

**`frontend/src/types/index.ts`** — add `ScreenerRow`, `ScreenerPreviewData` (extends the row shape with `already_tracked`), `ScreenerCommentary`, `ScreenerJobStatus` types matching the backend schemas.

**Fetch-all polling:** `ScreenerPage` calls `fetchAll()` → gets `job_id` → polls `getJobStatus(job_id)` every 2s until `status: "done"`, showing a progress indicator (`completed/total`), then calls `list()` again to refresh the grid with final data. Simple `setInterval`/`useEffect` polling, no websockets — consistent with the rest of the app having no real-time infrastructure.

## Testing

- Backend unit tests for `screener_fetcher.fetch_screener_row`: success path (mocked Schwab client), `SchwabAPIError` propagation, `fetch_technicals` error short-circuit.
- Backend unit tests for the relocated `compute_iv_percentile_from_chain` (moved, not changed — existing `cc_signal` tests covering it should still pass unmodified against the new import path).
- Router tests for `screener.py`: add symbol direct-mode (success + duplicate 409), add symbol via `precomputed` (asserts `fetch_screener_row` is NOT called again), preview endpoint (success shape incl. `already_tracked` true/false), get/list, fetch one (success + 404), fetch-all job lifecycle (status transitions running→done, completed count increments), delete, patch sector/category, commentary CRUD (including edit setting `updated_at`).
- Migration test: upgrade/downgrade round-trip for the two new tables.
- Frontend: manual verification via dev server — add a symbol via `AddSymbolForm`, confirm row populates; use `SymbolLookup` to preview a ticker, confirm preview card renders, click Add to Screener, confirm it appears in the grid without a second fetch delay; preview an already-tracked symbol, confirm `already_tracked` state shows; expand a row, confirm detail fields render; trigger fetch-all with 2-3 symbols, confirm progress polling and final refresh; add/edit/delete a commentary entry.

## Open Questions

- **Does Schwab's `/instruments?projection=fundamental` response actually include a sector/industry field?** Needs verification against a live API call during implementation. If it doesn't, `sector` simply stays manually-entered-only (the `PATCH` endpoint still covers that) and the auto-fetch attempt becomes a no-op — not a blocking issue either way.
- **`iv_rank` vs `iv_percentile`:** only `iv_percentile` (computed from historical volatility distribution, same method as `cc_signal`) is populated in v1. True IV Rank (current IV vs 52-week high/low IV) would need Schwab to expose historical IV data, which it doesn't appear to via the endpoints already in use. The column exists in the schema for future use but stays `null`.
