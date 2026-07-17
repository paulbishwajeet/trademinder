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

  const staleCount = trades.filter(t => t.status === 'open' && isStale(t)).length

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
