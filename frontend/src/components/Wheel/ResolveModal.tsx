import { useState, useEffect } from 'react'
import type { Trade } from '../../types'
import { wheelApi } from '../../api/wheel'
import { tradesApi } from '../../api/trades'

interface Props {
  slotId: string
  ticker: string
  onClose: () => void
  onResolved: () => void
}

interface OutcomeOption {
  value: string
  label: string
  needsNewTrade: boolean
  newTradeLabel?: string
  needsBuybackCost: boolean
}

const CC_OUTCOMES: OutcomeOption[] = [
  { value: 'cc_expired_otm', label: 'CC expired OTM (keep shares)', needsNewTrade: false, needsBuybackCost: false },
  { value: 'cc_expired_itm', label: 'CC expired ITM (shares called away)', needsNewTrade: false, needsBuybackCost: false },
  { value: 'cc_bought_back', label: 'Bought back early', needsNewTrade: false, needsBuybackCost: true },
  { value: 'cc_rolled', label: 'Rolled to new position', needsNewTrade: true, newTradeLabel: 'New CC trade', needsBuybackCost: true },
]

const PUT_OUTCOMES: OutcomeOption[] = [
  { value: 'put_expired_otm', label: 'Put expired OTM (no assignment)', needsNewTrade: false, needsBuybackCost: false },
  { value: 'put_assigned', label: 'Put assigned (got shares)', needsNewTrade: true, newTradeLabel: 'Stock trade', needsBuybackCost: false },
  { value: 'put_bought_back', label: 'Bought back early', needsNewTrade: false, needsBuybackCost: true },
  { value: 'put_rolled', label: 'Rolled to new position', needsNewTrade: true, newTradeLabel: 'New put trade', needsBuybackCost: true },
]

export function ResolveModal({ slotId, ticker, onClose, onResolved }: Props) {
  const [outcome, setOutcome] = useState('')
  const [buybackCost, setBuybackCost] = useState('')
  const [newTradeId, setNewTradeId] = useState('')
  const [trades, setTrades] = useState<Trade[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [slotStatus, setSlotStatus] = useState<string>('')

  useEffect(() => {
    tradesApi.list({ ticker, status: 'open' })
      .then(all => setTrades(all.filter(t => !t.session_id)))
      .catch(() => setTrades([]))
  }, [ticker])

  useEffect(() => {
    wheelApi.activeSlots().then(slots => {
      const slot = slots.find(s => s.id === slotId)
      if (slot) setSlotStatus(slot.status)
    }).catch(() => {})
  }, [slotId])

  const outcomes = slotStatus.startsWith('cc') ? CC_OUTCOMES : PUT_OUTCOMES
  const selected = outcomes.find(o => o.value === outcome)

  async function handleResolve() {
    if (!outcome) { setError('Select an outcome'); return }
    setSaving(true)
    setError(null)
    try {
      await wheelApi.resolve(slotId, {
        outcome,
        new_trade_id: selected?.needsNewTrade && newTradeId ? newTradeId : null,
        buyback_cost: selected?.needsBuybackCost && buybackCost ? buybackCost : null,
      })
      onResolved()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to resolve')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg w-full max-w-md p-6 shadow-xl" onClick={e => e.stopPropagation()}>
        <h2 className="text-lg font-bold text-gray-900 mb-4">Resolve &mdash; {ticker}</h2>
        {error && <p className="text-sm text-red-600 mb-3">{error}</p>}
        <div className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">What happened?</label>
            <select
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
              value={outcome}
              onChange={e => setOutcome(e.target.value)}
            >
              <option value="">Select outcome...</option>
              {outcomes.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>

          {selected?.needsBuybackCost && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Buyback Cost (per share)</label>
              <input
                type="number"
                step="0.01"
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
                value={buybackCost}
                onChange={e => setBuybackCost(e.target.value)}
                placeholder="e.g. 1.50"
              />
            </div>
          )}

          {selected?.needsNewTrade && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{selected.newTradeLabel}</label>
              {trades.length === 0 ? (
                <p className="text-xs text-gray-400 italic">No unlinked open {ticker} trades. Create the trade first, then resolve.</p>
              ) : (
                <select
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
                  value={newTradeId}
                  onChange={e => setNewTradeId(e.target.value)}
                >
                  <option value="">Select trade...</option>
                  {trades.map(t => (
                    <option key={t.id} value={t.id}>
                      {t.strategy} &middot; {t.open_date}{t.strike_price != null ? ` · $${t.strike_price}` : ''}{t.expiry_date ? ` · exp ${t.expiry_date}` : ''}
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}
        </div>
        <div className="flex gap-2 justify-end mt-5">
          <button onClick={onClose} className="px-4 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50">Cancel</button>
          <button onClick={handleResolve} disabled={saving || !outcome} className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
            {saving ? 'Resolving...' : 'Resolve'}
          </button>
        </div>
      </div>
    </div>
  )
}
