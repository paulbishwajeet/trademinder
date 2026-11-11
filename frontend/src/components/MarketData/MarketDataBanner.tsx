// frontend/src/components/MarketData/MarketDataBanner.tsx
import { useState } from 'react'
import { AlertTriangle, X } from 'lucide-react'
import { useMarketDataStatus } from '../../context/MarketDataContext'

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
 */
export function MarketDataBanner() {
  const status = useMarketDataStatus()
  const [dismissedFor, setDismissedFor] = useState<string | null>(null)
  if (!status || status.state === 'ok') return null

  const hours = status.hours_remaining ?? 0
  let tone: 'amber' | 'red'
  let message: string
  if (status.state === 'expiring') {
    const days = Math.max(1, Math.round(hours / 24))
    tone = 'amber'
    message = `Schwab connection expires in ${days} day${days === 1 ? '' : 's'}. Run ${CLI} to renew.`
  } else if (status.state === 'critical') {
    const h = Math.max(1, Math.floor(hours))
    tone = 'red'
    message = `Schwab connection expires in ${h} hour${h === 1 ? '' : 's'}. Run ${CLI} to renew.`
  } else {
    tone = 'red'
    message = `Market data offline. Run ${CLI}.`
  }

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
      <span className="flex-1">{message}</span>
      {status.state === 'offline' && status.last_error && (
        <span className="hidden text-xs opacity-75 md:inline" title={status.last_error}>{status.last_error}</span>
      )}
      {dismissible && (
        <button onClick={dismiss} aria-label="Dismiss for this session"
          className="rounded p-1 hover:bg-amber-100">
          <X size={14} />
        </button>
      )}
    </div>
  )
}
