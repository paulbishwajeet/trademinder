import { useState } from 'react'
import type { WheelSessionSummary } from '../../types'
import { wheelApi } from '../../api/wheel'

interface Props {
  onClose: () => void
  onCreated: (session: WheelSessionSummary) => void
}

export function NewWheelModalV2({ onClose, onCreated }: Props) {
  const [ticker, setTicker] = useState('')
  const [totalShares, setTotalShares] = useState(0)
  const [openedAt, setOpenedAt] = useState(() => new Date().toISOString().slice(0, 10))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleCreate() {
    if (!ticker.trim()) { setError('Ticker is required'); return }
    setSaving(true)
    setError(null)
    try {
      const session = await wheelApi.create({
        ticker: ticker.trim().toUpperCase(),
        total_shares: totalShares,
        opened_at: openedAt,
      })
      onCreated(session)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to create session')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg w-full max-w-md p-6 shadow-xl" onClick={e => e.stopPropagation()}>
        <h2 className="text-lg font-bold text-gray-900 mb-4">New Wheel</h2>
        {error && <p className="text-sm text-red-600 mb-3">{error}</p>}
        <div className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Ticker</label>
            <input
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm uppercase"
              value={ticker}
              onChange={e => setTicker(e.target.value.toUpperCase())}
              placeholder="e.g. NVDA"
              autoFocus
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Total Shares Held</label>
            <input
              type="number"
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
              value={totalShares}
              onChange={e => setTotalShares(parseInt(e.target.value) || 0)}
              min={0}
              step={100}
            />
            <p className="text-xs text-gray-400 mt-1">0 if starting with sold puts only</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Started On</label>
            <input
              type="date"
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
              value={openedAt}
              onChange={e => setOpenedAt(e.target.value)}
            />
          </div>
        </div>
        <div className="flex gap-2 justify-end mt-5">
          <button onClick={onClose} className="px-4 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50">Cancel</button>
          <button onClick={handleCreate} disabled={saving} className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
            {saving ? 'Creating...' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  )
}
