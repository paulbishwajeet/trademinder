# Trade Grouping — Design Spec

**Date:** 2026-05-23  
**Branch:** feature/trade-grouping  
**Status:** Approved

---

## Goal

Replace the flat trade table on the Trades page with a grouped view that organises trades by category (WHEEL, LEAP, HOLD, etc.). Each category is a collapsible section with its own header. The existing status filter buttons and the planned sort controls remain fully functional, working in tandem with the grouping. The goal is better visual organisation so the user can scan their portfolio by strategy at a glance.

---

## Data & Filtering

### Always-fetch, client-side filter

`tradesApi.list()` is called with no `status` parameter — all trades are always fetched on load. Grouping, filtering, and sorting all happen in the browser.

**Why:** Empty groups must stay visible even when a filter is active. Doing this with a server-side filter would require a second call to fetch all categories. Since TradeMinder is a personal app with a small trade list, the simpler single-fetch + client-side approach is the right tradeoff.

### Default status filter: `open`

`statusFilter` state initialises to `'open'` instead of `''`. The "open" button is highlighted on first load.

### Empty group behaviour

When a status filter is applied and a group has no matching trades, the group header remains visible and the body shows:  
> *No open trades in WHEEL*  
(message is contextual — uses the current filter value and category name)

---

## Components

### New: `GroupedTradeTable`

**File:** `frontend/src/components/Trades/GroupedTradeTable.tsx`

**Props:**
```ts
interface Props {
  trades: Trade[]
  onDelete: (id: string) => void
  statusFilter: string
}
```

**Internal state:**
| State | Type | Default | Purpose |
|---|---|---|---|
| `collapsed` | `Set<string>` | empty set | tracks which category names are collapsed |
| `sortKey` | `'ticker' \| 'expiry' \| null` | `null` | active sort column |
| `sortDir` | `1 \| -1` | `1` | ascending or descending |
| `groupOrder` | `string[]` | from localStorage, else `CATEGORY_ORDER` | current drag order of categories |

**Responsibilities:**
- Groups `trades` by `category` into a `Map<string, Trade[]>` using `groupOrder` to determine section sequence
- Applies `statusFilter` within each group before rendering rows
- Renders a column header row with clickable Ticker and Expiry sort controls
- Renders one group section per category in `groupOrder` (even if the category has no trades in the current dataset — it just shows an empty state)
- Manages collapse/expand, sort, and drag-and-drop reorder

### Modified: `TradesPage`

**File:** `frontend/src/pages/TradesPage.tsx`

Changes:
1. `statusFilter` default value changes from `''` to `'open'`
2. Remove `status` param from `tradesApi.list()` call — always fetch all trades
3. Replace `<TradeTable>` with `<GroupedTradeTable statusFilter={statusFilter} ...>`
4. Remove the `useEffect` dependency on `statusFilter` for re-fetching (fetch once on mount only; re-fetch only after create/delete)

### Modified: `TradeTable`

`TradeTable.tsx` is no longer used by `TradesPage`. It will be updated to import `CATEGORY_COLORS` and `CATEGORY_ORDER` from the new shared `categories.ts` file rather than defining them inline. The component itself is otherwise left in place.

---

## Group Header Design

Style: left-accent bar with gradient background.

```
┌──────────────────────────────────────────────────────────────┐
│▌ ⠿  ▼ WHEEL                              3 open · 1 closed  │
└──────────────────────────────────────────────────────────────┘
```

- **Left border:** 3px solid in the category's color from `CATEGORY_COLORS`
- **Background:** `linear-gradient(90deg, <color>1A 0%, transparent 70%)`
- **Drag handle (⠿):** leftmost element; `cursor: grab`
- **Chevron (▼/▶):** rotates 90° when collapsed, animated with CSS transition
- **Category name:** bold, colored to match category
- **Status breakdown:** right-aligned, muted — shows only non-zero status counts, e.g. `3 open · 1 closed · 2 expired`
- **Click behaviour:** clicking anywhere on the header except the drag handle toggles collapse

---

## Column Layout

Columns (in order), with Category column removed:

| Column | Sortable |
|--------|----------|
| Ticker | ✓ (click header) |
| Strategy | — |
| Type | — |
| Strike | — |
| Expiry | ✓ (click header) |
| Qty | — |
| Premium | — |
| P&L | — |
| Status | — |
| Commentary | — |
| Actions | — |

Sort is global — applies to all groups simultaneously. Clicking an active sort column reverses direction. Trades with a `null` expiry sort to the bottom when sorting by expiry.

---

## Drag-to-Reorder

- Each group section is wrapped in a `draggable="true"` container
- The `⠿` handle on the group header initiates the drag
- A blue 2px border indicates the drop target position (above or below the hovered group)
- On drop, `groupOrder` state is updated and immediately persisted to `localStorage` under the key `trademinder_group_order`
- On next page load, `GroupedTradeTable` reads `localStorage` to restore the saved order. If a saved order is missing a category (e.g. a new category was added), the new category is appended to the end.

---

## Category Order & Coverage

The canonical list of categories is `CATEGORY_COLORS` (currently defined inline in `TradeTable.tsx`, extracted to a new shared file):

**New file:** `frontend/src/components/Trades/categories.ts`

```ts
export const CATEGORY_COLORS: Record<string, string> = {
  WHEEL: '#3B82F6', SWING: '#06B6D4', HOLD: '#10B981', LEAP: '#8B5CF6',
  PUT_SPREAD: '#F59E0B', CALL_SPREAD: '#F97316', IRON_CONDOR: '#EF4444',
  IRON_BUTTERFLY: '#EC4899', SKIP: '#6B7280', HOPS: '#84CC16',
}
export const CATEGORY_ORDER = Object.keys(CATEGORY_COLORS)
```

Groups are rendered for every key in `CATEGORY_COLORS`, not only for categories that have trades — this ensures all categories are always visible and draggable even when empty.

---

## Error Handling & Edge Cases

| Case | Behaviour |
|------|-----------|
| Trade has an unknown category | Rendered in an "Other" group at the end |
| All trades filtered away in a group | Empty-state row shown, group header stays |
| localStorage unavailable | Fall back to `CATEGORY_ORDER` silently |
| No trades at all | Each group shows empty state |

---

## Files Changed

| File | Change |
|------|--------|
| `frontend/src/pages/TradesPage.tsx` | Default filter `'open'`, remove status API param, swap table component |
| `frontend/src/components/Trades/GroupedTradeTable.tsx` | **New** — grouped table with sort, collapse, drag-and-drop |
| `frontend/src/components/Trades/categories.ts` | **New** — exports `CATEGORY_COLORS` and `CATEGORY_ORDER` |
| `frontend/src/components/Trades/TradeTable.tsx` | Import `CATEGORY_COLORS` from `categories.ts` instead of defining inline |
| `frontend/src/types/index.ts` | No changes |
| `frontend/src/api/trades.ts` | No changes |

---

## Out of Scope

- Backend changes of any kind
- Per-group sort (sort is global across all groups)
- Saving group order to the backend / syncing across devices
- Adding new categories from the UI
- Drag-and-drop reordering of rows within a group
