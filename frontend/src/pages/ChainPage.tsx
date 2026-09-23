// frontend/src/pages/ChainPage.tsx
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { screenChain } from '../api/chain'
import type { ChainScreenResult, ChainCandidate, ChainExpiry } from '../api/chain'

const STRATEGIES = [
  { value: 'sell_put', label: 'Selling Short Puts' },
  { value: 'sell_call', label: 'Selling Short Calls (coming soon)' },
  { value: 'buy_call_6_12m', label: 'Buying 6-12mo Calls (coming soon)' },
  { value: 'buy_call_12_24m', label: 'Buying 12-24mo Calls (coming soon)' },
  { value: 'sell_put_3_6m', label: 'Selling 3-6mo Puts (coming soon)' },
]

function factorPillClass(points: number, max: number): string {
  const pct = max > 0 ? points / max : 0
  if (pct >= 0.7) return 'bg-green-100 text-green-700'
  if (pct >= 0.4) return 'bg-amber-100 text-amber-700'
  return 'bg-red-100 text-red-700'
}

function CandidateCard({ candidate, isBest }: { candidate: ChainCandidate; isBest: boolean }) {
  return (
    <div className={`border rounded-lg p-3 ${isBest ? 'border-blue-400 bg-blue-50' : 'border-gray-200 bg-white'}`}>
      <div className="flex items-center justify-between">
        <span className="font-bold text-gray-900">${candidate.strike.toFixed(2)}</span>
        <span className="text-xs text-gray-400">Score {candidate.score.toFixed(1)}</span>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 mt-2 text-xs">
        <div><span className="text-gray-400">Delta: </span><span className="text-gray-700">{candidate.delta.toFixed(3)}</span></div>
        <div><span className="text-gray-400">ARR: </span><span className="text-gray-700">{candidate.arr_pct.toFixed(1)}%</span></div>
        <div><span className="text-gray-400">Bid/Ask: </span><span className="text-gray-700">${candidate.bid.toFixed(2)}/${candidate.ask.toFixed(2)} ({(candidate.spread_pct * 100).toFixed(1)}%)</span></div>
        <div><span className="text-gray-400">Last: </span><span className="text-gray-700">${candidate.last.toFixed(2)}</span></div>
        <div><span className="text-gray-400">Volume: </span><span className="text-gray-700">{candidate.volume}</span></div>
        <div><span className="text-gray-400">OI: </span><span className="text-gray-700">{candidate.open_interest}</span></div>
        <div><span className="text-gray-400">Breakeven: </span><span className="text-gray-700">${candidate.breakeven.toFixed(2)}</span></div>
        <div><span className="text-gray-400">Cushion: </span><span className="text-gray-700">{candidate.downside_cushion_pct.toFixed(1)}%</span></div>
        <div className="col-span-2"><span className="text-gray-400">Capital: </span><span className="text-gray-700">${candidate.capital_required.toLocaleString()}</span></div>
      </div>
      <div className="flex flex-wrap gap-1 mt-2">
        {candidate.factors.map(f => (
          <span key={f.name} title={f.detail} className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${factorPillClass(f.points, f.max)}`}>
            {f.name} {f.points}/{f.max}
          </span>
        ))}
      </div>
    </div>
  )
}

function ExpiryBox({ expiry }: { expiry: ChainExpiry }) {
  return (
    <section className="mb-5">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-sm font-bold text-gray-700">{expiry.expiration_date} ({expiry.day_of_week}, {expiry.dte}d)</span>
        {expiry.earnings_in_window && (
          <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-red-100 text-red-800 border border-red-300">
            Earnings {expiry.earnings_date}
          </span>
        )}
      </div>
      {expiry.candidates.length === 0 ? (
        <p className="text-sm text-gray-400 italic">No strikes in target delta band for this expiry.</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {expiry.candidates.map((c, i) => (
            <CandidateCard key={c.strike} candidate={c} isBest={i === 0} />
          ))}
        </div>
      )}
    </section>
  )
}

function SignalStrip({ result }: { result: ChainScreenResult }) {
  const timing = result.sp_timing_signal
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="mb-6">
      <div className="flex items-center gap-4 text-sm">
        <span className="text-gray-700">Spot: <span className="font-bold">${result.spot?.toFixed(2) ?? '—'}</span></span>
        {timing && (
          <span className="text-gray-700">
            SP Timing:{' '}
            <button
              type="button"
              onClick={() => setExpanded(e => !e)}
              className="font-medium px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 hover:opacity-80"
            >
              {timing.grade} {timing.score}
            </button>
          </span>
        )}
        <span className="text-gray-700">IV Percentile: <span className="font-bold">{result.iv_percentile != null ? `${result.iv_percentile}%` : '—'}</span></span>
      </div>
      {timing && expanded && (
        <div className="mt-2 border border-gray-200 rounded-lg p-3 bg-gray-50 text-xs space-y-2 max-w-2xl">
          <p className="font-medium text-gray-500 mb-1">SP Timing breakdown</p>
          <div className="grid grid-cols-2 gap-x-6 gap-y-1">
            {timing.factors.map(f => (
              <div key={f.name} className="flex justify-between">
                <span className="text-gray-500">{f.name}</span>
                <span className="text-gray-700 font-medium">
                  {f.points}/{f.max}{' '}
                  <span className="text-gray-400 font-normal">{f.detail}</span>
                </span>
              </div>
            ))}
          </div>
          {timing.commentary && (
            <p className="text-gray-700 pt-1 border-t border-gray-200">{timing.commentary}</p>
          )}
          {timing.strike_hint && (
            <p className="text-blue-700">{timing.strike_hint}</p>
          )}
          {timing.caution && (
            <p className="text-amber-700 font-medium">{timing.caution}</p>
          )}
        </div>
      )}
    </div>
  )
}

interface FormState {
  ticker: string
  strategy: string
  numExpiries: number
  candidatesPerExpiry: number
  targetDelta: number
  deltaTolerance: number
  minArrPct: number
  minVolume: number
  minOi: number
  showAdvanced: boolean
}

type ScreenState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'success'; result: ChainScreenResult }
  | { status: 'error'; message: string }

export function ChainPage() {
  const [searchParams] = useSearchParams()
  const [form, setForm] = useState<FormState>({
    ticker: searchParams.get('symbol')?.toUpperCase() ?? '',
    strategy: searchParams.get('strategy') ?? 'sell_put',
    numExpiries: 3,
    candidatesPerExpiry: 3,
    targetDelta: 0.2,
    deltaTolerance: 0.1,
    minArrPct: 30,
    minVolume: 200,
    minOi: 500,
    showAdvanced: false,
  })
  const [screenState, setScreenState] = useState<ScreenState>({ status: 'idle' })

  const runScreen = async (overrideTicker?: string) => {
    const ticker = (overrideTicker ?? form.ticker).trim().toUpperCase()
    if (!ticker) return
    setScreenState({ status: 'loading' })
    try {
      const result = await screenChain(ticker, {
        strategy: form.strategy,
        num_expiries: form.numExpiries,
        candidates_per_expiry: form.candidatesPerExpiry,
        target_delta: form.targetDelta,
        delta_tolerance: form.deltaTolerance,
        min_arr_pct: form.minArrPct,
        min_volume: form.minVolume,
        min_oi: form.minOi,
      })
      setScreenState({ status: 'success', result })
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Screen failed. Try again.'
      setScreenState({ status: 'error', message })
    }
  }

  useEffect(() => {
    const symbol = searchParams.get('symbol')
    if (symbol) runScreen(symbol.toUpperCase())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Chain Screener</h1>

      <div className="bg-white border border-gray-200 rounded-lg p-4 mb-6">
        <div className="flex gap-4 items-end flex-wrap">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Symbol</label>
            <input
              value={form.ticker}
              onChange={e => setForm(f => ({ ...f, ticker: e.target.value.toUpperCase() }))}
              onKeyDown={e => { if (e.key === 'Enter') runScreen() }}
              className="border border-gray-300 rounded px-3 py-2 text-sm w-32"
              placeholder="NVDA"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Strategy</label>
            <select
              value={form.strategy}
              onChange={e => setForm(f => ({ ...f, strategy: e.target.value }))}
              className="border border-gray-300 rounded px-3 py-2 text-sm"
            >
              {STRATEGIES.map(s => (
                <option key={s.value} value={s.value} disabled={s.value !== 'sell_put'}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
          <button
            onClick={() => runScreen()}
            disabled={screenState.status === 'loading'}
            className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50"
          >
            {screenState.status === 'loading' ? 'Screening…' : 'Screen'}
          </button>
        </div>

        <button
          type="button"
          onClick={() => setForm(f => ({ ...f, showAdvanced: !f.showAdvanced }))}
          className="text-xs text-indigo-600 hover:underline mt-3"
        >
          {form.showAdvanced ? '▲ Hide Advanced' : '▼ Advanced Filters'}
        </button>
        {form.showAdvanced && (
          <div className="grid grid-cols-4 gap-3 mt-3">
            <div>
              <label className="block text-xs text-gray-500 mb-1"># Fridays</label>
              <input type="number" min={1} max={8} value={form.numExpiries}
                onChange={e => setForm(f => ({ ...f, numExpiries: Number(e.target.value) }))}
                className="border border-gray-300 rounded px-2 py-1 text-sm w-full" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Candidates/Expiry</label>
              <input type="number" min={1} max={10} value={form.candidatesPerExpiry}
                onChange={e => setForm(f => ({ ...f, candidatesPerExpiry: Number(e.target.value) }))}
                className="border border-gray-300 rounded px-2 py-1 text-sm w-full" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Target Delta</label>
              <input type="number" step={0.01} min={0} max={1} value={form.targetDelta}
                onChange={e => setForm(f => ({ ...f, targetDelta: Number(e.target.value) }))}
                className="border border-gray-300 rounded px-2 py-1 text-sm w-full" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Delta Tolerance</label>
              <input type="number" step={0.01} min={0} max={1} value={form.deltaTolerance}
                onChange={e => setForm(f => ({ ...f, deltaTolerance: Number(e.target.value) }))}
                className="border border-gray-300 rounded px-2 py-1 text-sm w-full" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Min ARR%</label>
              <input type="number" min={0} value={form.minArrPct}
                onChange={e => setForm(f => ({ ...f, minArrPct: Number(e.target.value) }))}
                className="border border-gray-300 rounded px-2 py-1 text-sm w-full" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Min Volume</label>
              <input type="number" min={0} value={form.minVolume}
                onChange={e => setForm(f => ({ ...f, minVolume: Number(e.target.value) }))}
                className="border border-gray-300 rounded px-2 py-1 text-sm w-full" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Min OI</label>
              <input type="number" min={0} value={form.minOi}
                onChange={e => setForm(f => ({ ...f, minOi: Number(e.target.value) }))}
                className="border border-gray-300 rounded px-2 py-1 text-sm w-full" />
            </div>
          </div>
        )}
      </div>

      {screenState.status === 'error' && (
        <p className="text-red-600 text-sm mb-4">{screenState.message}</p>
      )}
      {screenState.status === 'success' && (
        <>
          <SignalStrip result={screenState.result} />
          {screenState.result.expiries.length === 0 ? (
            <p className="text-sm text-gray-500 mb-3">No Friday expiries found in the requested window.</p>
          ) : (
            <>
              {screenState.result.expiries.length < form.numExpiries && (
                <p className="text-sm text-gray-500 mb-3">
                  Found {screenState.result.expiries.length} of {form.numExpiries} requested expiries.
                </p>
              )}
              {screenState.result.expiries.map(e => <ExpiryBox key={e.expiration_date} expiry={e} />)}
            </>
          )}
        </>
      )}
    </div>
  )
}
