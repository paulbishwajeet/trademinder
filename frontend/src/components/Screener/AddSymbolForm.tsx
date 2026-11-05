import { useState, type FormEvent } from 'react'
import { screenerApi } from '../../api/screener'
import { ApiError } from '../../api/client'
import { useAccounts, useCurrentAccount } from '../../context/AccountsContext'
import type { ScreenerRow } from '../../types'
import { AccountMultiSelect } from './AccountPicker'
import { addToAccounts, summarizeAdd } from './addToAccounts'

interface Props {
  onAdded: (row: ScreenerRow) => void
}

export function AddSymbolForm({ onAdded }: Props) {
  const [symbol, setSymbol] = useState('')
  const [category, setCategory] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const account = useCurrentAccount()
  const { accounts, defaultAccount } = useAccounts()
  // Research only: which accounts to add to (default account preselected).
  const [picked, setPicked] = useState<string[] | null>(null)
  const selected = picked ?? (defaultAccount ? [defaultAccount.id] : [])
  const nameOf = (id: string) => accounts.find(a => a.id === id)?.nickname ?? 'Unknown'

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!symbol.trim()) return
    setLoading(true)
    setError(null)
    try {
      const base = { symbol: symbol.trim().toUpperCase(), category: category.trim() || undefined }
      if (account) {
        onAdded(await screenerApi.add({ ...base, account_id: account.id }))
      } else {
        const res = await addToAccounts(base, selected)
        if (res.row) onAdded(res.row)
        // Keep the input on any failure, or when every account already had it.
        if (res.failed.length || !res.row) {
          setError(summarizeAdd(res, nameOf))
          return
        }
      }
      setSymbol('')
      setCategory('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to add symbol')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mb-4">
      <div className="flex items-end gap-2">
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
          disabled={loading || !symbol.trim() || (!account && selected.length === 0)}
          className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:bg-gray-300"
        >
          {loading ? 'Adding…' : 'Add Symbol'}
        </button>
        {error && <span className="text-red-500 text-xs">{error}</span>}
      </div>
      {!account && (
        <div className="mt-2">
          <AccountMultiSelect selected={selected} onChange={setPicked} />
        </div>
      )}
    </form>
  )
}
