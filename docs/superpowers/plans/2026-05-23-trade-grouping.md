# Trade Grouping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat trade table with a grouped view organised by category, with collapsible sections, client-side status filtering (default: open), sort by Ticker/Expiry, and drag-to-reorder groups persisted to localStorage.

**Architecture:** All trades are fetched once with no server-side filter (`tradesApi.list()` with no args). `GroupedTradeTable` receives all trades + the current `statusFilter` string and handles grouping, filtering, sorting, collapse, and drag-to-reorder internally. Group order is saved to `localStorage` under key `trademinder_group_order`.

**Tech Stack:** React 19, TypeScript 6, Tailwind CSS 3, React Router 7, HTML5 Drag-and-Drop API, localStorage. No new dependencies.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `frontend/src/components/Trades/categories.ts` | **Create** | Single source of truth for `CATEGORY_COLORS` and `CATEGORY_ORDER` |
| `frontend/src/components/Trades/GroupedTradeTable.tsx` | **Create** | Grouped table: sort, collapse, drag-to-reorder, filter, empty state |
| `frontend/src/components/Trades/TradeTable.tsx` | **Modify** | Import `CATEGORY_COLORS` from `categories.ts` instead of defining inline |
| `frontend/src/pages/TradesPage.tsx` | **Modify** | Default filter `'open'`, fetch all trades, swap `TradeTable` → `GroupedTradeTable` |

---

### Task 1: Extract CATEGORY_COLORS to shared file

**Files:**
- Create: `frontend/src/components/Trades/categories.ts`
- Modify: `frontend/src/components/Trades/TradeTable.tsx`

- [ ] **Step 1: Create `categories.ts`**

Create `frontend/src/components/Trades/categories.ts` with the exact values from `TradeTable.tsx`:

```ts
export const CATEGORY_COLORS: Record<string, string> = {
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

export const CATEGORY_ORDER = Object.keys(CATEGORY_COLORS)
```

- [ ] **Step 2: Update `TradeTable.tsx` to import from `categories.ts`**

In `frontend/src/components/Trades/TradeTable.tsx`:

Remove the inline constant (lines 13–24):
```ts
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
```

Add this import after the existing imports at the top:
```ts
import { CATEGORY_COLORS } from './categories'
```

- [ ] **Step 3: Verify the existing Trades page still renders correctly**

Start the frontend dev server:
```bash
cd frontend && npm run dev
```

Navigate to `http://localhost:5173/trades`. Confirm:
- Trade rows still have category-color left borders
- Category labels are still colored
- No console errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Trades/categories.ts frontend/src/components/Trades/TradeTable.tsx
git commit -m "refactor: extract CATEGORY_COLORS to shared categories.ts"
```

---

### Task 2: Create GroupedTradeTable — grouping, filtering, sorting, empty state

No collapse or drag yet. This task produces a fully functional grouped table (static layout).

**Files:**
- Create: `frontend/src/components/Trades/GroupedTradeTable.tsx`

- [ ] **Step 1: Create `GroupedTradeTable.tsx`**

Create `frontend/src/components/Trades/GroupedTradeTable.tsx`:

```tsx
import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { Trade } from '../../types'
import { StatusBadge } from '../shared/StatusBadge'
import { PnLDisplay } from '../shared/PnLDisplay'
import { CommentaryCell } from './CommentaryCell'
import { CATEGORY_COLORS, CATEGORY_ORDER } from './categories'

interface Props {
  trades: Trade[]
  onDelete: (id: string) => void
  statusFilter: string
}

type SortKey = 'ticker' | 'expiry'

// Number of <th>/<td> columns: handle + ticker + strategy + type + strike + expiry + qty + premium + p&l + status + commentary + actions
const COL_COUNT = 12

function groupTrades(trades: Trade[]): Map<string, Trade[]> {
  const map = new Map<string, Trade[]>()
  for (const trade of trades) {
    const key = CATEGORY_COLORS[trade.category] ? trade.category : 'Other'
    if (!map.has(key)) map.set(key, [])
    map.get(key)!.push(trade)
  }
  return map
}

function statusBreakdown(trades: Trade[]): string {
  const counts: Record<string, number> = {}
  for (const t of trades) counts[t.status] = (counts[t.status] ?? 0) + 1
  const parts = Object.entries(counts).map(([s, n]) => `${n} ${s}`)
  return parts.length > 0 ? parts.join(' · ') : '0 trades'
}

function applySort(trades: Trade[], sortKey: SortKey | null, sortDir: 1 | -1): Trade[] {
  if (!sortKey) return trades
  return [...trades].sort((a, b) => {
    const va = sortKey === 'ticker' ? a.ticker : (a.expiry_date ?? 'ZZZZ')
    const vb = sortKey === 'ticker' ? b.ticker : (b.expiry_date ?? 'ZZZZ')
    return va < vb ? -sortDir : va > vb ? sortDir : 0
  })
}

export function GroupedTradeTable({ trades, onDelete, statusFilter }: Props) {
  const [sortKey, setSortKey] = useState<SortKey | null>(null)
  const [sortDir, setSortDir] = useState<1 | -1>(1)

  function handleSort(key: SortKey) {
    if (sortKey === key) setSortDir(d => (d === 1 ? -1 : 1))
    else { setSortKey(key); setSortDir(1) }
  }

  function SortIcon({ k }: { k: SortKey }) {
    if (sortKey !== k) return <span className="ml-0.5 text-gray-300">↕</span>
    return <span className="ml-0.5 text-blue-500">{sortDir === 1 ? '↑' : '↓'}</span>
  }

  const grouped = groupTrades(trades)
  const categories = [...CATEGORY_ORDER]
  if (grouped.has('Other')) categories.push('Other')

  if (trades.length === 0 && !statusFilter) {
    return <p className="text-gray-500 text-center py-8">No trades yet. Add your first trade.</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead className="bg-gray-50 border-b border-gray-200">
          <tr>
            <th className="w-8 px-2 py-3" />
            <th className="px-4 py-3 text-left">
              <button
                onClick={() => handleSort('ticker')}
                className="flex items-center text-xs font-medium text-gray-500 uppercase tracking-wider hover:text-gray-700"
              >
                Ticker<SortIcon k="ticker" />
              </button>
            </th>
            {['Strategy', 'Type', 'Strike'].map(h => (
              <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{h}</th>
            ))}
            <th className="px-4 py-3 text-left">
              <button
                onClick={() => handleSort('expiry')}
                className="flex items-center text-xs font-medium text-gray-500 uppercase tracking-wider hover:text-gray-700"
              >
                Expiry<SortIcon k="expiry" />
              </button>
            </th>
            {['Qty', 'Premium', 'P&L', 'Status', 'Commentary', ''].map(h => (
              <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{h}</th>
            ))}
          </tr>
        </thead>

        {categories.map(category => {
          const allTrades = grouped.get(category) ?? []
          const filtered = statusFilter ? allTrades.filter(t => t.status === statusFilter) : allTrades
          const visible = applySort(filtered, sortKey, sortDir)
          const color = CATEGORY_COLORS[category]
          const emptyMsg = statusFilter
            ? `No ${statusFilter} trades in ${category}`
            : `No trades in ${category}`

          return (
            <tbody key={category}>
              <tr>
                <td className="w-8 px-2 py-2 border-t border-gray-200"
                  style={{
                    background: color ? `linear-gradient(90deg, ${color}1A 0%, transparent 70%)` : '#f9fafb',
                    borderLeft: `3px solid ${color ?? '#e5e7eb'}`,
                  }}
                />
                <td
                  colSpan={COL_COUNT - 1}
                  className="py-2 border-t border-gray-200"
                  style={{ background: color ? `linear-gradient(90deg, ${color}1A 0%, transparent 70%)` : '#f9fafb' }}
                >
                  <div className="flex items-center justify-between pr-4">
                    <span className="font-bold text-sm flex items-center gap-1.5" style={{ color: color ?? '#6b7280' }}>
                      ▼ {category}
                    </span>
                    <span className="text-xs text-gray-500">{statusBreakdown(allTrades)}</span>
                  </div>
                </td>
              </tr>

              {visible.length === 0 ? (
                <tr>
                  <td colSpan={COL_COUNT} className="px-4 py-3 text-center text-xs text-gray-400 italic">
                    {emptyMsg}
                  </td>
                </tr>
              ) : (
                visible.map(trade => (
                  <tr key={trade.id} className="hover:bg-gray-50 border-b border-gray-100 last:border-0">
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
                    <td className="px-4 py-3"><StatusBadge status={trade.status} /></td>
                    <td className="px-4 py-3"><CommentaryCell tradeId={trade.id} ticker={trade.ticker} /></td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        {trade.strategy === 'Stock' && trade.status === 'open' && (
                          <Link to={`/scanner?ticker=${trade.ticker}`} className="text-blue-500 hover:text-blue-700 text-xs">Scan →</Link>
                        )}
                        <button onClick={() => onDelete(trade.id)} className="text-red-500 hover:text-red-700 text-xs">Delete</button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          )
        })}
      </table>
    </div>
  )
}
```

- [ ] **Step 2: Check it compiles**

```bash
cd frontend && npx tsc --noEmit
```
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Trades/GroupedTradeTable.tsx
git commit -m "feat: add GroupedTradeTable with grouping, filtering, and sort"
```

---

### Task 3: Add collapse/expand to GroupedTradeTable

**Files:**
- Modify: `frontend/src/components/Trades/GroupedTradeTable.tsx`

- [ ] **Step 1: Add `collapsed` state and toggle**

Inside `GroupedTradeTable`, add after the `sortDir` state line:

```tsx
const [collapsed, setCollapsed] = useState<Set<string>>(new Set())

function toggleCollapse(category: string) {
  setCollapsed(prev => {
    const next = new Set(prev)
    next.has(category) ? next.delete(category) : next.add(category)
    return next
  })
}
```

- [ ] **Step 2: Add chevron to the group header and make it clickable**

In the group header `<td>` that holds `colSpan={COL_COUNT - 1}`, add `onClick` and update the category label to include a chevron:

Replace:
```tsx
<td
  colSpan={COL_COUNT - 1}
  className="py-2 border-t border-gray-200"
  style={{ background: color ? `linear-gradient(90deg, ${color}1A 0%, transparent 70%)` : '#f9fafb' }}
>
  <div className="flex items-center justify-between pr-4">
    <span className="font-bold text-sm flex items-center gap-1.5" style={{ color: color ?? '#6b7280' }}>
      ▼ {category}
    </span>
    <span className="text-xs text-gray-500">{statusBreakdown(allTrades)}</span>
  </div>
</td>
```

With:
```tsx
<td
  colSpan={COL_COUNT - 1}
  className="py-2 border-t border-gray-200 cursor-pointer select-none"
  onClick={() => toggleCollapse(category)}
  style={{ background: color ? `linear-gradient(90deg, ${color}1A 0%, transparent 70%)` : '#f9fafb' }}
>
  <div className="flex items-center justify-between pr-4">
    <span className="font-bold text-sm flex items-center gap-1.5" style={{ color: color ?? '#6b7280' }}>
      <span
        className="inline-block transition-transform duration-150"
        style={{ transform: collapsed.has(category) ? 'rotate(-90deg)' : 'rotate(0deg)' }}
      >
        ▼
      </span>
      {category}
    </span>
    <span className="text-xs text-gray-500">{statusBreakdown(allTrades)}</span>
  </div>
</td>
```

- [ ] **Step 3: Wrap trade rows in a collapsed guard**

Replace:
```tsx
{visible.length === 0 ? (
  <tr>
    <td colSpan={COL_COUNT} className="px-4 py-3 text-center text-xs text-gray-400 italic">
      {emptyMsg}
    </td>
  </tr>
) : (
  visible.map(trade => (
    <tr key={trade.id} className="hover:bg-gray-50 border-b border-gray-100 last:border-0">
      ...
    </tr>
  ))
)}
```

With:
```tsx
{!collapsed.has(category) && (
  visible.length === 0 ? (
    <tr>
      <td colSpan={COL_COUNT} className="px-4 py-3 text-center text-xs text-gray-400 italic">
        {emptyMsg}
      </td>
    </tr>
  ) : (
    visible.map(trade => (
      <tr key={trade.id} className="hover:bg-gray-50 border-b border-gray-100 last:border-0">
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
        <td className="px-4 py-3"><StatusBadge status={trade.status} /></td>
        <td className="px-4 py-3"><CommentaryCell tradeId={trade.id} ticker={trade.ticker} /></td>
        <td className="px-4 py-3">
          <div className="flex items-center gap-3">
            {trade.strategy === 'Stock' && trade.status === 'open' && (
              <Link to={`/scanner?ticker=${trade.ticker}`} className="text-blue-500 hover:text-blue-700 text-xs">Scan →</Link>
            )}
            <button onClick={() => onDelete(trade.id)} className="text-red-500 hover:text-red-700 text-xs">Delete</button>
          </div>
        </td>
      </tr>
    ))
  )
)}
```

- [ ] **Step 4: Check it compiles**

```bash
cd frontend && npx tsc --noEmit
```
Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Trades/GroupedTradeTable.tsx
git commit -m "feat: add collapse/expand to GroupedTradeTable group sections"
```

---

### Task 4: Add drag-to-reorder with localStorage persistence

**Files:**
- Modify: `frontend/src/components/Trades/GroupedTradeTable.tsx`

The drag unit is each `<tbody>` (one per category). The `⠿` symbol in the first `<td>` of the group header row is the visible drag handle.

- [ ] **Step 1: Add localStorage helpers above the component**

Add these two functions directly above the `GroupedTradeTable` function (after the `applySort` function):

```tsx
const LS_KEY = 'trademinder_group_order'

function loadGroupOrder(): string[] {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (raw) {
      const saved: string[] = JSON.parse(raw)
      const extras = CATEGORY_ORDER.filter(c => !saved.includes(c))
      return [...saved, ...extras]
    }
  } catch {}
  return [...CATEGORY_ORDER]
}

function saveGroupOrder(order: string[]): void {
  try { localStorage.setItem(LS_KEY, JSON.stringify(order)) } catch {}
}
```

- [ ] **Step 2: Add `groupOrder` state, drag ref, and `dragOver` state inside the component**

Add `useRef` to the React import at the top of the file:
```tsx
import { useState, useRef } from 'react'
```

Inside `GroupedTradeTable`, add after the `collapsed` state and `toggleCollapse` function:

```tsx
const [groupOrder, setGroupOrder] = useState<string[]>(loadGroupOrder)
const dragSrcRef = useRef<string | null>(null)
const [dragOver, setDragOver] = useState<{ category: string; position: 'above' | 'below' } | null>(null)

function handleDragStart(e: React.DragEvent, category: string) {
  dragSrcRef.current = category
  e.dataTransfer.effectAllowed = 'move'
}

function handleDragOver(e: React.DragEvent, category: string) {
  e.preventDefault()
  if (dragSrcRef.current === category) return
  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
  const position: 'above' | 'below' = e.clientY < rect.top + rect.height / 2 ? 'above' : 'below'
  setDragOver({ category, position })
}

function handleDragLeave() {
  setDragOver(null)
}

function handleDrop(e: React.DragEvent, targetCategory: string) {
  e.preventDefault()
  const src = dragSrcRef.current
  const position = dragOver?.position ?? 'below'
  if (!src || src === targetCategory) { setDragOver(null); return }
  const next = [...groupOrder]
  const srcIdx = next.indexOf(src)
  if (srcIdx === -1) { setDragOver(null); return }
  next.splice(srcIdx, 1)
  const tgtIdx = next.indexOf(targetCategory)
  if (tgtIdx === -1) { setDragOver(null); return }
  next.splice(position === 'above' ? tgtIdx : tgtIdx + 1, 0, src)
  dragSrcRef.current = null
  setDragOver(null)
  setGroupOrder(next)
  saveGroupOrder(next)
}

function handleDragEnd() {
  dragSrcRef.current = null
  setDragOver(null)
}
```

- [ ] **Step 3: Replace the `categories` derivation to use `groupOrder`**

Replace:
```tsx
const categories = [...CATEGORY_ORDER]
if (grouped.has('Other')) categories.push('Other')
```

With:
```tsx
const categories = [...groupOrder]
if (grouped.has('Other') && !categories.includes('Other')) categories.push('Other')
```

- [ ] **Step 4: Add drag events and drop indicator to each `<tbody>`, and add `⠿` drag handle to the header**

Replace each `<tbody key={category}>` opening tag with:
```tsx
<tbody
  key={category}
  draggable
  onDragStart={e => handleDragStart(e, category)}
  onDragOver={e => handleDragOver(e, category)}
  onDragLeave={handleDragLeave}
  onDrop={e => handleDrop(e, category)}
  onDragEnd={handleDragEnd}
>
```

Also update the group header `<tr>` opening tag to show the drop indicator (border-top/bottom on `<tr>` is reliable; `outline` on `<tbody>` is not):
```tsx
<tr
  style={{
    borderTop: dragOver?.category === category && dragOver.position === 'above' ? '2px solid #2563eb' : undefined,
    borderBottom: dragOver?.category === category && dragOver.position === 'below' ? '2px solid #2563eb' : undefined,
  }}
>
```

Replace the first `<td>` of the group header row (the empty placeholder cell) with the drag handle:
```tsx
<td
  className="w-8 px-2 py-2 border-t border-gray-200 text-gray-300 text-base cursor-grab select-none"
  title="Drag to reorder"
  style={{
    background: color ? `linear-gradient(90deg, ${color}1A 0%, transparent 70%)` : '#f9fafb',
    borderLeft: `3px solid ${color ?? '#e5e7eb'}`,
  }}
>
  ⠿
</td>
```

- [ ] **Step 5: Check it compiles**

```bash
cd frontend && npx tsc --noEmit
```
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Trades/GroupedTradeTable.tsx
git commit -m "feat: add drag-to-reorder group sections with localStorage persistence"
```

---

### Task 5: Wire GroupedTradeTable into TradesPage

**Files:**
- Modify: `frontend/src/pages/TradesPage.tsx`

- [ ] **Step 1: Replace the contents of `TradesPage.tsx`**

Replace the full file contents with:

```tsx
import { useState, useEffect } from 'react'
import { tradesApi } from '../api/trades'
import { technicalsApi } from '../api/technicals'
import type { Trade, TechnicalsData, TradeCreate } from '../types'
import { GroupedTradeTable } from '../components/Trades/GroupedTradeTable'
import { TradeForm } from '../components/Trades/TradeForm'

export function TradesPage() {
  const [trades, setTrades] = useState<Trade[]>([])
  const [showForm, setShowForm] = useState(false)
  const [statusFilter, setStatusFilter] = useState<string>('open')

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

  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-4">
        <h1 className="text-2xl font-bold text-gray-900">Trades</h1>
        <button onClick={() => setShowForm(true)} className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700">
          + Add Trade
        </button>
      </div>

      <div className="mb-4 flex gap-2">
        {(['', 'open', 'closed', 'expired', 'assigned'] as const).map(s => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`px-3 py-1 rounded text-sm border ${statusFilter === s ? 'bg-blue-600 text-white border-blue-600' : 'border-gray-300 hover:bg-gray-50'}`}
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
        <GroupedTradeTable trades={trades} onDelete={handleDelete} statusFilter={statusFilter} />
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Run TypeScript check**

```bash
cd frontend && npx tsc --noEmit
```
Expected: No errors.

- [ ] **Step 3: Full end-to-end verification in the browser**

With the dev server running, navigate to `http://localhost:5173/trades` and verify each of the following:

1. **Default filter:** Page loads with "open" button highlighted; only open trades are visible
2. **Groups visible:** Trade rows are grouped under category headers with accent-bar style (colored left border + faint gradient)
3. **Status breakdown:** Each group header shows counts like "3 open · 1 closed" reflecting ALL trades in that category regardless of filter
4. **Empty group state:** Switch to "closed" filter — groups with no closed trades show "No closed trades in [CATEGORY]" and remain visible
5. **Filter switching:** Clicking All/open/closed/expired/assigned updates trade rows across all groups without a page reload
6. **Sort by Ticker:** Click "Ticker" column header → rows within every group sort A→Z. Click again → Z→A. Arrow indicator updates.
7. **Sort by Expiry:** Click "Expiry" column header → rows sort earliest date first. Trades with no expiry (e.g. stock holds) go to the bottom.
8. **Collapse/expand:** Click a group header → chevron rotates to ▶ and rows hide. Click again → rows reappear.
9. **Drag-to-reorder:** Grab the ⠿ handle on a group header and drag it above/below another group. Blue outline shows drop position. Release to reorder.
10. **Order persistence:** After reordering, refresh the page (`Cmd+R`). Groups appear in the custom order.
11. **Add trade:** Click "+ Add Trade", fill in the form, submit. The new trade appears in the correct category group.
12. **Delete trade:** Click Delete on a trade row. The row disappears and the group header count updates.
13. **No console errors** in browser DevTools.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/TradesPage.tsx
git commit -m "feat: replace flat TradeTable with GroupedTradeTable in TradesPage"
```
