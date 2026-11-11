import { useCallback, useEffect, useRef, useState } from 'react'
import { screenerApi } from '../api/screener'
import type { ScreenerRow } from '../types'
import { AddSymbolForm } from '../components/Screener/AddSymbolForm'
import { SymbolLookup } from '../components/Screener/SymbolLookup'
import { ScreenerTable } from '../components/Screener/ScreenerTable'
import { useCurrentAccount } from '../context/AccountsContext'

export function ScreenerPage() {
  // Inside an account: that account's symbols only. Research (null): every symbol the user tracks.
  const account = useCurrentAccount()
  const accountId = account?.id
  const [rows, setRows] = useState<ScreenerRow[]>([])
  const [loading, setLoading] = useState(true)
  const [fetchingAll, setFetchingAll] = useState(false)
  const [fetchAllStartedAt, setFetchAllStartedAt] = useState<string | null>(null)
  const [jobProgress, setJobProgress] = useState<{ completed: number; total: number } | null>(null)
  const [pollError, setPollError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const loadRows = useCallback(async () => {
    setLoading(true)
    try {
      const data = await screenerApi.list(accountId)
      setRows(data)
    } finally {
      setLoading(false)
    }
  }, [accountId])

  // Same fetch as loadRows, but doesn't toggle the page-level loading flag —
  // used during Fetch All polling so the table doesn't flicker/unmount every 2s.
  const refreshRowsQuiet = useCallback(async () => {
    const data = await screenerApi.list(accountId)
    setRows(data)
  }, [accountId])

  useEffect(() => {
    loadRows()
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [loadRows])

  const handleAdded = (row: ScreenerRow) => {
    setRows(prev => {
      // Union memberships — an add response may only reflect the accounts touched so far.
      const existing = prev.find(r => r.symbol === row.symbol)
      const merged = existing
        ? { ...row, account_ids: [...new Set([...existing.account_ids, ...row.account_ids])] }
        : row
      return [...prev.filter(r => r.symbol !== row.symbol), merged].sort((a, b) => a.symbol.localeCompare(b.symbol))
    })
  }

  const handleRefreshRow = (row: ScreenerRow) => {
    setRows(prev => prev.map(r => (r.symbol === row.symbol ? row : r)))
  }

  const handleRemove = async (symbol: string) => {
    if (account) {
      // Removes only this account's membership.
      if (!confirm(`Remove ${symbol} from ${account.nickname}'s screener?`)) return
      await screenerApi.remove(symbol, account.id)
    } else {
      const n = rows.find(r => r.symbol === symbol)?.account_ids.length ?? 0
      if (!confirm(`Remove ${symbol} from all ${n} account${n === 1 ? '' : 's'}? This deletes it from every account's screener.`)) return
      await screenerApi.remove(symbol)
    }
    setRows(prev => prev.filter(r => r.symbol !== symbol))
  }

  const handleFetchAll = async () => {
    setFetchingAll(true)
    setFetchAllStartedAt(new Date().toISOString())
    setPollError(null)
    const job = await screenerApi.fetchAll()
    setJobProgress({ completed: job.completed, total: job.total })
    pollRef.current = setInterval(async () => {
      try {
        const status = await screenerApi.getJobStatus(job.job_id)
        setJobProgress({ completed: status.completed, total: status.total })
        await refreshRowsQuiet()
        if (status.status === 'done') {
          if (pollRef.current) clearInterval(pollRef.current)
          setFetchingAll(false)
          setJobProgress(null)
          setFetchAllStartedAt(null)
        }
      } catch {
        if (pollRef.current) clearInterval(pollRef.current)
        setFetchingAll(false)
        setJobProgress(null)
        setFetchAllStartedAt(null)
        setPollError('Lost connection to fetch-all job. Please try again.')
      }
    }, 2000)
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-lg font-semibold text-gray-800">Screener</h1>
        <button
          onClick={handleFetchAll}
          disabled={fetchingAll || rows.length === 0}
          className="px-3 py-1.5 bg-gray-700 text-white text-sm rounded hover:bg-gray-800 disabled:bg-gray-300"
        >
          {fetchingAll ? `Fetching ${jobProgress?.completed ?? 0}/${jobProgress?.total ?? 0}…` : 'Fetch All'}
        </button>
      </div>
      {pollError && <p className="text-red-600 text-sm mb-3">{pollError}</p>}
      <SymbolLookup rows={rows} onAdded={handleAdded} />
      <AddSymbolForm onAdded={handleAdded} />
      {loading ? (
        <p className="text-gray-400 text-sm">Loading…</p>
      ) : (
        <ScreenerTable
          rows={rows}
          onRefreshRow={handleRefreshRow}
          onRemove={handleRemove}
          bulkFetching={fetchingAll}
          fetchAllStartedAt={fetchAllStartedAt}
        />
      )}
    </div>
  )
}
