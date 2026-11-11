// frontend/src/hooks/useMarketDataOffline.ts
import { useSyncExternalStore } from 'react'
import { getMarketDataOffline, subscribeMarketDataOffline } from '../api/client'

/** True while the last market-aware response said market data is offline. */
export function useMarketDataOffline(): boolean {
  return useSyncExternalStore(subscribeMarketDataOffline, getMarketDataOffline, getMarketDataOffline)
}
