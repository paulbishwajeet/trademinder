// frontend/src/pages/SpreadsDashboardPage.tsx
import { useState, useEffect } from 'react'
import type { SessionSummary, SessionWithLegs } from '../types'
import { sessionsApi, quotePrice } from '../api/sessions'
import { SpreadSessionCard } from '../components/Spreads/SpreadSessionCard'

export function SpreadsDashboardPage() {
  const [sessions, setSessions] = useState<SessionWithLegs[]>([])
  const [closedSessions, setClosedSessions] = useState<SessionSummary[]>([])
  const [prices, setPrices] = useState<Record<string, number | null>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      // Fetch open IC and PBWB sessions in parallel
      const [icSummaries, pbwbSummaries, icClosed, pbwbClosed] = await Promise.all([
        sessionsApi.listSpreads('IRON_CONDOR', 'open'),
        sessionsApi.listSpreads('PUT_B_W_FLY', 'open'),
        sessionsApi.listSpreads('IRON_CONDOR', 'closed'),
        sessionsApi.listSpreads('PUT_B_W_FLY', 'closed'),
      ])

      // Fetch full leg detail for each open session
      const openSummaries = [...icSummaries, ...pbwbSummaries]
      const detailed = await Promise.all(openSummaries.map(s => sessionsApi.get(s.id)))
      setSessions(detailed)
      setClosedSessions([...icClosed, ...pbwbClosed])

      // Fetch current price for each unique ticker
      const tickers = [...new Set(openSummaries.map(s => s.ticker))]
      const priceResults = await Promise.all(tickers.map(t => quotePrice(t)))
      const priceMap: Record<string, number | null> = {}
      tickers.forEach((t, i) => { priceMap[t] = priceResults[i] })
      setPrices(priceMap)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load sessions')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  function handleClosed(id: string) {
    const session = sessions.find(s => s.id === id)
    if (session) setClosedSessions(prev => [{ ...session, status: 'closed' }, ...prev])
    setSessions(prev => prev.filter(s => s.id !== id))
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Spreads Dashboard</h1>
      </div>

      {loading && <p className="text-gray-500 text-center py-12">Loading…</p>}

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded p-4 mb-4 text-sm">{error}</div>
      )}

      {!loading && !error && sessions.length === 0 && (
        <div className="text-center py-16">
          <p className="text-gray-400 mb-2">No open spread sessions.</p>
          <p className="text-sm text-gray-400">
            Add a trade in the E*TRADE extension and link it to a new IC or PBWB session.
          </p>
        </div>
      )}

      {!loading && !error && sessions.length > 0 && (
        <section className="mb-8">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-sm font-bold text-gray-700">OPEN POSITIONS</span>
            <span className="bg-gray-100 text-gray-600 text-xs px-2 py-0.5 rounded-full font-medium">
              {sessions.length}
            </span>
          </div>
          <div className="space-y-2">
            {sessions.map(s => (
              <SpreadSessionCard
                key={s.id}
                session={s}
                price={prices[s.ticker] ?? null}
                onClosed={handleClosed}
              />
            ))}
          </div>
        </section>
      )}

      {!loading && !error && closedSessions.length > 0 && (
        <section>
          <div className="flex items-center gap-2 mb-3">
            <span className="text-sm font-bold text-gray-400">CLOSED</span>
            <span className="bg-gray-100 text-gray-400 text-xs px-2 py-0.5 rounded-full font-medium">
              {closedSessions.length}
            </span>
          </div>
          <div className="space-y-1">
            {closedSessions.map(s => (
              <div key={s.id} className="flex items-center gap-3 px-4 py-2 bg-white border border-gray-100 rounded text-sm text-gray-500">
                <span className="font-medium text-gray-700">{s.ticker}</span>
                <span className="text-xs">{s.strategy === 'IRON_CONDOR' ? 'IC' : 'PBWB'}</span>
                <span className="text-xs">{s.opened_at} → {s.closed_at ?? '—'}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
