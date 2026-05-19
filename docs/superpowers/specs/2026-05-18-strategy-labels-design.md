# Strategy Labels — Design Spec

**Date:** 2026-05-18
**Branch:** extension-strategy
**Status:** Approved — pending implementation plan

---

## Goal

Replace the existing 6 generic categories (Wheel, Speculative, etc.) with 10 precise trading-strategy labels. Each label gets a distinct color used to highlight rows on the web-app trades dashboard and in the E*TRADE extension overlay. A new "View / Edit Entry" right-click context menu item lets users edit any tracked trade without leaving E*TRADE.

---

## Category Labels

Stored as SNAKE_CASE strings in the `category` column. Displayed as-is in all UI (no formatting transformation).

| # | Name | Color | Icon | Meaning |
|---|------|-------|------|---------|
| 1 | WHEEL | `#3B82F6` | 🔄 | Systematic premium income (put → assignment → covered call) |
| 2 | SWING | `#06B6D4` | 📈 | Directional / short-term momentum trade |
| 3 | HOLD | `#10B981` | 🌱 | Long-term position, do not touch |
| 4 | LEAP | `#8B5CF6` | 🚀 | Long-dated options (1 year+) |
| 5 | PUT_SPREAD | `#F59E0B` | 📉 | Defined-risk put credit spread |
| 6 | CALL_SPREAD | `#F97316` | 📈 | Defined-risk call credit spread |
| 7 | IRON_CONDOR | `#EF4444` | 🦅 | Neutral range-bound strategy |
| 8 | IRON_BUTTERFLY | `#EC4899` | 🦋 | Tight neutral, high-premium strategy |
| 9 | SKIP | `#6B7280` | ⏭ | Watching, not acting |
| 10 | HOPS | `#84CC16` | 🌿 | Custom / experimental |

---

## Section 1: Data Layer

### Migration `004_strategy_categories.py`

Three operations in sequence:

**Step 1 — Delete old system categories**
```sql
DELETE FROM categories WHERE is_system = true;
```

**Step 2 — Insert 10 new system categories** with the names, colors, icons, and sort orders from the table above.

**Step 3 — Remap existing trade category strings and FK**

| Old value | New value |
|-----------|-----------|
| Wheel | WHEEL |
| Long Term | HOLD |
| Short Term | SWING |
| Speculative | SKIP |
| Momentum | SWING |
| Coach Suggested | SKIP |

Both the `category` string column and the `category_id` FK on `trades` are updated. The FK is set by joining on the new category name after insert.

### Downgrade
Restore the 6 original system categories and remap trades back using the reverse mapping. Trades that did not exist before the upgrade (new entries using new categories) are mapped to `Wheel` as a safe fallback.

---

## Section 2: Backend

### 2a — Trade lookup by `etrade_symbol`

Add an optional query param `etrade_symbol: str | None = None` to `GET /api/trades`. When provided, filter results to trades where `etrade_symbol` matches exactly. Used by the extension "View / Edit" modal to locate the trade for a given E*TRADE row before rendering the pre-filled form.

### 2b — PATCH schema completeness

Verify `PATCH /api/trades/{trade_id}` (TradeUpdate schema) includes all fields editable from the extension:
- `category`, `type`, `strategy`, `strike_price`, `expiry_date`, `quantity`, `premium`, `exit_strategy`, `rationale_notes`

Add any missing fields to the Pydantic schema. No DB schema changes needed.

---

## Section 3: Web App

### 3a — TradeForm category dropdown

Replace the hardcoded `CATEGORIES` array in `frontend/src/components/Trades/TradeForm.tsx` with a `useEffect` fetch from `GET /api/categories` on mount. Renders the live list ordered by `sort_order`. Falls back to an empty dropdown with an error message if the fetch fails. The `STRATEGIES` array (trade mechanics) remains hardcoded.

### 3b — Dashboard row highlighting

In the trades table component, apply per-row visual treatment keyed on the trade's `category` string:
- Left border: 3px solid, category color
- Row background: category color at 8% opacity (`#RRGGBB14`)

A `CATEGORY_COLORS` constant (Record<string, string>) holds the same hex values as the migration seed. This avoids an extra API call — trades are already fetched with their `category` field.

```ts
const CATEGORY_COLORS: Record<string, string> = {
  WHEEL: '#3B82F6',
  SWING: '#06B6D4',
  HOLD: '#10B981',
  LEAP: '#8B5CF6',
  PUT_SPREAD: '#F59E0B',
  CALL_SPREAD: '#F97316',
  IRON_CONDOR: '#EF4444',
  IRON_BUTTERFLY: '#EC4899',
  SKIP: '#6B7280',
  HOPS: '#84CC16',
};
```

Rows with an unrecognized or missing category render with no special treatment (neutral).

---

## Section 4: Extension

### 4a — Category dropdown: dynamic fetch

Both the "Add Trade" and "Edit Trade" modals fetch `GET /api/categories` once when the modal opens (using the configured `tmApiUrl`). The response populates the category `<select>` options. No hardcoded category values remain in `content.js`.

On fetch failure, the dropdown shows a single disabled option `"(categories unavailable)"` and the submit button is disabled until resolved by reopening the modal.

### 4b — "View / Edit Entry" context menu item

**`background.js` changes:**

1. Register a second context menu item on install:
```js
chrome.contextMenus.create({
  id: 'tm-view',
  title: 'View / Edit Entry',
  contexts: ['page'],
  documentUrlPatterns: ['https://*.etrade.com/*'],
});
```

2. In the `ROW_CONTEXT` handler, update both items based on `isTracked`:
   - `tm-add`: enabled when `!isTracked`, title "Add to TradeMinder" / "Already in TradeMinder"
   - `tm-view`: enabled when `isTracked`, title "View / Edit Entry" / "Not in TradeMinder"

3. In `onClicked`, handle `tm-view` by sending `{ type: 'SHOW_EDIT_MODAL', info: rowInfo }` to the active tab.

**`content.js` changes:**

1. Add a `SHOW_EDIT_MODAL` message handler.

2. `showEditTradeModal(info)`:
   - Fetches `GET /api/trades?etrade_symbol=<info.fullSymbol>` (falls back to `GET /api/trades?ticker=<info.ticker>&status=open` if no fullSymbol — picks the first result, ordered by `open_date` desc)
   - If no trade found: shows an error toast "Trade not found in TradeMinder"
   - If found: opens a modal pre-filled with all trade fields
   - Category dropdown populated from `GET /api/categories` (same call pattern as Add modal)
   - On submit: `PATCH /api/trades/:id` with changed fields
   - On success: invalidates the status cache for the row and closes the modal

**Modal structure:** Same layout as the existing Add Trade modal. Header shows "✏️ Edit Trade" with the ticker prominent at the top. The ticker field is read-only (the symbol doesn't change). A colored left-bar beside the ticker reflects the current category color, updating live as the user changes the category dropdown.

### 4c — `content.js` Add modal: category dropdown updated

The existing `showAddTradeModal` category `<select>` is refactored to use the same dynamic fetch introduced in 4a. The hardcoded `<option>` values are removed.

---

## Out of Scope

- Extension badge showing the category label or color (badge already shows DTE + RSI + commentary count)
- Category management UI (add/edit/delete categories from the web app settings)
- Filtering the trades table by category in the web app (existing filter toolbar handles this)
- Backend enforcement of valid category values (no DB check constraint added)

---

## Files Changed

| File | Change |
|------|--------|
| `backend/alembic/versions/004_strategy_categories.py` | New migration |
| `backend/app/routers/trades.py` | Add `etrade_symbol` query param to GET |
| `backend/app/schemas/trade.py` | Verify/extend TradeUpdate fields |
| `frontend/src/components/Trades/TradeForm.tsx` | Fetch categories from API |
| `frontend/src/pages/TradesPage.tsx` | Row highlighting via CATEGORY_COLORS |
| `extension/background.js` | Add `tm-view` context menu item |
| `extension/content.js` | Add Edit modal, dynamic category fetch in both modals |
