// frontend/src/pages/DashboardPage.tsx
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertFeed } from '../components/Dashboard/AlertFeed'
import { dashboardApi } from '../api/dashboard'
import { accountLabel, accountPath } from '../lib/paths'
import type { DashboardAccountCard, DashboardSummary } from '../types'

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

function formatPremium(raw: string): string {
  const value = Number.parseFloat(raw)
  return Number.isFinite(value) ? usd.format(value) : '—'
}

function Stat({ label, value, tone }: { label: string; value: string | number; tone?: string }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-gray-500">{label}</p>
      <p className={`text-lg font-semibold ${tone ?? 'text-gray-900'}`}>{value}</p>
    </div>
  )
}

function AccountCard({ card }: { card: DashboardAccountCard }) {
  const premium = Number.parseFloat(card.net_premium_month)
  return (
    <Link to={accountPath(card.account.id, 'wheel')}
      className="block rounded-lg border border-gray-200 bg-white p-4 hover:border-blue-300 hover:shadow-sm">
      <div className="flex items-baseline justify-between gap-2">
        <p className="truncate font-semibold text-gray-900">{accountLabel(card.account)}</p>
        <span className="shrink-0 text-xs text-gray-400">{card.account.broker}{card.is_default ? ' · default' : ''}</span>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-3">
        <Stat label="Open trades" value={card.open_trades} />
        <Stat label="Active wheels" value={card.active_wheels} />
        <Stat label="Needs action" value={card.slots_needing_action}
          tone={card.slots_needing_action > 0 ? 'text-amber-600' : undefined} />
        <Stat label="Expiring ≤7d" value={card.legs_expiring_7d}
          tone={card.legs_expiring_7d > 0 ? 'text-red-600' : undefined} />
        <Stat label="Net premium (month)" value={formatPremium(card.net_premium_month)}
          tone={premium < 0 ? 'text-red-600' : premium > 0 ? 'text-green-700' : undefined} />
      </div>
    </Link>
  )
}

function isEmpty(summary: DashboardSummary): boolean {
  return summary.accounts.length === 1
    && summary.needs_action.length === 0
    && summary.alerts.length === 0
    && summary.accounts.every(c => c.open_trades === 0 && c.active_wheels === 0 && Number.parseFloat(c.net_premium_month) === 0)
}

export function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    dashboardApi.summary()
      .then(s => { setSummary(s); setError(null) })
      .catch(e => setError(e instanceof Error ? e.message : 'Failed to load dashboard'))
  }, [])

  useEffect(() => { load() }, [load])

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="mt-1 text-sm text-gray-500">
          All accounts{summary ? ` · as of ${summary.as_of} (US/Eastern)` : ''}
        </p>
      </div>

      {error && <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      {!summary && !error && <p className="text-sm text-gray-500">Loading…</p>}

      {summary && isEmpty(summary) && (
        <div className="rounded-lg border border-dashed border-gray-300 bg-white p-8 text-center">
          <p className="font-medium text-gray-800">Nothing here yet</p>
          <p className="mt-1 text-sm text-gray-500">Add a trade or start a wheel in {accountLabel(summary.accounts[0].account)} to see it here.</p>
          <div className="mt-4 flex justify-center gap-3 text-sm">
            <Link to={accountPath(summary.accounts[0].account.id, 'trades')} className="text-blue-600 hover:underline">Go to Trades</Link>
            <Link to={accountPath(summary.accounts[0].account.id, 'wheel')} className="text-blue-600 hover:underline">Go to WHEEL</Link>
          </div>
        </div>
      )}

      {summary && !isEmpty(summary) && (
        <>
          <div className="grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(20rem,1fr))]">
            {summary.accounts.map(card => <AccountCard key={card.account.id} card={card} />)}
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <div className="bg-white rounded-lg border border-gray-200 p-4">
              <h2 className="text-sm font-semibold text-gray-700 mb-3">
                Needs action
                {summary.needs_action.length > 0 && (
                  <span className="ml-2 px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded text-xs">{summary.needs_action.length}</span>
                )}
              </h2>
              {summary.needs_action.length === 0 ? (
                <p className="text-sm text-gray-400">No slots need action.</p>
              ) : (
                <ul className="divide-y divide-gray-100">
                  {summary.needs_action.map(slot => (
                    <li key={slot.slot_id}>
                      <Link to={accountPath(slot.account.id, 'wheel')}
                        className="flex items-center justify-between gap-3 rounded px-2 py-2 text-sm hover:bg-gray-50">
                        <span className="flex min-w-0 items-center gap-2">
                          <span className="font-semibold text-gray-900">{slot.ticker}</span>
                          <span className="text-gray-500">slot {slot.slot_number}</span>
                          <span className="truncate text-xs text-gray-500">{slot.status.replace(/_/g, ' ')}</span>
                        </span>
                        <span className="flex shrink-0 items-center gap-2">
                          {slot.open_leg_expiry && <span className="text-xs text-gray-500">exp {slot.open_leg_expiry}</span>}
                          <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-600">{accountLabel(slot.account)}</span>
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <AlertFeed alerts={summary.alerts} onChanged={load} />
          </div>
        </>
      )}
    </div>
  )
}
