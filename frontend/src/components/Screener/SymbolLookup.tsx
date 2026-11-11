import { useState } from 'react'
import { screenerApi } from '../../api/screener'
import { ApiError } from '../../api/client'
import { useAccounts, useCurrentAccount } from '../../context/AccountsContext'
import type { ScreenerFetchedFields, ScreenerPreview, ScreenerRow } from '../../types'
import { AccountMultiSelect } from './AccountPicker'
import { addToAccounts, summarizeAdd } from './addToAccounts'

interface Props {
  /** The rows the page has loaded — used to tell which accounts already hold the symbol. */
  rows: ScreenerRow[]
  onAdded: (row: ScreenerRow) => void
}

export function SymbolLookup({ rows, onAdded }: Props) {
  const [ticker, setTicker] = useState('')
  const [loading, setLoading] = useState(false)
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<ScreenerPreview | null>(null)
  const account = useCurrentAccount()
  const { active, accounts, defaultAccount } = useAccounts()
  const [picked, setPicked] = useState<string[] | null>(null)

  // preview.already_tracked means "tracked in some account"; membership per account comes from the loaded rows.
  const memberIds = preview ? rows.find(r => r.symbol === preview.symbol)?.account_ids ?? [] : []
  const inThisAccount = account ? memberIds.includes(account.id) : false
  const inEveryAccount = !account && active.length > 0 && active.every(a => memberIds.includes(a.id))
  const defaultSelection = defaultAccount && !memberIds.includes(defaultAccount.id) ? [defaultAccount.id] : []
  const selected = (picked ?? defaultSelection).filter(id => !memberIds.includes(id))
  const nameOf = (id: string) => accounts.find(a => a.id === id)?.nickname ?? 'Unknown'

  const handleFetch = async () => {
    if (!ticker.trim()) return
    setLoading(true)
    setError(null)
    setPreview(null)
    setPicked(null)
    try {
      const data = await screenerApi.preview(ticker.trim().toUpperCase())
      setPreview(data)
      if (data.fetch_status === 'error') {
        setError(data.fetch_error ?? 'Fetch failed')
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Lookup failed')
    } finally {
      setLoading(false)
    }
  }

  const handleAdd = async () => {
    if (!preview) return
    setAdding(true)
    setError(null)
    try {
      const precomputed: ScreenerFetchedFields = {
        sector: preview.sector,
        price: preview.price,
        prev_close: preview.prev_close,
        change_pct: preview.change_pct,
        iv_rank: preview.iv_rank,
        iv_percentile: preview.iv_percentile,
        rsi_14: preview.rsi_14,
        macd_weekly_signal: preview.macd_weekly_signal,
        macd_daily_signal: preview.macd_daily_signal,
        ma_20d: preview.ma_20d,
        ma_50d: preview.ma_50d,
        ma_100d: preview.ma_100d,
        ma_200d: preview.ma_200d,
        bollinger_upper: preview.bollinger_upper,
        bollinger_mid: preview.bollinger_mid,
        bollinger_lower: preview.bollinger_lower,
        bollinger_position: preview.bollinger_position,
        next_earnings_date: preview.next_earnings_date,
        volume_spikes: preview.volume_spikes,
        fetch_status: preview.fetch_status,
        fetch_error: preview.fetch_error,
      }
      if (account) {
        onAdded(await screenerApi.add({ symbol: preview.symbol, precomputed, account_id: account.id }))
      } else {
        // First successful add carries precomputed; later accounts just gain a membership.
        const res = await addToAccounts({ symbol: preview.symbol, precomputed }, selected)
        if (res.row) onAdded(res.row)
        if (res.failed.length || !res.row) {
          setError(summarizeAdd(res, nameOf))
          return
        }
      }
      setPreview(null)
      setTicker('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to add symbol')
    } finally {
      setAdding(false)
    }
  }

  return (
    <div className="mb-6 p-3 border border-gray-200 rounded bg-white">
      <div className="text-xs font-semibold text-gray-600 mb-2">Quick Lookup</div>
      <div className="flex items-end gap-2">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Symbol</label>
          <input
            value={ticker}
            onChange={e => setTicker(e.target.value)}
            placeholder="TSLA"
            className="border border-gray-300 rounded px-2 py-1 text-sm w-28"
          />
        </div>
        <button
          onClick={handleFetch}
          disabled={loading || !ticker.trim()}
          className="px-3 py-1.5 bg-gray-700 text-white text-sm rounded hover:bg-gray-800 disabled:bg-gray-300"
        >
          {loading ? 'Fetching…' : 'Fetch'}
        </button>
      </div>
      {error && <p className="text-red-500 text-xs mt-2">{error}</p>}
      {preview && preview.fetch_status !== 'error' && (
        <div className="mt-3 text-xs grid grid-cols-4 gap-x-4 gap-y-1 border-t border-gray-100 pt-2">
          <div><span className="text-gray-400">Price: </span>{preview.price ?? '—'}</div>
          <div><span className="text-gray-400">Change%: </span>{preview.change_pct ?? '—'}</div>
          <div><span className="text-gray-400">IV Pctl: </span>{preview.iv_percentile ?? '—'}</div>
          <div><span className="text-gray-400">RSI(d): </span>{preview.rsi_14 ?? '—'}</div>
          <div><span className="text-gray-400">MACD(w): </span>{preview.macd_weekly_signal ?? '—'}</div>
          <div><span className="text-gray-400">20ma: </span>{preview.ma_20d ?? '—'}</div>
          <div><span className="text-gray-400">50ma: </span>{preview.ma_50d ?? '—'}</div>
          <div><span className="text-gray-400">100ma: </span>{preview.ma_100d ?? '—'}</div>
          <div><span className="text-gray-400">200ma: </span>{preview.ma_200d ?? '—'}</div>
          <div><span className="text-gray-400">BB: </span>{preview.bollinger_position ?? '—'}</div>
          <div className="col-span-4 mt-2">
            {inThisAccount ? (
              <span className="text-gray-400 italic">Already tracked in this account's screener.</span>
            ) : inEveryAccount ? (
              <span className="text-gray-400 italic">Already tracked in every account.</span>
            ) : (
              <div className="space-y-2">
                {!account && (
                  <AccountMultiSelect selected={selected} onChange={setPicked} disabledIds={memberIds} />
                )}
                <button
                  onClick={handleAdd}
                  disabled={adding || (!account && selected.length === 0)}
                  className="px-3 py-1.5 bg-blue-600 text-white text-xs rounded hover:bg-blue-700 disabled:bg-gray-300"
                >
                  {adding ? 'Adding…' : 'Add to Screener'}
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
