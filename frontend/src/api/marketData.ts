// frontend/src/api/marketData.ts
import { apiFetch } from './client'

export type MarketDataState = 'ok' | 'expiring' | 'critical' | 'offline'

export interface MarketDataStatus {
  provider: string
  state: MarketDataState
  refresh_expires_at: string | null
  hours_remaining: number | null
  last_success_at: string | null
  last_error: string | null
}

export interface CurrentUser {
  id: string
  email: string
  display_name: string | null
  role: 'admin' | 'user'
}

export const marketDataApi = {
  // Admin only (403 otherwise).
  status: () => apiFetch<MarketDataStatus>('/market-data/status'),
  me: () => apiFetch<CurrentUser>('/me'),
}
