// frontend/src/components/MarketData/ReconnectSchwabDialog.tsx
import { useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { CheckCircle2, ExternalLink, Loader2, RefreshCw, X } from 'lucide-react'
import { marketDataApi, type ReconnectStart } from '../../api/marketData'
import { ApiError, setMarketDataOffline } from '../../api/client'
import { useMarketData } from '../../context/MarketDataContext'

type Phase =
  | { kind: 'starting' }
  | { kind: 'ready'; start: ReconnectStart; error: string | null }
  | { kind: 'submitting'; start: ReconnectStart }
  | { kind: 'done'; refreshExpiresAt: string | null }
  | { kind: 'failed'; message: string }

// The pasted address was wrong but the reconnect link is still good: fix the paste, no need to start over.
const RETRY_PASTE = new Set(['bad_url', 'missing_code'])

function message(e: unknown, fallback: string): string {
  return e instanceof ApiError ? e.message : fallback
}

function time(ts: string): string {
  return new Date(ts).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
}

/**
 * Admin only. Renew the Schwab connection by pasting the redirect address:
 * 1. open the Schwab login (new tab); 2. after approving, the tab lands on a page that fails to load — copy its
 * address and paste it here. The backend checks it, exchanges the code and stores the new tokens.
 * The flow's state lives in ReconnectFlow, which mounts on every open, so each open starts fresh.
 */
export function ReconnectSchwabDialog({ open, onOpenChange }: Props) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/30" />
        <Dialog.Content data-escape-layer=""
          className="fixed left-1/2 top-1/2 z-50 w-[32rem] max-w-[calc(100vw-2rem)] max-h-[90vh] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg bg-white p-6 shadow-xl">
          <div className="flex items-start justify-between gap-4">
            <Dialog.Title className="text-lg font-semibold text-gray-900">Reconnect Schwab</Dialog.Title>
            <Dialog.Close className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600" aria-label="Close">
              <X size={16} />
            </Dialog.Close>
          </div>
          <Dialog.Description className="mt-1 text-sm text-gray-500">
            Renews market data for everyone for another 7 days.
          </Dialog.Description>
          <ReconnectFlow />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

function ReconnectFlow() {
  const { apply } = useMarketData()
  const [phase, setPhase] = useState<Phase>({ kind: 'starting' })
  const [pasted, setPasted] = useState('')
  const [attempt, setAttempt] = useState(0)

  // A fresh reconnect link on mount and on every Start again; a superseded or unmounted request is ignored.
  useEffect(() => {
    let active = true
    marketDataApi.reconnectStart().then(
      start => { if (active) setPhase({ kind: 'ready', start, error: null }) },
      (e: unknown) => { if (active) setPhase({ kind: 'failed', message: message(e, 'Could not start the reconnect.') }) },
    )
    return () => { active = false }
  }, [attempt])

  function startAgain() {
    setPhase({ kind: 'starting' })
    setPasted('')
    setAttempt(a => a + 1)
  }

  async function submit() {
    if (phase.kind !== 'ready' || !pasted.trim()) return
    const start = phase.start
    setPhase({ kind: 'submitting', start })
    try {
      const status = await marketDataApi.reconnectComplete(pasted.trim())
      apply(status)
      setMarketDataOffline(false)
      setPasted('')
      setPhase({ kind: 'done', refreshExpiresAt: status.refresh_expires_at })
    } catch (e) {
      const text = message(e, 'Reconnect failed.')
      if (e instanceof ApiError && e.code && RETRY_PASTE.has(e.code)) {
        setPhase({ kind: 'ready', start, error: text })
      } else {
        setPhase({ kind: 'failed', message: text })
      }
    }
  }

  const startAgainButton = (
    <button onClick={startAgain}
      className="inline-flex items-center gap-1.5 rounded border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50">
      <RefreshCw size={14} /> Start again
    </button>
  )

  return (
    <>
      {phase.kind === 'starting' && (
        <p className="mt-5 flex items-center gap-2 text-sm text-gray-500">
          <Loader2 size={16} className="animate-spin" /> Preparing the Schwab login…
        </p>
      )}

      {(phase.kind === 'ready' || phase.kind === 'submitting') && (
        <ol className="mt-5 space-y-5 text-sm">
          <li>
            <div className="font-medium text-gray-900">1. Log in at Schwab</div>
            <a href={phase.start.authorize_url} target="_blank" rel="noopener noreferrer"
              className="mt-2 inline-flex items-center gap-1.5 rounded bg-blue-600 px-3 py-1.5 text-white hover:bg-blue-700">
              Open Schwab login <ExternalLink size={14} />
            </a>
            <p className="mt-1.5 text-xs text-gray-500">
              Opens in a new tab. This link is valid until {time(phase.start.state_expires_at)}.
            </p>
          </li>
          <li>
            <label htmlFor="schwab-redirect" className="font-medium text-gray-900">
              2. Paste the address of the page Schwab sends you to
            </label>
            <p className="mt-1 text-xs text-gray-500">
              After you approve, the tab goes to <span className="font-mono">https://127.0.0.1:8765/callback…</span> and
              the page <strong>fails to load — that's expected</strong>. Copy the whole address from that tab's address
              bar and paste it here straight away: Schwab's code only lasts a short time.
            </p>
            <textarea id="schwab-redirect" rows={3} value={pasted} spellCheck={false} autoComplete="off"
              disabled={phase.kind === 'submitting'}
              onChange={e => setPasted(e.target.value)}
              placeholder="https://127.0.0.1:8765/callback?code=…"
              className="mt-2 w-full rounded border border-gray-300 px-3 py-2 font-mono text-xs disabled:bg-gray-50" />
            {phase.kind === 'ready' && phase.error && (
              <p role="alert" className="mt-1 text-sm text-red-600">{phase.error}</p>
            )}
          </li>
        </ol>
      )}

      {phase.kind === 'done' && (
        <div role="status" className="mt-5 flex items-start gap-2 rounded bg-green-50 px-3 py-2 text-sm text-green-800">
          <CheckCircle2 size={16} className="mt-0.5 shrink-0" />
          <span>
            Schwab reconnected.
            {phase.refreshExpiresAt && <> The connection now lasts until {new Date(phase.refreshExpiresAt).toLocaleString()}.</>}
          </span>
        </div>
      )}

      {phase.kind === 'failed' && (
        <p role="alert" className="mt-5 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{phase.message}</p>
      )}

      <div className="mt-6 flex justify-end gap-2">
        {(phase.kind === 'failed' || (phase.kind === 'ready' && phase.error)) && startAgainButton}
        {(phase.kind === 'ready' || phase.kind === 'submitting') && (
          <button onClick={() => { void submit() }} disabled={phase.kind === 'submitting' || !pasted.trim()}
            className="inline-flex items-center gap-1.5 rounded bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50">
            {phase.kind === 'submitting' && <Loader2 size={14} className="animate-spin" />}
            {phase.kind === 'submitting' ? 'Connecting…' : 'Connect'}
          </button>
        )}
        {(phase.kind === 'done' || phase.kind === 'failed') && (
          <Dialog.Close className="rounded border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50">Close</Dialog.Close>
        )}
      </div>
    </>
  )
}

/** The "Reconnect Schwab" button with its dialog. Render it for admins only. */
export function ReconnectSchwabButton({ className }: { className?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button onClick={() => setOpen(true)}
        className={className ?? 'inline-flex items-center gap-1.5 rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700'}>
        <RefreshCw size={14} /> Reconnect Schwab
      </button>
      <ReconnectSchwabDialog open={open} onOpenChange={setOpen} />
    </>
  )
}
