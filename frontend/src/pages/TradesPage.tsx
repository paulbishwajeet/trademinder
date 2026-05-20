// frontend/src/pages/TradesPage.tsx
import { useState, useEffect } from 'react'
import { tradesApi } from '../api/trades'
import { technicalsApi } from '../api/technicals'
import type { Trade, TechnicalsData } from '../types'
import { TradeTable } from '../components/Trades/TradeTable'
import { TradeForm } from '../components/Trades/TradeForm'
import type { TradeCreate } from '../types'

export function TradesPage() {
  const [trades, setTrades] = useState<Trade[]>([])
  const [showForm, setShowForm] = useState(false)
  const [statusFilter, setStatusFilter] = useState<string>('')

  const load = async () => {
    const data = await tradesApi.list(statusFilter ? { status: statusFilter } : undefined)
    setTrades(data)
  }

  useEffect(() => { load() }, [statusFilter])

  const handleCreate = async (payload: TradeCreate, technicals: TechnicalsData | null) => {
    const trade = await tradesApi.create(payload)
    if (technicals) {
      await technicalsApi.saveTradeRationale(trade.id, technicals)
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
        {['', 'open', 'closed', 'expired', 'assigned'].map(s => (
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
        <TradeTable trades={trades} onDelete={handleDelete} />
      </div>
    </div>
  )
}
