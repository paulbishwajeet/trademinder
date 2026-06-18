import { useState, useEffect } from 'react'
import type { Trade } from '../../types'
import { tradesApi } from '../../api/trades'
import { sessionsApi } from '../../api/sessions'

interface Props {
  sessionId: string
  ticker: string
  targetStatus: string
  onDone: () => void
  onCancel: () => void
}

const STATUS_LABELS: Record<string, string> = {
  cc_open: 'CC Open',
  put_open: 'Put Open',
}

export function LinkLegModal({ sessionId, ticker, targetStatus, onDone, onCancel }: Props) {
  const [trades, setTrades] = useState<Trade[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    tradesApi.list({ ticker })
      .then(all => setTrades(all.filter(t => !t.session_id && t.status === 'open')))
      .catch(() => setTrades([]))
      .finally(() => setLoading(false))
  }, [ticker])

  function toggle(id: string) {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function handleConfirm() {
    setSaving(true)
    setError(null)
    try {
      await Promise.all(
        [...selectedIds].map(id => tradesApi.update(id, { session_id: sessionId })),
      )
      await sessionsApi.update(sessionId, { status: targetStatus })
      onDone()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to link trade')
    } finally {
      setSaving(false)
    }
  }

  async function handleSkip() {
    setSaving(true)
    setError(null)
    try {
      await sessionsApi.update(sessionId, { status: targetStatus })
      onDone()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to update status')
    } finally {
      setSaving(false)
    }
  }

  const label = STATUS_LABELS[targetStatus] ?? targetStatus

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onCancel}>
      <div className="bg-white rounded-lg w-full max-w-md p-6 shadow-xl" onClick={e => e.stopPropagation()}>
        <h2 className="text-lg font-bold text-gray-900 mb-1">Link Trade to Session</h2>
        <p className="text-sm text-gray-500 mb-4">
          Select an open {ticker} trade to attach as a leg before moving to {label}.
        </p>

        {error && <p className="text-sm text-red-600 mb-3">{error}</p>}

        {loading && <p className="text-sm text-gray-400 italic mb-4">Loading trades…</p>}

        {!loading && trades.length === 0 && (
          <p className="text-sm text-gray-400 italic mb-4">
            No unlinked open {ticker} trades found. You can skip and link later.
          </p>
        )}

        {!loading && trades.length > 0 && (
          <div className="mb-4">
            <div className="space-y-1 border border-gray-300 rounded px-3 py-2 max-h-48 overflow-y-auto">
              {trades.map(t => (
                <label key={t.id} className="flex items-center gap-2 text-sm cursor-pointer hover:bg-gray-50 rounded px-1 py-0.5">
                  <input
                    type="checkbox"
                    checked={selectedIds.has(t.id)}
                    onChange={() => toggle(t.id)}
                  />
                  <span>{t.strategy}</span>
                  <span className="text-gray-400">·</span>
                  <span>{t.open_date}</span>
                  {t.strike_price != null && (
                    <>
                      <span className="text-gray-400">·</span>
                      <span>${t.strike_price}</span>
                    </>
                  )}
                  {t.expiry_date && (
                    <>
                      <span className="text-gray-400">·</span>
                      <span>exp {t.expiry_date}</span>
                    </>
                  )}
                </label>
              ))}
            </div>
          </div>
        )}

        <div className="flex gap-2 justify-end">
          <button
            onClick={onCancel}
            disabled={saving}
            className="px-4 py-2 text-sm text-gray-500 hover:text-gray-700"
          >
            Cancel
          </button>
          <button
            onClick={handleSkip}
            disabled={saving}
            className="px-4 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50"
          >
            {saving ? 'Updating…' : `Skip → ${label}`}
          </button>
          {selectedIds.size > 0 && (
            <button
              onClick={handleConfirm}
              disabled={saving}
              className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? 'Linking…' : `Link & Move → ${label}`}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
