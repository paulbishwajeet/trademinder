// frontend/src/pages/SettingsMarketDataPage.tsx
import { useEffect, useState, type ReactNode } from 'react'
import { useMarketData } from '../context/MarketDataContext'
import { ReconnectSchwabButton } from '../components/MarketData/ReconnectSchwabDialog'
import { PullTokensButton } from '../components/MarketData/PullTokensButton'
import { PULL_OUTCOME_LABEL, isFollower } from '../lib/tokenSync'
import type { MarketDataState } from '../api/marketData'

const STATE_LABEL: Record<MarketDataState, { text: string; className: string }> = {
  ok: { text: 'Connected', className: 'bg-green-50 text-green-700' },
  expiring: { text: 'Expiring soon', className: 'bg-amber-50 text-amber-800' },
  critical: { text: 'Expires within 24 hours', className: 'bg-red-50 text-red-700' },
  offline: { text: 'Offline', className: 'bg-red-50 text-red-700' },
}

function fmt(ts: string | null): string {
  return ts ? new Date(ts).toLocaleString() : '—'
}

/** Settings → Market data (admin only): the Schwab connection's status, with Reconnect at any time — or, on a
 *  token follower (dev), where the tokens come from and Pull now (reconnecting happens in production only). */
export function SettingsMarketDataPage() {
  const { status, refresh } = useMarketData()
  const [loaded, setLoaded] = useState(false)

  // The context polls every 15 minutes; on this page show a fresh status.
  useEffect(() => {
    let cancelled = false
    void refresh().finally(() => { if (!cancelled) setLoaded(true) })
    return () => { cancelled = true }
  }, [refresh])

  const label = status ? STATE_LABEL[status.state] : null
  const hours = status?.hours_remaining
  const follower = isFollower(status)

  return (
    <div className="max-w-2xl">
      {follower ? (
        <p className="text-sm text-gray-500">
          This environment follows production&rsquo;s Schwab connection: it pulls the current tokens from production
          and never reconnects or refreshes itself, because a second Schwab login would end production&rsquo;s
          connection. Reconnect in production (Settings → Market data there) once a week.
        </p>
      ) : (
        <p className="text-sm text-gray-500">
          Market data comes from one Schwab connection shared by every user. Schwab ends it 7 days after each
          login, so reconnect before then. You can reconnect at any time; the new connection lasts 7 days from now.
        </p>
      )}

      <div className="mt-4 rounded-lg border border-gray-200 bg-white">
        {!status ? (
          <p className="px-4 py-6 text-center text-sm text-gray-400">{loaded ? 'Status unavailable.' : 'Loading…'}</p>
        ) : (
          <dl className="divide-y divide-gray-100 text-sm">
            <Row label="Provider"><span className="capitalize">{status.provider}</span></Row>
            <Row label="Token source">{follower ? 'Production (token follower)' : 'This server'}</Row>
            {follower && (
              <>
                <Row label="Last pull">{fmt(status.last_pull_at)}</Row>
                <Row label="Last pull outcome">
                  {status.last_pull_outcome
                    ? <span className={status.last_pull_outcome === 'ok' ? '' : 'text-red-700'}>{PULL_OUTCOME_LABEL[status.last_pull_outcome]}</span>
                    : '—'}
                </Row>
              </>
            )}
            <Row label="State">
              {label && <span className={`rounded px-2 py-0.5 text-xs font-medium ${label.className}`}>{label.text}</span>}
            </Row>
            <Row label="Connection expires">{fmt(status.refresh_expires_at)}</Row>
            <Row label="Hours remaining">
              {hours == null ? '—' : hours <= 0 ? 'Expired' : `${hours.toFixed(1)} h`}
            </Row>
            <Row label="Last successful call">{fmt(status.last_success_at)}</Row>
            {status.last_error && <Row label="Last error"><span className="text-red-700">{status.last_error}</span></Row>}
          </dl>
        )}
      </div>

      {follower ? (
        <div className="mt-4 flex items-center gap-3">
          <PullTokensButton />
          <span className="text-xs text-gray-400">At most one pull a minute. Reconnect is disabled here.</span>
        </div>
      ) : (
        <div className="mt-4 flex items-center gap-3">
          <ReconnectSchwabButton />
          <span className="text-xs text-gray-400">
            Fallback: run <span className="font-mono">scripts/schwab_auth.py</span> against the server's database.
          </span>
        </div>
      )}
    </div>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center gap-4 px-4 py-2.5">
      <dt className="w-44 shrink-0 text-gray-500">{label}</dt>
      <dd className="text-gray-900">{children}</dd>
    </div>
  )
}
