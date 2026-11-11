// frontend/src/components/Dashboard/AlertFeed.tsx
import { Link } from 'react-router-dom'
import type { DashboardAlert } from '../../types'
import { alertsApi } from '../../api/alerts'
import { accountLabel, tradePath } from '../../lib/paths'

const SEVERITY_STYLES: Record<string, string> = {
  urgent: 'border-l-4 border-red-500 bg-red-50',
  warning: 'border-l-4 border-yellow-500 bg-yellow-50',
  info: 'border-l-4 border-gray-400 bg-gray-50',
}

const SEVERITY_ORDER: Record<string, number> = { urgent: 0, warning: 1, info: 2 }

function timeAgo(iso: string): string {
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

interface Props {
  alerts: DashboardAlert[]
  /** Called after mark-read / dismiss so the Dashboard can reload its summary. */
  onChanged: () => void
}

/** Today's alerts across every account, each tagged with its account. */
export function AlertFeed({ alerts, onChanged }: Props) {
  const sorted = [...alerts].sort(
    (a, b) => (SEVERITY_ORDER[a.severity] ?? 3) - (SEVERITY_ORDER[b.severity] ?? 3),
  )

  async function handleRead(id: string) {
    await alertsApi.markRead(id)
    onChanged()
  }

  async function handleDismiss(id: string) {
    await alertsApi.dismiss(id)
    onChanged()
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4">
      <h2 className="text-sm font-semibold text-gray-700 mb-3">
        Today's alerts
        {alerts.length > 0 && (
          <span className="ml-2 px-1.5 py-0.5 bg-red-100 text-red-700 rounded text-xs">
            {alerts.length}
          </span>
        )}
      </h2>
      {sorted.length === 0 ? (
        <p className="text-sm text-gray-400">No alerts today.</p>
      ) : (
        <div className="space-y-2">
          {sorted.map(alert => (
            <div
              key={alert.id}
              className={`rounded p-3 ${SEVERITY_STYLES[alert.severity] ?? 'border-l-4 border-gray-400 bg-gray-50'} ${alert.is_read ? 'opacity-60' : ''}`}
            >
              <div className="flex justify-between items-start gap-2">
                <p className="text-sm font-medium text-gray-800">{alert.title}</p>
                <span className="text-xs text-gray-400 shrink-0">{timeAgo(alert.triggered_at)}</span>
              </div>
              <p className="text-xs text-gray-600 mt-0.5">{alert.message}</p>
              <div className="flex items-center gap-3 mt-2">
                <span className="rounded bg-white px-1.5 py-0.5 text-[11px] text-gray-600 ring-1 ring-gray-200">
                  {accountLabel(alert.account)}
                </span>
                <Link to={tradePath(alert.account.id, alert.trade_id)} className="text-xs text-blue-600 hover:underline">
                  {alert.ticker}
                </Link>
                {!alert.is_read && (
                  <button onClick={() => handleRead(alert.id)} className="text-xs text-blue-600 hover:underline">
                    Mark read
                  </button>
                )}
                <button onClick={() => handleDismiss(alert.id)} className="text-xs text-gray-500 hover:underline">
                  Dismiss
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
