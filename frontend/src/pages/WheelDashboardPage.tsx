import { useState, useEffect } from 'react'
import type { WheelSessionDetail, WheelSessionSummary } from '../types'
import { wheelApi } from '../api/wheel'
import { WheelSessionCardV2 } from '../components/Wheel/WheelSessionCardV2'
import { NewWheelModalV2 } from '../components/Wheel/NewWheelModalV2'
import { ResolveModal } from '../components/Wheel/ResolveModal'
import { LinkLegModalV2 } from '../components/Wheel/LinkLegModalV2'

export function WheelDashboardPage() {
  const [sessions, setSessions] = useState<WheelSessionDetail[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showNewModal, setShowNewModal] = useState(false)
  const [resolveSlotId, setResolveSlotId] = useState<string | null>(null)
  const [linkSlotId, setLinkSlotId] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const summaries = await wheelApi.list()
      const detailed = await Promise.all(summaries.map(s => wheelApi.get(s.id)))
      setSessions(detailed)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  function handleNewSession(_s: WheelSessionSummary) {
    setShowNewModal(false)
    load()
  }

  const needsAction = sessions.filter(s => s.slots.some(sl => sl.needs_action))
  const monitoring = sessions.filter(s => !s.slots.some(sl => sl.needs_action))

  const resolveSlotTicker = resolveSlotId
    ? sessions.find(s => s.slots.some(sl => sl.id === resolveSlotId))?.ticker ?? ''
    : ''
  const linkSlotTicker = linkSlotId
    ? sessions.find(s => s.slots.some(sl => sl.id === linkSlotId))?.ticker ?? ''
    : ''
  const linkSlotStatus = linkSlotId
    ? sessions.flatMap(s => s.slots).find(sl => sl.id === linkSlotId)?.status ?? ''
    : ''

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold text-gray-900">WHEEL Strategy</h1>
        <button onClick={() => setShowNewModal(true)} className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700">
          + New Wheel
        </button>
      </div>

      {loading && <p className="text-gray-500 text-center py-12">Loading...</p>}
      {error && <div className="bg-red-50 border border-red-200 text-red-700 rounded p-4 mb-4 text-sm">{error}</div>}

      {!loading && !error && sessions.length === 0 && (
        <div className="text-center py-16">
          <p className="text-gray-400 mb-4">No wheels yet.</p>
          <button onClick={() => setShowNewModal(true)} className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700">
            + New Wheel
          </button>
        </div>
      )}

      {!loading && !error && sessions.length > 0 && (
        <>
          {needsAction.length > 0 && (
            <section className="mb-6">
              <div className="flex items-center gap-2 mb-3">
                <span className="text-sm font-bold text-amber-600">NEEDS ACTION</span>
                <span className="bg-amber-100 text-amber-700 text-xs px-2 py-0.5 rounded-full font-medium">{needsAction.length}</span>
              </div>
              <div className="space-y-3">
                {needsAction.map(s => (
                  <WheelSessionCardV2 key={s.id} session={s} onResolve={setResolveSlotId} onLinkLeg={setLinkSlotId} onRefresh={load} />
                ))}
              </div>
            </section>
          )}
          {monitoring.length > 0 && (
            <section>
              <div className="flex items-center gap-2 mb-3">
                <span className="text-sm font-bold text-blue-600">MONITORING</span>
                <span className="bg-blue-100 text-blue-700 text-xs px-2 py-0.5 rounded-full font-medium">{monitoring.length}</span>
              </div>
              <div className="space-y-3">
                {monitoring.map(s => (
                  <WheelSessionCardV2 key={s.id} session={s} onResolve={setResolveSlotId} onLinkLeg={setLinkSlotId} onRefresh={load} />
                ))}
              </div>
            </section>
          )}
        </>
      )}

      {showNewModal && <NewWheelModalV2 onClose={() => setShowNewModal(false)} onCreated={handleNewSession} />}
      {resolveSlotId && <ResolveModal slotId={resolveSlotId} ticker={resolveSlotTicker} onClose={() => setResolveSlotId(null)} onResolved={() => { setResolveSlotId(null); load() }} />}
      {linkSlotId && <LinkLegModalV2 slotId={linkSlotId} ticker={linkSlotTicker} slotStatus={linkSlotStatus} onClose={() => setLinkSlotId(null)} onLinked={() => { setLinkSlotId(null); load() }} />}
    </div>
  )
}
