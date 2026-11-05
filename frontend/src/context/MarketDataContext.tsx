// frontend/src/context/MarketDataContext.tsx
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { marketDataApi, type MarketDataStatus } from '../api/marketData'

const POLL_MS = 15 * 60 * 1000

interface MarketDataState {
  /** Provider status; null for non-admin users or before the first load. */
  status: MarketDataStatus | null
}

const MarketDataContext = createContext<MarketDataState>({ status: null })

/** For admin users: loads the market data status at app start and every 15 minutes. */
export function MarketDataProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<MarketDataStatus | null>(null)

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setInterval> | undefined

    const load = async () => {
      try {
        const next = await marketDataApi.status()
        if (!cancelled) setStatus(next)
      } catch {
        // Status unavailable (backend down): keep the last known value rather than guessing.
      }
    }

    void (async () => {
      try {
        const me = await marketDataApi.me()
        if (cancelled || me.role !== 'admin') return
      } catch {
        return
      }
      await load()
      timer = setInterval(() => { void load() }, POLL_MS)
    })()

    return () => {
      cancelled = true
      if (timer) clearInterval(timer)
    }
  }, [])

  return <MarketDataContext.Provider value={{ status }}>{children}</MarketDataContext.Provider>
}

export function useMarketDataStatus(): MarketDataStatus | null {
  return useContext(MarketDataContext).status
}
