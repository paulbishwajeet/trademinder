# Feature: Screener
**Status:** Implementation Complete — merged to `develop`, all three phases live
**Branch:** develop (built via short-lived feature branches, each merged and deleted: `feature/screener-page`, `feature/screener-sort-filter`, `feature/screener-fetching-indicator`)
**Created:** 2026-08-10

## Goal
A `/screener` page: a persisted watchlist of stock tickers with a compact technical-analysis grid (price, change%, IV percentile, RSI, weekly MACD, 20/50/100/200-day MAs color-coded vs. price, Bollinger position, last-fetched time, commentary), expandable per-row detail, on-demand and bulk (sequential background job) refresh, a symbol-lookup-preview-before-add flow alongside a direct-add form, and a per-symbol editable commentary thread.

## Scope
- In scope:
  - Backend: `screener` + `screener_commentary` Postgres tables, full CRUD router, background fetch-all job, Schwab-integration fetcher service reusing/extending existing technicals infrastructure
  - Frontend: grid with expand/collapse, two add flows (direct + preview-before-add), editable commentary dialog, column sorting, symbol filter, per-row "Fetching…" indicator during bulk fetch
- Out of scope (explicitly, per specs):
  - No scheduled/automatic background refresh — all fetches are user-triggered
  - No true IV Rank (only IV Percentile) — Schwab doesn't expose the historical IV data needed
  - No multi-column sort, no filtering by sector/category/status (symbol substring only)
  - No sort/filter state persistence across page reloads
  - No server-side sort/filter (client-side only, small personal watchlist)

## Key Files / Modules Involved

**Backend:**
- `backend/app/models/screener.py`, `backend/app/models/screener_commentary.py` — SQLAlchemy models
- `backend/alembic/versions/010_screener.py` — migration (both tables)
- `backend/app/schemas/screener.py` — Pydantic schemas, `ScreenerFetchedFields` is the single source of truth for the fetched-data field list, reused by both the router and the frontend's field enumeration
- `backend/app/services/screener_fetcher.py` — `fetch_screener_row(ticker, existing_sector=None)`, composes `fetch_technicals` + IV percentile + Schwab fundamentals sector lookup
- `backend/app/services/technicals_fetcher.py` — extended with `ma_20d`/`ma_100d`/`price_vs_ma20`/`price_vs_ma100`; also now hosts `compute_iv_percentile_from_chain` (relocated here from `cc_signal.py`, made public)
- `backend/app/services/cc_signal.py` — imports the relocated `compute_iv_percentile_from_chain` instead of defining it privately
- `backend/app/services/schwab_client.py` — new `get_instrument_fundamentals(ticker)` method
- `backend/app/routers/screener.py` — 13 endpoints: list/preview/add/fetch-one/delete/patch/fetch-all/job-status/commentary CRUD (4)

**Frontend:**
- `frontend/src/types/index.ts` — Screener types appended (`ScreenerRow`, `ScreenerFetchedFields`, `ScreenerPreview`, `ScreenerCommentary`, `ScreenerJobStatus`, `VolumeSpike`)
- `frontend/src/api/screener.ts` — `screenerApi` client
- `frontend/src/pages/ScreenerPage.tsx` — page orchestrator; owns row-list state, Fetch All job polling (2s interval), `fetchAllStartedAt` timestamp for per-row indicator derivation
- `frontend/src/components/Screener/ScreenerTable.tsx` — the grid: expand/collapse rows, column sort (click header, click again to reverse, nulls always sort last), symbol filter (case-insensitive substring), per-row bulk-fetch-pending derivation
- `frontend/src/components/Screener/ScreenerDetailRow.tsx`, `AddSymbolForm.tsx`, `SymbolLookup.tsx`, `ScreenerCommentaryCell.tsx`, `ScreenerCommentaryThread.tsx`, `timeAgo.ts`
- `frontend/src/App.tsx` — `/screener` route + nav item

**Specs/plans (chronological, one pair per phase):**
- `docs/superpowers/specs/2026-08-10-screener-page-design.md` + `docs/superpowers/plans/2026-08-10-screener-page.md` — original 15-task build
- `docs/superpowers/specs/2026-08-12-screener-sort-filter-design.md` + `docs/superpowers/plans/2026-08-12-screener-sort-filter.md` — sort/filter follow-up
- `docs/superpowers/specs/2026-08-14-screener-per-row-fetching-indicator-design.md` + `docs/superpowers/plans/2026-08-14-screener-per-row-fetching-indicator.md` — per-row fetching indicator follow-up

## Technical Approach
- All three phases built via subagent-driven development (fresh implementer + reviewer subagent per task, final whole-branch review before merge), each in its own short-lived worktree/branch off `develop`, merged and deleted immediately after.
- Backend fetch-all job: sequential (not parallel, to respect Schwab rate limits), in-memory job-status dict (`_jobs`), commits each row to the DB as it's processed (not batched at the end) — this progressive-commit behavior is what makes the frontend's per-row "Fetching…" indicator possible without any backend changes.
- **Critical, non-obvious backend fact discovered mid-build:** this repo's Pydantic schemas serialize `Decimal` fields as JSON **strings** (e.g. `"195.50"`), not numbers. All frontend Decimal-backed fields are typed `string | null` with explicit `parseFloat`/`toNum()` conversion at point of use — do NOT assume `number | null` here even though the older `Rationale`/`TechnicalsData` types elsewhere in the codebase are (incorrectly, but harmlessly, since nothing does arithmetic on them) typed as `number | null`.
- Frontend sort/filter: fully client-side (`useMemo` over the already-loaded `rows` array), no backend query params.
- Per-row fetching indicator: no backend changes — `ScreenerPage` records `fetchAllStartedAt` (ISO timestamp) at click time, and does a "quiet" row-list refresh (`refreshRowsQuiet`, does NOT toggle the page `loading` flag) on every 2s poll tick. Each row derives `bulkPending` by comparing its own `last_fetched_at` against `fetchAllStartedAt`; `isFetching = fetching || bulkPending` is the single source of truth for that row's Fetch button label/disabled state, so individually-clicked-fetch and bulk-fetch-pending are visually identical.

## Decisions Made
| Decision | Chosen | Reason |
|----------|--------|--------|
| IV Rank vs IV Percentile | Only IV Percentile populated, `iv_rank` column exists but stays `null` | Schwab doesn't expose historical IV needed for true IV Rank |
| Sector/category source | Best-effort auto-fetch from Schwab fundamentals endpoint, falls back to existing/manual value on failure | Schwab's fundamental payload's sector-field availability was uncertain going in; never let a failed lookup clobber a manually-set value |
| Commentary edit support | Full CRUD (add/edit/delete) with `updated_at` | User explicitly said "add new ones, edit old ones" — diverges from the trade-commentary pattern (add/delete only) |
| Symbol add flow | Both a direct "Add Symbol" form AND a separate "Quick Lookup" preview-before-add flow | User explicitly asked to keep both, not replace one with the other |
| Bulk fetch mechanism | Sequential `asyncio.create_task` + in-memory dict, no Celery/RQ | Personal single-user app; matches existing lightweight in-memory-cache patterns already in the codebase |
| Decimal JSON serialization | Frontend types Decimal-backed fields as `string \| null`, parses explicitly at use sites | Discovered empirically this repo's Pydantic setup serializes Decimal as JSON strings, not numbers — plan/spec were corrected mid-build once found |
| `next_earnings_date` persistence | Raw fetcher dict routed through `ScreenerFetchedFields(**raw).model_dump()` before ORM assignment, at all 3 persist call sites (`add_screener_symbol`, `fetch_screener_symbol`, `_run_fetch_all_job`) | Raw value is a string but the DB column is `Date`; asyncpg rejects the unconverted string |
| Fetch-all job testability | `_run_fetch_all_job` takes `session_factory` as an explicit parameter (default `AsyncSessionLocal`) instead of hardcoding the global | Initial version hardcoded the global, making it untestable through its real call path; fixed after task review flagged it as an Important finding |
| Sort null-handling | A row with `null` in the active sort column always sorts last, regardless of ascending/descending | User wants never-fetched rows out of the way at either end, not interleaved |
| Per-row fetch indicator mechanism | Poll the row list itself (`GET /api/screener`) every 2s alongside the existing job-status poll; infer "pending" per-row from `last_fetched_at` vs. a click-time timestamp | No backend change needed — approved over the alternative of adding a "currently processing symbol" field to the job status endpoint |
| Row-list refresh during bulk fetch | Separate `refreshRowsQuiet()` function that does NOT toggle the page's `loading` state | Reusing the existing `loadRows()` (which does toggle `loading`) would unmount/remount `ScreenerTable` every 2s during a bulk run, collapsing any expanded row and flickering the whole page — this was caught and fixed during plan-writing, before any code was written |

## Open Questions / Blockers
- None outstanding. All three phases shipped, reviewed clean, merged to `develop`.
- Deferred, non-blocking Minor findings from code review (not fixed, low priority, safe to leave):
  - `cc_signal.py` may still have latent lint-only cleanup opportunities unrelated to Screener (unrelated pre-existing errors: `WheelSlotCard.tsx` unused `ticker`, `WheelDashboardPage.tsx` unused `WheelSessionSummary` — both predate this feature, not introduced by it, present on `develop` at every checkpoint above)
  - Task 9's `updated_at`-on-edit test only checks the immediate PUT response, not a follow-up GET (adequate but not maximally rigorous coverage)
  - No test exercises `tags=None` overwrite semantics on commentary update, or the empty-symbol-list / delete-mid-job race edge cases in fetch-all (all low real-world risk for a single-user tool)

## Progress Log
- 2026-08-10 — Original Screener page spec approved and full 15-task implementation built via subagent-driven development (backend: models/migration/schemas/fetcher/router with fetch-all job/commentary CRUD; frontend: types/API client/table/add-flows/commentary/page+routing). Merged to `develop` at `5ca01ad`. Mid-build correction: discovered this repo serializes Decimal as JSON strings, not numbers — plan and all downstream frontend code updated before shipping.
- 2026-08-12 — Added clickable column sorting (all data columns except Commentary/actions, null-values-always-last) and a live case-insensitive symbol filter to the grid, fully client-side. Merged to `develop` at `a6d7e7a`.
- 2026-08-14 — Added a per-row "Fetching…" (disabled) indicator that shows while Fetch All is processing that row, reverting to "Fetch" automatically once the row's data refreshes — inferred client-side, no backend changes. Merged to `develop` at `845f573`.

## Current State (Resume Here)
All three Screener phases are implemented, reviewed, and merged into `develop`. Nothing is in-flight; no open branch, no open worktree, no pending review. `develop` is currently sitting one commit ahead of local with the `context/_active.md` update from this session, plus the routine pre-existing uncommitted `backend/uv.lock` diff (unrelated to this feature, been present across multiple sessions).

**Next action:** None required — the feature is done. If picking this up again, the natural next steps (not yet requested by the user, purely speculative) would be either (a) pushing `develop` to `origin` (it's currently ahead of `origin/develop` from this and prior sessions' local merges — verify with `git status` / `git log origin/develop..develop`), or (b) starting a new Screener enhancement following the same brainstorm → spec → plan → subagent-driven-build → finish-branch cycle used for all three phases so far.

To verify the feature is still working: start both dev servers (`cd backend && venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 5431 --reload` and `cd frontend && npm run dev`) and navigate to `http://localhost:5430/screener` — grid should load, Fetch All should show per-row "Fetching…" progressively, sort/filter should work on the header/input.
