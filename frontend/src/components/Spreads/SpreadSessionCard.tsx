import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { SessionWithLegs, SessionLeg } from '../../types'
import { sessionsApi } from '../../api/sessions'

interface Props {
  session: SessionWithLegs
  price: number | null
  onClosed: (id: string) => void
}

const STRATEGY_LABELS: Record<string, string> = {
  IRON_CONDOR: 'IC',
  PUT_B_W_FLY: 'PBWB',
}

const STRATEGY_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  IRON_CONDOR: { bg: '#EDE9FE', text: '#5B21B6', border: '#C4B5FD' },
  PUT_B_W_FLY:  { bg: '#CCFBF1', text: '#0F766E', border: '#5EEAD4' },
}

type Signal = 'safe' | 'warning' | 'danger' | 'unknown'

function computeSignal(legs: SessionLeg[], price: number, strategy: string): Signal {
  if (strategy === 'IRON_CONDOR') {
    const shortPutStrikes = legs
      .filter(l => l.strategy === 'Sell Put' && l.strike_price != null)
      .map(l => l.strike_price as number)
    const shortCallStrikes = legs
      .filter(l => l.strategy === 'Sell Call' && l.strike_price != null)
      .map(l => l.strike_price as number)
    if (!shortPutStrikes.length || !shortCallStrikes.length) return 'unknown'
    const sp = Math.max(...shortPutStrikes)
    const sc = Math.min(...shortCallStrikes)
    if (price <= sp || price >= sc) return 'danger'
    if (price < sp * 1.05 || price > sc * 0.95) return 'warning'
    return 'safe'
  }
  if (strategy === 'PUT_B_W_FLY') {
    const shortStrikes = legs
      .filter(l => l.strategy === 'Sell Put' && l.strike_price != null)
      .map(l => l.strike_price as number)
    if (shortStrikes.length < 2) return 'unknown'
    const low = Math.min(...shortStrikes)
    const high = Math.max(...shortStrikes)
    if (price <= low || price >= high) return 'danger'
    if (price < low * 1.05 || price > high * 0.95) return 'warning'
    return 'safe'
  }
  return 'unknown'
}

const SIGNAL_STYLES: Record<Signal, { bg: string; border: string; text: string; icon: string; label: string }> = {
  safe:    { bg: 'bg-green-50',  border: 'border-green-200', text: 'text-green-700',  icon: '✓', label: 'Safe' },
  warning: { bg: 'bg-amber-50',  border: 'border-amber-200', text: 'text-amber-700',  icon: '⚠', label: 'Approaching' },
  danger:  { bg: 'bg-red-50',    border: 'border-red-200',   text: 'text-red-700',    icon: '✗', label: 'Breached' },
  unknown: { bg: 'bg-gray-50',   border: 'border-gray-200',  text: 'text-gray-400',   icon: '?', label: 'No signal' },
}

function PriceSignal({ session, price }: { session: SessionWithLegs; price: number | null }) {
  if (price == null) return <span className="text-xs text-gray-400">Price unavailable</span>
  const signal = computeSignal(session.legs, price, session.strategy)
  const s = SIGNAL_STYLES[signal]
  return (
    <span className={`text-xs px-2 py-0.5 rounded border ${s.bg} ${s.border} ${s.text}`}>
      {s.icon} {s.label} · ${price.toFixed(2)}
    </span>
  )
}

// ── Spread chart ──────────────────────────────────────────────────────────────

const RED_DARK  = '#FCA5A5'  // outside long strikes / unlimited loss
const RED_MED   = '#FECACA'  // between long and short (wing zone, bounded loss)
const GREEN     = '#BBF7D0'  // between short strikes (profit zone)
const GREEN_PAD = '#D1FAE5'  // above highest short put for PBWB (premium collected)

function fmtStrike(v: number) {
  return v >= 1000 ? v.toLocaleString() : `$${v}`
}

function SpreadChart({ legs, price, strategy }: {
  legs: SessionLeg[]
  price: number | null
  strategy: string
}) {
  const shortPuts  = legs.filter(l => l.strategy === 'Sell Put'  && l.strike_price != null).map(l => Number(l.strike_price))
  const longPuts   = legs.filter(l => l.strategy === 'Buy Put'   && l.strike_price != null).map(l => Number(l.strike_price))
  const shortCalls = legs.filter(l => l.strategy === 'Sell Call' && l.strike_price != null).map(l => Number(l.strike_price))
  const longCalls  = legs.filter(l => l.strategy === 'Buy Call'  && l.strike_price != null).map(l => Number(l.strike_price))

  const allStrikes = [...shortPuts, ...longPuts, ...shortCalls, ...longCalls]
  if (allStrikes.length < 2) return null

  const minS = Math.min(...allStrikes)
  const maxS = Math.max(...allStrikes)
  const spread = maxS - minS || 1
  const pad = spread * 0.18
  const chartMin = minS - pad
  const chartMax = maxS + pad
  const chartRange = chartMax - chartMin
  const toPct = (v: number) => ((v - chartMin) / chartRange) * 100

  // Build gradient color segments
  type Seg = { from: number; to: number; color: string }
  const segs: Seg[] = []

  if (strategy === 'IRON_CONDOR') {
    const lp = longPuts.length  ? Math.min(...longPuts)  : null
    const sp = shortPuts.length ? Math.max(...shortPuts) : null
    const sc = shortCalls.length ? Math.min(...shortCalls) : null
    const lc = longCalls.length  ? Math.max(...longCalls)  : null

    let cur = chartMin
    if (lp != null) { segs.push({ from: cur, to: lp, color: RED_DARK });  cur = lp }
    if (sp != null) { segs.push({ from: cur, to: sp, color: RED_MED });   cur = sp }
    if (sc != null) { segs.push({ from: cur, to: sc, color: GREEN });     cur = sc }
    if (lc != null) { segs.push({ from: cur, to: lc, color: RED_MED });   cur = lc }
    segs.push({ from: cur, to: chartMax, color: RED_DARK })

  } else if (strategy === 'PUT_B_W_FLY') {
    const lp      = longPuts.length ? Math.min(...longPuts) : null
    const sorted  = [...shortPuts].sort((a, b) => a - b)
    const sp1     = sorted[0] ?? null
    const sp2     = sorted[sorted.length - 1] ?? null

    let cur = chartMin
    if (lp  != null)           { segs.push({ from: cur, to: lp,  color: RED_DARK });  cur = lp  }
    if (sp1 != null)           { segs.push({ from: cur, to: sp1, color: RED_MED });   cur = sp1 }
    if (sp2 != null && sp2 !== sp1) { segs.push({ from: cur, to: sp2, color: GREEN }); cur = sp2 }
    segs.push({ from: cur, to: chartMax, color: GREEN_PAD })
  }

  const gradientStops = segs.map(s => {
    const a = toPct(s.from).toFixed(2)
    const b = toPct(s.to).toFixed(2)
    return `${s.color} ${a}%, ${s.color} ${b}%`
  }).join(', ')

  const shortStrikeSet = new Set([...shortPuts, ...shortCalls])
  const uniqueStrikes  = [...new Set(allStrikes)].sort((a, b) => a - b)

  const pricePct = price != null ? toPct(price) : null
  // Clamp so arrow/label don't fall outside the rendered bar
  const clampedPricePct = pricePct != null
    ? Math.max(1, Math.min(99, pricePct))
    : null

  return (
    <div className="px-4 pb-2 pt-1">
      {/*
        Layout (total 60px):
          0–14px  : price arrow + label
          14–34px : gradient bar (20px tall)
          34–60px : strike labels
      */}
      <div className="relative select-none" style={{ height: 60 }}>

        {/* Gradient bar */}
        <div
          className="absolute inset-x-0"
          style={{
            top: 14,
            height: 20,
            borderRadius: 3,
            background: segs.length
              ? `linear-gradient(to right, ${gradientStops})`
              : '#E5E7EB',
          }}
        />

        {/* Strike markers */}
        {uniqueStrikes.map(strike => {
          const x = toPct(strike)
          const isShort = shortStrikeSet.has(strike)
          return (
            <div
              key={strike}
              className="absolute"
              style={{ left: `${x}%`, top: 8, transform: 'translateX(-50%)', zIndex: 2 }}
            >
              {/* Tick line through bar */}
              <div style={{
                width: 1,
                height: 30,
                margin: '0 auto',
                background: isShort ? '#374151' : '#9CA3AF',
              }} />
              {/* Strike label */}
              <div style={{
                position: 'absolute',
                top: 32,
                left: '50%',
                transform: 'translateX(-50%)',
                fontSize: 9,
                whiteSpace: 'nowrap',
                color: isShort ? '#374151' : '#9CA3AF',
                fontWeight: isShort ? 700 : 400,
              }}>
                {fmtStrike(strike)}
              </div>
            </div>
          )
        })}

        {/* Current price marker (downward-pointing triangle + label) */}
        {clampedPricePct != null && (
          <div
            className="absolute"
            style={{ left: `${clampedPricePct}%`, top: 0, transform: 'translateX(-50%)', zIndex: 3 }}
          >
            {/* Price label */}
            <div style={{
              fontSize: 9,
              fontWeight: 700,
              color: '#1D4ED8',
              whiteSpace: 'nowrap',
              textAlign: 'center',
              lineHeight: '10px',
              marginBottom: 2,
            }}>
              {price != null ? fmtStrike(price) : ''}
            </div>
            {/* Arrow */}
            <div style={{
              width: 0, height: 0,
              borderLeft: '5px solid transparent',
              borderRight: '5px solid transparent',
              borderTop: '8px solid #1D4ED8',
              margin: '0 auto',
            }} />
          </div>
        )}

        {/* "price unavailable" fallback */}
        {price == null && (
          <div
            className="absolute inset-x-0 text-center"
            style={{ top: 16, fontSize: 9, color: '#9CA3AF' }}
          >
            price unavailable
          </div>
        )}
      </div>
    </div>
  )
}

// ── Card ──────────────────────────────────────────────────────────────────────

export function SpreadSessionCard({ session, price, onClosed }: Props) {
  const [expanded, setExpanded] = useState(false)
  const [closing, setClosing] = useState(false)
  const [closeError, setCloseError] = useState<string | null>(null)

  const strategyLabel = STRATEGY_LABELS[session.strategy] ?? session.strategy
  const strategyColor = STRATEGY_COLORS[session.strategy] ?? { bg: '#F3F4F6', text: '#374151', border: '#D1D5DB' }
  const expiry = session.legs.find(l => l.expiry_date)?.expiry_date ?? null

  const hasStrikes = session.legs.some(l => l.strike_price != null)

  async function handleClose() {
    setClosing(true)
    setCloseError(null)
    try {
      await sessionsApi.update(session.id, { status: 'closed', closed_at: new Date().toISOString().slice(0, 10) })
      onClosed(session.id)
    } catch {
      setCloseError('Failed to close session')
    } finally {
      setClosing(false)
    }
  }

  return (
    <div
      className="bg-white border border-gray-200 rounded-lg overflow-hidden"
      style={{ borderLeft: `4px solid ${strategyColor.border}` }}
    >
      {/* Header row */}
      <div
        className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-gray-50 select-none"
        onClick={() => setExpanded(e => !e)}
      >
        <div className="flex items-center gap-3">
          <span
            className="text-gray-400 text-xs inline-block transition-transform duration-150"
            style={{ transform: expanded ? 'rotate(0deg)' : 'rotate(-90deg)' }}
          >▼</span>
          <span className="font-bold text-gray-900">{session.ticker}</span>
          <span
            className="text-xs font-medium px-2 py-0.5 rounded-full"
            style={{ background: strategyColor.bg, color: strategyColor.text, border: `1px solid ${strategyColor.border}` }}
          >
            {strategyLabel}
          </span>
          {expiry && <span className="text-xs text-gray-400">exp {expiry}</span>}
        </div>
        <div className="flex items-center gap-3" onClick={e => e.stopPropagation()}>
          <PriceSignal session={session} price={price} />
          <button
            onClick={handleClose}
            disabled={closing}
            className="px-2 py-1 text-xs border border-gray-300 rounded hover:bg-gray-100 disabled:opacity-50"
          >
            {closing ? 'Closing…' : 'Close Session'}
          </button>
        </div>
      </div>

      {/* Spread chart — always visible when legs have strikes */}
      {hasStrikes && (
        <div className="border-t border-gray-50">
          <SpreadChart legs={session.legs} price={price} strategy={session.strategy} />
        </div>
      )}

      {closeError && <p className="px-4 pb-2 text-xs text-red-600">{closeError}</p>}

      {/* Expanded legs table */}
      {expanded && (
        <div className="border-t border-gray-100 px-4 py-3">
          <div className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">
            Legs · opened {session.opened_at}
          </div>
          {session.legs.length === 0 ? (
            <p className="text-xs text-gray-400 italic">No legs linked yet.</p>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-gray-400 border-b border-gray-100">
                  <th className="pb-1 pr-3 font-normal">Date</th>
                  <th className="pb-1 pr-3 font-normal">Strategy</th>
                  <th className="pb-1 pr-3 font-normal">Type</th>
                  <th className="pb-1 pr-3 font-normal">Strike</th>
                  <th className="pb-1 pr-3 font-normal">Expiry</th>
                  <th className="pb-1 pr-3 font-normal">Qty</th>
                  <th className="pb-1 pr-3 font-normal">Premium</th>
                  <th className="pb-1 font-normal"></th>
                </tr>
              </thead>
              <tbody>
                {session.legs.map(leg => (
                  <tr key={leg.id} className="border-t border-gray-50">
                    <td className="py-1.5 pr-3 text-gray-500">{leg.open_date}</td>
                    <td className="py-1.5 pr-3">{leg.strategy}</td>
                    <td className="py-1.5 pr-3">{leg.type}</td>
                    <td className="py-1.5 pr-3">{leg.strike_price != null ? `$${leg.strike_price}` : '—'}</td>
                    <td className="py-1.5 pr-3">{leg.expiry_date ?? '—'}</td>
                    <td className="py-1.5 pr-3">{leg.quantity}</td>
                    <td className="py-1.5 pr-3">{leg.premium != null ? `$${leg.premium}` : '—'}</td>
                    <td className="py-1.5">
                      <Link to={`/trades/${leg.id}`} className="text-blue-500 hover:underline">view</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
