import { useState } from 'react'
import type { WheelSessionDetail } from '../../types'
import { wheelApi } from '../../api/wheel'

// Same rule as the backend's WheelSessionUpdate (a 422 there only surfaces as "Request failed").
const TICKER_RE = /^[A-Z0-9.\-/]{1,10}$/

interface Props {
  session: Pick<WheelSessionDetail, 'id' | 'ticker' | 'total_shares' | 'opened_at'>
  onClose: () => void
  onSaved: () => void
}

/** Edit a wheel that has no slot yet: ticker, shares held and start date. */
export function EditWheelModal({ session, onClose, onSaved }: Props) {
  const [ticker, setTicker] = useState(session.ticker)
  const [totalShares, setTotalShares] = useState(session.total_shares)
  const [openedAt, setOpenedAt] = useState(session.opened_at)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSave() {
    const t = ticker.trim().toUpperCase()
    if (!TICKER_RE.test(t)) { setError("Ticker must be 1–10 letters, digits, '.', '-' or '/'"); return }
    if (!openedAt) { setError('Start date is required'); return }
    setSaving(true)
    setError(null)
    try {
      await wheelApi.update(session.id, { ticker: t, total_shares: totalShares, opened_at: openedAt })
      onSaved()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg w-full max-w-md p-6 shadow-xl" onClick={e => e.stopPropagation()}>
        <h2 className="text-lg font-bold text-gray-900 mb-4">Edit Wheel</h2>
        {error && <p className="text-sm text-red-600 mb-3">{error}</p>}
        <div className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Ticker</label>
            <input
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm uppercase"
              value={ticker}
              onChange={e => setTicker(e.target.value.toUpperCase())}
              autoFocus
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Total Shares Held</label>
            <input
              type="number"
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
              value={totalShares}
              onChange={e => setTotalShares(Math.max(0, parseInt(e.target.value) || 0))}
              min={0}
              step={100}
            />
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
          <button onClick={handleSave} disabled={saving} className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
