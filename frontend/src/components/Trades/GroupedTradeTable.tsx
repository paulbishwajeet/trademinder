import { useState, useRef } from 'react'
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

// Number of columns: handle + ticker + strategy + type + strike + expiry + qty + premium + p&l + status + commentary + actions
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

export function GroupedTradeTable({ trades, onDelete, statusFilter }: Props) {
  const [sortKey, setSortKey] = useState<SortKey | null>(null)
  const [sortDir, setSortDir] = useState<1 | -1>(1)
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())

  function toggleCollapse(category: string) {
    setCollapsed(prev => {
      const next = new Set(prev)
      next.has(category) ? next.delete(category) : next.add(category)
      return next
    })
  }

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

  function handleDragLeave(e: React.DragEvent) {
    if (!(e.currentTarget as HTMLElement).contains(e.relatedTarget as Node)) {
      setDragOver(null)
    }
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

  function handleSort(key: SortKey) {
    if (sortKey === key) setSortDir(d => (d === 1 ? -1 : 1))
    else { setSortKey(key); setSortDir(1) }
  }

  function SortIcon({ k }: { k: SortKey }) {
    if (sortKey !== k) return <span className="ml-0.5 text-gray-300">↕</span>
    return <span className="ml-0.5 text-blue-500">{sortDir === 1 ? '↑' : '↓'}</span>
  }

  const grouped = groupTrades(trades)
  const categories = [...groupOrder]
  if (grouped.has('Other') && !categories.includes('Other')) categories.push('Other')

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
            <tbody
              key={category}
              draggable
              onDragStart={e => handleDragStart(e, category)}
              onDragOver={e => handleDragOver(e, category)}
              onDragLeave={handleDragLeave}
              onDrop={e => handleDrop(e, category)}
              onDragEnd={handleDragEnd}
            >
              <tr
                style={{
                  borderTop: dragOver?.category === category && dragOver.position === 'above' ? '2px solid #2563eb' : undefined,
                  borderBottom: dragOver?.category === category && dragOver.position === 'below' ? '2px solid #2563eb' : undefined,
                }}
              >
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
              </tr>

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
            </tbody>
          )
        })}
      </table>
    </div>
  )
}
