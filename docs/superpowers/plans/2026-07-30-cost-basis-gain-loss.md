# Cost-Basis Gain/Loss Column + Covered-Call Warning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a per-stock % gain/loss (cost basis vs. current price) on every section of the wheel dashboard, and warn (non-blocking) when the user is about to sell a covered call while the stock is underwater.

**Architecture:** Expose the stock trade's already-fetched `current_price` through the existing `WheelSlotLegItem` API response (one new field, no new endpoints). The frontend derives % gain/loss from the latest open `stock` leg on each slot and renders it as a new table column; the "+ CC" button is conditionally tinted/tooltipped based on the same calculation.

**Tech Stack:** FastAPI + Pydantic + SQLAlchemy (async) backend, pytest + httpx `AsyncClient` for backend tests, React + TypeScript frontend, Tailwind for styling.

## Global Constraints

- Advisory only — never block the "+ CC" action, per spec.
- No new price-fetching, no data model or migration changes (spec: Non-Goals).
- Cost basis comes from `Trade.premium` on the stock leg; current price from `Trade.current_price`.
- Use the **latest `leg_role='stock'` leg with `trade_status='open'`** on the slot, searched across all rotations (not filtered by `rotation_number`).
- New column appears in **all four** dashboard sections (Needs Action, Awaiting CC, Awaiting Sold Put, Active).

---

### Task 1: Backend — add `trade_current_price` to `WheelSlotLegItem`

**Files:**
- Modify: `backend/app/schemas/wheel.py` (`WheelSlotLegItem` class, ~line 51-66)
- Modify: `backend/app/routers/wheel.py` (`_build_leg_item`, ~line 45-58)
- Test: `backend/tests/test_wheel_crud.py`

**Interfaces:**
- Produces: `WheelSlotLegItem.trade_current_price: Optional[Decimal]` — consumed by Task 2 (frontend type) and Task 3 (frontend UI). Serializes over the wire the same way `trade_premium` already does (Pydantic `Decimal` field on this model — existing fields like `trade_premium` and `trade_strike_price` use this same pattern already).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_wheel_crud.py` (uses the existing `STOCK_TRADE` fixture already defined at the top of the file):

```python
async def test_stock_leg_exposes_current_price(client: AsyncClient):
    sess_resp = await client.post("/api/wheel", json=SESSION_PAYLOAD)
    session_id = sess_resp.json()["id"]
    slot_resp = await client.post(f"/api/wheel/{session_id}/slots", json={"contracts": 1, "shares_held": 100, "status": "awaiting_cc"})
    slot_id = slot_resp.json()["id"]
    trade_resp = await client.post("/api/trades", json=STOCK_TRADE)
    trade_id = trade_resp.json()["id"]
    await client.patch(f"/api/trades/{trade_id}", json={"current_price": "125.50"})
    await client.post(f"/api/wheel/slots/{slot_id}/legs", json={"trade_id": trade_id, "leg_role": "stock"})
    detail = await client.get(f"/api/wheel/{session_id}")
    leg = detail.json()["slots"][0]["legs"][0]
    assert leg["trade_current_price"] == "125.50"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_wheel_crud.py::test_stock_leg_exposes_current_price -v`
Expected: FAIL — `KeyError: 'trade_current_price'` (field not present in response yet).

- [ ] **Step 3: Add the field to the schema**

In `backend/app/schemas/wheel.py`, inside `WheelSlotLegItem`, add the new field right after `trade_premium`:

```python
class WheelSlotLegItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    slot_id: uuid.UUID
    trade_id: uuid.UUID
    leg_role: str
    rotation_number: int
    trade_type: Optional[str] = None
    trade_strategy: Optional[str] = None
    trade_ticker: Optional[str] = None
    trade_open_date: Optional[date] = None
    trade_expiry_date: Optional[date] = None
    trade_strike_price: Optional[Decimal] = None
    trade_quantity: Optional[int] = None
    trade_premium: Optional[Decimal] = None
    trade_current_price: Optional[Decimal] = None
    trade_status: Optional[str] = None
    trade_etrade_symbol: Optional[str] = None
```

- [ ] **Step 4: Populate the field in `_build_leg_item`**

In `backend/app/routers/wheel.py`, update `_build_leg_item`:

```python
def _build_leg_item(leg: WheelSlotLeg) -> WheelSlotLegItem:
    t = leg.trade
    return WheelSlotLegItem(
        id=leg.id, slot_id=leg.slot_id, trade_id=leg.trade_id,
        leg_role=leg.leg_role, rotation_number=leg.rotation_number,
        trade_type=t.type if t else None,
        trade_strategy=t.strategy if t else None,
        trade_ticker=t.ticker if t else None,
        trade_open_date=t.open_date if t else None,
        trade_expiry_date=t.expiry_date if t else None,
        trade_strike_price=t.strike_price if t else None,
        trade_quantity=t.quantity if t else None,
        trade_premium=t.premium if t else None,
        trade_current_price=t.current_price if t else None,
        trade_status=t.status if t else None,
        trade_etrade_symbol=t.etrade_symbol if t else None,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_wheel_crud.py::test_stock_leg_exposes_current_price -v`
Expected: PASS

- [ ] **Step 6: Run the full wheel test suite to check no regression**

Run: `cd backend && uv run pytest tests/test_wheel_crud.py tests/test_wheel_schemas.py tests/test_wheel_resolve.py tests/test_wheel_models.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/wheel.py backend/app/routers/wheel.py backend/tests/test_wheel_crud.py
git commit -m "feat(wheel): expose trade current_price on wheel slot legs"
```

---

### Task 2: Frontend — add `trade_current_price` to the `WheelSlotLegItem` TypeScript type

**Files:**
- Modify: `frontend/src/types/index.ts` (`WheelSlotLegItem` interface, ~line 180-196)

**Interfaces:**
- Consumes: Task 1's `trade_current_price` field on the JSON payload.
- Produces: `WheelSlotLegItem.trade_current_price: number | null` (frontend type) — consumed by Task 3.

- [ ] **Step 1: Add the field**

In `frontend/src/types/index.ts`, update `WheelSlotLegItem`:

```typescript
export interface WheelSlotLegItem {
  id: string
  slot_id: string
  trade_id: string
  leg_role: string
  rotation_number: number
  trade_type: string | null
  trade_strategy: string | null
  trade_ticker: string | null
  trade_open_date: string | null
  trade_expiry_date: string | null
  trade_strike_price: number | null
  trade_quantity: number | null
  trade_premium: number | null
  trade_current_price: number | null
  trade_status: string | null
  trade_etrade_symbol: string | null
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No new errors (this is an additive optional-shaped field, so nothing downstream references it yet — it's fine that it's unused until Task 3).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/index.ts
git commit -m "feat(wheel): add trade_current_price to WheelSlotLegItem type"
```

---

### Task 3: Frontend — cost-basis helper, `% G/L` column, and CC-warning button styling

**Files:**
- Modify: `frontend/src/pages/WheelDashboardPage.tsx`

**Interfaces:**
- Consumes: `WheelSlotDetail.legs: WheelSlotLegItem[]` (each leg has `leg_role`, `trade_status`, `trade_premium`, `trade_current_price` — from Task 2). Also consumes existing `FlatSlot`, `renderSlotRow`, `renderSection`, `renderLegRows`, `renderSignalDetailRow` from the current file.
- Produces: `stockLegCostBasis(slot: WheelSlotDetail): { costBasis: number; currentPrice: number } | null` — a pure function other code in this file (or future dashboard code) can reuse. Also produces the rendered `% G/L` column (11th column) and the conditional red/amber `+ CC` button.

This task has three parts. Since it's all UI wiring in one file with no isolated unit-test harness for this component (no existing frontend test suite for `WheelDashboardPage.tsx` — verified: `frontend/src/pages/WheelDashboardPage.tsx` has no companion test file, and none of the other Wheel components do either), verification is manual via the running app per the spec's Testing section. Follow TDD in spirit by writing the helper first and checking it against known inputs in the browser console step, then wire up the UI.

- [ ] **Step 1: Add the `stockLegCostBasis` helper**

Add this function near the other helpers (`activeLegInfo`, `activeLegSummary`, `renderPnlCell`) in `frontend/src/pages/WheelDashboardPage.tsx`:

```typescript
function stockLegCostBasis(slot: WheelSlotDetail): { costBasis: number; currentPrice: number } | null {
  const stockLegs = slot.legs.filter(l => l.leg_role === 'stock' && l.trade_status === 'open')
  const leg = stockLegs[stockLegs.length - 1]
  if (!leg || leg.trade_premium == null || leg.trade_current_price == null) return null
  const costBasis = Number(leg.trade_premium)
  if (!costBasis) return null
  return { costBasis, currentPrice: Number(leg.trade_current_price) }
}
```

Note: `slot.legs` as returned by the API is ordered by `created_at` ascending (see `_build_slot_detail` in `backend/app/routers/wheel.py`, which sorts `slot.legs` by `created_at` before building the response) — so `stockLegs[stockLegs.length - 1]` is the most recently created open stock leg, matching the spec's "latest open stock leg" rule.

- [ ] **Step 2: Add the `renderGainLossCell` renderer**

Add next to `renderPnlCell`:

```typescript
function renderGainLossCell(slot: WheelSlotDetail) {
  const basis = stockLegCostBasis(slot)
  if (!basis) return <td className="py-2 pr-3 text-xs text-gray-300">—</td>
  const pct = ((basis.currentPrice - basis.costBasis) / basis.costBasis) * 100
  const isProfit = pct >= 0
  return (
    <td className={`py-2 pr-3 text-xs font-medium ${isProfit ? 'text-green-600' : 'text-red-500'}`}>
      {isProfit ? '+' : ''}{pct.toFixed(1)}%
    </td>
  )
}
```

- [ ] **Step 3: Add the column header**

In `renderSection`, update the `<thead>` row (currently 9 `<th>` cells) to add a `% G/L` header before the trailing blank action-column header:

```typescript
<tr className="text-left text-xs text-gray-400 border-b border-gray-100">
  <th className="py-2 pr-3 pl-3 font-normal">Ticker</th>
  <th className="py-2 pr-3 font-normal">Size</th>
  <th className="py-2 pr-3 font-normal">Status</th>
  <th className="py-2 pr-3 font-normal">Active Leg</th>
  <th className="py-2 pr-3 font-normal">Rot</th>
  <th className="py-2 pr-3 font-normal">Premium</th>
  <th className="py-2 pr-3 font-normal">CC Signal</th>
  <th className="py-2 pr-3 font-normal">SP Signal</th>
  <th className="py-2 pr-3 font-normal">P&L %</th>
  <th className="py-2 pr-3 font-normal">% G/L</th>
  <th className="py-2 pr-3 font-normal"></th>
</tr>
```

- [ ] **Step 4: Render the cell in each row and fix `colSpan`s**

In `renderSlotRow`, insert the new cell right after `{renderPnlCell(slot)}` and before the trailing action `<td>`:

```typescript
{renderPnlCell(slot)}
{renderGainLossCell(slot)}
<td className="py-2 text-right">
```

Bump every full-width `colSpan` in this file from `10` to `11` (there are three: the signal-detail row in `renderSignalDetailRow`, the "No legs in current rotation" row in `renderLegRows`, and the leg-detail row's `colSpan={5}` trailing cell — that last one stays `5` since it's a fixed-width trailing span, not a full-width one; only the two `colSpan={10}` occurrences change to `11`).

- [ ] **Step 5: Add CC-warning styling to the "+ CC" button**

In `renderSlotRow`, find the existing action button block:

```typescript
{(slot.status === 'awaiting_cc' || slot.status === 'awaiting_sold_put') && !slot.needs_action && (
  <button onClick={() => setLinkSlotId(slot.id)} className="px-2 py-0.5 text-xs bg-blue-100 text-blue-800 rounded hover:bg-blue-200">
    {slot.status === 'awaiting_cc' ? '+ CC' : '+ Put'}
  </button>
)}
```

Replace it with a version that tints and adds a tooltip only for the `awaiting_cc` + underwater case:

```typescript
{(slot.status === 'awaiting_cc' || slot.status === 'awaiting_sold_put') && !slot.needs_action && (() => {
  const basis = slot.status === 'awaiting_cc' ? stockLegCostBasis(slot) : null
  const isUnderwater = basis != null && basis.currentPrice < basis.costBasis
  const label = slot.status === 'awaiting_cc' ? '+ CC' : '+ Put'
  const className = isUnderwater
    ? 'px-2 py-0.5 text-xs bg-red-100 text-red-800 rounded hover:bg-red-200'
    : 'px-2 py-0.5 text-xs bg-blue-100 text-blue-800 rounded hover:bg-blue-200'
  const title = isUnderwater
    ? `Cost basis $${basis!.costBasis} above current price $${basis!.currentPrice} — selling a CC may lock in a loss.`
    : undefined
  return (
    <button onClick={() => setLinkSlotId(slot.id)} className={className} title={title}>
      {label}
    </button>
  )
})()}
```

- [ ] **Step 6: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/WheelDashboardPage.tsx
git commit -m "feat(wheel): add cost-basis % gain/loss column and CC underwater warning"
```

---

### Task 4: Manual verification in the running app

**Files:** none (verification only)

**Interfaces:**
- Consumes: everything from Tasks 1-3.

- [ ] **Step 1: Start the app**

Use the project's `/run` skill (or manually start backend `cd backend && uv run uvicorn app.main:app --reload` and frontend `cd frontend && npm run dev`) and open the Wheel dashboard in a browser.

- [ ] **Step 2: Set up an underwater stock leg**

Pick (or create) a wheel session with a slot in `awaiting_cc` status that has a linked `stock` leg. Via the API or an existing trade, `PATCH /api/trades/{trade_id}` to set `current_price` below `premium` (cost basis) for that stock trade, e.g.:

```bash
curl -X PATCH http://localhost:8000/api/trades/<trade_id> -H "Content-Type: application/json" -d '{"current_price": "90.00"}'
```

(where `premium` on that trade is something higher, e.g. `100.00`).

- [ ] **Step 3: Verify the warning renders**

Reload the dashboard. Confirm:
- The `% G/L` column shows a red, negative percentage for that slot's row.
- The `+ CC` button on that row is red/amber-tinted (not blue).
- Hovering the `+ CC` button shows the tooltip text with the correct cost basis and current price.
- The button is still clickable and opens the link-leg modal as before.

- [ ] **Step 4: Verify the non-underwater case**

`PATCH` the same trade's `current_price` back above cost basis (e.g. `"110.00"`). Reload. Confirm the `% G/L` column shows green with a `+` prefix, and the `+ CC` button is back to blue with no tooltip.

- [ ] **Step 5: Verify the no-stock-leg case**

Check a slot with no linked stock leg (e.g. a fresh `awaiting_sold_put` slot, or an `awaiting_cc` slot before any stock leg is linked). Confirm its `% G/L` cell shows `—` and its action button (if any) is unaffected/default-styled.

- [ ] **Step 6: Report result to user**

Summarize what was checked and any issues found. If everything matches, this plan is complete — no commit needed for this task (verification only).

---

## Self-Review Notes

- **Spec coverage:** Backend field addition (spec §Backend Changes) → Task 1. Frontend type (spec §Frontend Changes, types/index.ts) → Task 2. Helper function, `% G/L` column in all sections, CC warning styling → Task 3. Testing section (backend schema/CRUD test, manual frontend verification) → Task 1 Step 1 and Task 4.
- **Placeholder scan:** No TBDs; every step has literal code or exact commands.
- **Type consistency:** `trade_current_price` named identically across schema (Task 1), TS type (Task 2), and helper usage (Task 3). `stockLegCostBasis` return shape `{ costBasis, currentPrice }` used consistently in both `renderGainLossCell` and the button-styling closure.
