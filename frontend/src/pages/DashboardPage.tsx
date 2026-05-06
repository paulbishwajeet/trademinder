// frontend/src/pages/DashboardPage.tsx
import { useState, useEffect } from 'react'
import { AlertFeed } from '../components/Dashboard/AlertFeed'
import { tradesApi } from '../api/trades'

export function DashboardPage() {
  const [openTradeCount, setOpenTradeCount] = useState<number | null>(null)
  const [alertCount, setAlertCount] = useState<number | null>(null)

  useEffect(() => {
    tradesApi.list({ status: 'open' }).then(trades => setOpenTradeCount(trades.length))
  }, [])

  const stats = [
    ['Active Trades', openTradeCount],
    ['Open Alerts', alertCount],
    ['Pending Review', '—'],
  ] as const

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="mt-1 text-gray-500">Morning briefing coming in Phase 3.</p>
      </div>

      <div className="grid grid-cols-3 gap-4">
        {stats.map(([label, value]) => (
          <div key={label} className="bg-white rounded-lg border border-gray-200 p-4">
            <p className="text-sm text-gray-500">{label}</p>
            <p className="text-3xl font-bold text-gray-900 mt-1">
              {value !== null && value !== undefined ? value : '—'}
            </p>
          </div>
        ))}
      </div>

      <AlertFeed onCountChange={setAlertCount} />
    </div>
  )
}
