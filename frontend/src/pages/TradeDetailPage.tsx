// frontend/src/pages/TradeDetailPage.tsx
import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { tradesApi } from '../api/trades'
import { commentaryApi } from '../api/commentary'
import type { Trade, Commentary, TradeUpdate } from '../types'
import { StatusBadge } from '../components/shared/StatusBadge'
import { PnLDisplay } from '../components/shared/PnLDisplay'
import { CommentaryThread } from '../components/Commentary/CommentaryThread'

interface Category { id: string; name: string; color: string }

const STRATEGIES = ['Stock', 'Put', 'Call', 'CoveredCall', 'PutCreditSpread', 'Leap']
const TYPES = ['Buy', 'Sell', 'Assigned']
const STATUSES = ['open', 'closed', 'expired', 'assigned'] as const

export function TradeDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [trade, setTrade] = useState<Trade | null>(null)
  const [commentary, setCommentary] = useState<Commentary[]>([])
  const [isEditing, setIsEditing] = useState(false)
  const [editForm, setEditForm] = useState<TradeUpdate>({})
  const [categories, setCategories] = useState<Category[]>([])
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const loadTrade = async () => {
    if (!id) return
    const t = await tradesApi.get(id)
    setTrade(t)
  }

  const loadCommentary = async () => {
    if (!id) return
    const c = await commentaryApi.list(id)
    setCommentary(c)
  }

  useEffect(() => {
    loadTrade()
    loadCommentary()
  }, [id])

  const startEditing = () => {
    if (!trade) return
    setEditForm({
      type: trade.type,
      strategy: trade.strategy,
      category: trade.category,
      strike_price: trade.strike_price ?? undefined,
      expiry_date: trade.expiry_date ?? undefined,
      quantity: trade.quantity,
      premium: trade.premium ?? undefined,
      collateral: trade.collateral ?? undefined,
      status: trade.status as TradeUpdate['status'],
      closed_date: trade.closed_date ?? undefined,
      exit_strategy: trade.exit_strategy ?? undefined,
      rationale_notes: trade.rationale?.notes ?? undefined,
      signal_action: trade.signal_action ?? undefined,
    })
    if (categories.length === 0) {
      fetch('/api/categories').then(r => r.json()).then(setCategories).catch(() => {})
    }
    setIsEditing(true)
  }

  const cancelEditing = () => {
    setIsEditing(false)
    setSaveError(null)
  }

  const set = <K extends keyof TradeUpdate>(field: K, value: TradeUpdate[K]) =>
    setEditForm(prev => ({ ...prev, [field]: value }))

  const handleSave = async () => {
    if (!trade) return
    setSaving(true)
    setSaveError(null)
    try {
      const updated = await tradesApi.update(trade.id, editForm)
      setTrade(updated)
      setIsEditing(false)
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to save changes')
    } finally {
      setSaving(false)
    }
  }

  if (!trade) return <div className="p-6 text-gray-500">Loading...</div>

  const dte = trade.expiry_date
    ? Math.ceil((new Date(trade.expiry_date).getTime() - Date.now()) / 86400000)
    : null

  return (
    <div className="p-6 max-w-4xl">
      <button onClick={() => navigate('/trades')} className="text-sm text-blue-600 hover:underline mb-4 block">
        ← Back to trades
      </button>

      {/* Header */}
      <div className="flex justify-between items-start mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{trade.ticker}</h1>
          {isEditing
            ? <p className="text-gray-400 text-sm">Editing — opened {trade.open_date}</p>
            : <p className="text-gray-500">{trade.strategy} · {trade.type} · {trade.category}</p>
          }
        </div>
        <div className="flex items-center gap-3">
          {!isEditing && trade.strategy === 'Stock' && trade.status === 'open' && (
            <button
              onClick={() => navigate(`/scanner?ticker=${trade.ticker}`)}
              className="px-3 py-1.5 text-sm border border-blue-300 text-blue-600 rounded hover:bg-blue-50"
            >
              Scan Options
            </button>
          )}
          {!isEditing && <StatusBadge status={trade.status} />}
          {!isEditing && (
            <button
              onClick={startEditing}
              className="px-3 py-1.5 text-sm border border-gray-300 text-gray-700 rounded hover:bg-gray-50"
            >
              Edit
            </button>
          )}
          {isEditing && (
            <>
              <button
                onClick={cancelEditing}
                disabled={saving}
                className="px-3 py-1.5 text-sm border border-gray-300 text-gray-700 rounded hover:bg-gray-50 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
            </>
          )}
        </div>
      </div>

      {/* Save error banner */}
      {isEditing && saveError && (
        <div className="mb-4 p-3 bg-red-50 text-red-700 rounded text-sm">{saveError}</div>
      )}

      {/* Field grid — read mode */}
      {!isEditing && (
        <div className="grid grid-cols-2 gap-4 mb-6">
          {[
            ['Strike', trade.strike_price !== null ? `$${trade.strike_price}` : '—'],
            ['Expiry', trade.expiry_date ? `${trade.expiry_date} (${dte}d)` : '—'],
            ['Quantity', trade.quantity],
            ['Premium', trade.premium !== null ? `$${trade.premium}` : '—'],
            ['Collateral', trade.collateral !== null ? `$${trade.collateral}` : '—'],
            ['Current Price', trade.current_price !== null ? `$${trade.current_price}` : '—'],
          ].map(([label, value]) => (
            <div key={String(label)} className="bg-gray-50 rounded p-3">
              <p className="text-xs text-gray-500">{label}</p>
              <p className="text-sm font-medium mt-0.5">{String(value)}</p>
            </div>
          ))}
          <div className="bg-gray-50 rounded p-3">
            <p className="text-xs text-gray-500">Unrealized P&L</p>
            <div className="mt-0.5"><PnLDisplay value={trade.unrealized_pnl} /></div>
          </div>
        </div>
      )}

      {/* Field grid — edit mode */}
      {isEditing && (
        <>
          <div className="grid grid-cols-2 gap-4 mb-4">
            {/* Locked */}
            <div className="bg-gray-100 rounded p-3">
              <p className="text-xs text-gray-400">Ticker (locked)</p>
              <p className="text-sm font-medium mt-0.5 text-gray-500">{trade.ticker}</p>
            </div>
            <div className="bg-gray-100 rounded p-3">
              <p className="text-xs text-gray-400">Open Date (locked)</p>
              <p className="text-sm font-medium mt-0.5 text-gray-500">{trade.open_date}</p>
            </div>

            {/* Type */}
            <div>
              <label className="block text-xs text-gray-500 mb-1">Type</label>
              <select value={editForm.type ?? ''}
                onChange={e => set('type', e.target.value)}
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm">
                {TYPES.map(t => <option key={t}>{t}</option>)}
              </select>
            </div>

            {/* Strategy */}
            <div>
              <label className="block text-xs text-gray-500 mb-1">Strategy</label>
              <select value={editForm.strategy ?? ''}
                onChange={e => set('strategy', e.target.value)}
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm">
                {STRATEGIES.map(s => <option key={s}>{s}</option>)}
              </select>
            </div>

            {/* Category */}
            <div>
              <label className="block text-xs text-gray-500 mb-1">Category</label>
              {categories.length > 0
                ? (
                  <select value={editForm.category ?? ''}
                    onChange={e => set('category', e.target.value)}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm">
                    {categories.map(c => <option key={c.id} value={c.name}>{c.name}</option>)}
                  </select>
                ) : (
                  <input value={editForm.category ?? ''}
                    onChange={e => set('category', e.target.value)}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
                )}
            </div>

            {/* Strike Price */}
            <div>
              <label className="block text-xs text-gray-500 mb-1">Strike Price</label>
              <input type="number" step="0.01" value={editForm.strike_price ?? ''}
                onChange={e => set('strike_price', e.target.value ? Number(e.target.value) : null)}
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
            </div>

            {/* Expiry Date */}
            <div>
              <label className="block text-xs text-gray-500 mb-1">Expiry Date</label>
              <input type="date" value={editForm.expiry_date ?? ''}
                onChange={e => set('expiry_date', e.target.value || null)}
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
            </div>

            {/* Quantity */}
            <div>
              <label className="block text-xs text-gray-500 mb-1">Quantity</label>
              <input type="number" min="1" value={editForm.quantity ?? ''}
                onChange={e => set('quantity', Number(e.target.value))}
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
            </div>

            {/* Premium */}
            <div>
              <label className="block text-xs text-gray-500 mb-1">Premium</label>
              <input type="number" step="0.01" value={editForm.premium ?? ''}
                onChange={e => set('premium', e.target.value ? Number(e.target.value) : null)}
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
            </div>

            {/* Collateral */}
            <div>
              <label className="block text-xs text-gray-500 mb-1">Collateral</label>
              <input type="number" step="0.01" value={editForm.collateral ?? ''}
                onChange={e => set('collateral', e.target.value ? Number(e.target.value) : null)}
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
            </div>

            {/* Signal Action */}
            <div>
              <label className="block text-xs text-gray-500 mb-1">Signal Action</label>
              <input value={editForm.signal_action ?? ''}
                onChange={e => set('signal_action', e.target.value || null)}
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
            </div>
          </div>

          {/* Status + Closed Date row */}
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Status</label>
              <select value={editForm.status ?? ''}
                onChange={e => {
                  const s = e.target.value as TradeUpdate['status']
                  const today = new Date().toISOString().split('T')[0]
                  setEditForm(prev => ({
                    ...prev,
                    status: s,
                    closed_date: s === 'closed' ? (prev.closed_date ?? today) : null,
                  }))
                }}
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm">
                {STATUSES.map(s => <option key={s}>{s}</option>)}
              </select>
            </div>
            {editForm.status === 'closed' && (
              <div>
                <label className="block text-xs text-gray-500 mb-1">Closed Date</label>
                <input type="date" value={editForm.closed_date ?? ''}
                  onChange={e => set('closed_date', e.target.value || null)}
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
              </div>
            )}
          </div>

          {/* Exit Strategy */}
          <div className="mb-4">
            <label className="block text-xs text-gray-500 mb-1">Exit Strategy</label>
            <textarea rows={2} value={editForm.exit_strategy ?? ''}
              onChange={e => set('exit_strategy', e.target.value || null)}
              className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
          </div>

          {/* Rationale notes */}
          <div className="mb-6">
            <label className="block text-xs text-gray-500 mb-1">Entry Notes</label>
            <textarea rows={3} value={editForm.rationale_notes ?? ''}
              onChange={e => set('rationale_notes', e.target.value || null)}
              className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
          </div>
        </>
      )}

      {/* Exit strategy — read mode */}
      {!isEditing && trade.exit_strategy && (
        <div className="mb-4 p-3 bg-yellow-50 rounded border border-yellow-100">
          <p className="text-xs font-medium text-yellow-700">Exit Strategy</p>
          <p className="text-sm mt-1 text-gray-800">{trade.exit_strategy}</p>
        </div>
      )}

      {/* Entry rationale — read mode */}
      {!isEditing && trade.rationale && (
        <div className="mb-6 p-4 bg-white border border-gray-200 rounded-lg">
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Entry Rationale</h3>
          <div className="grid grid-cols-3 gap-2 text-xs text-gray-600">
            {trade.rationale.rsi_14 !== null && <span>RSI: {trade.rationale.rsi_14} ({trade.rationale.rsi_result})</span>}
            {trade.rationale.macd_signal && <span>MACD: {trade.rationale.macd_signal}</span>}
            {trade.rationale.sentiment && <span>Sentiment: {trade.rationale.sentiment}</span>}
          </div>
          {trade.rationale.notes && <p className="mt-2 text-sm text-gray-700">{trade.rationale.notes}</p>}
          {trade.rationale.fetch_status !== 'ok' && (
            <p className="mt-1 text-xs text-orange-500">Indicator fetch: {trade.rationale.fetch_status}</p>
          )}
        </div>
      )}

      <CommentaryThread tradeId={trade.id} ticker={trade.ticker} entries={commentary} onRefresh={loadCommentary} />
    </div>
  )
}
