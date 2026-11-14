// frontend/src/components/MarketData/MarketDataBanner.tsx
import { useState } from 'react'
import { AlertTriangle, X } from 'lucide-react'
import { useMarketData } from '../../context/MarketDataContext'
import { isFollower, lastPullText } from '../../lib/tokenSync'
import { PullTokensButton } from './PullTokensButton'
import { ReconnectSchwabButton } from './ReconnectSchwabDialog'

const DISMISS_KEY = 'trademinder_market_banner_dismissed'
const CLI = 'scripts/schwab_auth.py'

function readDismissed(expiresAt: string | null): boolean {
  try {
    return expiresAt !== null && sessionStorage.getItem(DISMISS_KEY) === expiresAt
  } catch {
    return false
  }
}

/**
 * Schwab refresh-token banner (admins only — the status is only loaded for admins).
 * > 72h: nothing · 72h–24h: amber, dismissible for this session · < 24h: red · expired/failing: red.
 * Every state offers Reconnect Schwab (the in-app reconnect), with the CLI as a muted fallback.
 * Token follower (dev): Reconnect and the CLI are hidden (a reconnect here would invalidate production's grant);
 * the banner shows where the tokens come from, the last pull, and Pull now instead.
 */
export function MarketDataBanner() {
  const { status } = useMarketData()
  const [dismissedFor, setDismissedFor] = useState<string | null>(null)
  if (!status || status.state === 'ok') return null

  const follower = isFollower(status)
  const hours = status.hours_remaining ?? 0
  const renew = follower ? 'Reconnect in production to renew it.' : 'Reconnect to renew it.'
  let tone: 'amber' | 'red'
  let message: string
  if (status.state === 'expiring') {
    const days = Math.max(1, Math.round(hours / 24))
    tone = 'amber'
    message = `${follower ? "Production's " : ''}Schwab connection expires in ${days} day${days === 1 ? '' : 's'}. ${renew}`
  } else if (status.state === 'critical') {
    const h = Math.max(1, Math.floor(hours))
    tone = 'red'
    message = `${follower ? "Production's " : ''}Schwab connection expires in ${h} hour${h === 1 ? '' : 's'}. ${renew}`
  } else {
    tone = 'red'
    message = follower
      ? "Market data offline: couldn't get Schwab tokens from production."
      : 'Market data offline. Reconnect Schwab to restore it.'
  }
  const buttonClass = `inline-flex shrink-0 items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium text-white disabled:opacity-50 ${
    tone === 'red' ? 'bg-red-600 hover:bg-red-700' : 'bg-amber-600 hover:bg-amber-700'
  }`

  const dismissible = tone === 'amber'
  if (dismissible && (dismissedFor === status.refresh_expires_at || readDismissed(status.refresh_expires_at))) {
    return null
  }

  const dismiss = () => {
    try { sessionStorage.setItem(DISMISS_KEY, status.refresh_expires_at ?? '') } catch { /* private mode */ }
    setDismissedFor(status.refresh_expires_at)
  }

  return (
    <div
      role={tone === 'red' ? 'alert' : 'status'}
      className={`flex items-center gap-2 border-b px-4 py-2 text-sm ${
        tone === 'red' ? 'border-red-200 bg-red-50 text-red-800' : 'border-amber-200 bg-amber-50 text-amber-900'
      }`}
    >
      <AlertTriangle size={16} className="shrink-0" />
      <span className="flex-1">
        {message}
        {follower
          ? <span className="ml-2 text-xs opacity-60">{lastPullText(status)}</span>
          : <span className="ml-2 text-xs opacity-60">or run <span className="font-mono">{CLI}</span></span>}
      </span>
      {status.state === 'offline' && status.last_error && (
        <span className="hidden text-xs opacity-75 md:inline" title={status.last_error}>{status.last_error}</span>
      )}
      {follower ? <PullTokensButton className={buttonClass} /> : <ReconnectSchwabButton className={buttonClass} />}
      {dismissible && (
        <button onClick={dismiss} aria-label="Dismiss for this session"
          className="rounded p-1 hover:bg-amber-100">
          <X size={14} />
        </button>
      )}
    </div>
  )
}
