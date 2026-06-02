# E*TRADE Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reconciliation system that flags E*TRADE positions not in the backend (extension "Add" pill) and flags backend open trades not in E*TRADE (frontend "Stale" badge + Mark Closed button).

**Architecture:** The extension sends all visible E*TRADE positions to `POST /api/positions/reconcile` on each page load. The backend diffs against open trades, updates a `last_etrade_seen` timestamp on matched trades, and returns two lists: `unmatched_etrade` (extension shows "Add" pill) and `stale_backend` (frontend shows stale indicator). The frontend TradesPage detects stale trades from `last_etrade_seen` returned in the existing trade list.

**Tech Stack:** FastAPI + SQLAlchemy async (backend), Alembic (migrations), pytest + httpx (tests), React 19 + TypeScript (frontend), vanilla JS Chrome MV3 content script (extension).

**Spec:** `docs/superpowers/specs/2026-06-01-etrade-reconciliation-design.md`

---

## File Map

| Action | File |
|--------|------|
| Create | `backend/alembic/versions/007_last_etrade_seen.py` |
| Modify | `backend/app/models/trade.py` — add `last_etrade_seen` column |
| Modify | `backend/app/schemas/positions.py` — add Reconcile schemas |
| Modify | `backend/app/schemas/trade.py` — add `last_etrade_seen` to `TradeListItem` |
| Modify | `backend/app/routers/positions.py` — add `POST /api/positions/reconcile` |
| Modify | `backend/app/routers/trades.py` — add `?stale=true` to list endpoint |
| Create | `backend/tests/test_reconcile.py` — reconcile + stale filter tests |
| Modify | `frontend/src/types/index.ts` — add `last_etrade_seen` to `Trade` |
| Modify | `frontend/src/pages/TradesPage.tsx` — stale banner + handleClose |
| Modify | `frontend/src/components/Trades/GroupedTradeTable.tsx` — stale badge + Close button |
| Modify | `extension/content.js` — reconcile call + "Add" pill |

---

## Task 1: Alembic migration + Trade model column

**Files:**
- Create: `backend/alembic/versions/007_last_etrade_seen.py`
- Modify: `backend/app/models/trade.py`

- [ ] **Step 1: Create the migration file**

Create `backend/alembic/versions/007_last_etrade_seen.py`:

```python
"""add last_etrade_seen to trades

Revision ID: 007
Revises: 006
Create Date: 2026-06-01
"""
from alembic import op
import sqlalchemy as sa

revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'trades',
        sa.Column('last_etrade_seen', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        'idx_trades_status_last_etrade_seen',
        'trades',
        ['status', 'last_etrade_seen'],
    )


def downgrade() -> None:
    op.drop_index('idx_trades_status_last_etrade_seen', 'trades')
    op.drop_column('trades', 'last_etrade_seen')
```

- [ ] **Step 2: Add the column to the Trade SQLAlchemy model**

In `backend/app/models/trade.py`, add this line after `last_price_at` (line 47):

```python
last_etrade_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 3: Apply migration locally and verify**

```bash
cd /Users/bishwajeetpaul/workspace/github/TradeMinder
docker compose up -d db
docker compose exec backend alembic upgrade head
```

Expected: migration 007 applied without errors.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/007_last_etrade_seen.py backend/app/models/trade.py
git commit -m "feat: add last_etrade_seen column to trades"
```

---

## Task 2: Backend schemas — reconcile request/response + TradeListItem

**Files:**
- Modify: `backend/app/schemas/positions.py`
- Modify: `backend/app/schemas/trade.py`

- [ ] **Step 1: Add reconcile schemas to positions.py**

Append to `backend/app/schemas/positions.py`:

```python
class ReconcileRequest(BaseModel):
    positions: list[PositionInput]  # reuses existing PositionInput


class UnmatchedEtradeItem(BaseModel):
    ticker: str
    full_symbol: Optional[str] = None
    option_type: Optional[str] = None  # "Put", "Call", "Stock"
    strike: Optional[float] = None
    expiry: Optional[date] = None


class StaleBackendItem(BaseModel):
    id: uuid.UUID
    ticker: str
    type: str
    strategy: str
    quantity: int
    open_date: date
    last_etrade_seen: Optional[datetime] = None


class ReconcileResponse(BaseModel):
    unmatched_etrade: list[UnmatchedEtradeItem]
    stale_backend: list[StaleBackendItem]
```

In `backend/app/schemas/positions.py`, change the existing import:
```python
from datetime import date
```
to:
```python
from datetime import date, datetime
```

- [ ] **Step 2: Add `last_etrade_seen` to TradeListItem**

In `backend/app/schemas/trade.py`, add `last_etrade_seen` to `TradeListItem` after `updated_at`:

```python
last_etrade_seen: Optional[datetime] = None
```

Also add `datetime` to the existing import: change `from datetime import date, datetime` (it's already there — confirm `datetime` is imported).

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/positions.py backend/app/schemas/trade.py
git commit -m "feat: add reconcile schemas and last_etrade_seen to TradeListItem"
```

---

## Task 3: Backend — reconcile endpoint + stale filter on trades list

**Files:**
- Modify: `backend/app/routers/positions.py`
- Modify: `backend/app/routers/trades.py`

- [ ] **Step 1: Add imports to positions.py**

In `backend/app/routers/positions.py`, change the existing import:
```python
from datetime import date, datetime, timezone
```
to:
```python
from datetime import date, datetime, timezone, timedelta
```

Also update the schema import to add the new reconcile types:
```python
from app.schemas.positions import (
    PositionsStatusRequest, PositionStatus, ActiveSignal, DashboardTodayItem,
    ReconcileRequest, ReconcileResponse, UnmatchedEtradeItem, StaleBackendItem,
)
```

- [ ] **Step 2: Add the reconcile endpoint to positions.py**

Add this function after the `positions_status` function (after line 156, before the `_pick_best_trade` function):

```python
@router.post("/positions/reconcile", response_model=ReconcileResponse)
async def reconcile_positions(
    payload: ReconcileRequest,
    db: AsyncSession = Depends(get_db),
) -> ReconcileResponse:
    # Single query: all open trades (needed for both matching and stale detection)
    all_open_stmt = select(Trade).where(Trade.status == "open")
    all_result = await db.execute(all_open_stmt)
    all_open_trades = all_result.scalars().all()

    ticker_trades: dict[str, list[Trade]] = {}
    for trade in all_open_trades:
        ticker_trades.setdefault(trade.ticker, []).append(trade)

    matched_ids: set = set()
    unmatched_etrade: list[UnmatchedEtradeItem] = []

    for pos in payload.positions:
        ticker = pos.ticker.upper()
        candidates = ticker_trades.get(ticker, [])

        trade = None
        if pos.full_symbol and candidates:
            trade = next((t for t in candidates if t.etrade_symbol == pos.full_symbol), None)
        if trade is None and candidates:
            trade = _pick_best_trade(candidates, pos)

        if trade is None:
            unmatched_etrade.append(UnmatchedEtradeItem(
                ticker=ticker,
                full_symbol=pos.full_symbol,
                option_type=pos.type,
                strike=pos.strike,
                expiry=pos.expiry,
            ))
        else:
            matched_ids.add(trade.id)

    now = datetime.now(timezone.utc)
    for trade in all_open_trades:
        if trade.id in matched_ids:
            trade.last_etrade_seen = now
    await db.commit()

    stale_threshold = now - timedelta(days=1)
    stale_backend = [
        StaleBackendItem(
            id=t.id,
            ticker=t.ticker,
            type=t.type,
            strategy=t.strategy,
            quantity=t.quantity,
            open_date=t.open_date,
            last_etrade_seen=t.last_etrade_seen,
        )
        for t in all_open_trades
        if t.id not in matched_ids
        and t.last_etrade_seen is not None
        and t.last_etrade_seen < stale_threshold
    ]

    return ReconcileResponse(unmatched_etrade=unmatched_etrade, stale_backend=stale_backend)
```

- [ ] **Step 3: Add `?stale=true` filter to GET /api/trades**

In `backend/app/routers/trades.py`:

1. Add to imports at the top:
```python
from datetime import datetime, timezone, timedelta
```

2. Add `stale: bool = Query(False)` parameter to `list_trades`:
```python
@router.get("", response_model=list[TradeListItem])
async def list_trades(
    status: Optional[str] = Query(None),
    ticker: Optional[str] = Query(None),
    strategy: Optional[str] = Query(None),
    wheel_id: Optional[uuid.UUID] = Query(None),
    etrade_symbol: Optional[str] = Query(None),
    stale: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Trade)
    if stale:
        threshold = datetime.now(timezone.utc) - timedelta(days=1)
        stmt = stmt.where(
            Trade.status == "open",
            Trade.last_etrade_seen.isnot(None),
            Trade.last_etrade_seen < threshold,
        )
    else:
        if status:
            stmt = stmt.where(Trade.status == status)
        if ticker:
            stmt = stmt.where(Trade.ticker == ticker.upper())
        if strategy:
            stmt = stmt.where(Trade.strategy == strategy)
        if wheel_id:
            stmt = stmt.where(Trade.wheel_id == wheel_id)
        if etrade_symbol:
            stmt = stmt.where(Trade.etrade_symbol == etrade_symbol)
    stmt = stmt.order_by(Trade.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/positions.py backend/app/routers/trades.py
git commit -m "feat: add reconcile endpoint and stale filter to trades list"
```

---

## Task 4: Backend tests for reconcile

**Files:**
- Create: `backend/tests/test_reconcile.py`

- [ ] **Step 1: Write all tests (they will fail until Task 3 is implemented — but Task 3 is already done, so they should pass)**

Create `backend/tests/test_reconcile.py`:

```python
import pytest
from datetime import date, datetime, timezone, timedelta
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

STOCK_TRADE = {
    "type": "Buy",
    "category": "WHEEL",
    "strategy": "Stock",
    "ticker": "AAPL",
    "open_date": str(date.today()),
    "quantity": 100,
}

PUT_TRADE = {
    "type": "Sell",
    "category": "WHEEL",
    "strategy": "Put",
    "ticker": "NVDA",
    "open_date": str(date.today()),
    "expiry_date": "2026-09-19",
    "strike_price": "120.00",
    "quantity": 1,
    "premium": "3.00",
}

RECONCILE_URL = "/api/positions/reconcile"


async def test_reconcile_returns_unmatched_position(client: AsyncClient):
    """Position in E*TRADE with no backend trade appears in unmatched_etrade."""
    await client.post("/api/trades", json=STOCK_TRADE)  # AAPL in backend

    resp = await client.post(RECONCILE_URL, json={
        "positions": [
            {"ticker": "TSLA", "full_symbol": None, "type": "Stock"},  # not in backend
        ]
    })
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["unmatched_etrade"]) == 1
    assert data["unmatched_etrade"][0]["ticker"] == "TSLA"
    assert data["stale_backend"] == []


async def test_reconcile_matched_trade_gets_last_etrade_seen(
    client: AsyncClient, db_session: AsyncSession
):
    """Matched trade has last_etrade_seen set to a recent timestamp."""
    from sqlalchemy import select
    from app.models.trade import Trade

    create_resp = await client.post("/api/trades", json=STOCK_TRADE)
    trade_id = create_resp.json()["id"]

    resp = await client.post(RECONCILE_URL, json={
        "positions": [{"ticker": "AAPL", "full_symbol": None, "type": "Stock"}]
    })
    assert resp.status_code == 200

    result = await db_session.execute(select(Trade).where(Trade.id == trade_id))
    trade = result.scalar_one()
    await db_session.refresh(trade)
    assert trade.last_etrade_seen is not None
    assert trade.last_etrade_seen > datetime.now(timezone.utc) - timedelta(minutes=1)


async def test_reconcile_stale_trade_in_stale_backend(
    client: AsyncClient, db_session: AsyncSession
):
    """Open trade with last_etrade_seen > 1 day ago that's absent from snapshot → stale_backend."""
    from sqlalchemy import select
    from app.models.trade import Trade

    create_resp = await client.post("/api/trades", json=STOCK_TRADE)
    trade_id = create_resp.json()["id"]

    # Backdate last_etrade_seen to 2 days ago
    result = await db_session.execute(select(Trade).where(Trade.id == trade_id))
    trade = result.scalar_one()
    trade.last_etrade_seen = datetime.now(timezone.utc) - timedelta(days=2)
    await db_session.commit()

    # Reconcile without AAPL in snapshot
    resp = await client.post(RECONCILE_URL, json={
        "positions": [{"ticker": "TSLA", "full_symbol": None, "type": "Stock"}]
    })
    assert resp.status_code == 200
    data = resp.json()
    stale_ids = [item["id"] for item in data["stale_backend"]]
    assert trade_id in stale_ids


async def test_reconcile_recently_seen_not_stale(
    client: AsyncClient, db_session: AsyncSession
):
    """Trade seen within the last hour is not stale even if absent from snapshot."""
    from sqlalchemy import select
    from app.models.trade import Trade

    create_resp = await client.post("/api/trades", json=STOCK_TRADE)
    trade_id = create_resp.json()["id"]

    result = await db_session.execute(select(Trade).where(Trade.id == trade_id))
    trade = result.scalar_one()
    trade.last_etrade_seen = datetime.now(timezone.utc) - timedelta(hours=1)
    await db_session.commit()

    resp = await client.post(RECONCILE_URL, json={
        "positions": [{"ticker": "TSLA", "full_symbol": None, "type": "Stock"}]
    })
    assert resp.status_code == 200
    data = resp.json()
    stale_ids = [item["id"] for item in data["stale_backend"]]
    assert trade_id not in stale_ids


async def test_reconcile_never_seen_not_stale(client: AsyncClient):
    """Trade with null last_etrade_seen is never flagged stale."""
    create_resp = await client.post("/api/trades", json=STOCK_TRADE)
    trade_id = create_resp.json()["id"]

    resp = await client.post(RECONCILE_URL, json={
        "positions": [{"ticker": "TSLA", "full_symbol": None, "type": "Stock"}]
    })
    assert resp.status_code == 200
    stale_ids = [item["id"] for item in resp.json()["stale_backend"]]
    assert trade_id not in stale_ids


async def test_reconcile_option_matched_by_strike_and_expiry(
    client: AsyncClient, db_session: AsyncSession
):
    """Option position matched by strike+expiry sets last_etrade_seen."""
    from sqlalchemy import select
    from app.models.trade import Trade

    create_resp = await client.post("/api/trades", json=PUT_TRADE)
    trade_id = create_resp.json()["id"]

    resp = await client.post(RECONCILE_URL, json={
        "positions": [{
            "ticker": "NVDA",
            "full_symbol": "NVDA--260919P00120000",
            "type": "Put",
            "strike": 120.0,
            "expiry": "2026-09-19",
        }]
    })
    assert resp.status_code == 200
    assert resp.json()["unmatched_etrade"] == []

    result = await db_session.execute(select(Trade).where(Trade.id == trade_id))
    trade = result.scalar_one()
    await db_session.refresh(trade)
    assert trade.last_etrade_seen is not None


async def test_list_trades_stale_filter(client: AsyncClient, db_session: AsyncSession):
    """GET /api/trades?stale=true returns only trades with old last_etrade_seen."""
    from sqlalchemy import select
    from app.models.trade import Trade

    # Create two trades
    r1 = await client.post("/api/trades", json=STOCK_TRADE)
    r2 = await client.post("/api/trades", json={**STOCK_TRADE, "ticker": "MSFT"})
    stale_id = r1.json()["id"]
    fresh_id = r2.json()["id"]

    # Backdate one
    result = await db_session.execute(select(Trade).where(Trade.id == stale_id))
    t = result.scalar_one()
    t.last_etrade_seen = datetime.now(timezone.utc) - timedelta(days=2)
    await db_session.commit()

    # MSFT has null last_etrade_seen — should not appear
    resp = await client.get("/api/trades?stale=true")
    assert resp.status_code == 200
    ids = [item["id"] for item in resp.json()]
    assert stale_id in ids
    assert fresh_id not in ids
```

- [ ] **Step 2: Run tests**

```bash
cd /Users/bishwajeetpaul/workspace/github/TradeMinder
docker compose exec backend pytest backend/tests/test_reconcile.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 3: Run full test suite to verify no regressions**

```bash
docker compose exec backend pytest backend/tests/ -v --tb=short
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_reconcile.py
git commit -m "test: add reconcile endpoint and stale filter tests"
```

---

## Task 5: Frontend types + API

**Files:**
- Modify: `frontend/src/types/index.ts`

- [ ] **Step 1: Add `last_etrade_seen` to the Trade interface**

In `frontend/src/types/index.ts`, add `last_etrade_seen` to the `Trade` interface after `updated_at` (line 71):

```typescript
last_etrade_seen: string | null
```

The `tradesApi.close(id)` method already exists in `frontend/src/api/trades.ts` — no changes needed to the API layer.

- [ ] **Step 2: Add a shared `isStale` utility function**

At the bottom of `frontend/src/types/index.ts`, add:

```typescript
export function isStale(trade: Trade): boolean {
  if (!trade.last_etrade_seen) return false
  return new Date(trade.last_etrade_seen) < new Date(Date.now() - 24 * 60 * 60 * 1000)
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd /Users/bishwajeetpaul/workspace/github/TradeMinder/frontend
npm run build 2>&1 | tail -20
```

Expected: no TypeScript errors (there may be type errors in pages/components that use `Trade` if they access `last_etrade_seen` — those will be fixed in Task 6).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/index.ts
git commit -m "feat: add last_etrade_seen and isStale to Trade type"
```

---

## Task 6: Frontend stale indicator in TradesPage and GroupedTradeTable

**Files:**
- Modify: `frontend/src/pages/TradesPage.tsx`
- Modify: `frontend/src/components/Trades/GroupedTradeTable.tsx`

- [ ] **Step 1: Update GroupedTradeTable to accept stale props and render stale UI**

Replace the Props interface and function signature in `frontend/src/components/Trades/GroupedTradeTable.tsx`:

```typescript
import { isStale } from '../../types'  // add to existing import

interface Props {
  trades: Trade[]
  onDelete: (id: string) => void
  onClose?: (id: string) => void   // NEW
  staleOnly?: boolean              // NEW
  statusFilter: string
}
```

Update function signature:
```typescript
export function GroupedTradeTable({ trades, onDelete, onClose, staleOnly, statusFilter }: Props) {
```

In the filtering step (inside the `categories.map` block, where `filtered` is computed, around line 174), update to:

```typescript
const filtered = (() => {
  let result = statusFilter ? allTrades.filter(t => t.status === statusFilter) : allTrades
  if (staleOnly) result = result.filter(isStale)
  return result
})()
```

In the trade row (around line 237), add the stale badge before the existing `<td>` columns. Replace the `<tr key={trade.id}...>` row block with:

```tsx
<tr
  key={trade.id}
  className={`hover:bg-gray-50 border-b border-gray-100 last:border-0 ${isStale(trade) ? 'bg-amber-50' : ''}`}
>
  <td className="w-8 px-2 py-3" />
  <td className="px-4 py-3 font-semibold">
    <Link to={`/trades/${trade.id}`} className="text-blue-600 hover:underline">{trade.ticker}</Link>
  </td>
  <td className="px-4 py-3">{trade.strategy}</td>
  <td className="px-4 py-3">{trade.type}</td>
  <td className="px-4 py-3">{trade.strike_price ?? '—'}</td>
  <td className="px-4 py-3">{trade.expiry_date ?? '—'}</td>
  <td className="px-4 py-3">{trade.quantity}</td>
  <td className="px-4 py-3">{trade.premium !== null ? `$${trade.premium}` : '—'}</td>
  <td className="px-4 py-3"><PnLDisplay value={trade.unrealized_pnl} /></td>
  <td className="px-4 py-3">
    <div className="flex items-center gap-1.5">
      <StatusBadge status={trade.status} />
      {isStale(trade) && (
        <span className="text-xs px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 border border-amber-300 whitespace-nowrap">
          Not in E*TRADE
        </span>
      )}
    </div>
  </td>
  <td className="px-4 py-3"><CommentaryCell tradeId={trade.id} ticker={trade.ticker} /></td>
  <td className="px-4 py-3">
    <div className="flex items-center gap-3">
      {trade.strategy === 'Stock' && trade.status === 'open' && (
        <Link to={`/scanner?ticker=${trade.ticker}`} className="text-blue-500 hover:text-blue-700 text-xs">Scan →</Link>
      )}
      {isStale(trade) && onClose && (
        <button
          onClick={() => onClose(trade.id)}
          className="text-amber-600 hover:text-amber-800 text-xs font-medium"
        >
          Mark Closed
        </button>
      )}
      <button onClick={() => onDelete(trade.id)} className="text-red-500 hover:text-red-700 text-xs">Delete</button>
    </div>
  </td>
</tr>
```

- [ ] **Step 2: Update TradesPage to add stale banner and handleClose**

Replace `frontend/src/pages/TradesPage.tsx` with:

```tsx
import { useState, useEffect } from 'react'
import { tradesApi } from '../api/trades'
import { technicalsApi } from '../api/technicals'
import type { Trade, TechnicalsData, TradeCreate } from '../types'
import { isStale } from '../types'
import { GroupedTradeTable } from '../components/Trades/GroupedTradeTable'
import { TradeForm } from '../components/Trades/TradeForm'

export function TradesPage() {
  const [trades, setTrades] = useState<Trade[]>([])
  const [showForm, setShowForm] = useState(false)
  const [statusFilter, setStatusFilter] = useState<string>('open')
  const [staleOnly, setStaleOnly] = useState(false)

  const load = async () => {
    const data = await tradesApi.list()
    setTrades(data)
  }

  useEffect(() => { load() }, [])

  const handleCreate = async (payload: TradeCreate, technicals: TechnicalsData | null) => {
    const trade = await tradesApi.create(payload)
    if (technicals) {
      try {
        await technicalsApi.saveTradeRationale(trade.id, technicals)
      } catch {
        console.warn('Technicals save failed — trade was created successfully')
      }
    }
    setShowForm(false)
    load()
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this trade?')) return
    await tradesApi.delete(id)
    load()
  }

  const handleClose = async (id: string) => {
    await tradesApi.close(id)
    load()
  }

  const staleCount = trades.filter(isStale).length

  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-4">
        <h1 className="text-2xl font-bold text-gray-900">Trades</h1>
        <button onClick={() => setShowForm(true)} className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700">
          + Add Trade
        </button>
      </div>

      {staleCount > 0 && (
        <div className="mb-4 flex items-center justify-between px-4 py-2 bg-amber-50 border border-amber-200 rounded-lg text-sm">
          <span className="text-amber-800">
            <strong>{staleCount}</strong> open {staleCount === 1 ? 'trade' : 'trades'} not seen in E*TRADE — may be closed
          </span>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setStaleOnly(v => !v)}
              className={`text-xs px-2 py-1 rounded border ${staleOnly ? 'bg-amber-200 border-amber-400 text-amber-900' : 'border-amber-300 text-amber-700 hover:bg-amber-100'}`}
            >
              {staleOnly ? 'Showing stale only' : 'Show stale only'}
            </button>
          </div>
        </div>
      )}

      <div className="mb-4 flex gap-2">
        {(['', 'open', 'closed', 'expired', 'assigned'] as const).map(s => (
          <button
            key={s}
            onClick={() => { setStatusFilter(s); setStaleOnly(false) }}
            className={`px-3 py-1 rounded text-sm border ${statusFilter === s && !staleOnly ? 'bg-blue-600 text-white border-blue-600' : 'border-gray-300 hover:bg-gray-50'}`}
          >
            {s || 'All'}
          </button>
        ))}
      </div>

      {showForm && (
        <div className="mb-6 p-4 bg-white border border-gray-200 rounded-lg">
          <h2 className="text-lg font-semibold mb-4">New Trade</h2>
          <TradeForm onSubmit={handleCreate} onCancel={() => setShowForm(false)} />
        </div>
      )}

      <div className="bg-white rounded-lg border border-gray-200">
        <GroupedTradeTable
          trades={trades}
          onDelete={handleDelete}
          onClose={handleClose}
          staleOnly={staleOnly}
          statusFilter={staleOnly ? 'open' : statusFilter}
        />
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd /Users/bishwajeetpaul/workspace/github/TradeMinder/frontend
npm run build 2>&1 | tail -20
```

Expected: 0 TypeScript errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/TradesPage.tsx frontend/src/components/Trades/GroupedTradeTable.tsx
git commit -m "feat: add stale trade indicator and Mark Closed to TradesPage"
```

---

## Task 7: Extension — reconcile call and "Add" pill

**Files:**
- Modify: `extension/content.js`

- [ ] **Step 1: Add `reconcileCache` and `lastReconcileKey` to state section**

In `extension/content.js`, after line 38 (after the `sessionCache` declaration), add:

```javascript
// full_symbol||ticker (uppercase) → true: position is in E*TRADE but not backend
const reconcileCache = new Map();
let lastReconcileKey = '';
```

- [ ] **Step 2: Add `fireReconcile` function**

Add this function after the `applyWheelPillToRow` function (after line 628):

```javascript
// ============================================================
// RECONCILIATION
// ============================================================
async function fireReconcile(rows) {
  const positions = [];
  const keys = [];

  rows.forEach(row => {
    const info = getRowInfo(row);
    if (!info) return;
    const key = info.fullSymbol || info.ticker;
    keys.push(key);
    positions.push({
      ticker: info.ticker,
      full_symbol: info.fullSymbol || null,
      type: info.optionDetails?.type || (info.isOption ? 'Option' : 'Stock'),
      strike: info.optionDetails?.strike || null,
      expiry: info.optionDetails?.expiry || null,
    });
  });

  if (positions.length === 0) return;

  const posKey = keys.slice().sort().join(',');
  if (posKey === lastReconcileKey) return; // visible positions unchanged
  lastReconcileKey = posKey;

  try {
    const resp = await fetch(`${tmApiUrl}/api/positions/reconcile`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ positions }),
      signal: AbortSignal.timeout(5000),
    });
    if (!resp.ok) return;
    const data = await resp.json();

    reconcileCache.clear();
    (data.unmatched_etrade || []).forEach(item => {
      reconcileCache.set((item.full_symbol || item.ticker).toUpperCase(), true);
    });

    // Re-apply reconcile pill to all currently visible rows
    document.querySelectorAll(ETRADE.positionRows).forEach(row => {
      const info = getRowInfo(row);
      if (info) applyReconcilePillToRow(row, info);
    });
  } catch (err) {
    if (err.name !== 'AbortError') {
      console.debug('TradeMinder: reconcile failed', err.message);
    }
  }
}

function applyReconcilePillToRow(row, info) {
  const badge = row.querySelector('.tm-badge');
  if (!badge) return;

  badge.querySelector('.tm-reconcile-pill')?.remove();

  const key = (info.fullSymbol || info.ticker).toUpperCase();
  if (!reconcileCache.has(key)) return;

  const pill = document.createElement('span');
  pill.className = 'tm-reconcile-pill';
  pill.textContent = '+ Add';
  pill.title = 'Not tracked in TradeMinder — click to add';
  pill.style.cssText = [
    'display:inline-flex',
    'align-items:center',
    'font-size:10px',
    'padding:1px 6px',
    'border-radius:3px',
    'margin-left:4px',
    'white-space:nowrap',
    'background:#FEF9C3',
    'color:#713F12',
    'border:1px solid #FDE047',
    'cursor:pointer',
  ].join(';');
  pill.addEventListener('click', e => {
    e.stopPropagation();
    showAddTradeModal(info);
  });
  badge.appendChild(pill);
}
```

- [ ] **Step 3: Call `fireReconcile` and `applyReconcilePillToRow` in `processVisibleRows`**

In `processVisibleRows`, add the reconcile call right after collecting `rows` and `toProcess` but before the early-return check (after the `seenTickers` forEach block, around line 376):

Replace the existing early-return check block:
```javascript
if (toProcess.length === 0) return;
```

With:
```javascript
// Fire-and-forget: reconcile all visible positions against backend
if (rows.length > 0) {
  fireReconcile(rows);
}

if (toProcess.length === 0) return;
```

Then in the **cached path** (inside the `if (statusCache.has(item.cacheKey))` block), add `applyReconcilePillToRow` after `applyWheelPillToRow`:

```javascript
applyTMToRow(item.row, statusCache.get(item.cacheKey), item.info);
applyFilter(item.row, statusCache.get(item.cacheKey));
applyRsiToRow(item.row, item.info.ticker);
applyWheelPillToRow(item.row, item.info.ticker);
applyReconcilePillToRow(item.row, item.info);  // ADD THIS LINE
```

In the **fetched path** (inside `needsFetch.forEach`, after `applyWheelPillToRow`):

```javascript
statusCache.set(item.cacheKey, status);
applyTMToRow(item.row, status, item.info);
applyFilter(item.row, status);
applyRsiToRow(item.row, item.info.ticker);
applyWheelPillToRow(item.row, item.info.ticker);
applyReconcilePillToRow(item.row, item.info);  // ADD THIS LINE
```

- [ ] **Step 4: Reset `lastReconcileKey` when rows are cleared**

In `clearTMFromRow`, no change needed — it removes `.tm-badge` which includes the reconcile pill.

Add `reconcileCache.clear()` call to reset state when the extension reloads. Find the place where `processedRows`, `statusCache`, etc. are reset (if there's a reset function). If not, no action needed — the cache auto-clears on next reconcile call.

- [ ] **Step 5: Load the extension and manually verify**

1. Open the E*TRADE positions page in Chrome.
2. Open DevTools → Application → Extensions → Reload TradeMinder.
3. Reload the E*TRADE positions page.
4. Verify: E*TRADE positions that have no backend record show an amber `+ Add` pill.
5. Click a `+ Add` pill — the existing add-trade modal should open pre-filled with the position data.
6. Verify: positions that DO have backend records show no `+ Add` pill.

- [ ] **Step 6: Commit**

```bash
git add extension/content.js
git commit -m "feat: add reconcile call and untracked position Add pill to extension"
```

---

## Self-Review Checklist (run before marking complete)

- [ ] All 7 backend reconcile tests pass: `pytest backend/tests/test_reconcile.py -v`
- [ ] Full backend test suite passes: `pytest backend/tests/ -v`
- [ ] Frontend TypeScript compiles: `npm run build` in `frontend/`
- [ ] Spec coverage confirmed:
  - Case 1 (new trade in E*TRADE not in backend) → extension "Add" pill ✓ Task 7
  - Case 2 (closed in E*TRADE not updated in backend) → frontend stale badge + Mark Closed ✓ Task 6
  - Case 3 (historical bulk cleanup) → reconcile endpoint + stale banner ✓ Tasks 3 + 6
  - `last_etrade_seen` never flags null entries as stale ✓ Task 4 test_reconcile_never_seen_not_stale
