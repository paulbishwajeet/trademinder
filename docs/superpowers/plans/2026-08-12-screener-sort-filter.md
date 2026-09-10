# Screener Sort + Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add clickable-header column sorting and a live symbol-substring filter to the Screener grid, entirely client-side.

**Architecture:** Both features are self-contained inside `frontend/src/components/Screener/ScreenerTable.tsx`. The flat `COLUMNS: string[]` becomes an array of `{label, key}` descriptors so headers know which field they sort. Three new `useState` hooks (`filterText`, `sortKey`, `sortDirection`) plus one `useMemo` that filters then sorts `rows` before rendering. No other file changes.

**Tech Stack:** React 19, TypeScript strict mode, Tailwind CSS. No test suite exists for the frontend in this repo (consistent with the rest of the Screener feature) — verification is `tsc --noEmit -p tsconfig.app.json` plus manual browser check.

## Global Constraints

- Client-side only — no backend/API changes, no changes to `ScreenerPage.tsx`'s props into `ScreenerTable`.
- Single active sort column at a time (no multi-sort).
- Numeric columns (`price`, `change_pct`, `iv_percentile`, `rsi_14`, `ma_20d/50d/100d/200d`) are Decimal-backed strings — must go through the existing `toNum()` helper before comparison, never compared as raw strings.
- `last_fetched_at` sorts by actual timestamp (`new Date(...).getTime()`), not the rendered "X ago" text.
- A row whose value is `null` for the active sort column always sorts to the bottom, in both `asc` and `desc` — this rule is direction-independent.
- Filter matches case-insensitive substring against `row.symbol` only (not sector/category/status).
- Two distinct empty-state messages: `rows.length === 0` → "No symbols tracked yet." (unchanged); `rows.length > 0 && filteredSortedRows.length === 0` → a new "No symbols match …" message.
- Commentary column and the trailing action (Fetch/Remove) column are never sortable.
- Spec reference: `docs/superpowers/specs/2026-08-12-screener-sort-filter-design.md`.

---

## Task 1: Add sort + filter to ScreenerTable

**Files:**
- Modify: `frontend/src/components/Screener/ScreenerTable.tsx` (full-file rewrite of the module — see below for exact target content)

**Interfaces:**
- Consumes: `ScreenerRow` type, `toNum()` helper, `screenerApi.fetchOne` (all already in this file — unchanged).
- Produces: no new exports — `ScreenerTable`'s public props (`{ rows, onRefreshRow, onRemove }`) are unchanged, so `ScreenerPage.tsx` requires zero changes.

This is a single, cohesive change to one already-small file (125 lines). No test suite exists for the frontend in this repo, so this task is implement → type-check → manual-verify, matching every other frontend task in the original Screener build (no TDD red/green step, since there's nothing to run red).

- [ ] **Step 1: Read the current file to confirm no drift**

Run: `cat frontend/src/components/Screener/ScreenerTable.tsx`

Confirm it matches this (as of the merge of the original Screener feature, plus its one polish fix commit) — 125 lines, starting `import { useState } from 'react'` and ending with the closing `}` of `export function ScreenerTable`. If it doesn't match (someone else touched this file since), STOP and report NEEDS_CONTEXT with a diff — do not blindly overwrite.

- [ ] **Step 2: Replace the file with the sort+filter version**

Replace the entire contents of `frontend/src/components/Screener/ScreenerTable.tsx` with:

```tsx
import { useMemo, useState } from 'react'
import type { ScreenerRow } from '../../types'
import { screenerApi } from '../../api/screener'
import { ScreenerDetailRow } from './ScreenerDetailRow'
import { ScreenerCommentaryCell } from './ScreenerCommentaryCell'
import { timeAgo } from './timeAgo'

interface Props {
  rows: ScreenerRow[]
  onRefreshRow: (row: ScreenerRow) => void
  onRemove: (symbol: string) => void
}

const MACD_COLORS: Record<string, string> = {
  bullish: 'bg-green-100 text-green-700',
  bearish: 'bg-red-100 text-red-700',
  neutral: 'bg-gray-100 text-gray-600',
}

const BB_LABELS: Record<string, string> = {
  above_upper: 'Above',
  near_upper: 'Top',
  mid: 'Mid',
  near_lower: 'Bottom',
  below_lower: 'Below',
}

type SortKey =
  | 'symbol' | 'price' | 'change_pct' | 'iv_percentile' | 'rsi_14'
  | 'macd_weekly_signal' | 'ma_20d' | 'ma_50d' | 'ma_100d' | 'ma_200d'
  | 'bollinger_position' | 'last_fetched_at'

interface ColumnDef {
  label: string
  key: SortKey | null
}

const COLUMNS: ColumnDef[] = [
  { label: 'Symbol', key: 'symbol' },
  { label: 'Price', key: 'price' },
  { label: 'Change%', key: 'change_pct' },
  { label: 'IV Pctl', key: 'iv_percentile' },
  { label: 'RSI(d)', key: 'rsi_14' },
  { label: 'MACD(w)', key: 'macd_weekly_signal' },
  { label: '20ma', key: 'ma_20d' },
  { label: '50ma', key: 'ma_50d' },
  { label: '100ma', key: 'ma_100d' },
  { label: '200ma', key: 'ma_200d' },
  { label: 'BB', key: 'bollinger_position' },
  { label: 'Fetched', key: 'last_fetched_at' },
  { label: 'Commentary', key: null },
  { label: '', key: null },
]

const NUMERIC_KEYS = new Set<SortKey>(['price', 'change_pct', 'iv_percentile', 'rsi_14', 'ma_20d', 'ma_50d', 'ma_100d', 'ma_200d'])

// Decimal fields arrive as strings (see types/index.ts note) — parse before math/formatting.
function toNum(v: string | null): number | null {
  if (v == null) return null
  const n = parseFloat(v)
  return Number.isNaN(n) ? null : n
}

function getSortValue(row: ScreenerRow, key: SortKey): number | string | null {
  if (key === 'last_fetched_at') {
    return row.last_fetched_at ? new Date(row.last_fetched_at).getTime() : null
  }
  if (NUMERIC_KEYS.has(key)) {
    return toNum(row[key] as string | null)
  }
  return row[key] as string | null
}

function compareRows(a: ScreenerRow, b: ScreenerRow, key: SortKey, direction: 'asc' | 'desc'): number {
  const va = getSortValue(a, key)
  const vb = getSortValue(b, key)
  // Nulls always sort last, regardless of direction.
  if (va == null && vb == null) return 0
  if (va == null) return 1
  if (vb == null) return -1
  const cmp = typeof va === 'number' && typeof vb === 'number'
    ? va - vb
    : String(va).localeCompare(String(vb))
  return direction === 'asc' ? cmp : -cmp
}

function MaCell({ price, ma }: { price: string | null; ma: string | null }) {
  const maNum = toNum(ma)
  if (maNum == null) return <td className="px-3 py-2 text-gray-300">—</td>
  const priceNum = toNum(price)
  const below = priceNum != null && priceNum < maNum
  return (
    <td className={`px-3 py-2 font-medium ${below ? 'text-red-600' : 'text-green-600'}`}>
      {maNum.toFixed(2)}
    </td>
  )
}

function ScreenerRowView({ row, onRefreshRow, onRemove }: { row: ScreenerRow; onRefreshRow: (row: ScreenerRow) => void; onRemove: (symbol: string) => void }) {
  const [expanded, setExpanded] = useState(false)
  const [fetching, setFetching] = useState(false)

  const handleFetch = async () => {
    setFetching(true)
    try {
      const updated = await screenerApi.fetchOne(row.symbol)
      onRefreshRow(updated)
    } finally {
      setFetching(false)
    }
  }

  return (
    <>
      <tr className="border-t border-gray-100 hover:bg-gray-50">
        <td className="px-3 py-2">
          <button onClick={() => setExpanded(e => !e)} className="flex items-center gap-1 font-medium text-gray-800">
            <span style={{ transform: expanded ? 'rotate(0deg)' : 'rotate(-90deg)', display: 'inline-block', transition: 'transform 0.15s' }}>&#9660;</span>
            {row.symbol}
          </button>
        </td>
        <td className="px-3 py-2">{toNum(row.price) != null ? `$${toNum(row.price)!.toFixed(2)}` : '—'}</td>
        <td className={`px-3 py-2 font-medium ${(toNum(row.change_pct) ?? 0) < 0 ? 'text-red-600' : 'text-green-600'}`}>
          {toNum(row.change_pct) != null ? `${toNum(row.change_pct)!.toFixed(2)}%` : '—'}
        </td>
        <td className="px-3 py-2">{toNum(row.iv_percentile) != null ? `${toNum(row.iv_percentile)!.toFixed(0)}%` : '—'}</td>
        <td className="px-3 py-2">{toNum(row.rsi_14) != null ? toNum(row.rsi_14)!.toFixed(1) : '—'}</td>
        <td className="px-3 py-2">
          <span className={`px-2 py-0.5 rounded text-xs font-medium ${MACD_COLORS[row.macd_weekly_signal ?? 'neutral']}`}>
            {row.macd_weekly_signal ?? '—'}
          </span>
        </td>
        <MaCell price={row.price} ma={row.ma_20d} />
        <MaCell price={row.price} ma={row.ma_50d} />
        <MaCell price={row.price} ma={row.ma_100d} />
        <MaCell price={row.price} ma={row.ma_200d} />
        <td className="px-3 py-2 text-gray-600">{row.bollinger_position ? BB_LABELS[row.bollinger_position] ?? row.bollinger_position : '—'}</td>
        <td className="px-3 py-2 text-gray-400 text-xs">{timeAgo(row.last_fetched_at)}</td>
        <td className="px-3 py-2"><ScreenerCommentaryCell symbol={row.symbol} /></td>
        <td className="px-3 py-2 text-right space-x-2 whitespace-nowrap">
          <button onClick={handleFetch} disabled={fetching} className="text-xs text-blue-600 hover:underline disabled:text-gray-400">
            {fetching ? 'Fetching…' : 'Fetch'}
          </button>
          <button onClick={() => onRemove(row.symbol)} className="text-xs text-red-500 hover:underline">Remove</button>
        </td>
      </tr>
      {expanded && <ScreenerDetailRow row={row} colSpan={COLUMNS.length} />}
    </>
  )
}

export function ScreenerTable({ rows, onRefreshRow, onRemove }: Props) {
  const [filterText, setFilterText] = useState('')
  const [sortKey, setSortKey] = useState<SortKey | null>(null)
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc')

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDirection(d => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDirection('asc')
    }
  }

  const filteredSortedRows = useMemo(() => {
    const trimmed = filterText.trim().toLowerCase()
    const filtered = trimmed ? rows.filter(r => r.symbol.toLowerCase().includes(trimmed)) : rows
    if (sortKey == null) return filtered
    return [...filtered].sort((a, b) => compareRows(a, b, sortKey, sortDirection))
  }, [rows, filterText, sortKey, sortDirection])

  return (
    <div className="space-y-3">
      <input
        type="text"
        value={filterText}
        onChange={e => setFilterText(e.target.value)}
        placeholder="Filter by symbol…"
        className="border border-gray-300 rounded px-2 py-1 text-sm w-48"
      />
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              {COLUMNS.map((col, i) => (
                <th
                  key={i}
                  onClick={col.key ? () => handleSort(col.key!) : undefined}
                  className={`px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap ${col.key ? 'cursor-pointer select-none hover:text-gray-700' : ''}`}
                >
                  {col.label}
                  {col.key != null && sortKey === col.key && (
                    <span className="ml-1">{sortDirection === 'asc' ? '▲' : '▼'}</span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={COLUMNS.length} className="px-3 py-6 text-center text-gray-400">No symbols tracked yet.</td></tr>
            )}
            {rows.length > 0 && filteredSortedRows.length === 0 && (
              <tr><td colSpan={COLUMNS.length} className="px-3 py-6 text-center text-gray-400">No symbols match "{filterText}".</td></tr>
            )}
            {filteredSortedRows.map(row => (
              <ScreenerRowView key={row.id} row={row} onRefreshRow={onRefreshRow} onRemove={onRemove} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && npx tsc --noEmit -p tsconfig.app.json`
Expected: exactly the two pre-existing, unrelated errors already on `develop` before this change — `src/components/Wheel/WheelSlotCard.tsx(26,39): error TS6133: 'ticker' is declared but its value is never read.` and `src/pages/WheelDashboardPage.tsx(3,35): error TS6196: 'WheelSessionSummary' is declared but never used.` — nothing new. If anything else appears, it's a defect in Step 2's code; fix it before proceeding.

- [ ] **Step 4: Manual verification via dev server**

Start the backend (`cd backend && venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 5431 --reload`) and frontend (`cd frontend && npm run dev`), then in a browser at `http://localhost:5430/screener` (with at least 2-3 symbols already tracked, or add some via the existing Add Symbol / Quick Lookup UI first):

1. Click the "Symbol" header — rows reorder A→Z, an ▲ appears next to "Symbol". Click it again — rows reorder Z→A, indicator flips to ▼.
2. Click "Price" — rows reorder by price ascending; any row with a null price (never fetched) appears at the bottom. Click again — descending; the null-price row is still at the bottom, not the top.
3. Click "Fetched" — rows reorder by actual recency (most-recently-fetched first or last depending on direction), not alphabetically by the "X ago" text (e.g. "2 days ago" should not sort before "5 mins ago" as a string would).
4. Click "MACD(w)" — rows group by `bullish`/`bearish`/`neutral` alphabetically.
5. Type a partial ticker (e.g. if you have AAPL and MSFT tracked, type "AA") into the filter input — only AAPL remains. Clear the input — all rows return.
6. Type text that matches nothing (e.g. "ZZZZZ999") — the table body shows `No symbols match "ZZZZZ999".` instead of the row list or the "no symbols tracked" message.
7. Confirm the Commentary and Fetch/Remove columns are NOT clickable for sorting (no cursor-pointer, no indicator ever appears on them).
8. Confirm expand/collapse (chevron), Fetch, Remove, and the commentary dialog still all work exactly as before — this change must not regress existing row-level interactions.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Screener/ScreenerTable.tsx
git commit -m "feat(screener): add column sorting and symbol filter to ScreenerTable"
```

---

## Self-Review Notes

- **Spec coverage:** all three goals from the spec are covered by this one task — sortable headers with direction toggle (Steps 2/4.1-4.4), live symbol filter (Steps 2/4.5-4.6), purely client-side with zero prop/backend changes (confirmed: `Props` interface unchanged, no new imports beyond `useMemo`).
- **Null handling:** the spec's "null always sorts last, regardless of direction" rule is implemented as direction-independent branches (`return 1` / `return -1`) evaluated *before* the direction-flipped comparison — verified by re-reading `compareRows`.
- **Type consistency:** `SortKey`'s twelve values are exactly the twelve sortable `ColumnDef.key` entries in `COLUMNS`, and every `SortKey` value is a real field on `ScreenerRow` (checked against `frontend/src/types/index.ts`'s `ScreenerRow`/`ScreenerFetchedFields` interfaces from the original Screener build) — no drift.
- **No placeholders:** Step 2 is the complete target file content, not a diff description.
