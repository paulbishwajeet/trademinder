# Spec: Cost-Basis Gain/Loss Column + Covered-Call Warning

**Date:** 2026-07-30
**Feature:** WHEEL Strategy Dashboard v2 (context/feature-wheel-dashboard.md)
**Status:** Approved, ready for implementation plan

## Problem

The wheel dashboard has no visibility into whether a stock's current price is above or below the cost basis at which it was acquired. Users want to avoid selling a covered call while the stock is underwater relative to cost basis, since doing so risks locking in a loss if the CC gets assigned near the current (depressed) price.

## Goal

1. Add a `% Gain/Loss` column to every section of the wheel dashboard, computed from the stock leg's cost basis (`Trade.premium`) vs. its current price (`Trade.current_price`).
2. Surface a non-blocking warning on the "+ CC" action when the underlying stock is currently below cost basis.

## Non-Goals

- No hard block on selling a covered call while underwater — this is advisory only.
- No new price-fetching logic — `current_price` is already kept fresh by the existing scheduler job (`backend/app/scheduler.py` → `price_fetcher.py`).
- No data model or migration changes.
- No changes to the resolve flow, link-leg endpoint behavior, or other action buttons.

## Data Source

For a stock trade, `Trade.premium` stores the cost basis (price paid per share) and `Trade.current_price` stores the latest fetched price. A slot's stock position is represented by a `WheelSlotLeg` with `leg_role='stock'` joined to a `Trade`.

**Which stock leg to use:** the most recent `leg_role='stock'` leg on the slot with `trade_status='open'`, regardless of rotation number. This reflects whichever shares are currently held right now — a slot can accumulate stock legs across rotations (e.g. after a put assignment), and only the latest open one represents the live position.

## Backend Changes

**`backend/app/schemas/wheel.py`**
- Add `trade_current_price: Optional[Decimal] = None` field to `WheelSlotLegItem`.

**`backend/app/routers/wheel.py`**
- In `_build_leg_item()`, populate the new field: `trade_current_price=t.current_price if t else None`.

This is a pure additive field on an existing response model — no other endpoint behavior changes, no new endpoints.

## Frontend Changes

**`frontend/src/types/index.ts`**
- Add `trade_current_price?: string | number | null` to the `WheelSlotLegItem` (or equivalent) type to match the new backend field.

**`frontend/src/pages/WheelDashboardPage.tsx`**

1. New helper function, e.g.:
   ```ts
   function stockLegCostBasis(slot: WheelSlotDetail): { costBasis: number; currentPrice: number } | null
   ```
   Finds the latest `leg_role === 'stock'` leg with `trade_status === 'open'` (search all legs on the slot, not filtered by rotation_number). Returns `null` if no such leg, or if `trade_premium` / `trade_current_price` is missing.

2. New `% G/L` column:
   - Added to the `<thead>` row and to every row in `renderSlotRow()`, so it appears in all four sections (Needs Action, Awaiting CC, Awaiting Sold Put, Active).
   - Computed as `(currentPrice - costBasis) / costBasis * 100`.
   - Rendered like the existing P&L% cell: green text with `+` prefix when ≥ 0, red text otherwise; `—` in muted gray when `stockLegCostBasis` returns `null`.
   - Column count in `colSpan` values (currently 10) must be bumped to 11 everywhere a full-width row spans the table (leg detail rows, signal detail row, "no legs" row).

3. Covered-call warning on the `+ CC` button (Awaiting CC section only):
   - When `stockLegCostBasis(slot)` is non-null and `currentPrice < costBasis`, render the `+ CC` button with red/amber styling instead of the default blue (e.g. `bg-red-100 text-red-800 hover:bg-red-200`).
   - Add a `title` tooltip: `` `Cost basis $${costBasis} above current price $${currentPrice} — selling a CC may lock in a loss.` ``
   - Button remains fully clickable — this is advisory only, not a block. The `+ Put` button (Awaiting Sold Put section) is unaffected.

## Testing

- Backend: extend or add a schema/CRUD test asserting `trade_current_price` is present and correctly populated in `WheelSlotLegItem` responses (e.g. in `backend/tests/test_wheel_schemas.py` or `test_wheel_crud.py`).
- Frontend: manual verification via `/run` — check a wheel with a stock leg priced below cost basis shows red % and a red-tinted, tooltipped `+ CC` button; a wheel priced above cost basis shows green % and a normal blue `+ CC` button; a slot with no stock leg shows `—`.

## Open Questions

None — all resolved during brainstorming.
