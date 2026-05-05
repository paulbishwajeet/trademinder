// frontend/src/pages/TradeDetailPage.tsx
import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { tradesApi } from '../api/trades'
import { commentaryApi } from '../api/commentary'
import type { Trade, Commentary } from '../types'
import { StatusBadge } from '../components/shared/StatusBadge'
import { PnLDisplay } from '../components/shared/PnLDisplay'
import { CommentaryThread } from '../components/Commentary/CommentaryThread'

export function TradeDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [trade, setTrade] = useState<Trade | null>(null)
  const [commentary, setCommentary] = useState<Commentary[]>([])

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

  if (!trade) return <div className="p-6 text-gray-500">Loading...</div>

  const dte = trade.expiry_date
    ? Math.ceil((new Date(trade.expiry_date).getTime() - Date.now()) / 86400000)
    : null

  return (
    <div className="p-6 max-w-4xl">
      <button onClick={() => navigate('/trades')} className="text-sm text-blue-600 hover:underline mb-4 block">
        ← Back to trades
      </button>

      <div className="flex justify-between items-start mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{trade.ticker}</h1>
          <p className="text-gray-500">{trade.strategy} · {trade.type} · {trade.category}</p>
        </div>
        <StatusBadge status={trade.status} />
      </div>

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

      {trade.exit_strategy && (
        <div className="mb-4 p-3 bg-yellow-50 rounded border border-yellow-100">
          <p className="text-xs font-medium text-yellow-700">Exit Strategy</p>
          <p className="text-sm mt-1 text-gray-800">{trade.exit_strategy}</p>
        </div>
      )}

      {trade.rationale && (
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

      <CommentaryThread tradeId={trade.id} entries={commentary} onRefresh={loadCommentary} />
    </div>
  )
}
