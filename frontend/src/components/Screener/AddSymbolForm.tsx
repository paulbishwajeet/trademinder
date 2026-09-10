import { useState, type FormEvent } from 'react'
import { screenerApi } from '../../api/screener'
import { ApiError } from '../../api/client'
import type { ScreenerRow } from '../../types'

interface Props {
  onAdded: (row: ScreenerRow) => void
}

export function AddSymbolForm({ onAdded }: Props) {
  const [symbol, setSymbol] = useState('')
  const [category, setCategory] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!symbol.trim()) return
    setLoading(true)
    setError(null)
    try {
      const row = await screenerApi.add({
        symbol: symbol.trim().toUpperCase(),
        category: category.trim() || undefined,
      })
      onAdded(row)
      setSymbol('')
      setCategory('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to add symbol')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex items-end gap-2 mb-4">
      <div>
        <label className="block text-xs text-gray-500 mb-1">Symbol</label>
        <input
          value={symbol}
          onChange={e => setSymbol(e.target.value)}
          placeholder="AAPL"
          className="border border-gray-300 rounded px-2 py-1 text-sm w-28"
        />
      </div>
      <div>
        <label className="block text-xs text-gray-500 mb-1">Category</label>
        <input
          value={category}
          onChange={e => setCategory(e.target.value)}
          placeholder="Watchlist"
          className="border border-gray-300 rounded px-2 py-1 text-sm w-40"
        />
      </div>
      <button
        type="submit"
        disabled={loading || !symbol.trim()}
        className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:bg-gray-300"
      >
        {loading ? 'Adding…' : 'Add Symbol'}
      </button>
      {error && <span className="text-red-500 text-xs">{error}</span>}
    </form>
  )
}
