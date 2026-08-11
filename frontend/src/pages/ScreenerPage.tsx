import { useCallback, useEffect, useRef, useState } from 'react'
import { screenerApi } from '../api/screener'
import type { ScreenerRow } from '../types'
import { AddSymbolForm } from '../components/Screener/AddSymbolForm'
import { SymbolLookup } from '../components/Screener/SymbolLookup'
import { ScreenerTable } from '../components/Screener/ScreenerTable'

export function ScreenerPage() {
  const [rows, setRows] = useState<ScreenerRow[]>([])
  const [loading, setLoading] = useState(true)
  const [fetchingAll, setFetchingAll] = useState(false)
  const [jobProgress, setJobProgress] = useState<{ completed: number; total: number } | null>(null)
  const [pollError, setPollError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const loadRows = useCallback(async () => {
    setLoading(true)
    try {
      const data = await screenerApi.list()
      setRows(data)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadRows()
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [loadRows])

  const handleAdded = (row: ScreenerRow) => {
    setRows(prev =>
      [...prev.filter(r => r.symbol !== row.symbol), row].sort((a, b) => a.symbol.localeCompare(b.symbol))
    )
  }

  const handleRefreshRow = (row: ScreenerRow) => {
    setRows(prev => prev.map(r => (r.symbol === row.symbol ? row : r)))
  }

  const handleRemove = async (symbol: string) => {
    if (!confirm(`Remove ${symbol} from the screener?`)) return
    await screenerApi.remove(symbol)
    setRows(prev => prev.filter(r => r.symbol !== symbol))
  }

  const handleFetchAll = async () => {
    setFetchingAll(true)
    setPollError(null)
    const job = await screenerApi.fetchAll()
    setJobProgress({ completed: job.completed, total: job.total })
    pollRef.current = setInterval(async () => {
      try {
        const status = await screenerApi.getJobStatus(job.job_id)
        setJobProgress({ completed: status.completed, total: status.total })
        if (status.status === 'done') {
          if (pollRef.current) clearInterval(pollRef.current)
          setFetchingAll(false)
          setJobProgress(null)
          loadRows()
        }
      } catch {
        if (pollRef.current) clearInterval(pollRef.current)
        setFetchingAll(false)
        setJobProgress(null)
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
      <SymbolLookup onAdded={handleAdded} />
      <AddSymbolForm onAdded={handleAdded} />
      {loading ? (
        <p className="text-gray-400 text-sm">Loading…</p>
      ) : (
        <ScreenerTable rows={rows} onRefreshRow={handleRefreshRow} onRemove={handleRemove} />
      )}
    </div>
  )
}
