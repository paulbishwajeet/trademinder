// frontend/src/components/Wheel/NewWheelModal.tsx
import { useState } from 'react'
import type { SessionSummary, Trade } from '../../types'
import { sessionsApi } from '../../api/sessions'
import { tradesApi } from '../../api/trades'

interface Props {
  onClose: () => void
  onCreated: (session: SessionSummary) => void
}

const WHEEL_STATUSES = [
  { value: 'put_open', label: 'Put Open — I have an active Sold Put' },
  { value: 'shares_sitting', label: 'Shares Sitting — I own the stock, no CC yet' },
  { value: 'cc_open', label: 'CC Open — I have an active Covered Call' },
  { value: 'called_away', label: 'Called Away / Waiting Cash' },
]

export function NewWheelModal({ onClose, onCreated }: Props) {
  const [step, setStep] = useState<1 | 2>(1)
  const [ticker, setTicker] = useState('')
  const [status, setStatus] = useState('put_open')
  const [openedAt, setOpenedAt] = useState(() => new Date().toISOString().slice(0, 10))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [createdSession, setCreatedSession] = useState<SessionSummary | null>(null)

  // Step 2 state
  const [availableTrades, setAvailableTrades] = useState<Trade[]>([])
  const [selectedTradeId, setSelectedTradeId] = useState('')
  const [linking, setLinking] = useState(false)

  async function handleCreateSession() {
    if (!ticker.trim()) { setError('Ticker is required'); return }
    setSaving(true)
    setError(null)
    try {
      const session = await sessionsApi.create({
        ticker: ticker.trim().toUpperCase(),
        strategy: 'WHEEL',
        status: status as 'put_open' | 'shares_sitting' | 'cc_open' | 'called_away' | 'completed',
        opened_at: openedAt,
      })
      setCreatedSession(session)
      const all = await tradesApi.list({ ticker: ticker.trim().toUpperCase() })
      setAvailableTrades(all.filter(t => !t.session_id))
      setStep(2)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to create session')
    } finally {
      setSaving(false)
    }
  }

  async function handleLinkAndFinish() {
    if (!selectedTradeId || !createdSession) return
    setLinking(true)
    setError(null)
    try {
      await tradesApi.update(selectedTradeId, { session_id: createdSession.id })
      onCreated(createdSession)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to link trade')
    } finally {
      setLinking(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg w-full max-w-md p-6 shadow-xl">
        {step === 1 && (
          <>
            <h2 className="text-lg font-bold text-gray-900 mb-4">New WHEEL Session</h2>
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
                <label className="block text-sm font-medium text-gray-700 mb-1">Current Phase</label>
                <select
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
                  value={status}
                  onChange={e => setStatus(e.target.value)}
                >
                  {WHEEL_STATUSES.map(s => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </select>
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
              <button onClick={onClose} className="px-4 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50">
                Cancel
              </button>
              <button
                onClick={handleCreateSession}
                disabled={saving}
                className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
              >
                {saving ? 'Creating…' : 'Create Session →'}
              </button>
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <h2 className="text-lg font-bold text-gray-900 mb-1">Link an Existing Trade</h2>
            <p className="text-sm text-gray-500 mb-4">
              Optionally attach an existing {ticker} trade to this session as a leg.
            </p>
            {error && <p className="text-sm text-red-600 mb-3">{error}</p>}
            {availableTrades.length === 0 ? (
              <p className="text-sm text-gray-400 italic mb-4">No unlinked {ticker} trades found.</p>
            ) : (
              <div className="mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-1">Select trade to link</label>
                <select
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
                  value={selectedTradeId}
                  onChange={e => setSelectedTradeId(e.target.value)}
                >
                  <option value="">— Skip —</option>
                  {availableTrades.map(t => (
                    <option key={t.id} value={t.id}>
                      {t.strategy} · {t.open_date}{t.strike_price != null ? ` · $${t.strike_price}` : ''} · {t.status}
                    </option>
                  ))}
                </select>
              </div>
            )}
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => createdSession && onCreated(createdSession)}
                className="px-4 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50"
              >
                Skip
              </button>
              {selectedTradeId && (
                <button
                  onClick={handleLinkAndFinish}
                  disabled={linking}
                  className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
                >
                  {linking ? 'Linking…' : 'Link & Done'}
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
