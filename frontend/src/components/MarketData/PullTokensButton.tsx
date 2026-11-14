// frontend/src/components/MarketData/PullTokensButton.tsx
import { useState } from 'react'
import { Download } from 'lucide-react'
import { ApiError, setMarketDataOffline } from '../../api/client'
import { marketDataApi } from '../../api/marketData'
import { useMarketData } from '../../context/MarketDataContext'
import { PULL_OUTCOME_LABEL } from '../../lib/tokenSync'

/**
 * Token follower (dev) only: pull Schwab tokens from production now. At most one pull a minute (the server
 * answers 429 inside the window). Reconnecting is done in production; this never reconnects.
 */
export function PullTokensButton({ className }: { className?: string }) {
  const { apply } = useMarketData()
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  async function pull() {
    setBusy(true)
    setMessage(null)
    try {
      const next = await marketDataApi.pullNow()
      apply(next)
      if (next.state !== 'offline') setMarketDataOffline(false)
      if (next.last_pull_outcome && next.last_pull_outcome !== 'ok') {
        setMessage(`Pull failed: ${PULL_OUTCOME_LABEL[next.last_pull_outcome]}`)
      }
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : 'Pull failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <span className="inline-flex items-center gap-2">
      <button onClick={pull} disabled={busy}
        className={className ?? 'inline-flex items-center gap-1.5 rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50'}>
        <Download size={14} /> {busy ? 'Pulling…' : 'Pull now'}
      </button>
      {message && <span className="text-xs opacity-80" role="status">{message}</span>}
    </span>
  )
}
