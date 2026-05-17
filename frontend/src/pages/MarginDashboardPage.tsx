// frontend/src/pages/MarginDashboardPage.tsx
import { useState, useCallback, useMemo, useRef, type DragEvent, type ChangeEvent } from 'react'

const API_URL = 'http://localhost:3001'

// ─── Types ────────────────────────────────────────────────────────────────────

interface ShortPut {
  symbol: string
  ticker: string
  expiry: Date
  expiryLabel: string
  strike: number
  qty: number
  obligation: number
  entryPremium: number
  closeValue: number
  pnl: number
  dte: number
  iv: string
  gainPct: number            // pnl / |entryPremium|, clamped 0–1; computed in parsePortfolioCSV
  stockPrice: number | null  // current price from backend; null until loaded
  rsi: number | null         // RSI-14 from backend; null until loaded
  assignmentProb: number | null  // BS put delta; null if stockPrice or IV unavailable
  weightedObligation: number     // obligation × (assignmentProb ?? 1); defaults to full obligation
}

interface ParsedData {
  shortPuts: ShortPut[]
  liquidBuffer: number
  totalEquity: number
}

interface ExpiryGroup {
  label: string
  expiry: Date
  dte: number
  count: number
  obligation: number
  weightedObligation: number
}

interface MarketData {
  price: number | null
  rsi: number | null
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const MONTHS: Record<string, number> = {
  Jan: 0, Feb: 1, Mar: 2, Apr: 3, May: 4, Jun: 5,
  Jul: 6, Aug: 7, Sep: 8, Oct: 9, Nov: 10, Dec: 11,
}

const OPTION_SYM_RE = /^(\S+)\s+([A-Za-z]+)\s+(\d{1,2})\s+'(\d{2})\s+\$(\d+(?:\.\d+)?)\s+(Call|Put)$/

function parseNum(s: string): number {
  if (!s || s === '--') return 0
  const n = parseFloat(s.replace(/,/g, ''))
  return isNaN(n) ? 0 : n
}

function getDte(expiry: Date): number {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const d = new Date(expiry)
  d.setHours(0, 0, 0, 0)
  return Math.round((d.getTime() - today.getTime()) / 86_400_000)
}

function dteClass(dte: number): string {
  if (dte <= 7) return 'bg-red-100 text-red-700 border border-red-300'
  if (dte <= 21) return 'bg-amber-100 text-amber-700 border border-amber-300'
  if (dte <= 60) return 'bg-green-100 text-green-700 border border-green-300'
  return 'bg-blue-100 text-blue-700 border border-blue-300'
}

function fmt$(n: number): string {
  return '$' + Math.abs(Math.round(n)).toLocaleString('en-US')
}

function fmtSigned$(n: number): string {
  const sign = n >= 0 ? '+' : '-'
  return sign + '$' + Math.abs(Math.round(n)).toLocaleString('en-US')
}

function fmtPct(n: number): string {
  return n.toFixed(1) + '%'
}

/** Abramowitz & Stegun rational approximation — accurate to ~7 decimal places. */
function normalCDF(x: number): number {
  const a1 =  0.254829592, a2 = -0.284496736, a3 =  1.421413741
  const a4 = -1.453152027, a5 =  1.061405429, p  =  0.3275911
  const sign = x < 0 ? -1 : 1
  const t = 1 / (1 + p * Math.abs(x) / Math.SQRT2)
  const poly = t * (a1 + t * (a2 + t * (a3 + t * (a4 + t * a5))))
  return 0.5 * (1 + sign * (1 - poly * Math.exp(-x * x / 2)))
}

/**
 * Black-Scholes put delta (absolute value) = probability of assignment.
 * Returns null when any required input is missing or invalid.
 */
function bsPutAssignmentProb(
  S: number,        // current stock price
  K: number,        // strike price
  T: number,        // time to expiry in years (DTE / 365)
  sigma: number,    // implied volatility as decimal (e.g. 0.35 for 35%)
  r = 0.045,        // risk-free rate (approx T-bill rate)
): number | null {
  if (!S || !K || T <= 0 || sigma <= 0) return null
  const d1 = (Math.log(S / K) + (r + (sigma * sigma) / 2) * T) / (sigma * Math.sqrt(T))
  return normalCDF(-d1)
}

// @ts-expect-error TS6133 - will be used in Task 4
function gainClass(pct: number): string {
  if (pct >= 0.70) return 'text-green-600 font-medium'
  if (pct >= 0.40) return 'text-amber-600 font-medium'
  return 'text-red-600 font-medium'
}

// @ts-expect-error TS6133 - will be used in Task 4
function probClass(prob: number): string {
  if (prob < 0.15) return 'text-green-600 font-medium'
  if (prob < 0.35) return 'text-amber-600 font-medium'
  return 'text-red-600 font-medium'
}

// @ts-expect-error TS6133 - will be used in Task 4
function rsiPillClass(rsi: number): string {
  if (rsi < 30)  return 'bg-green-100 text-green-700 border border-green-300'
  if (rsi < 40)  return 'bg-emerald-100 text-emerald-700 border border-emerald-300'
  if (rsi <= 60) return 'bg-gray-100 text-gray-600 border border-gray-200'
  if (rsi <= 70) return 'bg-amber-100 text-amber-700 border border-amber-300'
  return 'bg-red-100 text-red-700 border border-red-300'
}

// ─── CSV Parser ───────────────────────────────────────────────────────────────

function parsePortfolioCSV(text: string): ParsedData {
  const lines = text.trim().split('\n').filter(l => l.trim())
  let liquidBuffer = 0
  let totalEquity = 0
  const shortPuts: ShortPut[] = []

  for (let i = 1; i < lines.length; i++) {
    const cols = lines[i].split(',')
    const symbol = cols[0]?.trim() ?? ''
    const qty = parseNum(cols[1])
    const pricePaid = parseNum(cols[7])
    const totalGain = parseNum(cols[9])
    const value = parseNum(cols[11])
    const type = cols[13]?.trim() ?? ''
    const iv = cols[14]?.trim() ?? '--'

    if (type === 'Equity') {
      const absVal = Math.abs(value)
      totalEquity += absVal
      if (symbol === 'SGOV' || symbol.toLowerCase() === 'cash') {
        liquidBuffer += absVal
      }
      continue
    }

    if (type !== 'Option' || qty >= 0) continue

    const m = OPTION_SYM_RE.exec(symbol)
    if (!m) continue
    const [, ticker, monthStr, dayStr, yearStr, strikeStr, optionType] = m
    if (optionType !== 'Put') continue

    const month = MONTHS[monthStr]
    if (month === undefined) continue
    const year = 2000 + parseInt(yearStr, 10)
    const expiry = new Date(year, month, parseInt(dayStr, 10))
    const expiryLabel = `${monthStr} ${parseInt(dayStr, 10)} '${yearStr}`
    const strike = parseFloat(strikeStr)
    const absQty = Math.abs(qty)

    const obligation = strike * absQty * 100
    const entryPremium = pricePaid * absQty * 100
    const absEntry = Math.abs(entryPremium)
    const gainPct = absEntry > 0 ? Math.min(Math.max(totalGain / absEntry, 0), 1) : 0

    shortPuts.push({
      symbol,
      ticker,
      expiry,
      expiryLabel,
      strike,
      qty,
      obligation,
      entryPremium,
      closeValue: Math.abs(value),
      pnl: totalGain,
      dte: getDte(expiry),
      iv,
      gainPct,
      stockPrice: null,
      rsi: null,
      assignmentProb: null,
      weightedObligation: obligation,   // conservative default: 100% risk until market data loads
    })
  }

  shortPuts.sort((a, b) => a.dte - b.dte)
  return { shortPuts, liquidBuffer, totalEquity }
}

function groupByExpiry(positions: ShortPut[]): ExpiryGroup[] {
  const map = new Map<string, ExpiryGroup>()
  for (const p of positions) {
    if (!map.has(p.expiryLabel)) {
      map.set(p.expiryLabel, {
        label: p.expiryLabel,
        expiry: p.expiry,
        dte: p.dte,
        count: 0,
        obligation: 0,
        weightedObligation: 0,
      })
    }
    const g = map.get(p.expiryLabel)!
    g.count++
    g.obligation += p.obligation
    g.weightedObligation += p.weightedObligation
  }
  return Array.from(map.values()).sort((a, b) => a.dte - b.dte)
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function SummaryCard({
  label, value, sub, accentClass,
}: { label: string; value: string; sub: string; accentClass: string }) {
  return (
    <div className={`bg-white border border-gray-200 rounded-xl p-4 border-t-4 ${accentClass}`}>
      <div className="text-xs text-gray-500 font-medium uppercase tracking-wide mb-1">{label}</div>
      <div className="text-2xl font-bold text-gray-900 mt-1">{value}</div>
      <div className="text-xs text-gray-400 mt-1">{sub}</div>
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export function MarginDashboardPage() {
  const [parsed, setParsed] = useState<ParsedData | null>(null)
  const [fileName, setFileName] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [marketData, setMarketData] = useState<Record<string, MarketData>>({})
  const [marketLoading, setMarketLoading] = useState(false)
  const [marketError, setMarketError] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const abortCtrlRef = useRef<AbortController | null>(null)

  const fetchMarketData = useCallback(async (tickers: string[]) => {
    abortCtrlRef.current?.abort()
    const ctrl = new AbortController()
    abortCtrlRef.current = ctrl

    setMarketLoading(true)
    setMarketError(false)
    try {
      const resp = await fetch(`${API_URL}/api/market/rsi`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tickers }),
        signal: ctrl.signal,
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const raw: Record<string, { rsi: number | null; price: number | null } | null> = await resp.json()
      const out: Record<string, MarketData> = {}
      for (const [ticker, val] of Object.entries(raw)) {
        out[ticker] = { price: val?.price ?? null, rsi: val?.rsi ?? null }
      }
      setMarketData(out)
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') return
      console.error('Market data fetch failed:', err)
      setMarketError(true)
    } finally {
      setMarketLoading(false)
    }
  }, [])

  const loadFile = useCallback((file: File) => {
    if (!file.name.toLowerCase().endsWith('.csv')) {
      alert('Please upload a .csv file exported from E*TRADE.')
      return
    }
    setFileName(file.name)
    setMarketData({})
    setMarketLoading(false)
    setMarketError(false)
    const reader = new FileReader()
    reader.onload = (e) => {
      const text = e.target?.result as string
      const data = parsePortfolioCSV(text)
      setParsed(data)
      const tickers = [...new Set(data.shortPuts.map(p => p.ticker))]
      if (tickers.length > 0) fetchMarketData(tickers)
    }
    reader.readAsText(file)
  }, [fetchMarketData])

  const onDrop = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) loadFile(file)
  }, [loadFile])

  const onInputChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) loadFile(file)
    e.target.value = ''
  }

  const enrichedPuts = useMemo((): ShortPut[] => {
    return (parsed?.shortPuts ?? []).map(p => {
      const md = marketData[p.ticker]
      const stockPrice = md?.price ?? null
      const rsi = md?.rsi ?? null
      const ivDecimal = p.iv !== '--' ? parseFloat(p.iv) / 100 : null
      const T = p.dte / 365
      const prob = stockPrice !== null && ivDecimal !== null
        ? bsPutAssignmentProb(stockPrice, p.strike, T, ivDecimal)
        : null
      return {
        ...p,
        stockPrice,
        rsi,
        assignmentProb: prob,
        weightedObligation: p.obligation * (prob ?? 1),
      }
    })
  }, [parsed, marketData])

  // ── Upload screen ──────────────────────────────────────────────────────────
  if (!parsed) {
    return (
      <div className="flex items-center justify-center min-h-[calc(100vh-56px)] bg-gray-50">
        <div
          className={`border-2 border-dashed rounded-2xl p-16 text-center transition-colors cursor-pointer max-w-lg w-full mx-4 ${
            dragOver ? 'border-blue-400 bg-blue-50' : 'border-gray-300 bg-white hover:border-gray-400'
          }`}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
        >
          <div className="text-5xl mb-4">📊</div>
          <h2 className="text-lg font-semibold text-gray-800 mb-2">Portfolio Margin Analysis</h2>
          <p className="text-sm text-gray-500 mb-6 leading-relaxed">
            Drop your E*TRADE portfolio CSV export here,<br />or click to browse.
          </p>
          <button
            className="px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
            onClick={(e) => { e.stopPropagation(); inputRef.current?.click() }}
          >
            Select CSV File
          </button>
          <p className="text-xs text-gray-400 mt-4">
            Analyzes short put positions. Calculates assignment obligations and liquidity coverage.
          </p>
          <input ref={inputRef} type="file" accept=".csv" className="hidden" onChange={onInputChange} />
        </div>
      </div>
    )
  }

  // ── Dashboard ──────────────────────────────────────────────────────────────
  const { shortPuts, liquidBuffer, totalEquity } = parsed
  const totalObligation = shortPuts.reduce((s, p) => s + p.obligation, 0)
  const coveragePct = totalObligation > 0 ? (liquidBuffer / totalObligation) * 100 : 0
  const fullCoveragePct = totalObligation > 0 ? (totalEquity / totalObligation) * 100 : 0
  const nearTermPuts = shortPuts.filter(p => p.dte <= 21)
  const nearTermObligation = nearTermPuts.reduce((s, p) => s + p.obligation, 0)
  const expiryGroups = groupByExpiry(enrichedPuts)
  const totalWeightedObligation = enrichedPuts.reduce((s, p) => s + p.weightedObligation, 0)
  const adjustedCoverage = totalWeightedObligation > 0
    ? (liquidBuffer / totalWeightedObligation) * 100
    : 0

  const healthBarColor =
    coveragePct >= 150 ? 'bg-green-500' :
    coveragePct >= 100 ? 'bg-yellow-400' :
    coveragePct >= 75  ? 'bg-orange-400' : 'bg-red-500'

  const healthTextClass =
    coveragePct >= 150 ? 'text-green-700 bg-green-50 border-green-200' :
    coveragePct >= 100 ? 'text-yellow-700 bg-yellow-50 border-yellow-200' :
    coveragePct >= 75  ? 'text-orange-700 bg-orange-50 border-orange-200' : 'text-red-700 bg-red-50 border-red-200'

  return (
    <div className="p-6 max-w-7xl mx-auto">

      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Portfolio Margin Analysis</h1>
          <p className="text-sm text-gray-400 mt-0.5">{fileName}</p>
        </div>
        <button
          onClick={() => { setParsed(null); setFileName(''); setMarketData({}); setMarketLoading(false); setMarketError(false) }}
          className="px-3 py-1.5 text-sm text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
        >
          Upload New File
        </button>
      </div>

      {/* Market data status banner */}
      {(marketLoading || marketError) && (
        <div className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm mb-4 ${
          marketLoading
            ? 'bg-gray-50 border border-gray-200 text-gray-500'
            : 'bg-amber-50 border border-amber-200 text-amber-700'
        }`}>
          {marketLoading
            ? <><span className="animate-spin">⏳</span> Fetching market data…</>
            : <><span>⚠️</span> Market data unavailable — probability columns not shown</>}
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mb-6">
        <SummaryCard
          label="Total Assignment Obligation"
          value={fmt$(totalObligation)}
          sub={`${shortPuts.length} short put${shortPuts.length !== 1 ? 's' : ''}`}
          accentClass="border-t-blue-500"
        />
        <SummaryCard
          label="Liquid Buffer (SGOV + Cash)"
          value={fmt$(liquidBuffer)}
          sub="T-bills and cash equivalents"
          accentClass="border-t-green-500"
        />
        <SummaryCard
          label="Liquid Coverage"
          value={fmtPct(coveragePct)}
          sub={marketLoading
            ? 'Adj. coverage: loading…'
            : `Adj. coverage: ${fmtPct(adjustedCoverage)}`}
          accentClass={coveragePct >= 100 ? 'border-t-green-500' : coveragePct >= 75 ? 'border-t-amber-500' : 'border-t-red-500'}
        />
        <SummaryCard
          label="Near-Term (≤ 21 DTE)"
          value={fmt$(nearTermObligation)}
          sub={`${nearTermPuts.length} position${nearTermPuts.length !== 1 ? 's' : ''} expiring soon`}
          accentClass={nearTermPuts.length > 0 ? 'border-t-amber-500' : 'border-t-gray-300'}
        />
        <SummaryCard
          label="Confidence-Adjusted Obligation"
          value={marketLoading || marketError ? '—' : fmt$(totalWeightedObligation)}
          sub={marketLoading
            ? 'Fetching market data…'
            : marketError
            ? 'Market data unavailable'
            : `${fmtPct(totalWeightedObligation > 0 ? (totalWeightedObligation / totalObligation) * 100 : 0)} of worst-case`}
          accentClass={marketLoading || marketError ? 'border-t-gray-300' : 'border-t-violet-500'}
        />
      </div>

      {/* Middle row: Expiry table + Liquidity health */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">

        {/* Expiry Breakdown */}
        <div className="lg:col-span-2 bg-white border border-gray-200 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-700">Obligation by Expiry</h2>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
                <th className="px-4 py-2 text-left font-medium">Expiry</th>
                <th className="px-4 py-2 text-center font-medium">DTE</th>
                <th className="px-4 py-2 text-center font-medium">Positions</th>
                <th className="px-4 py-2 text-right font-medium">Obligation</th>
                <th className="px-4 py-2 text-right font-medium">% of Total</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {expiryGroups.map(g => (
                <tr key={g.label} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-2.5 font-medium text-gray-800">{g.label}</td>
                  <td className="px-4 py-2.5 text-center">
                    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${dteClass(g.dte)}`}>
                      {g.dte}d
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-center text-gray-600">{g.count}</td>
                  <td className="px-4 py-2.5 text-right font-medium text-gray-800">{fmt$(g.obligation)}</td>
                  <td className="px-4 py-2.5 text-right text-gray-500">
                    {fmtPct(totalObligation > 0 ? (g.obligation / totalObligation) * 100 : 0)}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="bg-gray-50 text-sm font-semibold border-t border-gray-200">
                <td className="px-4 py-2.5 text-gray-700" colSpan={3}>Total</td>
                <td className="px-4 py-2.5 text-right text-gray-900">{fmt$(totalObligation)}</td>
                <td className="px-4 py-2.5 text-right text-gray-500">100%</td>
              </tr>
            </tfoot>
          </table>
        </div>

        {/* Liquidity Health */}
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Liquidity Health</h2>

          <div className={`rounded-lg border px-4 py-3 mb-4 text-center ${healthTextClass}`}>
            <div className="text-3xl font-bold">{fmtPct(coveragePct)}</div>
            <div className="text-xs font-medium mt-0.5">Liquid Coverage Ratio</div>
          </div>

          <div className="mb-5">
            <div className="flex justify-between text-xs text-gray-500 mb-1.5">
              <span>Liquid buffer vs obligation</span>
              <span>{fmtPct(Math.min(coveragePct, 100))}</span>
            </div>
            <div className="w-full bg-gray-100 rounded-full h-3">
              <div
                className={`h-3 rounded-full transition-all ${healthBarColor}`}
                style={{ width: `${Math.min(coveragePct, 100)}%` }}
              />
            </div>
          </div>

          <div className="space-y-2.5 text-sm mb-5">
            <div className="flex justify-between">
              <span className="text-gray-500">SGOV / Cash</span>
              <span className="font-medium text-gray-800">{fmt$(liquidBuffer)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Total Equity Value</span>
              <span className="font-medium text-gray-800">{fmt$(totalEquity)}</span>
            </div>
            <div className="flex justify-between border-t border-gray-100 pt-2.5">
              <span className="text-gray-500">Total Obligation</span>
              <span className="font-semibold text-gray-900">{fmt$(totalObligation)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Full Portfolio Coverage</span>
              <span className="font-medium text-green-700">{fmtPct(fullCoveragePct)}</span>
            </div>
          </div>

          <div className="border-t border-gray-100 pt-3">
            <div className="text-xs text-gray-400 font-medium uppercase tracking-wide mb-2">DTE Legend</div>
            {[
              { label: '≤ 7d', cls: 'bg-red-400', text: 'Critical' },
              { label: '≤ 21d', cls: 'bg-amber-400', text: 'Near-term' },
              { label: '≤ 60d', cls: 'bg-green-400', text: 'Active' },
              { label: '> 60d', cls: 'bg-blue-400', text: 'Long-dated' },
            ].map(item => (
              <div key={item.label} className="flex items-center gap-2 text-xs text-gray-600 mb-1">
                <span className={`inline-block w-2.5 h-2.5 rounded-full ${item.cls}`} />
                <span className="font-mono w-12">{item.label}</span>
                <span className="text-gray-400">{item.text}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Position Table */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-700">Short Put Positions</h2>
          <span className="text-xs text-gray-400">{shortPuts.length} positions</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
                <th className="px-4 py-2.5 text-left font-medium">Symbol</th>
                <th className="px-4 py-2.5 text-center font-medium">Expiry</th>
                <th className="px-4 py-2.5 text-center font-medium">DTE</th>
                <th className="px-4 py-2.5 text-right font-medium">Strike</th>
                <th className="px-4 py-2.5 text-right font-medium">Qty</th>
                <th className="px-4 py-2.5 text-right font-medium">Obligation</th>
                <th className="px-4 py-2.5 text-right font-medium">Entry Premium</th>
                <th className="px-4 py-2.5 text-right font-medium">Close Cost</th>
                <th className="px-4 py-2.5 text-right font-medium">P&amp;L</th>
                <th className="px-4 py-2.5 text-right font-medium">IV</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {shortPuts.map((p, i) => (
                <tr key={i} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-2.5">
                    <div className="font-medium text-gray-800">{p.ticker}</div>
                    <div className="text-xs text-gray-400 truncate max-w-[180px]" title={p.symbol}>
                      ${p.strike} Put
                    </div>
                  </td>
                  <td className="px-4 py-2.5 text-center text-gray-600 whitespace-nowrap">{p.expiryLabel}</td>
                  <td className="px-4 py-2.5 text-center">
                    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${dteClass(p.dte)}`}>
                      {p.dte}d
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right text-gray-700">
                    ${p.strike.toLocaleString()}
                  </td>
                  <td className="px-4 py-2.5 text-right text-gray-600">{p.qty}</td>
                  <td className="px-4 py-2.5 text-right font-medium text-gray-800">{fmt$(p.obligation)}</td>
                  <td className="px-4 py-2.5 text-right text-gray-600">{fmt$(p.entryPremium)}</td>
                  <td className="px-4 py-2.5 text-right text-gray-600">{fmt$(p.closeValue)}</td>
                  <td className={`px-4 py-2.5 text-right font-medium ${p.pnl >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                    {fmtSigned$(p.pnl)}
                  </td>
                  <td className="px-4 py-2.5 text-right text-gray-500">
                    {p.iv !== '--' ? p.iv + '%' : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
