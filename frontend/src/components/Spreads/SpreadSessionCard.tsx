// frontend/src/components/Spreads/SpreadSessionCard.tsx
import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { SessionWithLegs, SessionLeg } from '../../types'
import { sessionsApi } from '../../api/sessions'

interface Props {
  session: SessionWithLegs
  price: number | null
  onClosed: (id: string) => void
}

const STRATEGY_LABELS: Record<string, string> = {
  IRON_CONDOR: 'IC',
  PUT_B_W_FLY: 'PBWB',
}

const STRATEGY_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  IRON_CONDOR: { bg: '#EDE9FE', text: '#5B21B6', border: '#C4B5FD' },
  PUT_B_W_FLY: { bg: '#CCFBF1', text: '#0F766E', border: '#5EEAD4' },
}

type Signal = 'safe' | 'warning' | 'danger' | 'unknown'

function computeSignal(legs: SessionLeg[], price: number, strategy: string): Signal {
  if (strategy === 'IRON_CONDOR') {
    const shortPutStrikes = legs
      .filter(l => l.strategy === 'Sell Put' && l.strike_price != null)
      .map(l => l.strike_price as number)
    const shortCallStrikes = legs
      .filter(l => l.strategy === 'Sell Call' && l.strike_price != null)
      .map(l => l.strike_price as number)
    if (!shortPutStrikes.length || !shortCallStrikes.length) return 'unknown'
    const sp = Math.max(...shortPutStrikes)
    const sc = Math.min(...shortCallStrikes)
    if (price <= sp || price >= sc) return 'danger'
    if (price < sp * 1.05 || price > sc * 0.95) return 'warning'
    return 'safe'
  }
  if (strategy === 'PUT_B_W_FLY') {
    const shortStrikes = legs
      .filter(l => l.strategy === 'Sell Put' && l.strike_price != null)
      .map(l => l.strike_price as number)
    if (shortStrikes.length < 2) return 'unknown'
    const low = Math.min(...shortStrikes)
    const high = Math.max(...shortStrikes)
    if (price <= low || price >= high) return 'danger'
    if (price < low * 1.05 || price > high * 0.95) return 'warning'
    return 'safe'
  }
  return 'unknown'
}

const SIGNAL_STYLES: Record<Signal, { bg: string; border: string; text: string; icon: string; label: string }> = {
  safe:    { bg: 'bg-green-50', border: 'border-green-200', text: 'text-green-700', icon: '✓', label: 'Safe' },
  warning: { bg: 'bg-amber-50', border: 'border-amber-200', text: 'text-amber-700', icon: '⚠', label: 'Approaching' },
  danger:  { bg: 'bg-red-50',   border: 'border-red-200',   text: 'text-red-700',   icon: '✗', label: 'Breached' },
  unknown: { bg: 'bg-gray-50',  border: 'border-gray-200',  text: 'text-gray-400',  icon: '?', label: 'No signal' },
}

function PriceSignal({ session, price }: { session: SessionWithLegs; price: number | null }) {
  if (price == null) {
    return <span className="text-xs text-gray-400">Price unavailable</span>
  }
  const signal = computeSignal(session.legs, price, session.strategy)
  const s = SIGNAL_STYLES[signal]
  return (
    <span className={`text-xs px-2 py-0.5 rounded border ${s.bg} ${s.border} ${s.text}`}>
      {s.icon} {s.label} · ${price.toFixed(2)}
    </span>
  )
}

export function SpreadSessionCard({ session, price, onClosed }: Props) {
  const [expanded, setExpanded] = useState(false)
  const [closing, setClosing] = useState(false)
  const [closeError, setCloseError] = useState<string | null>(null)

  const strategyLabel = STRATEGY_LABELS[session.strategy] ?? session.strategy
  const strategyColor = STRATEGY_COLORS[session.strategy] ?? { bg: '#F3F4F6', text: '#374151', border: '#D1D5DB' }

  const expiry = session.legs.find(l => l.expiry_date)?.expiry_date ?? null

  async function handleClose() {
    setClosing(true)
    setCloseError(null)
    try {
      await sessionsApi.update(session.id, { status: 'closed', closed_at: new Date().toISOString().slice(0, 10) })
      onClosed(session.id)
    } catch {
      setCloseError('Failed to close session')
    } finally {
      setClosing(false)
    }
  }

  return (
    <div
      className="bg-white border border-gray-200 rounded-lg overflow-hidden"
      style={{ borderLeft: `4px solid ${strategyColor.border}` }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-gray-50 select-none"
        onClick={() => setExpanded(e => !e)}
      >
        <div className="flex items-center gap-3">
          <span
            className="text-gray-400 text-xs inline-block transition-transform duration-150"
            style={{ transform: expanded ? 'rotate(0deg)' : 'rotate(-90deg)' }}
          >▼</span>
          <span className="font-bold text-gray-900">{session.ticker}</span>
          <span
            className="text-xs font-medium px-2 py-0.5 rounded-full"
            style={{ background: strategyColor.bg, color: strategyColor.text, border: `1px solid ${strategyColor.border}` }}
          >
            {strategyLabel}
          </span>
          {expiry && <span className="text-xs text-gray-400">exp {expiry}</span>}
        </div>
        <div className="flex items-center gap-3" onClick={e => e.stopPropagation()}>
          <PriceSignal session={session} price={price} />
          <button
            onClick={handleClose}
            disabled={closing}
            className="px-2 py-1 text-xs border border-gray-300 rounded hover:bg-gray-100 disabled:opacity-50"
          >
            {closing ? 'Closing…' : 'Close Session'}
          </button>
        </div>
      </div>

      {closeError && (
        <p className="px-4 pb-2 text-xs text-red-600">{closeError}</p>
      )}

      {/* Expanded legs */}
      {expanded && (
        <div className="border-t border-gray-100 px-4 py-3">
          <div className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">
            Legs · opened {session.opened_at}
          </div>
          {session.legs.length === 0 ? (
            <p className="text-xs text-gray-400 italic">No legs linked yet.</p>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-gray-400 border-b border-gray-100">
                  <th className="pb-1 pr-3 font-normal">Date</th>
                  <th className="pb-1 pr-3 font-normal">Strategy</th>
                  <th className="pb-1 pr-3 font-normal">Type</th>
                  <th className="pb-1 pr-3 font-normal">Strike</th>
                  <th className="pb-1 pr-3 font-normal">Expiry</th>
                  <th className="pb-1 pr-3 font-normal">Qty</th>
                  <th className="pb-1 pr-3 font-normal">Premium</th>
                  <th className="pb-1 font-normal"></th>
                </tr>
              </thead>
              <tbody>
                {session.legs.map(leg => (
                  <tr key={leg.id} className="border-t border-gray-50">
                    <td className="py-1.5 pr-3 text-gray-500">{leg.open_date}</td>
                    <td className="py-1.5 pr-3">{leg.strategy}</td>
                    <td className="py-1.5 pr-3">{leg.type}</td>
                    <td className="py-1.5 pr-3">{leg.strike_price != null ? `$${leg.strike_price}` : '—'}</td>
                    <td className="py-1.5 pr-3">{leg.expiry_date ?? '—'}</td>
                    <td className="py-1.5 pr-3">{leg.quantity}</td>
                    <td className="py-1.5 pr-3">{leg.premium != null ? `$${leg.premium}` : '—'}</td>
                    <td className="py-1.5">
                      <Link to={`/trades/${leg.id}`} className="text-blue-500 hover:underline">view</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
