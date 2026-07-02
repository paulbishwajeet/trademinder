import { useState, useEffect } from 'react'
import type { Trade } from '../../types'
import { wheelApi } from '../../api/wheel'
import { tradesApi } from '../../api/trades'

interface Props {
  slotId: string
  ticker: string
  slotStatus: string
  onClose: () => void
  onLinked: () => void
}

export function LinkLegModalV2({ slotId, ticker, slotStatus, onClose, onLinked }: Props) {
  const [trades, setTrades] = useState<Trade[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedId, setSelectedId] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const legRole = slotStatus === 'awaiting_cc' ? 'covered_call' : 'sold_put'
  const label = slotStatus === 'awaiting_cc' ? 'Covered Call' : 'Sold Put'

  useEffect(() => {
    tradesApi.list({ ticker, status: 'open' })
      .then(all => setTrades(all.filter(t => !t.session_id)))
      .catch(() => setTrades([]))
      .finally(() => setLoading(false))
  }, [ticker])

  async function handleLink() {
    if (!selectedId) { setError('Select a trade'); return }
    setSaving(true)
    setError(null)
    try {
      await wheelApi.linkLeg(slotId, { trade_id: selectedId, leg_role: legRole })
      onLinked()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to link')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg w-full max-w-md p-6 shadow-xl" onClick={e => e.stopPropagation()}>
        <h2 className="text-lg font-bold text-gray-900 mb-1">Link {label}</h2>
        <p className="text-sm text-gray-500 mb-4">Select an open {ticker} trade to link as a {label.toLowerCase()}.</p>
        {error && <p className="text-sm text-red-600 mb-3">{error}</p>}
        {loading && <p className="text-sm text-gray-400 italic mb-4">Loading...</p>}
        {!loading && trades.length === 0 && (
          <p className="text-sm text-gray-400 italic mb-4">No unlinked open {ticker} trades. Create the trade first.</p>
        )}
        {!loading && trades.length > 0 && (
          <div className="mb-4 space-y-1 border border-gray-300 rounded px-3 py-2 max-h-48 overflow-y-auto">
            {trades.map(t => (
              <label key={t.id} className="flex items-center gap-2 text-sm cursor-pointer hover:bg-gray-50 rounded px-1 py-0.5">
                <input type="radio" name="trade" value={t.id} checked={selectedId === t.id} onChange={() => setSelectedId(t.id)} />
                <span>{t.strategy}</span>
                <span className="text-gray-400">&middot;</span>
                <span>{t.open_date}</span>
                {t.strike_price != null && <><span className="text-gray-400">&middot;</span><span>${t.strike_price}</span></>}
                {t.expiry_date && <><span className="text-gray-400">&middot;</span><span>exp {t.expiry_date}</span></>}
              </label>
            ))}
          </div>
        )}
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} disabled={saving} className="px-4 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50">Cancel</button>
          <button onClick={handleLink} disabled={saving || !selectedId} className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
            {saving ? 'Linking...' : `Link as ${label}`}
          </button>
        </div>
      </div>
    </div>
  )
}
