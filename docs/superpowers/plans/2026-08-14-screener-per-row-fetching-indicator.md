# Screener Per-Row Fetching Indicator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** While "Fetch All" is running, each row's own Fetch button shows "Fetching…" (disabled) until the bulk job actually refreshes that row, then it flips back to "Fetch" automatically.

**Architecture:** `ScreenerPage.tsx` records the ISO timestamp when Fetch All starts and refreshes the row list on every 2s job-status poll tick (not just once at the end), using a new "quiet" refresh that doesn't toggle the page's loading spinner. `ScreenerTable.tsx` receives that timestamp plus the bulk-fetching flag as two new props, threads them to each row, and each row derives whether it's still "pending" by comparing its own `last_fetched_at` against the start timestamp — no new backend field, no per-row state beyond what's already there.

**Tech Stack:** React 19, TypeScript strict mode, Tailwind CSS. No test suite exists for the frontend in this repo — verification is `tsc --noEmit -p tsconfig.app.json` plus manual browser check.

## Global Constraints

- No backend changes — the fetch-all job already commits each row's `last_fetched_at` progressively; only the frontend needs to observe it more often.
- Job-status polling interval stays 2000ms; the row-list refresh piggybacks on the same tick, not a separate timer.
- A row's bulk-pending state must be indistinguishable in the UI from that row's own individually-clicked-Fetch state — same "Fetching…" label, same disabled button, one code path (`isFetching = fetching || bulkPending`), not two different visual treatments.
- Refreshing rows during the poll must NOT toggle the page-level `loading` flag — doing so would flicker/unmount `ScreenerTable` (and its row-local `expanded` state) every 2 seconds during a bulk fetch.
- Spec reference: `docs/superpowers/specs/2026-08-14-screener-per-row-fetching-indicator-design.md`.

---

## Task 1: Wire per-row bulk-fetch-pending state through ScreenerPage and ScreenerTable

**Files:**
- Modify: `frontend/src/pages/ScreenerPage.tsx` (full-file rewrite — see target content below)
- Modify: `frontend/src/components/Screener/ScreenerTable.tsx` (full-file rewrite — see target content below)

**Interfaces:**
- `ScreenerTable`'s exported `Props` interface gains two new **required** fields: `bulkFetching: boolean` and `fetchAllStartedAt: string | null`. Both files must land together — `ScreenerPage` starts passing them in the same change that `ScreenerTable` starts requiring them, otherwise the build breaks between commits. This is why both files are one task, not two.
- Produces: no new exports beyond the two new props — nothing outside these two files needs to change (no other component renders `<ScreenerTable>`).

This is a single, cohesive change to two already-small, tightly-coupled files. No test suite exists for the frontend in this repo, so this task is implement → type-check → manual-verify, matching every other frontend task in this feature so far.

- [ ] **Step 1: Read both current files to confirm no drift**

Run: `cat frontend/src/pages/ScreenerPage.tsx frontend/src/components/Screener/ScreenerTable.tsx`

`ScreenerPage.tsx` should be 92 lines, starting `import { useCallback, useEffect, useRef, useState } from 'react'`. `ScreenerTable.tsx` should be 216 lines, starting `import { useMemo, useState } from 'react'`. If either doesn't match (someone else touched these files since), STOP and report NEEDS_CONTEXT with a diff — do not blindly overwrite.

- [ ] **Step 2: Replace `frontend/src/pages/ScreenerPage.tsx`**

Replace its entire contents with:

```tsx
import { useCallback, useEffect, useRef, useState } from 'react'
import { screenerApi } from '../api/screener'
import type { ScreenerRow } from '../types'
import { AddSymbolForm } from '../components/Screener/AddSymbolForm'
import { SymbolLookup } from '../components/Screener/SymbolLookup'
import { ScreenerTable } from '../components/Screener/ScreenerTable'

export function ScreenerPage() {
  const [rows, setRows] = useState<ScreenerRow[]>([])
  const [loading, setLoading] = useState(true)
  const [fetchingAll, setFetchingAll] = useState(false)
  const [fetchAllStartedAt, setFetchAllStartedAt] = useState<string | null>(null)
  const [jobProgress, setJobProgress] = useState<{ completed: number; total: number } | null>(null)
  const [pollError, setPollError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const loadRows = useCallback(async () => {
    setLoading(true)
    try {
      const data = await screenerApi.list()
      setRows(data)
    } finally {
      setLoading(false)
    }
  }, [])

  // Same fetch as loadRows, but doesn't toggle the page-level loading flag —
  // used during Fetch All polling so the table doesn't flicker/unmount every 2s.
  const refreshRowsQuiet = useCallback(async () => {
    const data = await screenerApi.list()
    setRows(data)
  }, [])

  useEffect(() => {
    loadRows()
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [loadRows])

  const handleAdded = (row: ScreenerRow) => {
    setRows(prev =>
      [...prev.filter(r => r.symbol !== row.symbol), row].sort((a, b) => a.symbol.localeCompare(b.symbol))
    )
  }

  const handleRefreshRow = (row: ScreenerRow) => {
    setRows(prev => prev.map(r => (r.symbol === row.symbol ? row : r)))
  }

  const handleRemove = async (symbol: string) => {
    if (!confirm(`Remove ${symbol} from the screener?`)) return
    await screenerApi.remove(symbol)
    setRows(prev => prev.filter(r => r.symbol !== symbol))
  }

  const handleFetchAll = async () => {
    setFetchingAll(true)
    setFetchAllStartedAt(new Date().toISOString())
    setPollError(null)
    const job = await screenerApi.fetchAll()
    setJobProgress({ completed: job.completed, total: job.total })
    pollRef.current = setInterval(async () => {
      try {
        const status = await screenerApi.getJobStatus(job.job_id)
        setJobProgress({ completed: status.completed, total: status.total })
        await refreshRowsQuiet()
        if (status.status === 'done') {
          if (pollRef.current) clearInterval(pollRef.current)
          setFetchingAll(false)
          setJobProgress(null)
          setFetchAllStartedAt(null)
        }
      } catch {
        if (pollRef.current) clearInterval(pollRef.current)
        setFetchingAll(false)
        setJobProgress(null)
        setFetchAllStartedAt(null)
        setPollError('Lost connection to fetch-all job. Please try again.')
      }
    }, 2000)
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-lg font-semibold text-gray-800">Screener</h1>
        <button
          onClick={handleFetchAll}
          disabled={fetchingAll || rows.length === 0}
          className="px-3 py-1.5 bg-gray-700 text-white text-sm rounded hover:bg-gray-800 disabled:bg-gray-300"
        >
          {fetchingAll ? `Fetching ${jobProgress?.completed ?? 0}/${jobProgress?.total ?? 0}…` : 'Fetch All'}
        </button>
      </div>
      {pollError && <p className="text-red-600 text-sm mb-3">{pollError}</p>}
      <SymbolLookup onAdded={handleAdded} />
      <AddSymbolForm onAdded={handleAdded} />
      {loading ? (
        <p className="text-gray-400 text-sm">Loading…</p>
      ) : (
        <ScreenerTable
          rows={rows}
          onRefreshRow={handleRefreshRow}
          onRemove={handleRemove}
          bulkFetching={fetchingAll}
          fetchAllStartedAt={fetchAllStartedAt}
        />
      )}
    </div>
  )
}
```

- [ ] **Step 3: Replace `frontend/src/components/Screener/ScreenerTable.tsx`**

Replace its entire contents with:

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
  bulkFetching: boolean
  fetchAllStartedAt: string | null
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

function ScreenerRowView({
  row,
  onRefreshRow,
  onRemove,
  bulkFetching,
  fetchAllStartedAt,
}: {
  row: ScreenerRow
  onRefreshRow: (row: ScreenerRow) => void
  onRemove: (symbol: string) => void
  bulkFetching: boolean
  fetchAllStartedAt: string | null
}) {
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

  // True while Fetch All is running and this row's data hasn't been
  // refreshed since the job started — string comparison is safe since
  // both are ISO-8601 UTC timestamps (lexicographic order == chronological order).
  const bulkPending =
    bulkFetching &&
    fetchAllStartedAt != null &&
    (row.last_fetched_at == null || row.last_fetched_at <= fetchAllStartedAt)

  const isFetching = fetching || bulkPending

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
          <button onClick={handleFetch} disabled={isFetching} className="text-xs text-blue-600 hover:underline disabled:text-gray-400">
            {isFetching ? 'Fetching…' : 'Fetch'}
          </button>
          <button onClick={() => onRemove(row.symbol)} className="text-xs text-red-500 hover:underline">Remove</button>
        </td>
      </tr>
      {expanded && <ScreenerDetailRow row={row} colSpan={COLUMNS.length} />}
    </>
  )
}

export function ScreenerTable({ rows, onRefreshRow, onRemove, bulkFetching, fetchAllStartedAt }: Props) {
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
              <ScreenerRowView
                key={row.id}
                row={row}
                onRefreshRow={onRefreshRow}
                onRemove={onRemove}
                bulkFetching={bulkFetching}
                fetchAllStartedAt={fetchAllStartedAt}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Type-check**

Run: `cd frontend && npx tsc --noEmit -p tsconfig.app.json`
Expected: exactly the two pre-existing, unrelated errors already on `develop` — `src/components/Wheel/WheelSlotCard.tsx(26,39): error TS6133: 'ticker' is declared but its value is never read.` and `src/pages/WheelDashboardPage.tsx(3,35): error TS6196: 'WheelSessionSummary' is declared but never used.` — nothing new. If anything else appears, it's a defect in Steps 2/3; fix before proceeding.

- [ ] **Step 5: Manual verification via dev server**

Start the backend (`cd backend && venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 5431 --reload`) and frontend (`cd frontend && npm run dev`), then in a browser at `http://localhost:5430/screener` with **at least 3 symbols tracked** (add more via Quick Lookup / Add Symbol if needed — more symbols make the per-row transition easier to observe since the job takes longer):

1. Click "Fetch All". Immediately (within the same second), every row's action-column button should read "Fetching…" and be greyed out/disabled — not just the page-level header button.
2. Watch the grid over the following seconds: rows should flip back to a normal, enabled "Fetch" button **one at a time**, in roughly the order the backend processes them — not all simultaneously at the very end. (If your symbol count is small, this transition may be fast; adding more tracked symbols makes it easier to observe mid-job.)
3. Confirm no row is ever left permanently stuck on "Fetching…" after the page-level button reverts from "Fetching N/M…" back to "Fetch All".
4. Outside of any bulk run, click a single row's own "Fetch" button — confirm it still shows "Fetching…" (disabled) while that individual request is in flight, then reverts, exactly as before this change (this path must be unaffected).
5. Confirm the table does NOT flicker, flash a "Loading…" state, or visibly re-mount (e.g. an expanded row's detail panel collapsing unexpectedly) during the Fetch All run — this would indicate the page-level `loading` flag is incorrectly toggling during polling.
6. Confirm sorting and the symbol filter (from the prior enhancement) still work normally both during and after a Fetch All run.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/ScreenerPage.tsx frontend/src/components/Screener/ScreenerTable.tsx
git commit -m "feat(screener): show per-row Fetching indicator during Fetch All"
```

---

## Self-Review Notes

- **Spec coverage:** all three goals covered — per-row "Fetching…" while pending (Steps 3/5.1), automatic revert as each row completes (Steps 2-3/5.2-5.3), shared visual state with individual fetch via the `isFetching = fetching || bulkPending` OR (Step 3/5.4).
- **Non-goal respected:** the spec explicitly ruled out `loadRows()` causing flicker was actually a gap in the spec's own phrasing ("changes to also call `loadRows()` on every tick") — this plan corrects that by introducing `refreshRowsQuiet()` instead, which does not toggle `loading`. Documented here since it's a deviation from the spec's literal wording, made to satisfy the spec's own Non-Goal ("no separate timer," implicitly: no page-level disruption) and Design section's overall intent (smooth per-row transitions, not a flickering page).
- **Type consistency:** `bulkFetching`/`fetchAllStartedAt` prop names and types are identical across `ScreenerPage.tsx` (where they're produced) and `ScreenerTable.tsx`'s `Props` interface and `ScreenerRowView`'s inline prop type (where they're consumed) — no drift.
- **No placeholders:** Steps 2 and 3 are complete target file contents, not diffs or descriptions.
