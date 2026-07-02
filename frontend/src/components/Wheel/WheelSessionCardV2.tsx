import { useState } from 'react'
import type { WheelSessionDetail } from '../../types'
import { WheelSlotCard } from './WheelSlotCard'
import { AddSlotModal } from './AddSlotModal'

interface Props {
  session: WheelSessionDetail
  onResolve: (slotId: string) => void
  onLinkLeg: (slotId: string) => void
  onRefresh: () => void
}

export function WheelSessionCardV2({ session, onResolve, onLinkLeg, onRefresh }: Props) {
  const [expanded, setExpanded] = useState(true)
  const [showAddSlot, setShowAddSlot] = useState(false)
  const hasAction = session.slots.some(s => s.needs_action)

  return (
    <div className={`bg-white border rounded-lg overflow-hidden ${hasAction ? 'border-amber-300' : 'border-gray-200'}`}>
      <div
        className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-gray-50"
        onClick={() => setExpanded(e => !e)}
      >
        <div className="flex items-center gap-3">
          <span className="text-gray-400 text-xs inline-block transition-transform duration-150"
            style={{ transform: expanded ? 'rotate(0deg)' : 'rotate(-90deg)' }}
          >&#9660;</span>
          <span className="font-bold text-gray-900 text-lg">{session.ticker}</span>
          <span className="text-xs text-gray-400">{session.total_shares} shares &middot; {session.slots.length} slot{session.slots.length !== 1 ? 's' : ''}</span>
          {hasAction && (
            <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 border border-amber-300">
              Action Required
            </span>
          )}
        </div>
        <div className="flex items-center gap-3" onClick={e => e.stopPropagation()}>
          <span className="text-sm font-medium text-green-600">${session.total_premium} collected</span>
          <button
            onClick={() => setShowAddSlot(true)}
            className="px-2 py-1 text-xs border border-gray-300 rounded hover:bg-gray-100"
          >
            + Slot
          </button>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-gray-100 px-4 py-3 space-y-2">
          {session.slots.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-4">No slots yet. Add a slot to start wheeling.</p>
          ) : (
            session.slots.map(slot => (
              <WheelSlotCard
                key={slot.id}
                slot={slot}
                ticker={session.ticker}
                onResolve={onResolve}
                onLinkLeg={onLinkLeg}
              />
            ))
          )}
        </div>
      )}

      {showAddSlot && (
        <AddSlotModal
          sessionId={session.id}
          onClose={() => setShowAddSlot(false)}
          onCreated={() => { setShowAddSlot(false); onRefresh() }}
        />
      )}
    </div>
  )
}
