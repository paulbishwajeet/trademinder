# Spec: Screener Table Sorting + Symbol Filter

**Date:** 2026-08-12
**Feature:** Screener page enhancement (builds on `docs/superpowers/specs/2026-08-10-screener-page-design.md`)
**Status:** Approved, ready for implementation plan

## Problem

The Screener grid (`frontend/src/components/Screener/ScreenerTable.tsx`) currently renders rows in whatever order `GET /api/screener` returns them (alphabetical by symbol, fixed). As the watchlist grows, a trader wants to reorder the grid by any column (e.g. sort by IV percentile to find the richest premium, or by change% to see today's movers) and to quickly narrow the grid to one or a few symbols by typing part of a ticker.

## Goal

1. Every data column header in `ScreenerTable` is clickable and sorts the grid by that column; clicking the active column again reverses direction.
2. A text input above the grid filters rows to those whose symbol contains the typed text (case-insensitive), live as the user types.
3. Both behaviors are purely client-side, operating on the rows already loaded into the page — no backend changes.

## Non-Goals

- No server-side sort/filter query params — the watchlist is small (a personal tool, not a paginated dataset), so client-side is sufficient and matches the existing "load everything on page mount" architecture.
- No multi-column sort — single active sort column only, matching the existing UI's simplicity elsewhere (no other table in this app has multi-sort).
- No filtering by sector/category/fetch-status — only symbol, per the explicit request. Can be added later if needed.
- No persistence of sort/filter state across page reloads (resets to unsorted/unfiltered on navigation away and back) — this is ephemeral view state, not a saved preference.
- No changes to `ScreenerDetailRow`, `ScreenerPage`, or any backend file.

## Design

### State

`ScreenerTable.tsx` gains three new pieces of local state (via `useState`), scoped entirely to that component — no prop changes to `ScreenerPage.tsx`, which continues to pass `rows`/`onRefreshRow`/`onRemove` unchanged:

- `sortKey: SortKey | null` — which column is active (`null` = insertion order, the current default).
- `sortDirection: 'asc' | 'desc'` — direction for the active column; irrelevant when `sortKey` is null.
- `filterText: string` — the current symbol-filter input value.

```typescript
type SortKey =
  | 'symbol' | 'price' | 'change_pct' | 'iv_percentile' | 'rsi_14'
  | 'macd_weekly_signal' | 'ma_20d' | 'ma_50d' | 'ma_100d' | 'ma_200d'
  | 'bollinger_position' | 'last_fetched_at'
```

Commentary and the trailing action column (Fetch/Remove buttons) are not sortable — they have no `SortKey` entry and their headers stay plain text.

### Filtering

Before sorting, rows are filtered: `rows.filter(r => r.symbol.toLowerCase().includes(filterText.trim().toLowerCase()))`. An empty `filterText` matches everything (no-op). This runs unconditionally, even when `filterText` is empty, to keep the data flow single-path (filter always runs, sort always runs, whether or not either has an effect).

### Sorting

A single comparator function drives all columns, dispatched by `sortKey`:

- **Numeric columns** (`price`, `change_pct`, `iv_percentile`, `rsi_14`, `ma_20d/50d/100d/200d`): parse both sides via the existing `toNum()` helper (already in `ScreenerTable.tsx` from the Decimal-as-string handling) before comparing.
- **String columns** (`symbol`, `macd_weekly_signal`, `bollinger_position`): plain locale-aware string comparison (`localeCompare`).
- **`last_fetched_at`**: compared as timestamps (`new Date(a).getTime()`), not the rendered "X ago" text — sorting must reflect actual recency, not string-format artifacts.
- **Null handling**: a row whose value for the active `sortKey` is `null` always sorts to the bottom of the list, regardless of `sortDirection` — a trader scanning "highest IV first" or "lowest IV first" doesn't want never-fetched rows interleaved either way, they want them out of the way at the end.

Sort is computed via `useMemo`, keyed on `[rows, filterText, sortKey, sortDirection]`, so it only recomputes when one of those actually changes — not on every render (e.g. not when a sibling row's local `expanded` state toggles, since that's independent per-row state in `ScreenerRowView`, not lifted to `ScreenerTable`).

### Header interaction

Each sortable header becomes a `<button>` (or the `<th>` itself gets an `onClick`) that:
- If clicking a new column: sets `sortKey` to that column, `sortDirection` to `'asc'`.
- If clicking the already-active column: flips `sortDirection` (`asc ↔ desc`).

An indicator (▲/▼, reusing the existing chevron-style Unicode characters already used for row-expand in this file) appears next to the active column's label, pointing in the current direction. Inactive sortable columns show no indicator (not even a faded one) — keeps the header row visually calm.

### Filter input placement

A single `<input type="text">` with a placeholder like "Filter by symbol…" rendered directly above the `<table>` in `ScreenerTable`'s return block (this component already renders the table's outer wrapper `<div>`, so no new file/component is needed — it's a small addition to existing JSX, not a new `FilterBar` component, per YAGNI). Styled consistent with existing Tailwind input patterns already used in `AddSymbolForm.tsx`/`SymbolLookup.tsx` (`border border-gray-300 rounded px-2 py-1 text-sm`).

### Empty-state interaction with the filter

The existing "No symbols tracked yet." empty-state message (shown when `rows.length === 0`) needs a second, distinct message for "rows exist, but none match the current filter" (`rows.length > 0 && filteredSortedRows.length === 0`) — e.g. "No symbols match "<filterText>"." — so a user isn't confused about whether their watchlist emptied out or their filter is just too narrow.

## Testing

No test suite exists for the frontend in this repo (consistent with every other frontend task in the original Screener build) — verification is via `tsc --noEmit -p tsconfig.app.json` (must show only the two pre-existing unrelated errors already on this branch) and manual browser verification: sort each column both directions and confirm correct ordering including null-handling, type a partial symbol and confirm live filtering, clear the filter and confirm all rows return, and confirm the two distinct empty-state messages appear at the right times.

## Open Questions

None — client-side scope, single-column sort, and symbol-only filter were all explicitly settled during brainstorming.
