// frontend/src/components/Wheel/WheelSessionCard.tsx
import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { SessionWithLegs, SessionSummary, SessionLeg } from '../../types'
import { sessionsApi } from '../../api/sessions'

interface Props {
  session: SessionWithLegs
  onStatusUpdate: (id: string, newStatus: string) => void
}

const STATUS_LABELS: Record<string, string> = {
  put_open: 'Put Open',
  shares_sitting: 'Shares Sitting',
  cc_open: 'CC Open',
  called_away: 'Called Away / Waiting Cash',
  completed: 'Completed',
}

const STATUS_COLORS: Record<string, string> = {
  put_open: '#3B82F6',
  shares_sitting: '#F59E0B',
  cc_open: '#3B82F6',
  called_away: '#F59E0B',
  completed: '#10B981',
}

const VALID_NEXT_STATUSES: Record<string, string[]> = {
  put_open: ['shares_sitting', 'completed'],
  shares_sitting: ['cc_open'],
  cc_open: ['shares_sitting', 'called_away', 'completed'],
  called_away: ['completed'],
  completed: [],
}

function activeLegSummary(legs: SessionLeg[]): string {
  const openLegs = legs.filter(l => l.status === 'open')
  const leg = openLegs.length > 0 ? openLegs[openLegs.length - 1] : legs[legs.length - 1]
  if (!leg) return '—'
  const parts: string[] = []
  if (leg.strategy) parts.push(leg.strategy)
  if (leg.strike_price != null) parts.push(`$${leg.strike_price}`)
  if (leg.expiry_date) parts.push(`exp ${leg.expiry_date}`)
  if (leg.premium != null) parts.push(`$${leg.premium} prem`)
  return parts.join(' · ')
}

export function WheelSessionCard({ session, onStatusUpdate }: Props) {
  const [expanded, setExpanded] = useState(false)
  const [showStatusEdit, setShowStatusEdit] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const color = STATUS_COLORS[session.status] ?? '#6B7280'
  const label = STATUS_LABELS[session.status] ?? session.status
  const nextStatuses = VALID_NEXT_STATUSES[session.status] ?? []

  const totalPremium = session.legs
    .filter(l => l.premium != null)
    .reduce((sum, l) => sum + (l.premium ?? 0) * l.quantity, 0)

  async function handleStatusChange(newStatus: string) {
    setSaving(true)
    setSaveError(null)
    try {
      await sessionsApi.update(session.id, { status: newStatus as 'put_open' | 'shares_sitting' | 'cc_open' | 'called_away' | 'completed' })
      onStatusUpdate(session.id, newStatus)
      setShowStatusEdit(false)
    } catch {
      setSaveError('Failed to update status')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="bg-white border border-gray-200 rounded-lg overflow-hidden" style={{ borderLeft: `4px solid ${color}` }}>
      {/* Collapsed header */}
      <div
        className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-gray-50 select-none"
        onClick={() => {
          if (expanded) {
            setShowStatusEdit(false)
            setSaveError(null)
          }
          setExpanded(e => !e)
        }}
      >
        <div className="flex items-center gap-3">
          <span
            className="text-gray-400 text-xs inline-block transition-transform duration-150"
            style={{ transform: expanded ? 'rotate(0deg)' : 'rotate(-90deg)' }}
          >▼</span>
          <span className="font-bold text-gray-900">{session.ticker}</span>
          <span
            className="text-xs font-medium px-2 py-0.5 rounded-full text-white"
            style={{ background: color }}
          >
            {label}
          </span>
          <span className="text-xs text-gray-400">Rotation {session.rotation_number}</span>
        </div>

        <div className="flex items-center gap-3 text-sm text-gray-500">
          <span className="hidden sm:block">{activeLegSummary(session.legs)}</span>
          <div className="flex gap-2" onClick={e => e.stopPropagation()}>
            {session.status === 'called_away' && (
              <Link
                to="/trades"
                className="px-2 py-1 text-xs bg-amber-100 text-amber-800 rounded hover:bg-amber-200"
              >
                + New Put
              </Link>
            )}
            {session.status === 'shares_sitting' && (
              <Link
                to="/trades"
                className="px-2 py-1 text-xs bg-amber-100 text-amber-800 rounded hover:bg-amber-200"
              >
                + Sell CC
              </Link>
            )}
            {nextStatuses.length > 0 && !showStatusEdit && (
              <button
                onClick={() => setShowStatusEdit(true)}
                className="px-2 py-1 text-xs border border-gray-300 rounded hover:bg-gray-100"
              >
                Update Status
              </button>
            )}
            {showStatusEdit && (
              <div className="flex flex-col gap-1 items-start">
                <div className="flex items-center gap-1">
                  <select
                    className="text-xs border border-gray-300 rounded px-1 py-0.5"
                    defaultValue=""
                    onChange={e => e.target.value && handleStatusChange(e.target.value)}
                    disabled={saving}
                  >
                    <option value="" disabled>Move to…</option>
                    {nextStatuses.map(s => (
                      <option key={s} value={s}>{STATUS_LABELS[s] ?? s}</option>
                    ))}
                  </select>
                  <button
                    onClick={() => setShowStatusEdit(false)}
                    className="text-xs text-gray-400 hover:text-gray-600"
                  >✕</button>
                </div>
                {saveError && <span className="text-xs text-red-500">{saveError}</span>}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Expanded body */}
      {expanded && (
        <div className="border-t border-gray-100 px-4 py-3 space-y-3">
          {/* Current rotation legs */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wider">
                Rotation {session.rotation_number} · started {session.opened_at}
              </span>
              {totalPremium > 0 && (
                <span className="text-xs font-medium text-green-600">${totalPremium.toFixed(2)} collected</span>
              )}
            </div>

            {session.legs.length === 0 ? (
              <p className="text-xs text-gray-400 italic">No legs linked yet.</p>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-gray-400 border-b border-gray-100">
                    <th className="pb-1 pr-3 font-normal">Date</th>
                    <th className="pb-1 pr-3 font-normal">Strategy</th>
                    <th className="pb-1 pr-3 font-normal">Strike</th>
                    <th className="pb-1 pr-3 font-normal">Expiry</th>
                    <th className="pb-1 pr-3 font-normal">Qty</th>
                    <th className="pb-1 pr-3 font-normal">Premium</th>
                    <th className="pb-1 pr-3 font-normal">Status</th>
                    <th className="pb-1 font-normal"></th>
                  </tr>
                </thead>
                <tbody>
                  {[...session.legs].reverse().map(leg => (
                    <tr key={leg.id} className="border-t border-gray-50">
                      <td className="py-1.5 pr-3 text-gray-500">{leg.open_date}</td>
                      <td className="py-1.5 pr-3">{leg.strategy}</td>
                      <td className="py-1.5 pr-3">{leg.strike_price != null ? `$${leg.strike_price}` : '—'}</td>
                      <td className="py-1.5 pr-3">{leg.expiry_date ?? '—'}</td>
                      <td className="py-1.5 pr-3">{leg.quantity}</td>
                      <td className="py-1.5 pr-3">{leg.premium != null ? `$${leg.premium}` : '—'}</td>
                      <td className="py-1.5 pr-3 capitalize">{leg.status}</td>
                      <td className="py-1.5">
                        <Link to={`/trades/${leg.id}`} className="text-blue-500 hover:underline">view</Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Rotation chain */}
          {session.rotation_chain.length > 0 && (
            <div className="border-t border-gray-100 pt-3">
              <div className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-1">Past Rotations</div>
              {session.rotation_chain.map((r: SessionSummary) => (
                <div key={r.id} className="text-xs text-gray-500 py-0.5">
                  Rotation {r.rotation_number} &middot; {r.opened_at} → {r.closed_at ?? 'ongoing'} &middot; {STATUS_LABELS[r.status] ?? r.status}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
