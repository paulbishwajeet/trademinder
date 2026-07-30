# Ticker-Level Stock Cost Basis Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the wheel dashboard's `% G/L` column and covered-call underwater warning, which are currently empty/inactive for nearly all real data because they read cost basis from a slot-linked stock leg that almost never exists — instead, source cost basis from the ticker-matched open `category=WHEEL, strategy=Stock` trade, at the session level (one lookup per ticker, shared across all that ticker's slots).

**Architecture:** Add a small backend helper that looks up the matching open stock `Trade` for a session's ticker (exact match, then `GOOG`/`GOOGL` alias fallback, then latest `open_date` on ties), expose the result as two new fields on `WheelSessionDetail`. On the frontend, thread those two values from the session down through `FlatSlot` (replacing the deleted leg-based helper) into the existing `% G/L` cell and `+ CC` button-warning logic, which are otherwise unchanged.

**Tech Stack:** FastAPI + Pydantic + SQLAlchemy (async) backend, pytest + httpx `AsyncClient` for backend tests, React + TypeScript frontend, Tailwind for styling.

## Global Constraints

- Advisory only — the "+ CC" button must never be disabled/blocked.
- Cost basis source: `trades.premium` where `category='WHEEL' AND strategy='Stock' AND status='open'`; current price from `trades.current_price`.
- Ticker matching: exact `ticker == session.ticker` first; only fall back to the alias (`GOOG`↔`GOOGL`) if no exact match exists.
- If more than one matching trade exists for a ticker, use the one with the latest `open_date`.
- No new price-fetching, no data model or migration changes (spec: Non-Goals).
- `% G/L` column and `+ CC` warning behavior (styling, tooltip text, which sections show the column) are unchanged from the prior iteration — only the data source changes.

---

### Task 1: Backend — ticker-matched stock position on `WheelSessionDetail`

**Files:**
- Modify: `backend/app/schemas/wheel.py` (`WheelSessionDetail`, at the end of the file)
- Modify: `backend/app/routers/wheel.py` (`_build_session_detail`, `get_wheel_session`, imports)
- Test: `backend/tests/test_wheel_crud.py`

**Interfaces:**
- Produces: `WheelSessionDetail.stock_cost_basis: Optional[Decimal]` and `WheelSessionDetail.stock_current_price: Optional[Decimal]` — consumed by Task 2 (frontend type + UI).
- Produces: `_find_stock_position(db: AsyncSession, ticker: str) -> tuple[Optional[Decimal], Optional[Decimal]]` in `backend/app/routers/wheel.py` — a private helper, not exported, but its behavior (exact match → alias fallback → latest `open_date`) is the contract Task 3's manual verification will exercise.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_wheel_crud.py` (this file already defines `SESSION_PAYLOAD` at the top — reuse it for the exact-match test, and build new payloads for the alias/no-match cases):

```python
async def test_session_detail_exposes_stock_cost_basis(client: AsyncClient):
    sess_resp = await client.post("/api/wheel", json=SESSION_PAYLOAD)
    session_id = sess_resp.json()["id"]
    trade_resp = await client.post("/api/trades", json={
        "type": "Buy", "category": "WHEEL", "strategy": "Stock",
        "ticker": "NVDA", "open_date": str(date.today()), "quantity": 100, "premium": "125.00",
    })
    trade_id = trade_resp.json()["id"]
    await client.patch(f"/api/trades/{trade_id}", json={"current_price": "110.00"})

    detail = await client.get(f"/api/wheel/{session_id}")
    assert detail.json()["stock_cost_basis"] == "125.00"
    assert detail.json()["stock_current_price"] == "110.00"


async def test_session_detail_no_stock_trade_is_null(client: AsyncClient):
    sess_resp = await client.post("/api/wheel", json=SESSION_PAYLOAD)
    session_id = sess_resp.json()["id"]

    detail = await client.get(f"/api/wheel/{session_id}")
    assert detail.json()["stock_cost_basis"] is None
    assert detail.json()["stock_current_price"] is None


async def test_session_detail_uses_alias_fallback(client: AsyncClient):
    sess_resp = await client.post("/api/wheel", json={"ticker": "GOOG", "total_shares": 100, "opened_at": str(date.today())})
    session_id = sess_resp.json()["id"]
    # Only a GOOGL stock trade exists (no exact GOOG match) — must fall back to the alias.
    trade_resp = await client.post("/api/trades", json={
        "type": "Buy", "category": "WHEEL", "strategy": "Stock",
        "ticker": "GOOGL", "open_date": str(date.today()), "quantity": 100, "premium": "342.51",
    })
    trade_id = trade_resp.json()["id"]
    await client.patch(f"/api/trades/{trade_id}", json={"current_price": "330.00"})

    detail = await client.get(f"/api/wheel/{session_id}")
    assert detail.json()["stock_cost_basis"] == "342.51"
    assert detail.json()["stock_current_price"] == "330.00"


async def test_session_detail_exact_match_wins_over_alias(client: AsyncClient):
    sess_resp = await client.post("/api/wheel", json={"ticker": "GOOGL", "total_shares": 100, "opened_at": str(date.today())})
    session_id = sess_resp.json()["id"]
    # A GOOG trade exists too, but the exact GOOGL match must win.
    goog_resp = await client.post("/api/trades", json={
        "type": "Buy", "category": "WHEEL", "strategy": "Stock",
        "ticker": "GOOG", "open_date": str(date.today()), "quantity": 360, "premium": "110.14",
    })
    await client.patch(f"/api/trades/{goog_resp.json()['id']}", json={"current_price": "332.77"})
    googl_resp = await client.post("/api/trades", json={
        "type": "Buy", "category": "WHEEL", "strategy": "Stock",
        "ticker": "GOOGL", "open_date": str(date.today()), "quantity": 100, "premium": "342.51",
    })
    await client.patch(f"/api/trades/{googl_resp.json()['id']}", json={"current_price": "330.00"})

    detail = await client.get(f"/api/wheel/{session_id}")
    assert detail.json()["stock_cost_basis"] == "342.51"
    assert detail.json()["stock_current_price"] == "330.00"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_wheel_crud.py -k "stock_cost_basis or stock_trade_is_null or alias_fallback or exact_match_wins" -v`
Expected: FAIL — `KeyError: 'stock_cost_basis'` (field not present in response yet).

- [ ] **Step 3: Add the fields to the schema**

In `backend/app/schemas/wheel.py`, update the final class:

```python
class WheelSessionDetail(WheelSessionSummary):
    slots: list[WheelSlotDetail] = []
    total_premium: Decimal = Decimal("0")
    stock_cost_basis: Optional[Decimal] = None
    stock_current_price: Optional[Decimal] = None
```

- [ ] **Step 4: Add the alias map and lookup helper, make `_build_session_detail` async**

In `backend/app/routers/wheel.py`, add the alias map near the top (after the existing `LEG_ROLE_TO_STATUS`/`LEG_ROLE_TO_EVENT`/`OUTCOME_MAP` constants):

```python
TICKER_ALIASES = {"GOOG": "GOOGL", "GOOGL": "GOOG"}


async def _find_stock_position(db: AsyncSession, ticker: str) -> tuple[Optional[Decimal], Optional[Decimal]]:
    async def _latest_open_stock_trade(t: str) -> Optional[Trade]:
        stmt = (
            select(Trade)
            .where(
                Trade.category == "WHEEL",
                Trade.strategy == "Stock",
                Trade.status == "open",
                Trade.ticker == t,
            )
            .order_by(Trade.open_date.desc())
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    trade = await _latest_open_stock_trade(ticker)
    if trade is None and ticker in TICKER_ALIASES:
        trade = await _latest_open_stock_trade(TICKER_ALIASES[ticker])
    if trade is None:
        return None, None
    return trade.premium, trade.current_price
```

Then change `_build_session_detail` to accept `db` and be `async`:

```python
async def _build_session_detail(db: AsyncSession, session: WheelSession) -> WheelSessionDetail:
    slots = [_build_slot_detail(s) for s in sorted(session.slots, key=lambda s: s.slot_number)]
    total = sum((s.total_premium for s in slots), Decimal("0"))
    stock_cost_basis, stock_current_price = await _find_stock_position(db, session.ticker)
    return WheelSessionDetail(
        id=session.id, ticker=session.ticker, total_shares=session.total_shares,
        status=session.status, opened_at=session.opened_at, closed_at=session.closed_at,
        slots=slots, total_premium=total,
        stock_cost_basis=stock_cost_basis, stock_current_price=stock_current_price,
    )
```

- [ ] **Step 5: Update the one call site**

In `backend/app/routers/wheel.py`, `get_wheel_session`:

```python
@router.get("/{session_id}", response_model=WheelSessionDetail)
async def get_wheel_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    opts = _load_session_options()
    stmt = select(WheelSession).where(WheelSession.id == session_id).options(*opts)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Wheel session not found")
    return await _build_session_detail(db, session)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && venv/bin/python -m pytest tests/test_wheel_crud.py -k "stock_cost_basis or stock_trade_is_null or alias_fallback or exact_match_wins" -v`
Expected: 4 PASS

- [ ] **Step 7: Run the full wheel test suite to check no regression**

Run: `cd backend && venv/bin/python -m pytest tests/test_wheel_crud.py tests/test_wheel_schemas.py tests/test_wheel_resolve.py tests/test_wheel_models.py -v`
Expected: All PASS (30 tests: 26 existing + 4 new)

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas/wheel.py backend/app/routers/wheel.py backend/tests/test_wheel_crud.py
git commit -m "fix(wheel): source stock cost basis from ticker-matched trade, not linked leg"
```

---

### Task 2: Frontend — switch `% G/L` and CC-warning to session-level stock position

**Files:**
- Modify: `frontend/src/types/index.ts` (`WheelSessionDetail`, ~line 225-228)
- Modify: `frontend/src/pages/WheelDashboardPage.tsx` (`FlatSlot`, `flattenSlots`, `stockLegCostBasis` deletion, `renderGainLossCell`, button logic in `renderSlotRow`)

**Interfaces:**
- Consumes: `WheelSessionDetail.stock_cost_basis: number | null` and `WheelSessionDetail.stock_current_price: number | null` from Task 1.
- Produces: `FlatSlot.stockCostBasis: number | null` and `FlatSlot.stockCurrentPrice: number | null` — the new source of truth other dashboard code should read for this ticker's cost basis. `renderGainLossCell` and the `+ CC` warning logic both switch from taking `slot: WheelSlotDetail` to taking `f: FlatSlot` (renderSlotRow already has `f` in scope).

There is no automated test suite for this page component (verified in the prior iteration — still true). Verification is `tsc --noEmit` plus manual browser check in Task 3.

- [ ] **Step 1: Add the two fields to the TypeScript type**

In `frontend/src/types/index.ts`, update:

```typescript
export interface WheelSessionDetail extends WheelSessionSummary {
  slots: WheelSlotDetail[]
  total_premium: string
  stock_cost_basis: number | null
  stock_current_price: number | null
}
```

- [ ] **Step 2: Thread the values through `FlatSlot`**

In `frontend/src/pages/WheelDashboardPage.tsx`, update:

```typescript
interface FlatSlot {
  slot: WheelSlotDetail
  ticker: string
  sessionId: string
  stockCostBasis: number | null
  stockCurrentPrice: number | null
}

function flattenSlots(sessions: WheelSessionDetail[]): FlatSlot[] {
  return sessions.flatMap(s => s.slots.map(slot => ({
    slot,
    ticker: s.ticker,
    sessionId: s.id,
    stockCostBasis: s.stock_cost_basis,
    stockCurrentPrice: s.stock_current_price,
  })))
}
```

- [ ] **Step 3: Delete the leg-based helper and rewrite the gain/loss cell**

Delete `stockLegCostBasis` entirely (currently at ~line 205-212):

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

Replace `renderGainLossCell` (currently at ~line 214-224) with a version that takes a `FlatSlot`:

```typescript
  function renderGainLossCell(f: FlatSlot) {
    const { stockCostBasis: costBasis, stockCurrentPrice: currentPrice } = f
    if (costBasis == null || currentPrice == null || !costBasis) {
      return <td className="py-2 pr-3 text-xs text-gray-300">—</td>
    }
    const pct = ((currentPrice - costBasis) / costBasis) * 100
    const isProfit = pct >= 0
    return (
      <td className={`py-2 pr-3 text-xs font-medium ${isProfit ? 'text-green-600' : 'text-red-500'}`}>
        {isProfit ? '+' : ''}{pct.toFixed(1)}%
      </td>
    )
  }
```

- [ ] **Step 4: Update the call site in `renderSlotRow`**

In `renderSlotRow` (~line 289-318), change the call from `{renderGainLossCell(slot)}` to `{renderGainLossCell(f)}`:

```typescript
        {renderPnlCell(slot)}
        {renderGainLossCell(f)}
```

- [ ] **Step 5: Update the `+ CC` button warning logic**

In `renderSlotRow`, replace the button IIFE (~line 326-341):

```typescript
            {(slot.status === 'awaiting_cc' || slot.status === 'awaiting_sold_put') && !slot.needs_action && (() => {
              const isUnderwater = slot.status === 'awaiting_cc'
                && f.stockCostBasis != null && f.stockCurrentPrice != null
                && f.stockCurrentPrice < f.stockCostBasis
              const label = slot.status === 'awaiting_cc' ? '+ CC' : '+ Put'
              const className = isUnderwater
                ? 'px-2 py-0.5 text-xs bg-red-100 text-red-800 rounded hover:bg-red-200'
                : 'px-2 py-0.5 text-xs bg-blue-100 text-blue-800 rounded hover:bg-blue-200'
              const title = isUnderwater
                ? `Cost basis $${f.stockCostBasis} above current price $${f.stockCurrentPrice} — selling a CC may lock in a loss.`
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
Expected: No errors. (If `WheelSlotDetail` import becomes unused after deleting `stockLegCostBasis`'s signature, `tsc --noEmit` won't flag unused type imports by default — but double check the `import type { ... WheelSlotDetail ... }` line at the top of the file: `WheelSlotDetail` is still used elsewhere in this file, e.g. `FlatSlot.slot: WheelSlotDetail` and other function signatures like `activeLegInfo(slot: WheelSlotDetail)` — so no import cleanup is needed.)

- [ ] **Step 7: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/pages/WheelDashboardPage.tsx
git commit -m "fix(wheel): read stock cost basis from session-level data, not slot leg"
```

---

### Task 3: Manual verification in the running app

**Files:** none (verification only)

**Interfaces:**
- Consumes: everything from Tasks 1-2.

- [ ] **Step 1: Start the app**

Start backend and frontend against the real dev database (same approach as the prior iteration's Task 4 — see that plan's notes if unfamiliar: `docs/superpowers/plans/2026-07-30-cost-basis-gain-loss.md` Task 4). Use disposable scratch ports if the user's own dev servers are already running on the default ports, to avoid interfering with their live session.

- [ ] **Step 2: Verify a real underwater ticker**

Pick a ticker known to be underwater from the earlier investigation, e.g. **AVAV** (cost basis $217.49, current price $144.59 as of this writing — re-check via `GET /api/wheel` → find the AVAV session → `GET /api/wheel/{id}` to confirm current values, since prices may have moved). Confirm its `awaiting_cc` row now shows a red, negative `% G/L` and a red-tinted `+ CC` button with the correct tooltip values.

- [ ] **Step 3: Verify a real profitable ticker**

Pick a ticker known to be profitable, e.g. **AMD** (cost basis $469.96, current price $487.52 as of this writing — re-verify current values the same way). Confirm its row shows a green, positive `% G/L` and a normal blue `+ CC` button.

- [ ] **Step 4: Verify the alias fallback with disposable scratch data**

Do not use the real GOOG/GOOGL data (it has two different real positions and touching it risks confusing production bookkeeping). Instead:
1. Create a scratch wheel session with a throwaway ticker not used elsewhere, e.g. `ZZALIAS` — but note `ZZALIAS` has no alias entry, so this only tests the exact-match path. To test the alias path specifically, temporarily use the real `GOOG`/`GOOGL` alias pair but with a scratch ticker approach isn't possible since the alias map is hardcoded to those two tickers.
2. Since the alias behavior is already covered by an automated test in Task 1 (`test_session_detail_uses_alias_fallback`) against a fully disposable scratch session and trade (ticker `GOOG`, cleaned up in the test's own transaction/test-db teardown), it is safe to rely on that automated coverage for the alias path rather than exercising it manually against production data. Skip manual alias verification; note this decision in your report.

- [ ] **Step 5: Verify the no-position case**

Find a ticker in `awaiting_cc` or `awaiting_sold_put` with no matching open Stock trade at all (any ticker not in the `category='WHEEL', strategy='Stock', status='open'` list gathered during investigation, e.g. check via the API rather than assuming). Confirm its `% G/L` cell shows `—` and its action button is default-styled with no tooltip.

- [ ] **Step 6: Clean up and report**

Stop any scratch servers started for this verification (do not leave background processes running). Report what was checked, the actual values observed, and any issues found. If everything matches, this plan is complete — no commit needed for this task (verification only).

---

## Self-Review Notes

- **Spec coverage:** Ticker-matching rule (exact → alias → latest open_date) → Task 1 Step 4 (`_find_stock_position`). New `WheelSessionDetail` fields → Task 1 Step 3 + Task 2 Step 1. Frontend threading through `FlatSlot` and removal of the leg-based helper → Task 2 Steps 2-3. Unchanged rendering/warning behavior → Task 2 Steps 3-5 (same styling/tooltip as before, only the data source changed). Testing section of the spec (exact match, alias fallback, no match) → Task 1's four new tests; manual verification → Task 3.
- **Placeholder scan:** No TBDs; every step has literal code or exact commands. Task 3 Step 4 explains *why* manual alias verification is skipped (relies on Task 1's automated test) rather than leaving a vague "TODO test alias".
- **Type consistency:** `stock_cost_basis`/`stock_current_price` named identically across the Pydantic schema (Task 1), the TS interface (Task 2 Step 1), and `FlatSlot.stockCostBasis`/`stockCurrentPrice` (Task 2 Step 2) — camelCase on the frontend-only `FlatSlot`, matching the file's existing convention (e.g. `sessionId` vs. `session_id`). `renderGainLossCell` and the button logic both consistently take `f: FlatSlot` after Task 2.
