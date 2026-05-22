# Edit Trade — Design Spec

**Date:** 2026-05-22
**Branch:** frontend-edittrade
**Status:** Approved

---

## Problem

`TradeDetailPage` is read-only. Fields captured by the browser extension (strategy, category, type, strike, expiry, quantity, premium, collateral) cannot be corrected after the fact. Status cannot be updated from the frontend — users who close a trade on E*TRADE must delete and re-enter or use the extension's Edit modal.

---

## Scope

Single-page edit mode on `TradeDetailPage`. No new routes or files.

Out of scope: extension auto-close on E*TRADE position close (deferred to a future revision).

---

## Approach

An **Edit** button in the trade detail header toggles `isEditing` state. All editable fields swap from display cards to form inputs in-place. The header Edit button is replaced by **Save** + **Cancel**. Save calls `PATCH /api/trades/{id}` and returns to read mode. Cancel resets to current values without a network call.

---

## Component Structure

All logic lives in `TradeDetailPage.tsx`. New state:

- `isEditing: boolean` — false by default
- `editForm: TradeEditForm` — local copy of trade values, initialized on Edit click
- `categories: Category[]` — fetched from `/api/categories` on first Edit click, cached in component state
- `saving: boolean` — disables Save + Cancel during PATCH
- `saveError: string | null` — inline error banner

No new files. No new routes.

---

## Locked vs Editable Fields

**Locked (static text in edit mode):**
- `ticker`
- `open_date`

**Editable:**

| Field | Control | Notes |
|-------|---------|-------|
| type | select | Buy / Sell / Assigned |
| strategy | select | Stock / Put / Call / CoveredCall / PutCreditSpread / Leap |
| category | select | Fetched from /api/categories |
| strike_price | number input | |
| expiry_date | date input | |
| quantity | number input | |
| premium | number input | |
| collateral | number input | |
| status | select | open / closed / expired / assigned |
| closed_date | date input | Appears only when status = "closed"; defaults to today |
| exit_strategy | textarea | |
| rationale_notes | textarea | Maps to `trade.rationale.notes` |
| signal_action | text input | |

The status + closed_date pair renders in its own row below the main grid so the conditional reveal is visually clear. When status is changed away from "closed", `closed_date` is cleared in `editForm` (sent as `null` on Save).

---

## Save Flow

1. User clicks Save → `saving = true`, both buttons disabled, spinner on Save
2. Call `PATCH /api/trades/{id}` with full `editForm` payload (all fields, `exclude_none`)
3. On success → `isEditing = false`, update `trade` state from PATCH response (no second GET needed — endpoint returns `TradeResponse`)
4. On error → set `saveError`, stay in edit mode (user's changes preserved)

Cancel: reset `editForm` to current `trade` values, `isEditing = false`, no network call.

---

## API Changes

### Frontend — `src/api/trades.ts`

Replace the narrow `update()` type with a full `TradeUpdate` interface covering all editable fields:

```ts
interface TradeUpdate {
  type?: string
  category?: string
  strategy?: string
  strike_price?: number | null
  expiry_date?: string | null
  quantity?: number
  premium?: number | null
  collateral?: number | null
  status?: 'open' | 'closed' | 'expired' | 'assigned'
  closed_date?: string | null
  exit_strategy?: string | null
  rationale_notes?: string | null
  signal_action?: string | null
}
```

### Backend — `app/schemas/trade.py`

Add one field to `TradeUpdate`:

```python
closed_date: Optional[date] = None
```

### Backend — `app/routers/trades.py` (PATCH handler)

`closed_date` flows through the generic `setattr` loop — no special handling needed once it's in the schema. No migration required; the column already exists.

---

## Error Handling

- Save error: inline red banner above the form (same pattern as `TradeForm`). User stays in edit mode with changes intact.
- Categories fetch failure: falls back to a text input for category (same graceful degradation as `TradeForm`).

---

## What Is Not Changing

- `TradeForm.tsx` — create-trade form is untouched
- Commentary thread — rendered below edit form as today, unaffected
- Rationale technicals display — read-only technicals panel stays; only `rationale.notes` is editable
- Backend close endpoint (`POST /api/trades/{id}/close`) — kept as-is, not removed
- No new DB migration needed
