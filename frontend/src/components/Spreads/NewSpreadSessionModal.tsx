import { useState } from 'react'
import type { SessionSummary, Trade } from '../../types'
import { sessionsApi } from '../../api/sessions'
import { tradesApi } from '../../api/trades'

interface Props {
  onClose: () => void
  onCreated: (session: SessionSummary) => void
}

const STRATEGY_OPTIONS = [
  { value: 'IRON_CONDOR', label: 'Iron Condor (IC)' },
  { value: 'PUT_B_W_FLY', label: 'Put Broken Wing Butterfly (PBWB)' },
]

export function NewSpreadSessionModal({ onClose, onCreated }: Props) {
  const [step, setStep] = useState<1 | 2>(1)
  const [ticker, setTicker] = useState('')
  const [strategy, setStrategy] = useState('IRON_CONDOR')
  const [openedAt, setOpenedAt] = useState(() => new Date().toISOString().slice(0, 10))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [createdSession, setCreatedSession] = useState<SessionSummary | null>(null)

  // Step 2 state
  const [availableTrades, setAvailableTrades] = useState<Trade[]>([])
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [linking, setLinking] = useState(false)

  async function handleCreateSession() {
    if (!ticker.trim()) { setError('Ticker is required'); return }
    setSaving(true)
    setError(null)
    try {
      const session = await sessionsApi.create({
        ticker: ticker.trim().toUpperCase(),
        strategy,
        status: 'open',
        opened_at: openedAt,
      })
      setCreatedSession(session)
      try {
        const all = await tradesApi.list({ ticker: ticker.trim().toUpperCase() })
        setAvailableTrades(all.filter(t => !t.session_id))
      } catch {
        // non-fatal — advance to step 2 with empty list
      }
      setStep(2)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to create session')
    } finally {
      setSaving(false)
    }
  }

  function toggleTrade(id: string) {
    setSelectedIds(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  async function handleLinkAndFinish() {
    if (!createdSession) return
    setLinking(true)
    setError(null)
    try {
      await Promise.all(
        [...selectedIds].map(id => tradesApi.update(id, { session_id: createdSession.id }))
      )
      onCreated(createdSession)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to link trades')
    } finally {
      setLinking(false)
    }
  }

  const strategyLabel = STRATEGY_OPTIONS.find(o => o.value === strategy)?.label ?? strategy

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg w-full max-w-md p-6 shadow-xl">
        {step === 1 && (
          <>
            <h2 className="text-lg font-bold text-gray-900 mb-4">New Spread Session</h2>
            {error && <p className="text-sm text-red-600 mb-3">{error}</p>}
            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Ticker</label>
                <input
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm uppercase"
                  value={ticker}
                  onChange={e => setTicker(e.target.value.toUpperCase())}
                  placeholder="e.g. QQQ"
                  autoFocus
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Strategy</label>
                <select
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
                  value={strategy}
                  onChange={e => setStrategy(e.target.value)}
                >
                  {STRATEGY_OPTIONS.map(o => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Opened On</label>
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
            <h2 className="text-lg font-bold text-gray-900 mb-1">Link Existing Legs</h2>
            <p className="text-sm text-gray-500 mb-4">
              Select unlinked {ticker} trades to attach as legs to this {strategyLabel} session.
            </p>
            {error && <p className="text-sm text-red-600 mb-3">{error}</p>}
            {availableTrades.length === 0 ? (
              <p className="text-sm text-gray-400 italic mb-4">No unlinked {ticker} trades found.</p>
            ) : (
              <div className="mb-4 space-y-1 max-h-64 overflow-y-auto border border-gray-100 rounded p-2">
                {availableTrades.map(t => (
                  <label key={t.id} className="flex items-center gap-2 text-sm cursor-pointer hover:bg-gray-50 px-2 py-1 rounded">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(t.id)}
                      onChange={() => toggleTrade(t.id)}
                      className="rounded"
                    />
                    <span className="text-gray-700">{t.strategy}</span>
                    <span className="text-gray-400">·</span>
                    <span className="text-gray-500">{t.open_date}</span>
                    {t.strike_price != null && (
                      <><span className="text-gray-400">·</span><span className="text-gray-600">${t.strike_price}</span></>
                    )}
                    {t.expiry_date && (
                      <><span className="text-gray-400">·</span><span className="text-gray-500">exp {t.expiry_date}</span></>
                    )}
                  </label>
                ))}
              </div>
            )}
            <div className="flex gap-2 justify-end">
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm text-gray-500 hover:text-gray-700"
              >
                Close
              </button>
              <button
                onClick={() => createdSession && onCreated(createdSession)}
                className="px-4 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50"
              >
                Skip
              </button>
              {selectedIds.size > 0 && (
                <button
                  onClick={handleLinkAndFinish}
                  disabled={linking}
                  className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
                >
                  {linking ? 'Linking…' : `Link ${selectedIds.size} trade${selectedIds.size > 1 ? 's' : ''} & Done`}
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
