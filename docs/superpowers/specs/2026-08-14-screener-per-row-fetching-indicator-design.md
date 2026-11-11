# Spec: Per-Row "Fetching…" Indicator During Fetch All

**Date:** 2026-08-14
**Feature:** Screener page enhancement (builds on `docs/superpowers/specs/2026-08-10-screener-page-design.md` and the sort/filter follow-up)
**Status:** Approved, ready for implementation plan

## Problem

Clicking "Fetch All" on the Screener page runs a sequential background job that refetches every tracked symbol, but the grid gives no per-row feedback while it runs — each row's individual action-column button still says "Fetch" the entire time, even for a row the job has already reached (or is currently on). A user can't tell which rows are done, in progress, or not yet started without watching the page-level `Fetching N/M…` counter and guessing.

## Goal

1. While Fetch All is running, a row whose data the job hasn't refreshed yet shows "Fetching…" in place of "Fetch" in its action column, and that button is disabled.
2. As soon as the job actually updates that row's data, it reverts to the normal enabled "Fetch" button — automatically, without a page reload.
3. This uses the existing per-row button slot (already showing "Fetching…"/disabled when a user clicks that row's own Fetch button) — bulk-fetch-pending and individually-fetching look identical, not two different states.

## Non-Goals

- No backend changes — the fetch-all job already commits each row's `last_fetched_at` progressively as it processes symbols (built in the original Screener feature); this only needs the frontend to observe that more often.
- No exact "currently processing symbol X" precision — a row is inferred "pending" purely from whether its `last_fetched_at` has moved past the moment Fetch All was clicked, not from a live pointer into the job's iteration order. Close enough for a personal watchlist tool; exact tracking would require a backend field change, explicitly out of scope per the approved design discussion.
- No change to the Remove button, the commentary cell, or row expand/collapse — only the action-column Fetch button's label/disabled state is touched.
- No change to polling cadence for job status (`GET /api/screener/jobs/{job_id}` stays on its existing 2000ms interval) — the row-list refresh piggybacks on the same interval tick, not a separate timer.

## Design

### State: `ScreenerPage.tsx`

One new piece of state: `fetchAllStartedAt: string | null` (an ISO timestamp string, matching the format `last_fetched_at` already uses so they're directly comparable). Set to `new Date().toISOString()` at the top of `handleFetchAll`, right before the `POST /fetch-all` call. Cleared back to `null` when the job reaches `status === 'done'` (same place `jobProgress` is already cleared).

The existing poll `setInterval` callback (currently: poll job status, update `jobProgress`, and on `done` call `loadRows()` once) changes to *also* call `loadRows()` on every tick, not just the final one — so `rows` state refreshes every 2s while the job runs, picking up whichever rows the backend has committed so far. This is the single change that makes per-row progress observable at all; everything else is derived from it.

### Derivation: which rows are "pending"

No new per-row state is stored. Whether a row is "still pending in the bulk fetch" is computed inline wherever it's needed, from three already-available values: `fetchingAll` (existing page-level bool, renamed conceptually to "bulk fetch active" but the prop/state name stays `fetchingAll` — no gratuitous rename), `fetchAllStartedAt`, and the row's own `last_fetched_at`:

```
bulkPending = fetchingAll && fetchAllStartedAt != null &&
  (row.last_fetched_at == null || row.last_fetched_at <= fetchAllStartedAt)
```

(String comparison is safe here since both are ISO-8601 UTC timestamps, which sort lexicographically the same as chronologically — no `Date` parsing needed for the comparison itself, though the existing `timeAgo()` helper already parses `last_fetched_at` for display elsewhere in the same file.)

### Prop threading

`ScreenerPage` passes `fetchingAll` and `fetchAllStartedAt` down to `<ScreenerTable>` as two new props. `ScreenerTable` passes them through unchanged to each `<ScreenerRowView>`. `ScreenerRowView` combines `bulkPending` (derived as above) with its existing local `fetching` state (set only while *that row's own* Fetch button click is in flight) — the button shows "Fetching…" and is disabled if `fetching || bulkPending` is true, "Fetch" and enabled otherwise. This is a pure OR: whichever reason applies, the visual state is identical, satisfying Goal 3.

### Edge cases

- **A row fetched individually seconds before Fetch All is clicked:** its `last_fetched_at` could already be `<= fetchAllStartedAt`... no — `fetchAllStartedAt` is captured at click time, so any fetch that completed *before* the click has a `last_fetched_at` strictly less than `fetchAllStartedAt`, correctly marking it pending (accurate: the bulk job WILL still refetch it, since fetch-all always processes every tracked symbol regardless of recency). No special-casing needed.
- **Job fails entirely (network drop, `pollError` path already handled):** the existing `catch` block already clears `fetchingAll` on poll failure; once `fetchingAll` is false, `bulkPending` evaluates false for every row automatically (short-circuit on the first condition), so all rows revert to normal "Fetch" without any new code in the error path.
- **A per-symbol fetch error inside the job** (row ends up with `fetch_status: "error"`): the row's `last_fetched_at` still gets updated (the job sets it regardless of per-symbol success, per the existing `_run_fetch_all_job` implementation), so the row correctly flips out of "pending" even though its data shows an error state — consistent with "the job reached this row," which is what the indicator communicates.

## Testing

No test suite exists for the frontend in this repo (consistent with every other Screener frontend task) — verification is `tsc --noEmit -p tsconfig.app.json` plus manual browser verification: track 3+ symbols, click Fetch All, and confirm (a) all rows show "Fetching…" (disabled) immediately, (b) rows flip back to "Fetch" (enabled) one at a time as the job progresses — not all at once at the very end, (c) a row's own individual Fetch button (clicked outside of a bulk run) still shows "Fetching…" exactly as before, unaffected by this change, (d) after the job finishes, no row is stuck showing "Fetching…".

## Open Questions

None — the client-side, poll-derived approach and the disable-during-bulk-pending behavior were both explicitly settled during brainstorming.
