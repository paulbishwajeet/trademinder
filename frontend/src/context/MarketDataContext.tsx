// frontend/src/context/MarketDataContext.tsx
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { marketDataApi, type MarketDataStatus } from '../api/marketData'
import { useAuth } from './AuthContext'

const POLL_MS = 15 * 60 * 1000

interface MarketDataState {
  /** Provider status; null for non-admin users or before the first load. */
  status: MarketDataStatus | null
  /** Reload the status now (admins only; a no-op otherwise). */
  refresh: () => Promise<void>
  /** Use a status the server just returned (e.g. after a Schwab reconnect) without another request. */
  apply: (status: MarketDataStatus) => void
}

const MarketDataContext = createContext<MarketDataState>({
  status: null,
  refresh: async () => {},
  apply: () => {},
})

/** For admin users only: loads the market data status at app start and every 15 minutes. */
export function MarketDataProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<MarketDataStatus | null>(null)
  const isAdmin = useAuth().user?.role === 'admin'

  const refresh = useCallback(async () => {
    if (!isAdmin) return
    try {
      setStatus(await marketDataApi.status())
    } catch {
      // Status unavailable (backend down): keep the last known value rather than guessing.
    }
  }, [isAdmin])

  useEffect(() => {
    if (!isAdmin) {
      setStatus(null)
      return
    }
    let cancelled = false
    const load = async () => {
      try {
        const next = await marketDataApi.status()
        if (!cancelled) setStatus(next)
      } catch {
        // Status unavailable (backend down): keep the last known value rather than guessing.
      }
    }
    void load()
    const timer = setInterval(() => { void load() }, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [isAdmin])

  const value = useMemo(() => ({ status, refresh, apply: setStatus }), [status, refresh])
  return <MarketDataContext.Provider value={value}>{children}</MarketDataContext.Provider>
}

/** status (null for non-admins) plus refresh / apply (the reconnect dialog, Settings → Market data). */
export function useMarketData(): MarketDataState {
  return useContext(MarketDataContext)
}
