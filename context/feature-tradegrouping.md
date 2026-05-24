# Feature: Trade Grouping
**Status:** Implementation Complete — branch ready to push
**Branch:** frontend-groupby
**Created:** 2026-05-23

## Goal
Replace the flat trade table on the Trades page with a grouped view that organises trades by category (WHEEL, LEAP, HOLD, etc.). Each category is a collapsible section. Status filter buttons and sort controls work in tandem with the grouping. Group order is drag-and-drop reorderable and persists in localStorage.

## Scope
- In scope:
  - New `GroupedTradeTable` component replacing `TradeTable` in `TradesPage`
  - Client-side grouping, filtering (default: open), and sorting (Ticker, Expiry)
  - Collapsible group sections (expanded by default)
  - Accent-bar group headers with status breakdown (e.g. "3 open · 1 closed")
  - Drag-to-reorder groups via ⠿ handle; order saved to localStorage
  - Empty group state when filter removes all trades from a group
  - Extract `CATEGORY_COLORS` / `CATEGORY_ORDER` to shared `categories.ts`
- Out of scope:
  - Backend changes
  - Per-group sort (sort is global)
  - Syncing group order across devices
  - Row-level drag-and-drop within a group

## Key Files / Modules Involved
- `frontend/src/pages/TradesPage.tsx` — default filter `'open'`, fetch all trades (no status param), uses `GroupedTradeTable`
- `frontend/src/components/Trades/GroupedTradeTable.tsx` — **new** main component: grouping, filtering, sort, collapse, drag-to-reorder, localStorage
- `frontend/src/components/Trades/categories.ts` — **new** shared `CATEGORY_COLORS` and `CATEGORY_ORDER`
- `frontend/src/components/Trades/TradeTable.tsx` — updated to import `CATEGORY_COLORS` from `categories.ts`; otherwise unchanged and intentionally kept

## Technical Approach
- Always fetch all trades (no server-side status filter); grouping/filtering/sorting done client-side
- `GroupedTradeTable` holds all state: `collapsed` (Set), `sortKey`, `sortDir`, `groupOrder` (from localStorage)
- HTML5 drag-and-drop API for group reordering; `localStorage` key: `trademinder_group_order`
- Groups rendered for every key in `CATEGORY_ORDER` (not just categories with trades) to keep empty groups visible

## Decisions Made
| Decision | Chosen | Reason |
|----------|--------|--------|
| Filtering approach | Client-side, always fetch all | Enables empty groups; small dataset makes this trivial |
| Group order persistence | localStorage | Personal single-user app; zero backend work |
| Default status filter | `open` | User's primary use case is tracking active positions |
| Group header style | Accent-bar (left color border + faint gradient) | Best visual scan at a glance |
| Header info | Status breakdown (3 open · 1 closed) | More useful than count-only or P&L at the group level |
| Sortable columns | Ticker (alpha) and Expiry (date) | The two most useful sort axes for options traders |
| `dragSrcRef` as `useRef` | `useRef<string \| null>` instead of `useState` | Drag source doesn't need to trigger re-renders |
| `onDragOver` on header `<tr>` not `<tbody>` | Attached to header row | `tbody` rect spans all trade rows; header row gives accurate above/below midpoint |
| `handleDragLeave` checks `relatedTarget` | Only clear `dragOver` when leaving `<tbody>` entirely | Prevents drop-indicator flicker on internal child boundary crossings |
| `SortIcon` as top-level component | Defined above `GroupedTradeTable` with explicit props | Nested component definition causes React to remount on every render |

## Open Questions / Blockers
- [ ] None — all implementation complete, TypeScript clean, reviewed and approved

## Progress Log
- 2026-05-23 — Feature created; design spec written and approved; spec at `docs/superpowers/specs/2026-05-23-trade-grouping-design.md`
- 2026-05-24 — Full implementation complete via subagent-driven development (5 tasks, 7 commits). All tasks passed spec compliance and code quality review. Branch `frontend-groupby` is ready to push.

## Current State (Resume Here)
All implementation is done and reviewed. The branch `frontend-groupby` has not been pushed yet.

**Next action:** Push the branch and open a PR against `master`:
```bash
git push -u origin frontend-groupby
gh pr create --title "feat: replace flat trade table with grouped category view" --body "..."
```

The feature is fully working locally. To verify before pushing: start the dev server (`npm run dev` in `frontend/`) and navigate to `/trades` — groups should appear with accent-bar headers, default filter "open", sort by Ticker/Expiry, collapsible sections, and drag-to-reorder via the ⠿ handle.
