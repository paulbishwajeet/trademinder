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
