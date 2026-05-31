// frontend/src/pages/WheelDashboardPage.tsx
import { useState, useEffect } from 'react'
import type { SessionSummary, SessionWithLegs } from '../types'
import { sessionsApi } from '../api/sessions'
import { WheelSessionCard } from '../components/Wheel/WheelSessionCard'
import { NewWheelModal } from '../components/Wheel/NewWheelModal'

const NEEDS_ACTION = new Set(['called_away', 'shares_sitting'])

export function WheelDashboardPage() {
  const [sessions, setSessions] = useState<SessionWithLegs[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showNewModal, setShowNewModal] = useState(false)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const summaries = await sessionsApi.list({ strategy: 'WHEEL' })
      const detailed = await Promise.all(summaries.map(s => sessionsApi.get(s.id)))
      setSessions(detailed)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load sessions')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  function handleStatusUpdate(id: string, newStatus: string) {
    setSessions(prev => prev.map(s => s.id === id ? { ...s, status: newStatus } : s))
  }

  function handleNewSession(_session: SessionSummary) {
    setShowNewModal(false)
    load()
  }

  const needsAction = sessions.filter(s => NEEDS_ACTION.has(s.status))
  const monitoring = sessions.filter(s => !NEEDS_ACTION.has(s.status) && s.status !== 'completed')

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold text-gray-900">WHEEL Strategy</h1>
        <button
          onClick={() => setShowNewModal(true)}
          className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700"
        >
          + New Wheel
        </button>
      </div>

      {loading && (
        <p className="text-gray-500 text-center py-12">Loading…</p>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded p-4 mb-4 text-sm">
          {error}
        </div>
      )}

      {!loading && !error && sessions.length === 0 && (
        <div className="text-center py-16">
          <p className="text-gray-400 mb-4">No WHEEL sessions yet.</p>
          <button
            onClick={() => setShowNewModal(true)}
            className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700"
          >
            + New Wheel
          </button>
        </div>
      )}

      {!loading && !error && sessions.length > 0 && (
        <>
          {needsAction.length > 0 && (
            <section className="mb-6">
              <div className="flex items-center gap-2 mb-3">
                <span className="text-sm font-bold text-amber-600">⚠ NEEDS ACTION</span>
                <span className="bg-amber-100 text-amber-700 text-xs px-2 py-0.5 rounded-full font-medium">
                  {needsAction.length}
                </span>
              </div>
              <div className="space-y-2">
                {needsAction.map(s => (
                  <WheelSessionCard key={s.id} session={s} onStatusUpdate={handleStatusUpdate} />
                ))}
              </div>
            </section>
          )}

          {monitoring.length > 0 && (
            <section>
              <div className="flex items-center gap-2 mb-3">
                <span className="text-sm font-bold text-blue-600">✓ MONITORING</span>
                <span className="bg-blue-100 text-blue-700 text-xs px-2 py-0.5 rounded-full font-medium">
                  {monitoring.length}
                </span>
              </div>
              <div className="space-y-2">
                {monitoring.map(s => (
                  <WheelSessionCard key={s.id} session={s} onStatusUpdate={handleStatusUpdate} />
                ))}
              </div>
            </section>
          )}
        </>
      )}

      {showNewModal && (
        <NewWheelModal onClose={() => setShowNewModal(false)} onCreated={handleNewSession} />
      )}
    </div>
  )
}
