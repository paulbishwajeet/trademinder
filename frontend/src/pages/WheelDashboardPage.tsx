import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import type { WheelSessionDetail, WheelSessionSummary, WheelSlotDetail, CCSignalResult, OptionPriceResult, TechnicalsData } from '../types'
import { wheelApi, combinedSignalApi, optionPriceApi, ccTimingSignalApi, spTimingSignalApi } from '../api/wheel'
import { technicalsApi, type QuoteData } from '../api/technicals'
import { timeAgo } from '../components/Screener/timeAgo'
import { NewWheelModalV2 } from '../components/Wheel/NewWheelModalV2'
import { AddSlotModal } from '../components/Wheel/AddSlotModal'
import { ResolveModal } from '../components/Wheel/ResolveModal'
import { LinkLegModalV2 } from '../components/Wheel/LinkLegModalV2'

interface FlatSlot {
  slot: WheelSlotDetail
  ticker: string
  sessionId: string
  stockCostBasis: number | null
  stockCurrentPrice: number | null
}

function flattenSlots(sessions: WheelSessionDetail[]): FlatSlot[] {
  return sessions.flatMap(s => s.slots.map(slot => ({
    slot,
    ticker: s.ticker,
    sessionId: s.id,
    stockCostBasis: s.stock_cost_basis,
    stockCurrentPrice: s.stock_current_price,
  })))
}

const STATUS_LABELS: Record<string, string> = {
  awaiting_cc: 'Awaiting CC',
  cc_active: 'CC Active',
  awaiting_sold_put: 'Awaiting Sold Put',
  sold_put_active: 'Sold Put Active',
}

const MACD_COLORS: Record<string, string> = {
  bullish: 'bg-green-100 text-green-700',
  bearish: 'bg-red-100 text-red-700',
  neutral: 'bg-gray-100 text-gray-600',
}

const GRADE_COLORS: Record<string, string> = {
  strong: 'bg-green-100 text-green-800 border-green-300',
  moderate: 'bg-amber-100 text-amber-800 border-amber-300',
  weak: 'bg-gray-100 text-gray-600 border-gray-300',
  wait: 'bg-gray-50 text-gray-400 border-gray-200',
}

// Module-level (survives page navigation within the SPA, cleared on full reload) caches for
// signal/quote/technicals lookups, so switching pages and coming back doesn't re-fetch from
// Schwab every time. Only the "Fetch Signals" button (force=true) bypasses this.
const CACHE_TTL_MS = 60 * 60 * 1000 // 1 hour

interface CacheEntry<T> { data: T; ts: number }

const signalsCache: Record<string, CacheEntry<CCSignalResult>> = {}
const spSignalsCache: Record<string, CacheEntry<CCSignalResult>> = {}
const quotesCache: Record<string, CacheEntry<QuoteData>> = {}
const technicalsCache: Record<string, CacheEntry<TechnicalsData>> = {}
const optionPricesCache: Record<string, CacheEntry<OptionPriceResult>> = {}
const ccTimingCache: Record<string, CacheEntry<CCSignalResult>> = {}
const spTimingCache: Record<string, CacheEntry<CCSignalResult>> = {}

function seedFromCache<T>(cache: Record<string, CacheEntry<T>>): Record<string, T> {
  const now = Date.now()
  const seeded: Record<string, T> = {}
  for (const [key, entry] of Object.entries(cache)) {
    if (now - entry.ts < CACHE_TTL_MS) seeded[key] = entry.data
  }
  return seeded
}

function isCacheFresh(cache: Record<string, CacheEntry<unknown>>, key: string): boolean {
  const entry = cache[key]
  return entry != null && Date.now() - entry.ts < CACHE_TTL_MS
}

export function WheelDashboardPage() {
  const [sessions, setSessions] = useState<WheelSessionDetail[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showNewModal, setShowNewModal] = useState(false)
  const [addSlotSessionId, setAddSlotSessionId] = useState<string | null>(null)
  const [resolveSlotId, setResolveSlotId] = useState<string | null>(null)
  const [linkSlotId, setLinkSlotId] = useState<string | null>(null)
  const [expandedSlot, setExpandedSlot] = useState<string | null>(null)
  const [signals, setSignals] = useState<Record<string, CCSignalResult | 'loading' | 'error'>>(() => seedFromCache(signalsCache))
  const [spSignals, setSpSignals] = useState<Record<string, CCSignalResult | 'loading' | 'error'>>(() => seedFromCache(spSignalsCache))
  const [ccTimingSignals, setCcTimingSignals] = useState<Record<string, CCSignalResult | 'loading' | 'error'>>(() => seedFromCache(ccTimingCache))
  const [spTimingSignals, setSpTimingSignals] = useState<Record<string, CCSignalResult | 'loading' | 'error'>>(() => seedFromCache(spTimingCache))
  const [signalDetail, setSignalDetail] = useState<string | null>(null)
  const [signalsFetching, setSignalsFetching] = useState(false)
  const [sectionFetching, setSectionFetching] = useState<Record<string, boolean>>({})
  const [optionPrices, setOptionPrices] = useState<Record<string, OptionPriceResult | 'loading' | 'error'>>(() => seedFromCache(optionPricesCache))
  const [quotes, setQuotes] = useState<Record<string, QuoteData | 'loading' | 'error'>>(() => seedFromCache(quotesCache))
  const [technicals, setTechnicals] = useState<Record<string, TechnicalsData | 'loading' | 'error'>>(() => seedFromCache(technicalsCache))

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const summaries = await wheelApi.list()
      const detailed = await Promise.all(summaries.map(s => wheelApi.get(s.id)))
      setSessions(detailed)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  async function loadSignals(force = false, opts?: { tickers?: string[]; includeOptionPrices?: boolean }) {
    if (sessions.length === 0) return
    const allTickers = [...new Set(sessions.map(s => s.ticker))]
    const tickers = opts?.tickers ? allTickers.filter(t => opts.tickers!.includes(t)) : allTickers
    const includeOptionPrices = opts?.includeOptionPrices ?? true

    // Collect active option legs (keyed by slot id)
    const activeLegs = !includeOptionPrices ? [] : flattenSlots(sessions)
      .filter(f => (f.slot.status === 'cc_active' || f.slot.status === 'sold_put_active') && tickers.includes(f.ticker))
      .flatMap(f => {
        const openLegs = f.slot.legs.filter(l => l.rotation_number === f.slot.rotation_number && l.trade_status === 'open' && l.leg_role !== 'stock')
        const leg = openLegs[openLegs.length - 1] // latest open leg (legs ordered by created_at)
        if (!leg || leg.trade_strike_price == null || !leg.trade_expiry_date) return []
        return [{ slotId: f.slot.id, ticker: f.ticker, strike: leg.trade_strike_price, expiry: leg.trade_expiry_date, contractType: f.slot.status === 'cc_active' ? 'call' : 'put' }]
      })

    if (force) {
      tickers.forEach(ticker => {
        setSignals(prev => ({ ...prev, [ticker]: 'loading' }))
        setSpSignals(prev => ({ ...prev, [ticker]: 'loading' }))
        setCcTimingSignals(prev => ({ ...prev, [ticker]: 'loading' }))
        setSpTimingSignals(prev => ({ ...prev, [ticker]: 'loading' }))
        setQuotes(prev => ({ ...prev, [ticker]: 'loading' }))
        setTechnicals(prev => ({ ...prev, [ticker]: 'loading' }))
      })
      activeLegs.forEach(({ slotId }) => setOptionPrices(prev => ({ ...prev, [slotId]: 'loading' })))
    } else {
      tickers.forEach(ticker => {
        if (!isCacheFresh(signalsCache, ticker)) setSignals(prev => ({ ...prev, [ticker]: 'loading' }))
        if (!isCacheFresh(spSignalsCache, ticker)) setSpSignals(prev => ({ ...prev, [ticker]: 'loading' }))
        if (!isCacheFresh(ccTimingCache, ticker)) setCcTimingSignals(prev => ({ ...prev, [ticker]: 'loading' }))
        if (!isCacheFresh(spTimingCache, ticker)) setSpTimingSignals(prev => ({ ...prev, [ticker]: 'loading' }))
        if (!isCacheFresh(quotesCache, ticker)) setQuotes(prev => ({ ...prev, [ticker]: 'loading' }))
        if (!isCacheFresh(technicalsCache, ticker)) setTechnicals(prev => ({ ...prev, [ticker]: 'loading' }))
      })
      activeLegs.forEach(({ slotId }) => {
        if (!isCacheFresh(optionPricesCache, slotId)) setOptionPrices(prev => ({ ...prev, [slotId]: 'loading' }))
      })
    }

    const tickersToFetch = tickers.filter(ticker => force || !isCacheFresh(signalsCache, ticker))
    const legsToFetch = activeLegs.filter(({ slotId }) => force || !isCacheFresh(optionPricesCache, slotId))

    await Promise.allSettled([
      ...tickersToFetch.map(ticker =>
        combinedSignalApi.get(ticker, force)
          .then(result => {
            setSignals(prev => ({ ...prev, [ticker]: result.cc }))
            setSpSignals(prev => ({ ...prev, [ticker]: result.sp }))
            signalsCache[ticker] = { data: result.cc, ts: Date.now() }
            spSignalsCache[ticker] = { data: result.sp, ts: Date.now() }
          })
          .catch(() => {
            setSignals(prev => ({ ...prev, [ticker]: 'error' }))
            setSpSignals(prev => ({ ...prev, [ticker]: 'error' }))
          })
      ),
      ...tickersToFetch.map(ticker =>
        ccTimingSignalApi.get(ticker, force)
          .then(result => {
            setCcTimingSignals(prev => ({ ...prev, [ticker]: result }))
            ccTimingCache[ticker] = { data: result, ts: Date.now() }
          })
          .catch(() => setCcTimingSignals(prev => ({ ...prev, [ticker]: 'error' })))
      ),
      ...tickersToFetch.map(ticker =>
        spTimingSignalApi.get(ticker, force)
          .then(result => {
            setSpTimingSignals(prev => ({ ...prev, [ticker]: result }))
            spTimingCache[ticker] = { data: result, ts: Date.now() }
          })
          .catch(() => setSpTimingSignals(prev => ({ ...prev, [ticker]: 'error' })))
      ),
      ...tickersToFetch.map(ticker =>
        technicalsApi.quote(ticker)
          .then(result => {
            setQuotes(prev => ({ ...prev, [ticker]: result }))
            quotesCache[ticker] = { data: result, ts: Date.now() }
          })
          .catch(() => setQuotes(prev => ({ ...prev, [ticker]: 'error' })))
      ),
      ...tickersToFetch.map(ticker =>
        technicalsApi.fetch(ticker)
          .then(result => {
            setTechnicals(prev => ({ ...prev, [ticker]: result }))
            technicalsCache[ticker] = { data: result, ts: Date.now() }
          })
          .catch(() => setTechnicals(prev => ({ ...prev, [ticker]: 'error' })))
      ),
      ...legsToFetch.map(({ slotId, ticker, strike, expiry, contractType }) =>
        optionPriceApi.get(ticker, strike, expiry, contractType)
          .then(result => {
            setOptionPrices(prev => ({ ...prev, [slotId]: result }))
            optionPricesCache[slotId] = { data: result, ts: Date.now() }
          })
          .catch(() => setOptionPrices(prev => ({ ...prev, [slotId]: 'error' })))
      ),
    ])
  }

  async function fetchSection(key: string, tickers: string[], includeOptionPrices: boolean) {
    setSectionFetching(prev => ({ ...prev, [key]: true }))
    try {
      await loadSignals(true, { tickers, includeOptionPrices })
    } finally {
      setSectionFetching(prev => ({ ...prev, [key]: false }))
    }
  }

  async function fetchAllSignals() {
    setSignalsFetching(true)
    try {
      await loadSignals(true)
    } finally {
      setSignalsFetching(false)
    }
  }

  function sectionFetchedLabel(tickers: string[]): string {
    const timestamps = tickers
      .map(t => quotesCache[t]?.ts)
      .filter((ts): ts is number => ts != null)
    if (timestamps.length === 0) return 'Fetched: never'
    const oldest = Math.min(...timestamps)
    return `Fetched ${timeAgo(new Date(oldest).toISOString())}`
  }

  useEffect(() => { loadSignals() }, [sessions])

  const allSlots = flattenSlots(sessions)
  const needsAction = allSlots.filter(f => f.slot.needs_action)
  const awaitingCC = allSlots.filter(f => f.slot.status === 'awaiting_cc' && !f.slot.needs_action)
  const awaitingSP = allSlots.filter(f => f.slot.status === 'awaiting_sold_put' && !f.slot.needs_action)
  const active = allSlots
    .filter(f => (f.slot.status === 'cc_active' || f.slot.status === 'sold_put_active') && !f.slot.needs_action)
    .sort((a, b) => {
      const legExpiry = (f: FlatSlot) => {
        const legs = f.slot.legs.filter(l => l.rotation_number === f.slot.rotation_number && l.trade_status === 'open' && l.leg_role !== 'stock')
        return legs[legs.length - 1]?.trade_expiry_date ?? null
      }
      const ea = legExpiry(a)
      const eb = legExpiry(b)
      if (!ea && !eb) return 0
      if (!ea) return 1
      if (!eb) return -1
      return ea < eb ? -1 : ea > eb ? 1 : 0
    })
  const emptyWheels = sessions.filter(s => s.slots.length === 0)

  const resolveSlotTicker = resolveSlotId
    ? allSlots.find(f => f.slot.id === resolveSlotId)?.ticker ?? ''
    : ''
  const linkSlotTicker = linkSlotId
    ? allSlots.find(f => f.slot.id === linkSlotId)?.ticker ?? ''
    : ''
  const linkSlotStatus = linkSlotId
    ? allSlots.find(f => f.slot.id === linkSlotId)?.slot.status ?? ''
    : ''

  function activeLegInfo(slot: WheelSlotDetail): string {
    const leg = slot.legs.find(l => l.rotation_number === slot.rotation_number && l.trade_status === 'open' && l.leg_role !== 'stock')
    if (!leg) return '—'
    const parts: string[] = []
    if (leg.trade_strike_price != null) parts.push(`$${leg.trade_strike_price}`)
    if (leg.trade_expiry_date) parts.push(`exp ${leg.trade_expiry_date}`)
    if (leg.trade_premium != null) parts.push(`$${leg.trade_premium} prem`)
    return parts.join(' · ') || '—'
  }

  function activeLegSummary(slot: WheelSlotDetail): string | null {
    const leg = slot.legs.find(l => l.rotation_number === slot.rotation_number && l.trade_status === 'open' && l.leg_role !== 'stock')
    if (!leg) return null
    const parts: string[] = []
    if (leg.trade_expiry_date) {
      const [y, m, d] = leg.trade_expiry_date.split('-')
      parts.push(`${parseInt(m)}/${parseInt(d)}/${y.slice(2)}`)
    }
    if (leg.trade_strike_price != null) parts.push(`$${leg.trade_strike_price}`)
    if (leg.leg_role === 'covered_call') parts.push('CC')
    else if (leg.leg_role === 'sold_put') parts.push('SP')
    return parts.length ? parts.join(' ') : null
  }

  function renderPnlCell(slot: WheelSlotDetail) {
    const isActive = slot.status === 'cc_active' || slot.status === 'sold_put_active'
    if (!isActive) return <td className="py-2 pr-3" />

    const priceData = optionPrices[slot.id]
    if (!priceData || priceData === 'loading') {
      return <td className="py-2 pr-3 text-xs text-gray-400 animate-pulse">...</td>
    }
    if (priceData === 'error' || priceData.fetch_status !== 'ok' || priceData.mid == null) {
      return <td className="py-2 pr-3 text-xs text-gray-300">—</td>
    }

    const openLegs = slot.legs.filter(l => l.rotation_number === slot.rotation_number && l.trade_status === 'open' && l.leg_role !== 'stock')
    const leg = openLegs[openLegs.length - 1]
    if (!leg || leg.trade_premium == null) {
      return <td className="py-2 pr-3 text-xs text-gray-300">—</td>
    }

    const premium = Number(leg.trade_premium)
    if (!premium) return <td className="py-2 pr-3 text-xs text-gray-300">—</td>
    const pnlPct = ((premium - priceData.mid) / premium) * 100
    const isProfit = pnlPct >= 0
    return (
      <td className={`py-2 pr-3 text-xs font-medium ${isProfit ? 'text-green-600' : 'text-red-500'}`}>
        {isProfit ? '+' : ''}{pnlPct.toFixed(1)}%
      </td>
    )
  }

  function renderGainLossCell(f: FlatSlot) {
    const { stockCostBasis: costBasis, stockCurrentPrice: currentPrice } = f
    if (costBasis == null || currentPrice == null || !costBasis) {
      return <td className="py-2 pr-3 text-xs text-gray-300">—</td>
    }
    const pct = ((currentPrice - costBasis) / costBasis) * 100
    const isProfit = pct >= 0
    return (
      <td className={`py-2 pr-3 text-xs font-medium ${isProfit ? 'text-green-600' : 'text-red-500'}`}>
        {isProfit ? '+' : ''}{pct.toFixed(1)}%
      </td>
    )
  }

  function renderPriceCell(ticker: string) {
    const q = quotes[ticker]
    if (q === 'loading') return <td className="py-2 pr-3 text-xs text-gray-400 animate-pulse">...</td>
    if (!q || q === 'error') return <td className="py-2 pr-3 text-xs text-gray-300">—</td>
    return <td className="py-2 pr-3 text-xs text-gray-700">${q.price.toFixed(2)}</td>
  }

  function renderChangeCell(ticker: string) {
    const q = quotes[ticker]
    if (q === 'loading') return <td className="py-2 pr-3 text-xs text-gray-400 animate-pulse">...</td>
    if (!q || q === 'error' || q.change_pct == null) return <td className="py-2 pr-3 text-xs text-gray-300">—</td>
    const isProfit = q.change_pct >= 0
    return (
      <td className={`py-2 pr-3 text-xs font-medium ${isProfit ? 'text-green-600' : 'text-red-500'}`}>
        {isProfit ? '+' : ''}{q.change_pct.toFixed(2)}%
      </td>
    )
  }

  function renderRsiCell(ticker: string) {
    const t = technicals[ticker]
    if (t === 'loading') return <td className="py-2 pr-3 text-xs text-gray-400 animate-pulse">...</td>
    if (!t || t === 'error' || t.fetch_status !== 'ok' || t.rsi_14 == null) return <td className="py-2 pr-3 text-xs text-gray-300">—</td>
    return <td className="py-2 pr-3 text-xs text-gray-700">{t.rsi_14.toFixed(1)}</td>
  }

  function renderMacdCell(ticker: string) {
    const t = technicals[ticker]
    if (t === 'loading') return <td className="py-2 pr-3 text-xs text-gray-400 animate-pulse">...</td>
    if (!t || t === 'error' || t.fetch_status !== 'ok') return <td className="py-2 pr-3 text-xs text-gray-300">—</td>
    return (
      <td className="py-2 pr-3">
        <span className={`px-2 py-0.5 rounded text-xs font-medium ${MACD_COLORS[t.macd_signal ?? 'neutral']}`}>
          {t.macd_signal ?? '—'}
        </span>
      </td>
    )
  }

  function renderSignalBadge(ticker: string, sigMap: Record<string, CCSignalResult | 'loading' | 'error'>, type: 'CC' | 'SP' | 'Timing') {
    const sig = sigMap[ticker]
    const detailKey = `${ticker}-${type}`
    if (sig === 'loading') return <span className="text-xs text-gray-400 animate-pulse">...</span>
    if (sig === 'error' || !sig) return <span className="text-xs text-gray-300" title="Signal unavailable">&mdash;</span>
    return (
      <button
        onClick={() => setSignalDetail(signalDetail === detailKey ? null : detailKey)}
        className={`text-xs font-medium px-2 py-0.5 rounded-full border ${GRADE_COLORS[sig.grade] ?? GRADE_COLORS.wait} hover:opacity-80`}
        title={`Score: ${sig.score}`}
      >
        {sig.grade === 'wait' ? 'Wait' : `${sig.grade.charAt(0).toUpperCase() + sig.grade.slice(1)} ${sig.score}`}
      </button>
    )
  }

  function renderSignalDetailRow(ticker: string, colCount = 11) {
    const ccKey = `${ticker}-CC`
    const spKey = `${ticker}-SP`
    const timingKey = `${ticker}-Timing`
    const isCC = signalDetail === ccKey
    const isSP = signalDetail === spKey
    const isTiming = signalDetail === timingKey
    if (!isCC && !isSP && !isTiming) return null
    const sig = isCC ? signals[ticker] : isSP ? spSignals[ticker] : ccTimingSignals[ticker]
    const label = isCC ? 'CC Signal' : isSP ? 'SP Signal' : 'CC Timing'
    if (!sig || sig === 'loading' || sig === 'error') return null

    return (
      <tr key={`${ticker}-signal-detail`}>
        <td colSpan={colCount} className="py-3 px-4 bg-gray-50 border-t border-gray-200">
          <div className="space-y-2 text-xs">
            <p className="font-medium text-gray-500 mb-1">{label} breakdown</p>
            <div className="grid grid-cols-2 gap-x-6 gap-y-1">
              {sig.factors.map(f => (
                <div key={f.name} className="flex justify-between">
                  <span className="text-gray-500">{f.name}</span>
                  <span className="text-gray-700 font-medium">
                    {f.points}/{f.max}{' '}
                    <span className="text-gray-400 font-normal">{f.detail}</span>
                  </span>
                </div>
              ))}
            </div>
            {sig.commentary && (
              <p className="text-gray-700 pt-1 border-t border-gray-200">{sig.commentary}</p>
            )}
            {sig.strike_hint && (
              <p className="text-blue-700">{sig.strike_hint}</p>
            )}
            {sig.caution && (
              <p className="text-amber-700 font-medium">{sig.caution}</p>
            )}
            <p className="text-gray-400">
              IV Pct: {sig.iv_percentile != null ? `${sig.iv_percentile}%` : 'N/A'}
              {sig.atm_iv != null && ` · ATM IV: ${(sig.atm_iv * 100).toFixed(1)}%`}
              {sig.spot_price != null && ` · Spot: $${sig.spot_price}`}
              {' · '}Updated: {new Date(sig.cached_at).toLocaleTimeString()}
            </p>
          </div>
        </td>
      </tr>
    )
  }

  function renderSlotRow(f: FlatSlot) {
    const { slot, ticker } = f
    const isExpanded = expandedSlot === slot.id

    return (
      <tr key={slot.id} className="group">
        <td className="py-2 pr-3">
          <span className="font-bold text-gray-900">{ticker}</span>
          {activeLegSummary(slot) && (
            <div className="text-xs text-gray-400 font-normal leading-tight">{activeLegSummary(slot)}</div>
          )}
        </td>
        <td className="py-2 pr-3 text-gray-500 text-xs">{slot.contracts}x100</td>
        <td className="py-2 pr-3">
          <span className={`text-xs font-medium px-2 py-0.5 rounded-full text-white ${
            slot.status.includes('active') ? 'bg-blue-500' : 'bg-amber-500'
          }`}>
            {STATUS_LABELS[slot.status] ?? slot.status}
          </span>
          {slot.needs_action && (
            <span className="ml-1 text-xs font-medium px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 border border-amber-300">!</span>
          )}
        </td>
        <td className="py-2 pr-3 text-xs text-gray-500">{activeLegInfo(slot)}</td>
        <td className="py-2 pr-3 text-xs text-gray-400">R{slot.rotation_number}</td>
        <td className="py-2 pr-3 text-xs font-medium text-green-600">${slot.total_premium}</td>
        <td className="py-2 pr-3">{renderSignalBadge(ticker, signals, 'CC')}</td>
        <td className="py-2 pr-3">{renderSignalBadge(ticker, spSignals, 'SP')}</td>
        {renderPnlCell(slot)}
        {renderGainLossCell(f)}
        <td className="py-2 text-right">
          <div className="flex items-center gap-1 justify-end">
            {(slot.status === 'cc_active' || slot.status === 'sold_put_active' || slot.needs_action) && (
              <button onClick={() => setResolveSlotId(slot.id)} className="px-2 py-0.5 text-xs bg-amber-100 text-amber-800 rounded hover:bg-amber-200">
                Resolve
              </button>
            )}
            {(slot.status === 'awaiting_cc' || slot.status === 'awaiting_sold_put') && !slot.needs_action && (() => {
              const isUnderwater = slot.status === 'awaiting_cc'
                && f.stockCostBasis != null && f.stockCurrentPrice != null
                && f.stockCurrentPrice < f.stockCostBasis
              const label = slot.status === 'awaiting_cc' ? '+ CC' : '+ Put'
              const className = isUnderwater
                ? 'px-2 py-0.5 text-xs bg-red-100 text-red-800 rounded hover:bg-red-200'
                : 'px-2 py-0.5 text-xs bg-blue-100 text-blue-800 rounded hover:bg-blue-200'
              const title = isUnderwater
                ? `Cost basis $${f.stockCostBasis} above current price $${f.stockCurrentPrice} — selling a CC may lock in a loss.`
                : undefined
              return (
                <button onClick={() => setLinkSlotId(slot.id)} className={className} title={title}>
                  {label}
                </button>
              )
            })()}
            <button
              onClick={() => setExpandedSlot(isExpanded ? null : slot.id)}
              className="px-1.5 py-0.5 text-xs text-gray-400 hover:text-gray-600 rounded hover:bg-gray-100"
              title="Show legs"
            >
              {isExpanded ? '−' : '+'}
            </button>
          </div>
        </td>
      </tr>
    )
  }

  function renderAwaitingCCSlotRow(f: FlatSlot) {
    const { slot, ticker } = f
    const isExpanded = expandedSlot === slot.id

    return (
      <tr key={slot.id} className="group">
        <td className="py-2 pr-3">
          <span className="font-bold text-gray-900">{ticker}</span>
        </td>
        <td className="py-2 pr-3 text-gray-500 text-xs">{slot.contracts}x100</td>
        <td className="py-2 pr-3 text-xs text-gray-400">R{slot.rotation_number}</td>
        <td className="py-2 pr-3 text-xs font-medium text-green-600">${slot.total_premium}</td>
        {renderPriceCell(ticker)}
        {renderChangeCell(ticker)}
        {renderRsiCell(ticker)}
        {renderMacdCell(ticker)}
        <td className="py-2 pr-3">{renderSignalBadge(ticker, signals, 'CC')}</td>
        <td className="py-2 pr-3">{renderSignalBadge(ticker, ccTimingSignals, 'Timing')}</td>
        {renderGainLossCell(f)}
        <td className="py-2 text-right">
          <div className="flex items-center gap-1 justify-end">
            {!slot.needs_action && (() => {
              const isUnderwater = f.stockCostBasis != null && f.stockCurrentPrice != null
                && f.stockCurrentPrice < f.stockCostBasis
              const className = isUnderwater
                ? 'px-2 py-0.5 text-xs bg-red-100 text-red-800 rounded hover:bg-red-200'
                : 'px-2 py-0.5 text-xs bg-blue-100 text-blue-800 rounded hover:bg-blue-200'
              const title = isUnderwater
                ? `Cost basis $${f.stockCostBasis} above current price $${f.stockCurrentPrice} — selling a CC may lock in a loss.`
                : undefined
              return (
                <button onClick={() => setLinkSlotId(slot.id)} className={className} title={title}>
                  + CC
                </button>
              )
            })()}
            <button
              onClick={() => setExpandedSlot(isExpanded ? null : slot.id)}
              className="px-1.5 py-0.5 text-xs text-gray-400 hover:text-gray-600 rounded hover:bg-gray-100"
              title="Show legs"
            >
              {isExpanded ? '−' : '+'}
            </button>
          </div>
        </td>
      </tr>
    )
  }

  function renderSectionFetchControls(key: string, tickers: string[], includeOptionPrices: boolean) {
    const fetching = sectionFetching[key] ?? false
    return (
      <>
        <span className="text-xs text-gray-400">{sectionFetchedLabel(tickers)}</span>
        <button
          onClick={() => fetchSection(key, tickers, includeOptionPrices)}
          disabled={fetching}
          className="px-2 py-0.5 text-xs bg-gray-100 text-gray-700 rounded hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {fetching ? 'Fetching…' : 'Fetch'}
        </button>
      </>
    )
  }

  function renderAwaitingCCSection(slots: FlatSlot[]) {
    if (slots.length === 0) return null
    const tickers = [...new Set(slots.map(f => f.ticker))]
    return (
      <section className="mb-5">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-sm font-bold text-amber-600">AWAITING CC</span>
          <span className="bg-amber-50 text-amber-600 text-xs px-2 py-0.5 rounded-full font-medium">{slots.length}</span>
          {renderSectionFetchControls('awaitingCC', tickers, false)}
        </div>
        <div className="bg-white border border-amber-200 rounded-lg overflow-x-auto">
          <table className="min-w-max w-full text-sm whitespace-nowrap">
            <thead>
              <tr className="text-left text-xs text-gray-400 border-b border-gray-100">
                <th className="py-2 pr-3 pl-3 font-normal">Ticker</th>
                <th className="py-2 pr-3 font-normal">Size</th>
                <th className="py-2 pr-3 font-normal">Rot</th>
                <th className="py-2 pr-3 font-normal">Premium</th>
                <th className="py-2 pr-3 font-normal">Price</th>
                <th className="py-2 pr-3 font-normal">Change%</th>
                <th className="py-2 pr-3 font-normal">RSI(D)</th>
                <th className="py-2 pr-3 font-normal">MACD(W)</th>
                <th className="py-2 pr-3 font-normal">CC Signal</th>
                <th className="py-2 pr-3 font-normal">CC Timing</th>
                <th className="py-2 pr-3 font-normal">% G/L</th>
                <th className="py-2 pr-3 font-normal"></th>
              </tr>
            </thead>
            {slots.map((f, idx) => {
              const isFirstForTicker = slots.findIndex(s => s.ticker === f.ticker) === idx
              return (
                <tbody key={f.slot.id} className="border-t border-gray-50">
                  {renderAwaitingCCSlotRow(f)}
                  {renderLegRows(f, 12)}
                  {isFirstForTicker && renderSignalDetailRow(f.ticker, 12)}
                </tbody>
              )
            })}
          </table>
        </div>
      </section>
    )
  }

  function renderAwaitingSPSlotRow(f: FlatSlot) {
    const { slot, ticker } = f
    const isExpanded = expandedSlot === slot.id

    return (
      <tr key={slot.id} className="group">
        <td className="py-2 pr-3">
          <span className="font-bold text-gray-900">{ticker}</span>
        </td>
        <td className="py-2 pr-3 text-gray-500 text-xs">{slot.contracts}x100</td>
        <td className="py-2 pr-3 text-xs text-gray-400">R{slot.rotation_number}</td>
        <td className="py-2 pr-3 text-xs font-medium text-green-600">${slot.total_premium}</td>
        {renderPriceCell(ticker)}
        {renderChangeCell(ticker)}
        {renderRsiCell(ticker)}
        {renderMacdCell(ticker)}
        <td className="py-2 pr-3">{renderSignalBadge(ticker, spSignals, 'SP')}</td>
        {renderGainLossCell(f)}
        <td className="py-2 text-right">
          <div className="flex items-center gap-1 justify-end">
            {!slot.needs_action && (
              <button onClick={() => setLinkSlotId(slot.id)} className="px-2 py-0.5 text-xs bg-blue-100 text-blue-800 rounded hover:bg-blue-200">
                + Put
              </button>
            )}
            <button
              onClick={() => setExpandedSlot(isExpanded ? null : slot.id)}
              className="px-1.5 py-0.5 text-xs text-gray-400 hover:text-gray-600 rounded hover:bg-gray-100"
              title="Show legs"
            >
              {isExpanded ? '−' : '+'}
            </button>
          </div>
        </td>
      </tr>
    )
  }

  function renderAwaitingSPSection(slots: FlatSlot[]) {
    if (slots.length === 0) return null
    const tickers = [...new Set(slots.map(f => f.ticker))]
    return (
      <section className="mb-5">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-sm font-bold text-orange-600">AWAITING SOLD PUT</span>
          <span className="bg-orange-50 text-orange-600 text-xs px-2 py-0.5 rounded-full font-medium">{slots.length}</span>
          {renderSectionFetchControls('awaitingSP', tickers, false)}
        </div>
        <div className="bg-white border border-orange-200 rounded-lg overflow-x-auto">
          <table className="min-w-max w-full text-sm whitespace-nowrap">
            <thead>
              <tr className="text-left text-xs text-gray-400 border-b border-gray-100">
                <th className="py-2 pr-3 pl-3 font-normal">Ticker</th>
                <th className="py-2 pr-3 font-normal">Size</th>
                <th className="py-2 pr-3 font-normal">Rot</th>
                <th className="py-2 pr-3 font-normal">Premium</th>
                <th className="py-2 pr-3 font-normal">Price</th>
                <th className="py-2 pr-3 font-normal">Change%</th>
                <th className="py-2 pr-3 font-normal">RSI(D)</th>
                <th className="py-2 pr-3 font-normal">MACD(W)</th>
                <th className="py-2 pr-3 font-normal">SP Signal</th>
                <th className="py-2 pr-3 font-normal">% G/L</th>
                <th className="py-2 pr-3 font-normal"></th>
              </tr>
            </thead>
            {slots.map((f, idx) => {
              const isFirstForTicker = slots.findIndex(s => s.ticker === f.ticker) === idx
              return (
                <tbody key={f.slot.id} className="border-t border-gray-50">
                  {renderAwaitingSPSlotRow(f)}
                  {renderLegRows(f, 11)}
                  {isFirstForTicker && renderSignalDetailRow(f.ticker, 11)}
                </tbody>
              )
            })}
          </table>
        </div>
      </section>
    )
  }

  function renderLegRows(f: FlatSlot, colCount = 11) {
    if (expandedSlot !== f.slot.id) return null
    const currentLegs = f.slot.legs.filter(l => l.rotation_number === f.slot.rotation_number)
    if (currentLegs.length === 0) {
      return (
        <tr key={`${f.slot.id}-legs`}>
          <td colSpan={colCount} className="py-1 pl-8 text-xs text-gray-400 italic">No legs in current rotation.</td>
        </tr>
      )
    }
    return currentLegs.map(leg => (
      <tr key={leg.id} className="bg-gray-50">
        <td className="py-1 pl-8 text-xs text-gray-400 capitalize">{leg.leg_role.replace('_', ' ')}</td>
        <td className="py-1 pr-3 text-xs text-gray-500">{leg.trade_strategy}</td>
        <td className="py-1 pr-3 text-xs text-gray-500">{leg.trade_strike_price != null ? `$${leg.trade_strike_price}` : '—'}</td>
        <td className="py-1 pr-3 text-xs text-gray-500">
          {leg.trade_expiry_date ?? '—'}{leg.trade_premium != null ? ` · $${leg.trade_premium}` : ''}
        </td>
        <td className="py-1 pr-3 text-xs text-gray-400 capitalize">{leg.trade_status}</td>
        <td colSpan={colCount - 5} className="py-1 text-xs text-right">
          <Link to={`/trades/${leg.trade_id}`} className="text-blue-500 hover:underline">view</Link>
        </td>
      </tr>
    ))
  }

  function renderSection(title: string, color: string, bgColor: string, borderColor: string, slots: FlatSlot[], fetchKey?: string) {
    if (slots.length === 0) return null
    const tickers = [...new Set(slots.map(f => f.ticker))]
    return (
      <section className="mb-5">
        <div className="flex items-center gap-2 mb-2">
          <span className={`text-sm font-bold ${color}`}>{title}</span>
          <span className={`${bgColor} ${color} text-xs px-2 py-0.5 rounded-full font-medium`}>{slots.length}</span>
          {fetchKey && renderSectionFetchControls(fetchKey, tickers, true)}
        </div>
        <div className={`bg-white border ${borderColor} rounded-lg overflow-x-auto`}>
          <table className="min-w-max w-full text-sm whitespace-nowrap">
            <thead>
              <tr className="text-left text-xs text-gray-400 border-b border-gray-100">
                <th className="py-2 pr-3 pl-3 font-normal">Ticker</th>
                <th className="py-2 pr-3 font-normal">Size</th>
                <th className="py-2 pr-3 font-normal">Status</th>
                <th className="py-2 pr-3 font-normal">Active Leg</th>
                <th className="py-2 pr-3 font-normal">Rot</th>
                <th className="py-2 pr-3 font-normal">Premium</th>
                <th className="py-2 pr-3 font-normal">CC Signal</th>
                <th className="py-2 pr-3 font-normal">SP Signal</th>
                <th className="py-2 pr-3 font-normal">P&L %</th>
                <th className="py-2 pr-3 font-normal">% G/L</th>
                <th className="py-2 pr-3 font-normal"></th>
              </tr>
            </thead>
            {slots.map((f, idx) => {
              const isFirstForTicker = slots.findIndex(s => s.ticker === f.ticker) === idx
              return (
                <tbody key={f.slot.id} className="border-t border-gray-50">
                  {renderSlotRow(f)}
                  {renderLegRows(f)}
                  {isFirstForTicker && renderSignalDetailRow(f.ticker)}
                </tbody>
              )
            })}
          </table>
        </div>
      </section>
    )
  }

  return (
    <div className="p-6 max-w-screen-2xl mx-auto">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold text-gray-900">WHEEL Strategy</h1>
        <div className="flex gap-2">
          <button
            onClick={fetchAllSignals}
            disabled={signalsFetching || sessions.length === 0}
            className="px-4 py-2 bg-gray-100 text-gray-700 rounded text-sm hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {signalsFetching ? 'Fetching…' : 'Fetch Signals'}
          </button>
          <button onClick={() => setShowNewModal(true)} className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700">
            + New Wheel
          </button>
        </div>
      </div>

      {loading && <p className="text-gray-500 text-center py-12">Loading...</p>}
      {error && <div className="bg-red-50 border border-red-200 text-red-700 rounded p-4 mb-4 text-sm">{error}</div>}

      {!loading && !error && sessions.length === 0 && (
        <div className="text-center py-16">
          <p className="text-gray-400 mb-4">No wheels yet.</p>
          <button onClick={() => setShowNewModal(true)} className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700">
            + New Wheel
          </button>
        </div>
      )}

      {!loading && !error && sessions.length > 0 && (
        <>
          {emptyWheels.length > 0 && (
            <section className="mb-5">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-sm font-bold text-purple-600">NEW — NEEDS SLOT</span>
                <span className="bg-purple-50 text-purple-600 text-xs px-2 py-0.5 rounded-full font-medium">{emptyWheels.length}</span>
              </div>
              <div className="bg-white border border-purple-200 rounded-lg overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-gray-400 border-b border-gray-100">
                      <th className="py-2 pr-3 pl-3 font-normal">Ticker</th>
                      <th className="py-2 pr-3 font-normal">Shares</th>
                      <th className="py-2 pr-3 font-normal">Created</th>
                      <th className="py-2 pr-3 font-normal"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {emptyWheels.map(s => (
                      <tr key={s.id} className="border-t border-gray-50">
                        <td className="py-2 pr-3 pl-3 font-bold text-gray-900">{s.ticker}</td>
                        <td className="py-2 pr-3 text-gray-500 text-xs">{s.total_shares}</td>
                        <td className="py-2 pr-3 text-gray-400 text-xs">{s.opened_at}</td>
                        <td className="py-2 text-right">
                          <button
                            onClick={() => setAddSlotSessionId(s.id)}
                            className="px-2 py-0.5 text-xs bg-purple-100 text-purple-800 rounded hover:bg-purple-200"
                          >
                            + Add Slot
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
          {renderSection('NEEDS ACTION', 'text-amber-600', 'bg-amber-100', 'border-amber-300', needsAction)}
          {renderAwaitingCCSection(awaitingCC)}
          {renderAwaitingSPSection(awaitingSP)}
          {renderSection('ACTIVE', 'text-blue-600', 'bg-blue-50', 'border-blue-200', active, 'active')}
        </>
      )}

      {showNewModal && <NewWheelModalV2 onClose={() => setShowNewModal(false)} onCreated={(s) => { setShowNewModal(false); setAddSlotSessionId(s.id); load() }} />}
      {addSlotSessionId && <AddSlotModal sessionId={addSlotSessionId} onClose={() => setAddSlotSessionId(null)} onCreated={() => { setAddSlotSessionId(null); load() }} />}
      {resolveSlotId && <ResolveModal slotId={resolveSlotId} ticker={resolveSlotTicker} onClose={() => setResolveSlotId(null)} onResolved={() => { setResolveSlotId(null); load() }} />}
      {linkSlotId && <LinkLegModalV2 slotId={linkSlotId} ticker={linkSlotTicker} slotStatus={linkSlotStatus} onClose={() => setLinkSlotId(null)} onLinked={() => { setLinkSlotId(null); load() }} />}
    </div>
  )
}
