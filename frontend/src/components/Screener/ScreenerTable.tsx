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
