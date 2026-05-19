# Strategy Labels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 6 generic category labels with 10 precise SNAKE_CASE trading-strategy labels, highlight trade rows by category color on the dashboard, add a dynamic category dropdown to all entry forms, and add a "View / Edit Entry" right-click context menu item in the E*TRADE extension.

**Architecture:** A new Alembic migration replaces the seeded categories and remaps existing trades. The backend gains an `etrade_symbol` filter on `GET /api/trades` and an extended `TradeUpdate` schema. The frontend fetches categories live from `/api/categories`. The extension gains a shared `fetchCategories()` helper used by both the Add and new Edit modals, and a second context menu item wired via `background.js`.

**Tech Stack:** FastAPI/SQLAlchemy (backend), React/TypeScript/Tailwind (frontend), Chrome MV3 content script (extension), PostgreSQL/Alembic (database), pytest-asyncio (backend tests)

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/alembic/versions/004_strategy_categories.py` | Create | Replace old categories, remap existing trades |
| `backend/app/schemas/trade.py` | Modify | Extend `TradeUpdate` with all editable fields |
| `backend/app/routers/trades.py` | Modify | Add `etrade_symbol` query param; update `category_id` on PATCH |
| `backend/tests/test_trades.py` | Modify | Tests for etrade_symbol filter and extended PATCH |
| `frontend/src/components/Trades/TradeForm.tsx` | Modify | Fetch categories from API instead of hardcoded list |
| `frontend/src/components/Trades/TradeTable.tsx` | Modify | Add CATEGORY_COLORS, apply left-border + tint per row |
| `extension/background.js` | Modify | Register `tm-view` context menu; update both items on hover |
| `extension/content.js` | Modify | `fetchCategories()` helper; refactor Add modal; add Edit modal |

---

## Task 1: DB Migration — Replace Category Seed Data

**Files:**
- Create: `backend/alembic/versions/004_strategy_categories.py`

- [ ] **Step 1: Create the migration file**

```python
# backend/alembic/versions/004_strategy_categories.py
"""replace strategy category labels

Revision ID: 004
Revises: 003
Create Date: 2026-05-18
"""
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Remove old system categories
    op.execute("DELETE FROM categories WHERE is_system = true")

    # 2. Insert 10 new system categories
    op.execute("""
        INSERT INTO categories (name, color, icon, is_system, sort_order) VALUES
          ('WHEEL',          '#3B82F6', '🔄', true,  1),
          ('SWING',          '#06B6D4', '📈', true,  2),
          ('HOLD',           '#10B981', '🌱', true,  3),
          ('LEAP',           '#8B5CF6', '🚀', true,  4),
          ('PUT_SPREAD',     '#F59E0B', '📉', true,  5),
          ('CALL_SPREAD',    '#F97316', '📈', true,  6),
          ('IRON_CONDOR',    '#EF4444', '🦅', true,  7),
          ('IRON_BUTTERFLY', '#EC4899', '🦋', true,  8),
          ('SKIP',           '#6B7280', '⏭',  true,  9),
          ('HOPS',           '#84CC16', '🌿', true, 10)
    """)

    # 3. Remap category string on existing trades
    op.execute("""
        UPDATE trades SET category = CASE category
          WHEN 'Wheel'           THEN 'WHEEL'
          WHEN 'Long Term'       THEN 'HOLD'
          WHEN 'Short Term'      THEN 'SWING'
          WHEN 'Speculative'     THEN 'SKIP'
          WHEN 'Momentum'        THEN 'SWING'
          WHEN 'Coach Suggested' THEN 'SKIP'
          ELSE category
        END
    """)

    # 4. Update category_id FK to point to new categories
    op.execute("""
        UPDATE trades t
        SET category_id = c.id
        FROM categories c
        WHERE c.name = t.category
    """)


def downgrade() -> None:
    # 1. Restore old system categories
    op.execute("""
        INSERT INTO categories (name, color, icon, is_system, sort_order) VALUES
          ('Wheel',           '#3B82F6', '🔄', true, 1),
          ('Speculative',     '#EF4444', '🎲', true, 2),
          ('Momentum',        '#F59E0B', '🚀', true, 3),
          ('Short Term',      '#8B5CF6', '⚡', true, 4),
          ('Long Term',       '#10B981', '🌱', true, 5),
          ('Coach Suggested', '#EC4899', '🎓', true, 6)
    """)

    # 2. Remap trades back (new-only categories fall back to Wheel)
    op.execute("""
        UPDATE trades SET category = CASE category
          WHEN 'WHEEL'          THEN 'Wheel'
          WHEN 'HOLD'           THEN 'Long Term'
          WHEN 'SWING'          THEN 'Short Term'
          WHEN 'SKIP'           THEN 'Speculative'
          WHEN 'LEAP'           THEN 'Wheel'
          WHEN 'PUT_SPREAD'     THEN 'Wheel'
          WHEN 'CALL_SPREAD'    THEN 'Wheel'
          WHEN 'IRON_CONDOR'    THEN 'Speculative'
          WHEN 'IRON_BUTTERFLY' THEN 'Speculative'
          WHEN 'HOPS'           THEN 'Wheel'
          ELSE 'Wheel'
        END
    """)

    # 3. Remove new system categories
    op.execute("""
        DELETE FROM categories WHERE is_system = true
          AND name IN (
            'WHEEL','SWING','HOLD','LEAP','PUT_SPREAD','CALL_SPREAD',
            'IRON_CONDOR','IRON_BUTTERFLY','SKIP','HOPS'
          )
    """)

    # 4. Restore category_id FK
    op.execute("""
        UPDATE trades t
        SET category_id = c.id
        FROM categories c
        WHERE c.name = t.category
    """)
```

- [ ] **Step 2: Run the migration**

```bash
cd backend && alembic upgrade head
```

Expected: `Running upgrade 003 -> 004, replace strategy category labels`

- [ ] **Step 3: Verify categories and remapping**

```bash
cd backend && python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
import os

engine = create_async_engine(os.environ['DATABASE_URL'])

async def check():
    async with engine.connect() as conn:
        cats = await conn.execute(text('SELECT name, color FROM categories ORDER BY sort_order'))
        print('Categories:', [r[0] for r in cats])
        trades = await conn.execute(text('SELECT DISTINCT category FROM trades'))
        print('Trade categories:', [r[0] for r in trades])

asyncio.run(check())
"
```

Expected: Categories list shows the 10 new SNAKE_CASE names. Trade categories show only new values.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/004_strategy_categories.py
git commit -m "feat: replace category seed data with 10 strategy labels"
```

---

## Task 2: Backend — etrade_symbol Filter + Extended TradeUpdate

**Files:**
- Modify: `backend/app/schemas/trade.py`
- Modify: `backend/app/routers/trades.py`
- Modify: `backend/tests/test_trades.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/test_trades.py`:

```python
async def test_filter_trades_by_etrade_symbol(client: AsyncClient):
    payload = {**TRADE_PAYLOAD, "etrade_symbol": "AAPL--260508P00180000"}
    await client.post("/api/trades", json=payload)
    response = await client.get("/api/trades?etrade_symbol=AAPL--260508P00180000")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["ticker"] == "AAPL"


async def test_filter_trades_by_etrade_symbol_no_match(client: AsyncClient):
    await client.post("/api/trades", json=TRADE_PAYLOAD)
    response = await client.get("/api/trades?etrade_symbol=NONEXISTENT")
    assert response.status_code == 200
    assert response.json() == []


async def test_patch_trade_category_and_quantity(client: AsyncClient):
    create_resp = await client.post("/api/trades", json=TRADE_PAYLOAD)
    trade_id = create_resp.json()["id"]
    response = await client.patch(
        f"/api/trades/{trade_id}",
        json={"category": "SWING", "quantity": 3, "premium": "4.20"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["category"] == "SWING"
    assert data["quantity"] == 3
    assert float(data["premium"]) == 4.20
```

- [ ] **Step 2: Run to confirm failures**

```bash
cd backend && pytest tests/test_trades.py::test_filter_trades_by_etrade_symbol tests/test_trades.py::test_patch_trade_category_and_quantity -v
```

Expected: FAIL — `etrade_symbol` query param not accepted; PATCH rejects unknown fields.

- [ ] **Step 3: Extend TradeUpdate schema**

Replace `TradeUpdate` in `backend/app/schemas/trade.py`:

```python
class TradeUpdate(BaseModel):
    # Fields editable from the extension Edit modal
    type: Optional[str] = None
    category: Optional[str] = None
    strategy: Optional[str] = None
    strike_price: Optional[Decimal] = None
    expiry_date: Optional[date] = None
    quantity: Optional[int] = None
    premium: Optional[Decimal] = None
    collateral: Optional[Decimal] = None
    exit_strategy: Optional[str] = None
    rationale_notes: Optional[str] = None  # maps to trade.rationale.notes
    signal_action: Optional[str] = None
    status: Optional[Literal["open", "closed", "expired", "assigned"]] = None
    current_price: Optional[Decimal] = None
    unrealized_pnl: Optional[Decimal] = None
```

- [ ] **Step 4: Add etrade_symbol filter and fix PATCH handler in trades.py**

Replace the `list_trades` function signature and body, and the `update_trade` body in `backend/app/routers/trades.py`. Also add the `Category` import:

```python
# Add to imports at top of trades.py:
from app.models.category import Category
```

```python
@router.get("", response_model=list[TradeListItem])
async def list_trades(
    status: Optional[str] = Query(None),
    ticker: Optional[str] = Query(None),
    strategy: Optional[str] = Query(None),
    wheel_id: Optional[uuid.UUID] = Query(None),
    etrade_symbol: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Trade)
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

```python
@router.patch("/{trade_id}", response_model=TradeResponse)
async def update_trade(trade_id: uuid.UUID, payload: TradeUpdate, db: AsyncSession = Depends(get_db)):
    stmt = select(Trade).where(Trade.id == trade_id).options(selectinload(Trade.rationale))
    result = await db.execute(stmt)
    trade = result.scalar_one_or_none()
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found")

    data = payload.model_dump(exclude_none=True)

    # Handle rationale_notes separately — stored in the related Rationale row
    rationale_notes = data.pop('rationale_notes', None)

    # When category string changes, sync category_id FK
    if 'category' in data:
        cat_result = await db.execute(select(Category).where(Category.name == data['category']))
        cat = cat_result.scalar_one_or_none()
        trade.category_id = cat.id if cat else None

    for field, value in data.items():
        setattr(trade, field, value)

    if rationale_notes is not None and trade.rationale:
        trade.rationale.notes = rationale_notes

    await db.commit()
    stmt2 = select(Trade).where(Trade.id == trade_id).options(selectinload(Trade.rationale))
    result2 = await db.execute(stmt2)
    trade = result2.scalar_one()
    return trade
```

- [ ] **Step 5: Run tests**

```bash
cd backend && pytest tests/test_trades.py -v
```

Expected: All tests PASS including the 3 new ones.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/trade.py backend/app/routers/trades.py backend/tests/test_trades.py
git commit -m "feat: add etrade_symbol filter to GET /api/trades; extend TradeUpdate schema"
```

---

## Task 3: Frontend — TradeForm Category Dropdown from API

**Files:**
- Modify: `frontend/src/components/Trades/TradeForm.tsx`

- [ ] **Step 1: Add a Category type and fetch categories on mount**

Replace the top of `TradeForm.tsx` with the following (keep all JSX below `handleSubmit` unchanged):

```tsx
// frontend/src/components/Trades/TradeForm.tsx
import { useState, useEffect } from 'react'
import type { TradeCreate } from '../../types'

interface Category {
  id: string
  name: string
  color: string
}

interface Props {
  onSubmit: (payload: TradeCreate) => Promise<void>
  onCancel: () => void
}

const STRATEGIES = ['Stock', 'Put', 'Call', 'CoveredCall', 'PutCreditSpread', 'Leap']
const TYPES = ['Buy', 'Sell', 'Assigned']

export function TradeForm({ onSubmit, onCancel }: Props) {
  const today = new Date().toISOString().split('T')[0]
  const [form, setForm] = useState<TradeCreate>({
    type: 'Sell',
    category: 'WHEEL',
    strategy: 'Put',
    ticker: '',
    open_date: today,
    quantity: 1,
  })
  const [categories, setCategories] = useState<Category[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/categories')
      .then(r => r.json())
      .then((data: Category[]) => setCategories(data))
      .catch(() => {})
  }, [])

  const set = (field: keyof TradeCreate, value: unknown) =>
    setForm(prev => ({ ...prev, [field]: value }))
```

- [ ] **Step 2: Replace the Category select in the JSX**

Find the Category `<div>` block (currently rendering `CATEGORIES.map`) and replace it:

```tsx
        <div>
          <label className="block text-sm font-medium text-gray-700">Category *</label>
          <select value={form.category} onChange={e => set('category', e.target.value)} className="mt-1 block w-full border border-gray-300 rounded px-3 py-2 text-sm">
            {categories.length === 0
              ? <option value="" disabled>Loading...</option>
              : categories.map(c => <option key={c.id} value={c.name}>{c.name}</option>)
            }
          </select>
        </div>
```

- [ ] **Step 3: Build and check for type errors**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

Expected: Build succeeds with 0 errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Trades/TradeForm.tsx
git commit -m "feat: fetch categories from API in TradeForm dropdown"
```

---

## Task 4: Frontend — TradeTable Row Highlighting

**Files:**
- Modify: `frontend/src/components/Trades/TradeTable.tsx`

- [ ] **Step 1: Add CATEGORY_COLORS and apply to rows**

Replace the full content of `TradeTable.tsx`:

```tsx
// frontend/src/components/Trades/TradeTable.tsx
import { Link } from 'react-router-dom'
import type { Trade } from '../../types'
import { StatusBadge } from '../shared/StatusBadge'
import { PnLDisplay } from '../shared/PnLDisplay'
import { CommentaryCell } from './CommentaryCell'

interface Props {
  trades: Trade[]
  onDelete: (id: string) => void
}

const CATEGORY_COLORS: Record<string, string> = {
  WHEEL:          '#3B82F6',
  SWING:          '#06B6D4',
  HOLD:           '#10B981',
  LEAP:           '#8B5CF6',
  PUT_SPREAD:     '#F59E0B',
  CALL_SPREAD:    '#F97316',
  IRON_CONDOR:    '#EF4444',
  IRON_BUTTERFLY: '#EC4899',
  SKIP:           '#6B7280',
  HOPS:           '#84CC16',
}

export function TradeTable({ trades, onDelete }: Props) {
  if (trades.length === 0) {
    return <p className="text-gray-500 text-center py-8">No trades yet. Add your first trade.</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead className="bg-gray-50">
          <tr>
            {['Ticker', 'Category', 'Strategy', 'Type', 'Strike', 'Expiry', 'Qty', 'Premium', 'P&L', 'Status', 'Commentary', ''].map(h => (
              <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {trades.map(trade => {
            const color = CATEGORY_COLORS[trade.category]
            const rowStyle = color
              ? { borderLeft: `3px solid ${color}`, backgroundColor: `${color}14` }
              : {}
            return (
              <tr key={trade.id} style={rowStyle} className="hover:brightness-95">
                <td className="px-4 py-3 font-semibold">
                  <Link to={`/trades/${trade.id}`} className="text-blue-600 hover:underline">
                    {trade.ticker}
                  </Link>
                </td>
                <td className="px-4 py-3">
                  {color
                    ? <span style={{ color, fontWeight: 600, fontSize: '0.75rem' }}>{trade.category}</span>
                    : <span className="text-gray-500">{trade.category}</span>
                  }
                </td>
                <td className="px-4 py-3">{trade.strategy}</td>
                <td className="px-4 py-3">{trade.type}</td>
                <td className="px-4 py-3">{trade.strike_price ?? '—'}</td>
                <td className="px-4 py-3">{trade.expiry_date ?? '—'}</td>
                <td className="px-4 py-3">{trade.quantity}</td>
                <td className="px-4 py-3">{trade.premium !== null ? `$${trade.premium}` : '—'}</td>
                <td className="px-4 py-3"><PnLDisplay value={trade.unrealized_pnl} /></td>
                <td className="px-4 py-3"><StatusBadge status={trade.status} /></td>
                <td className="px-4 py-3">
                  <CommentaryCell tradeId={trade.id} ticker={trade.ticker} />
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-3">
                    {trade.strategy === 'Stock' && trade.status === 'open' && (
                      <Link
                        to={`/scanner?ticker=${trade.ticker}`}
                        className="text-blue-500 hover:text-blue-700 text-xs"
                      >
                        Scan →
                      </Link>
                    )}
                    <button
                      onClick={() => onDelete(trade.id)}
                      className="text-red-500 hover:text-red-700 text-xs"
                    >
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
```

- [ ] **Step 2: Build and check**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

Expected: Build succeeds with 0 errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Trades/TradeTable.tsx
git commit -m "feat: highlight trade rows by category color in TradeTable"
```

---

## Task 5: Extension — Dynamic Category Fetch Helper + Refactor Add Modal

**Files:**
- Modify: `extension/content.js`

- [ ] **Step 1: Add fetchCategories and buildCategoryOptions helpers**

Find the comment `// ADD TRADE MODAL` section (around line 810) and insert these two functions immediately before `function showAddTradeModal(info)`:

```js
// ============================================================
// CATEGORY HELPERS
// ============================================================
async function fetchCategories() {
  try {
    const resp = await fetch(`${tmApiUrl}/api/categories`, { signal: AbortSignal.timeout(5000) });
    if (!resp.ok) return [];
    return await resp.json();
  } catch (_) {
    return [];
  }
}

function buildCategoryOptions(categories, selectedValue = 'WHEEL') {
  if (categories.length === 0) {
    return '<option value="" disabled selected>(categories unavailable)</option>';
  }
  return categories
    .map(c => `<option value="${c.name}"${c.name === selectedValue ? ' selected' : ''}>${c.name}</option>`)
    .join('');
}
```

- [ ] **Step 2: Make showAddTradeModal async and replace hardcoded category options**

Change the function signature and add the categories fetch at the top:

```js
async function showAddTradeModal(info) {
  if (document.getElementById('tm-modal-overlay')) return;

  const categories = await fetchCategories();
  const today = new Date().toISOString().split('T')[0];

  const defaultType = info.isOption ? 'Sell' : 'Buy';
  const defaultStrategy = info.isOption
    ? (info.type === 'Put' ? 'Sell Put' : 'Sell Call')
    : 'Stock';
```

Then find the category `<select>` block inside `overlay.innerHTML` (currently has hardcoded `<option>` tags for Wheel, Speculative, etc.) and replace it with:

```js
        <div class="tm-field-row tm-field-full">
          <label>Category <span class="tm-required">*</span></label>
          <select name="category">
            ${buildCategoryOptions(categories, 'WHEEL')}
          </select>
        </div>
```

- [ ] **Step 3: Verify the extension loads without JS errors**

Load the extension in Chrome (`chrome://extensions` → Reload), navigate to the E*TRADE positions page, open DevTools Console. Right-click a row → "Add to TradeMinder". Confirm:
- No console errors
- Category dropdown shows WHEEL, SWING, HOLD, LEAP, PUT_SPREAD, CALL_SPREAD, IRON_CONDOR, IRON_BUTTERFLY, SKIP, HOPS

- [ ] **Step 4: Commit**

```bash
git add extension/content.js
git commit -m "feat: fetch categories dynamically in Add Trade extension modal"
```

---

## Task 6: Extension — tm-view Context Menu Item

**Files:**
- Modify: `extension/background.js`

- [ ] **Step 1: Register tm-view on install and update both items on ROW_CONTEXT**

Replace the full content of `extension/background.js`:

```js
// background.js — service worker
// Provides API URL to content script and manages settings

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.get(['tmApiUrl', 'tmStages'], (result) => {
    if (!result.tmApiUrl) {
      chrome.storage.local.set({ tmApiUrl: 'http://localhost:5431' });
    }
    if (!result.tmStages) {
      chrome.storage.local.set({
        tmStages: { stage1: true, stage2: true, stage3: true, stage4: true }
      });
    }
  });

  chrome.contextMenus.create({
    id: 'tm-add',
    title: 'Add to TradeMinder',
    contexts: ['page'],
    documentUrlPatterns: ['https://*.etrade.com/*'],
  });

  chrome.contextMenus.create({
    id: 'tm-view',
    title: 'View / Edit Entry',
    contexts: ['page'],
    documentUrlPatterns: ['https://*.etrade.com/*'],
  });
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'GET_SETTINGS') {
    chrome.storage.local.get(['tmApiUrl', 'tmStages'], (result) => {
      sendResponse({
        apiUrl: result.tmApiUrl || 'http://localhost:5431',
        stages: result.tmStages || { stage1: true, stage2: true, stage3: true, stage4: true },
      });
    });
    return true;
  }

  if (message.type === 'ROW_CONTEXT') {
    const isTracked = message.isTracked;
    chrome.contextMenus.update('tm-add', {
      title: isTracked ? 'Already in TradeMinder' : 'Add to TradeMinder',
      enabled: !isTracked,
    });
    chrome.contextMenus.update('tm-view', {
      title: isTracked ? 'View / Edit Entry' : 'Not in TradeMinder',
      enabled: !!isTracked,
    });
    chrome.storage.session
      ? chrome.storage.session.set({ tmPendingRow: message.info })
      : chrome.storage.local.set({ tmPendingRow: message.info });
    sendResponse({ ok: true });
    return true;
  }
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (!tab?.id) return;

  const fetchPending = (cb) => {
    if (chrome.storage.session) {
      chrome.storage.session.get('tmPendingRow', (r) => cb(r.tmPendingRow || null));
    } else {
      chrome.storage.local.get('tmPendingRow', (r) => cb(r.tmPendingRow || null));
    }
  };

  if (info.menuItemId === 'tm-add') {
    fetchPending((rowInfo) => {
      chrome.tabs.sendMessage(tab.id, { type: 'SHOW_ADD_MODAL', info: rowInfo });
    });
  }

  if (info.menuItemId === 'tm-view') {
    fetchPending((rowInfo) => {
      chrome.tabs.sendMessage(tab.id, { type: 'SHOW_EDIT_MODAL', info: rowInfo });
    });
  }
});
```

- [ ] **Step 2: Reload extension and verify both menu items appear**

In Chrome → `chrome://extensions` → Reload TradeMinder. Navigate to E*TRADE positions. Right-click an untracked row — confirm only "Add to TradeMinder" is enabled. Right-click a tracked row — confirm "Add to TradeMinder" is disabled and "View / Edit Entry" is enabled.

- [ ] **Step 3: Commit**

```bash
git add extension/background.js
git commit -m "feat: add View/Edit Entry context menu item to extension"
```

---

## Task 7: Extension — Edit Trade Modal

**Files:**
- Modify: `extension/content.js`

- [ ] **Step 1: Add the SHOW_EDIT_MODAL message handler**

Find the existing `SHOW_ADD_MODAL` handler (around line 804):

```js
chrome.runtime.onMessage.addListener((message) => {
  if (message.type === 'SHOW_ADD_MODAL') {
    showAddTradeModal(message.info || {});
  }
});
```

Replace it with:

```js
chrome.runtime.onMessage.addListener((message) => {
  if (message.type === 'SHOW_ADD_MODAL') {
    showAddTradeModal(message.info || {});
  }
  if (message.type === 'SHOW_EDIT_MODAL') {
    showEditTradeModal(message.info || {});
  }
});
```

- [ ] **Step 2: Add showEditTradeModal function**

Add the following function immediately after `showAddTradeModal` (after its closing `}` around line 972):

```js
// ============================================================
// EDIT TRADE MODAL
// ============================================================
async function showEditTradeModal(info) {
  if (document.getElementById('tm-modal-overlay')) return;

  // 1. Look up the trade by etrade_symbol or ticker fallback
  let tradeId;
  let trade;
  try {
    const searchUrl = info.fullSymbol
      ? `${tmApiUrl}/api/trades?etrade_symbol=${encodeURIComponent(info.fullSymbol)}`
      : `${tmApiUrl}/api/trades?ticker=${encodeURIComponent(info.ticker || '')}&status=open`;
    const searchResp = await fetch(searchUrl, { signal: AbortSignal.timeout(6000) });
    if (!searchResp.ok) throw new Error(`HTTP ${searchResp.status}`);
    const matches = await searchResp.json();
    if (!matches.length) {
      alert('Trade not found in TradeMinder. Add it first via "Add to TradeMinder".');
      return;
    }
    tradeId = matches[0].id;
  } catch (err) {
    alert('Could not reach TradeMinder backend: ' + (err.message || 'unknown error'));
    return;
  }

  // 2. Fetch full trade detail (includes rationale.notes)
  try {
    const detailResp = await fetch(`${tmApiUrl}/api/trades/${tradeId}`, { signal: AbortSignal.timeout(6000) });
    if (!detailResp.ok) throw new Error(`HTTP ${detailResp.status}`);
    trade = await detailResp.json();
  } catch (err) {
    alert('Failed to load trade details: ' + (err.message || 'unknown error'));
    return;
  }

  // 3. Fetch categories for the dropdown
  const categories = await fetchCategories();

  // 4. Render modal
  const overlay = document.createElement('div');
  overlay.id = 'tm-modal-overlay';

  overlay.innerHTML = `
    <div id="tm-modal">
      <div id="tm-modal-header">
        <span id="tm-modal-title">✏️ Edit Trade — ${trade.ticker}</span>
        <button id="tm-modal-close" title="Close">✕</button>
      </div>
      <form id="tm-modal-form" autocomplete="off">
        <div class="tm-field-row">
          <label>Type</label>
          <select name="type">
            <option value="Sell" ${trade.type === 'Sell' ? 'selected' : ''}>Sell</option>
            <option value="Buy" ${trade.type === 'Buy' ? 'selected' : ''}>Buy</option>
            <option value="Assigned" ${trade.type === 'Assigned' ? 'selected' : ''}>Assigned</option>
          </select>
        </div>
        <div class="tm-field-row">
          <label>Strategy</label>
          <select name="strategy">
            <option value="Sell Put" ${trade.strategy === 'Sell Put' ? 'selected' : ''}>Sell Put</option>
            <option value="Sell Call" ${trade.strategy === 'Sell Call' ? 'selected' : ''}>Sell Call</option>
            <option value="Buy Put" ${trade.strategy === 'Buy Put' ? 'selected' : ''}>Buy Put</option>
            <option value="Buy Call" ${trade.strategy === 'Buy Call' ? 'selected' : ''}>Buy Call</option>
            <option value="Put Credit Spread" ${trade.strategy === 'Put Credit Spread' ? 'selected' : ''}>Put Credit Spread</option>
            <option value="Call Credit Spread" ${trade.strategy === 'Call Credit Spread' ? 'selected' : ''}>Call Credit Spread</option>
            <option value="Covered Call" ${trade.strategy === 'Covered Call' ? 'selected' : ''}>Covered Call</option>
            <option value="Stock" ${trade.strategy === 'Stock' ? 'selected' : ''}>Stock</option>
          </select>
        </div>
        <div class="tm-field-row tm-field-full">
          <label>Category <span class="tm-required">*</span></label>
          <select name="category">
            ${buildCategoryOptions(categories, trade.category || 'WHEEL')}
          </select>
        </div>
        <div class="tm-field-row">
          <label>Strike</label>
          <input type="number" name="strike_price" step="0.01" value="${trade.strike_price != null ? trade.strike_price : ''}" placeholder="optional" />
        </div>
        <div class="tm-field-row">
          <label>Expiry</label>
          <input type="date" name="expiry_date" value="${trade.expiry_date || ''}" />
        </div>
        <div class="tm-field-row">
          <label>Qty</label>
          <input type="number" name="quantity" min="1" step="1" value="${trade.quantity}" required />
        </div>
        <div class="tm-field-row">
          <label>Premium</label>
          <input type="number" name="premium" step="0.01" min="0" value="${trade.premium != null ? trade.premium : ''}" placeholder="0.00" />
        </div>
        <div class="tm-field-row tm-field-full">
          <label>Exit Strategy</label>
          <input type="text" name="exit_strategy" value="${trade.exit_strategy ? trade.exit_strategy.replace(/"/g, '&quot;') : ''}" placeholder="e.g. Close at 50% profit" />
        </div>
        <div class="tm-field-row tm-field-full">
          <label>Notes</label>
          <textarea name="rationale_notes" rows="2">${trade.rationale?.notes || ''}</textarea>
        </div>
        <div id="tm-modal-error" class="tm-hidden"></div>
        <div id="tm-modal-actions">
          <button type="button" id="tm-modal-cancel">Cancel</button>
          <button type="submit" id="tm-modal-submit">Save Changes</button>
        </div>
      </form>
    </div>`;

  document.body.appendChild(overlay);

  const closeModal = () => overlay.remove();
  overlay.querySelector('#tm-modal-close').addEventListener('click', closeModal);
  overlay.querySelector('#tm-modal-cancel').addEventListener('click', closeModal);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) closeModal(); });

  overlay.querySelector('#tm-modal-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const errorEl = overlay.querySelector('#tm-modal-error');
    const submitBtn = overlay.querySelector('#tm-modal-submit');
    errorEl.classList.add('tm-hidden');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Saving…';

    const fd = new FormData(e.target);
    const strike_price = fd.get('strike_price') ? parseFloat(fd.get('strike_price')) : null;
    const expiry_date = fd.get('expiry_date') || null;
    const premium = fd.get('premium') ? parseFloat(fd.get('premium')) : null;
    const payload = {
      type: fd.get('type'),
      strategy: fd.get('strategy'),
      category: fd.get('category'),
      quantity: parseInt(fd.get('quantity'), 10),
      exit_strategy: fd.get('exit_strategy') || null,
      rationale_notes: fd.get('rationale_notes')?.trim() || null,
      ...(strike_price != null && { strike_price }),
      ...(expiry_date && { expiry_date }),
      ...(premium != null && { premium }),
    };

    try {
      const resp = await fetch(`${tmApiUrl}/api/trades/${tradeId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(8000),
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${resp.status}`);
      }

      // Invalidate cache so the row badge refreshes
      const cacheKey = info.fullSymbol || info.ticker;
      statusCache.delete(cacheKey);
      if (info.ticker) statusCache.delete(info.ticker);
      processedRows.forEach((val, key) => {
        if (val === cacheKey || val === info.ticker) processedRows.delete(key);
      });
      processVisibleRows();
      closeModal();

    } catch (err) {
      errorEl.textContent = err.message || 'Failed to save changes';
      errorEl.classList.remove('tm-hidden');
      submitBtn.disabled = false;
      submitBtn.textContent = 'Save Changes';
    }
  });
}
```

- [ ] **Step 3: Reload extension and test the full flow**

1. Reload the extension in Chrome.
2. Navigate to E*TRADE positions page.
3. Right-click a tracked trade row → "View / Edit Entry".
4. Confirm the modal opens pre-filled with the trade's current values.
5. Change the category to a different value.
6. Click "Save Changes".
7. Confirm no error, modal closes, row badge refreshes.
8. Right-click again → "View / Edit Entry" → confirm the new category is now pre-filled.

- [ ] **Step 4: Commit**

```bash
git add extension/content.js
git commit -m "feat: add View/Edit Entry modal to extension with pre-filled form and PATCH save"
```

---

## Self-Review Checklist

- [x] **Migration** — deletes old system categories, inserts 10 new, remaps category string, updates category_id FK
- [x] **etrade_symbol filter** — covered in Task 2, tested with 3 new tests
- [x] **TradeUpdate schema** — all extension-editable fields added; rationale_notes handled separately
- [x] **category_id sync on PATCH** — handled in update_trade with Category lookup
- [x] **TradeForm** — fetches from /api/categories, falls back to Loading state
- [x] **TradeTable** — CATEGORY_COLORS constant, left-border + tinted row, Category column added
- [x] **Extension Add modal** — async, fetchCategories() called at open, hardcoded options removed
- [x] **Extension background.js** — tm-view registered; both items updated on ROW_CONTEXT
- [x] **Extension Edit modal** — two-step lookup (symbol → detail), pre-filled form, PATCH on submit, cache invalidation
- [x] **No placeholders** — every step has actual code
- [x] **Type consistency** — `buildCategoryOptions` defined in Task 5, used in Tasks 5 and 7; `fetchCategories` defined in Task 5, used in Tasks 5 and 7
