import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { scanOptions } from '../api/scanner'
import type { OptionRow, ScanResult } from '../api/scanner'

type OptType = 'calls' | 'puts' | 'both'
type TabKey = 'calls' | 'puts'

interface FormState {
  ticker: string
  optType: OptType
  minDte: number
  minOi: number
  maxDelta: number
  showAdvanced: boolean
}

type ScanState =
  | { status: 'idle' }
  | { status: 'loading'; ticker: string }
  | { status: 'success'; result: ScanResult; activeTab: TabKey }
  | { status: 'empty'; ticker: string }
  | { status: 'error'; message: string; ticker: string }

function dteClass(dte: number): string {
  if (dte <= 7) return 'text-red-600 font-semibold'
  if (dte <= 21) return 'text-amber-600 font-semibold'
  if (dte <= 60) return 'text-green-600'
  return 'text-blue-600'
}

function fmtExp(expiration: string, earningsCount: number): string {
  const d = new Date(expiration + 'T00:00:00')
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
  const tag = earningsCount > 0 ? ` ${earningsCount}E` : ''
  return `${months[d.getMonth()]} ${d.getDate()} '${String(d.getFullYear()).slice(2)}${tag}`
}

function fmtShortDate(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00')
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
  return `${months[d.getMonth()]} ${d.getDate()} '${String(d.getFullYear()).slice(2)}`
}

function OptionsTable({ rows }: { rows: OptionRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            {['Strike','Expiration','DTE','Bid','Ask','Mid','IV%','IV+pp','Delta','Ann%','OI'].map(h => (
              <th key={h} className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-100">
          {rows.map((r, i) => (
            <tr key={i} className="hover:bg-gray-50">
              <td className="px-3 py-2 font-medium">${r.strike.toFixed(0)}</td>
              <td className="px-3 py-2 whitespace-nowrap">{fmtExp(r.expiration, r.earnings_count)}</td>
              <td className={`px-3 py-2 ${dteClass(r.dte)}`}>{r.dte}</td>
              <td className="px-3 py-2">${r.bid.toFixed(2)}</td>
              <td className="px-3 py-2">${r.ask.toFixed(2)}</td>
              <td className="px-3 py-2 font-medium">${r.mid.toFixed(2)}</td>
              <td className="px-3 py-2">{(r.iv * 100).toFixed(1)}</td>
              <td className={`px-3 py-2 font-medium ${r.iv_excess >= 0 ? 'text-orange-600' : 'text-gray-400'}`}>
                {r.iv_excess >= 0 ? '+' : ''}{(r.iv_excess * 100).toFixed(1)}
              </td>
              <td className="px-3 py-2">{r.delta.toFixed(2)}</td>
              <td className="px-3 py-2">{r.ann_yield_pct.toFixed(1)}%</td>
              <td className="px-3 py-2 text-gray-500">{r.open_interest.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function ScannerPage() {
  const [searchParams] = useSearchParams()
  const [form, setForm] = useState<FormState>({
    ticker: searchParams.get('ticker')?.toUpperCase() ?? '',
    optType: 'both',
    minDte: 365,
    minOi: 25,
    maxDelta: 0.70,
    showAdvanced: false,
  })
  const [scanState, setScanState] = useState<ScanState>({ status: 'idle' })

  const runScan = async (overrideTicker?: string) => {
    const ticker = (overrideTicker ?? form.ticker).trim().toUpperCase()
    if (!ticker) return
    setScanState({ status: 'loading', ticker })
    try {
      const result = await scanOptions(ticker, {
        type: form.optType,
        min_dte: form.minDte,
        min_oi: form.minOi,
        max_delta: form.maxDelta,
      })
      if (result.options.length === 0) {
        setScanState({ status: 'empty', ticker })
      } else {
        const defaultTab: TabKey = form.optType === 'puts' ? 'puts' : 'calls'
        setScanState({ status: 'success', result, activeTab: defaultTab })
      }
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Scan failed. Try again.'
      setScanState({ status: 'error', message, ticker })
    }
  }

  useEffect(() => {
    const ticker = searchParams.get('ticker')
    if (ticker) runScan(ticker.toUpperCase())
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="p-6 max-w-5xl">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Options Scanner</h1>

      {/* Input zone */}
      <div className="bg-white border border-gray-200 rounded-lg p-4 mb-6">
        <div className="flex gap-4 items-end flex-wrap">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Ticker</label>
            <input
              type="text"
              className="border border-gray-300 rounded px-3 py-2 text-sm w-28 uppercase"
              placeholder="e.g. AMD"
              value={form.ticker}
              onChange={e => setForm(f => ({ ...f, ticker: e.target.value.toUpperCase() }))}
              onKeyDown={e => { if (e.key === 'Enter') runScan() }}
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Type</label>
            <div className="flex gap-3">
              {(['calls', 'puts', 'both'] as OptType[]).map(t => (
                <label key={t} className="flex items-center gap-1 text-sm cursor-pointer select-none">
                  <input
                    type="radio"
                    name="optType"
                    value={t}
                    checked={form.optType === t}
                    onChange={() => setForm(f => ({ ...f, optType: t }))}
                  />
                  {t.charAt(0).toUpperCase() + t.slice(1)}
                </label>
              ))}
            </div>
          </div>
          <button
            onClick={() => runScan()}
            disabled={scanState.status === 'loading'}
            className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50"
          >
            {scanState.status === 'loading' ? 'Scanning…' : 'Scan'}
          </button>
        </div>

        <div className="mt-3">
          <button
            type="button"
            className="text-xs text-blue-600 hover:underline"
            onClick={() => setForm(f => ({ ...f, showAdvanced: !f.showAdvanced }))}
          >
            {form.showAdvanced ? '▲ Hide filters' : '▼ Advanced filters'}
          </button>
          {form.showAdvanced && (
            <div className="flex gap-4 mt-2 flex-wrap">
              {(
                [
                  { label: 'Min DTE', key: 'minDte', step: 30, min: 1 },
                  { label: 'Min OI',  key: 'minOi',  step: 5,  min: 0 },
                  { label: 'Max Δ',   key: 'maxDelta', step: 0.05, min: 0.01 },
                ] as { label: string; key: keyof FormState; step: number; min: number }[]
              ).map(({ label, key, step, min }) => (
                <div key={key}>
                  <label className="block text-xs text-gray-500 mb-1">{label}</label>
                  <input
                    type="number"
                    className="border border-gray-300 rounded px-2 py-1 text-sm w-24"
                    value={form[key] as number}
                    step={step}
                    min={min}
                    onChange={e => setForm(f => ({ ...f, [key]: Number(e.target.value) }))}
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* States */}
      {scanState.status === 'idle' && (
        <p className="text-center text-gray-400 py-16 text-sm">
          Enter a ticker and click Scan to find LEAPS options ranked by IV excess.
        </p>
      )}

      {scanState.status === 'loading' && (
        <div className="text-center py-16">
          <div className="animate-spin inline-block w-6 h-6 border-2 border-blue-600 border-t-transparent rounded-full mb-3" />
          <p className="text-gray-500 text-sm">Scanning {scanState.ticker}… this takes ~10s</p>
        </div>
      )}

      {scanState.status === 'error' && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex items-center justify-between">
          <p className="text-sm text-red-700">{scanState.message}</p>
          <button onClick={() => runScan(scanState.ticker)} className="text-sm text-red-600 hover:underline ml-4">
            Retry
          </button>
        </div>
      )}

      {scanState.status === 'empty' && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-sm text-yellow-700">
          No options found for <strong>{scanState.ticker}</strong> — try relaxing the filters (lower Min OI, lower Min DTE, or higher Max Delta).
        </div>
      )}

      {scanState.status === 'success' && (() => {
        const { result, activeTab } = scanState
        const callRows = result.options.filter(o => o.type === 'call')
        const putRows  = result.options.filter(o => o.type === 'put')
        const showTabs = form.optType === 'both'
        const visibleRows = showTabs ? (activeTab === 'calls' ? callRows : putRows) : result.options

        return (
          <>
            <div className="text-xs text-gray-500 mb-4 flex flex-wrap gap-x-4 gap-y-1">
              <span className="font-semibold text-gray-800">{result.ticker}</span>
              <span>spot: ${result.spot.toFixed(2)}</span>
              <span>scanned: {result.scan_ts.slice(0, 10)}</span>
              <span>LT close if opened today: {fmtShortDate(result.lt_close_date)}</span>
              {result.earnings_dates.length > 0 && (
                <span>
                  upcoming earnings: {result.earnings_dates.slice(0, 3).map(fmtShortDate).join(', ')}
                </span>
              )}
            </div>

            {showTabs && (
              <div className="flex gap-1 mb-0 border-b border-gray-200">
                {(['calls', 'puts'] as TabKey[]).map(tab => (
                  <button
                    key={tab}
                    onClick={() =>
                      setScanState(s =>
                        s.status === 'success' ? { ...s, activeTab: tab } : s,
                      )
                    }
                    className={`px-4 py-2 text-sm -mb-px border-b-2 ${
                      activeTab === tab
                        ? 'border-blue-600 text-blue-600 font-medium'
                        : 'border-transparent text-gray-500 hover:text-gray-700'
                    }`}
                  >
                    {tab.charAt(0).toUpperCase() + tab.slice(1)}{' '}
                    <span className="text-xs text-gray-400">
                      ({tab === 'calls' ? callRows.length : putRows.length})
                    </span>
                  </button>
                ))}
              </div>
            )}

            <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
              <OptionsTable rows={visibleRows} />
            </div>

            <div className="mt-3 space-y-1 text-xs text-gray-400">
              <p><strong className="text-gray-500">IV+pp</strong> — percentage points above the fitted IV surface. &gt;3pp = some richness; &gt;5pp = genuine signal.</p>
              <p><strong className="text-gray-500">Delta</strong> — approximate probability of expiring in-the-money. Lower = safer, less premium.</p>
              <p><strong className="text-gray-500">Ann%</strong> — annualized yield on premium collected. Calls: vs. spot; puts: vs. strike.</p>
            </div>
          </>
        )
      })()}
    </div>
  )
}
