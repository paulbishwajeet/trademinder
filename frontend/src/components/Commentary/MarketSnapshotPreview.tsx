import type { CCSignalResult, WheelSignalSnapshot } from '../../types'

function TimingBreakdown({ label, signal }: { label: string; signal: CCSignalResult | null }) {
  if (!signal) return null
  return (
    <div className="border-t border-gray-100 pt-1.5 mt-1.5 first:border-t-0 first:pt-0 first:mt-0">
      <p className="text-gray-500">
        <span className="font-medium text-gray-700">{label}:</span> {signal.grade} {signal.score}
        {signal.caution && <span className="text-amber-600"> — {signal.caution}</span>}
      </p>
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 mt-1">
        {signal.factors.map(f => (
          <div key={f.name} className="flex justify-between">
            <span className="text-gray-400">{f.name}</span>
            <span className="text-gray-600">{f.points}/{f.max} <span className="text-gray-400">{f.detail}</span></span>
          </div>
        ))}
      </div>
      {signal.strike_hint && <p className="text-blue-600 mt-1">{signal.strike_hint}</p>}
    </div>
  )
}

export function MarketSnapshotPreview({ snapshot }: { snapshot: WheelSignalSnapshot }) {
  return (
    <div className="border border-gray-200 rounded-lg p-3 bg-gray-50 text-xs space-y-1">
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
        <div><span className="text-gray-400">Premium: </span><span className="text-gray-700">{snapshot.premium ?? '—'}</span></div>
        <div><span className="text-gray-400">Price: </span><span className="text-gray-700">{snapshot.price != null ? `$${snapshot.price}` : '—'}</span></div>
        <div><span className="text-gray-400">Change%: </span><span className="text-gray-700">{snapshot.change_pct != null ? `${snapshot.change_pct}%` : '—'}</span></div>
        <div><span className="text-gray-400">RSI-14: </span><span className="text-gray-700">{snapshot.rsi_14 ?? '—'}</span></div>
        <div><span className="text-gray-400">MACD (W/D/3D): </span><span className="text-gray-700">{snapshot.macd_weekly ?? '—'} / {snapshot.macd_daily ?? '—'} / {snapshot.macd_3day ?? '—'}</span></div>
        <div><span className="text-gray-400">P&amp;L%: </span><span className="text-gray-700">{snapshot.pnl_pct != null ? `${snapshot.pnl_pct.toFixed(1)}%` : '—'}</span></div>
        <div><span className="text-gray-400">%G/L: </span><span className="text-gray-700">{snapshot.gain_loss_pct != null ? `${snapshot.gain_loss_pct.toFixed(1)}%` : '—'}</span></div>
      </div>
      <TimingBreakdown label="CC Timing" signal={snapshot.cc_timing} />
      <TimingBreakdown label="SP Timing" signal={snapshot.sp_timing} />
      <p className="text-gray-400 pt-1 border-t border-gray-100">Captured: {new Date(snapshot.captured_at).toLocaleString()}</p>
    </div>
  )
}
