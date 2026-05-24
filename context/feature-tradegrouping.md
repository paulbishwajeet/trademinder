# Feature: Trade Grouping
**Status:** Not Started
**Branch:** feature/trade-grouping
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
- `frontend/src/pages/TradesPage.tsx` — default filter change, remove API status param, swap component
- `frontend/src/components/Trades/GroupedTradeTable.tsx` — new component (main work)
- `frontend/src/components/Trades/categories.ts` — new shared file for CATEGORY_COLORS / CATEGORY_ORDER
- `frontend/src/components/Trades/TradeTable.tsx` — update to import from categories.ts

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

## Open Questions / Blockers
- [ ] None

## Progress Log
- 2026-05-23 — Feature created; design spec written and approved
- 2026-05-23 — Spec at `docs/superpowers/specs/2026-05-23-trade-grouping-design.md`

## Current State (Resume Here)
Next step: Write implementation plan (invoke writing-plans skill)
