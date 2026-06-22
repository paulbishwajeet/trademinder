import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { WheelSlotDetail } from '../../types'

interface Props {
  slot: WheelSlotDetail
  ticker: string
  onResolve: (slotId: string) => void
  onLinkLeg: (slotId: string) => void
}

const STATUS_LABELS: Record<string, string> = {
  awaiting_cc: 'Awaiting CC',
  cc_active: 'CC Active',
  awaiting_sold_put: 'Awaiting Sold Put',
  sold_put_active: 'Sold Put Active',
}

const STATUS_COLORS: Record<string, string> = {
  awaiting_cc: '#F59E0B',
  cc_active: '#3B82F6',
  awaiting_sold_put: '#F59E0B',
  sold_put_active: '#3B82F6',
}

export function WheelSlotCard({ slot, ticker, onResolve, onLinkLeg }: Props) {
  const [expanded, setExpanded] = useState(false)
  const color = STATUS_COLORS[slot.status] ?? '#6B7280'
  const label = STATUS_LABELS[slot.status] ?? slot.status
  const currentLegs = slot.legs.filter(l => l.rotation_number === slot.rotation_number)
  const pastLegs = slot.legs.filter(l => l.rotation_number < slot.rotation_number)
  const activeLeg = currentLegs.find(l => l.trade_status === 'open' && l.leg_role !== 'stock')

  return (
    <div className="border border-gray-100 rounded bg-gray-50 overflow-hidden">
      <div
        className="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-gray-100"
        onClick={() => setExpanded(e => !e)}
      >
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400"
            style={{ transform: expanded ? 'rotate(0deg)' : 'rotate(-90deg)', display: 'inline-block', transition: 'transform 0.15s' }}
          >&#9660;</span>
          <span className="text-sm font-medium text-gray-700">
            Slot {slot.slot_number}
          </span>
          <span className="text-xs text-gray-400">{slot.contracts}x100 shares</span>
          <span className="text-xs font-medium px-2 py-0.5 rounded-full text-white" style={{ background: color }}>
            {label}
          </span>
          {slot.needs_action && (
            <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 border border-amber-300">
              Action Required
            </span>
          )}
          <span className="text-xs text-gray-400">R{slot.rotation_number}</span>
        </div>
        <div className="flex items-center gap-2 text-xs" onClick={e => e.stopPropagation()}>
          {activeLeg && (
            <span className="text-gray-500">
              {activeLeg.trade_strategy} ${activeLeg.trade_strike_price} exp {activeLeg.trade_expiry_date}
            </span>
          )}
          <span className="text-green-600 font-medium">${slot.total_premium}</span>
          {slot.needs_action && (
            <button onClick={() => onResolve(slot.id)} className="px-2 py-1 bg-amber-100 text-amber-800 rounded hover:bg-amber-200">
              Resolve
            </button>
          )}
          {(slot.status === 'awaiting_cc' || slot.status === 'awaiting_sold_put') && !slot.needs_action && (
            <button onClick={() => onLinkLeg(slot.id)} className="px-2 py-1 bg-blue-100 text-blue-800 rounded hover:bg-blue-200">
              {slot.status === 'awaiting_cc' ? '+ Sell CC' : '+ Sell Put'}
            </button>
          )}
        </div>
      </div>

      {expanded && (
        <div className="border-t border-gray-200 px-3 py-2 space-y-2">
          {currentLegs.length === 0 ? (
            <p className="text-xs text-gray-400 italic">No legs in current rotation.</p>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-gray-400 border-b border-gray-200">
                  <th className="pb-1 pr-2 font-normal">Role</th>
                  <th className="pb-1 pr-2 font-normal">Strategy</th>
                  <th className="pb-1 pr-2 font-normal">Strike</th>
                  <th className="pb-1 pr-2 font-normal">Expiry</th>
                  <th className="pb-1 pr-2 font-normal">Qty</th>
                  <th className="pb-1 pr-2 font-normal">Premium</th>
                  <th className="pb-1 pr-2 font-normal">Status</th>
                  <th className="pb-1 font-normal"></th>
                </tr>
              </thead>
              <tbody>
                {currentLegs.map(leg => (
                  <tr key={leg.id} className="border-t border-gray-100">
                    <td className="py-1 pr-2 capitalize">{leg.leg_role.replace('_', ' ')}</td>
                    <td className="py-1 pr-2">{leg.trade_strategy}</td>
                    <td className="py-1 pr-2">{leg.trade_strike_price != null ? `$${leg.trade_strike_price}` : '—'}</td>
                    <td className="py-1 pr-2">{leg.trade_expiry_date ?? '—'}</td>
                    <td className="py-1 pr-2">{leg.trade_quantity}</td>
                    <td className="py-1 pr-2">{leg.trade_premium != null ? `$${leg.trade_premium}` : '—'}</td>
                    <td className="py-1 pr-2 capitalize">{leg.trade_status}</td>
                    <td className="py-1"><Link to={`/trades/${leg.trade_id}`} className="text-blue-500 hover:underline">view</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {pastLegs.length > 0 && (
            <div className="border-t border-gray-200 pt-2">
              <span className="text-xs font-medium text-gray-400 uppercase">Past Rotations</span>
              <table className="w-full text-xs mt-1">
                <tbody>
                  {pastLegs.map(leg => (
                    <tr key={leg.id} className="text-gray-400">
                      <td className="py-0.5 pr-2">R{leg.rotation_number}</td>
                      <td className="py-0.5 pr-2 capitalize">{leg.leg_role.replace('_', ' ')}</td>
                      <td className="py-0.5 pr-2">{leg.trade_strategy}</td>
                      <td className="py-0.5 pr-2">{leg.trade_strike_price != null ? `$${leg.trade_strike_price}` : '—'}</td>
                      <td className="py-0.5 pr-2">{leg.trade_expiry_date ?? '—'}</td>
                      <td className="py-0.5"><Link to={`/trades/${leg.trade_id}`} className="text-blue-400 hover:underline">view</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {slot.premium_logs.length > 0 && (
            <div className="border-t border-gray-200 pt-2">
              <span className="text-xs font-medium text-gray-400 uppercase">Premium Log</span>
              <div className="mt-1 space-y-0.5">
                {slot.premium_logs.map(log => (
                  <div key={log.id} className="flex justify-between text-xs">
                    <span className="text-gray-500">{log.event_date} &middot; {log.event_type.replace(/_/g, ' ')}</span>
                    <span className={parseFloat(log.premium_amount) >= 0 ? 'text-green-600' : 'text-red-600'}>
                      {parseFloat(log.premium_amount) >= 0 ? '+' : ''}${log.premium_amount}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
