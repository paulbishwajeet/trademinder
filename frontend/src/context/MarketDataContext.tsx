// frontend/src/context/MarketDataContext.tsx
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { marketDataApi, type MarketDataStatus } from '../api/marketData'
import { useAuth } from './AuthContext'

const POLL_MS = 15 * 60 * 1000

interface MarketDataState {
  /** Provider status; null for non-admin users or before the first load. */
  status: MarketDataStatus | null
}

const MarketDataContext = createContext<MarketDataState>({ status: null })

/** For admin users only: loads the market data status at app start and every 15 minutes. */
export function MarketDataProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<MarketDataStatus | null>(null)
  const isAdmin = useAuth().user?.role === 'admin'

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

  return <MarketDataContext.Provider value={{ status }}>{children}</MarketDataContext.Provider>
}

export function useMarketDataStatus(): MarketDataStatus | null {
  return useContext(MarketDataContext).status
}
