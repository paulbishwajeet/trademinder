// frontend/src/pages/ChainPage.tsx
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { screenChain } from '../api/chain'
import type { ChainScreenResult } from '../api/chain'

const STRATEGIES = [
  { value: 'sell_put', label: 'Selling Short Puts' },
  { value: 'sell_call', label: 'Selling Short Calls (coming soon)' },
  { value: 'buy_call_6_12m', label: 'Buying 6-12mo Calls (coming soon)' },
  { value: 'buy_call_12_24m', label: 'Buying 12-24mo Calls (coming soon)' },
  { value: 'sell_put_3_6m', label: 'Selling 3-6mo Puts (coming soon)' },
]

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
        <pre className="text-xs bg-gray-50 border border-gray-200 rounded p-4 overflow-x-auto">
          {JSON.stringify(screenState.result, null, 2)}
        </pre>
      )}
    </div>
  )
}
