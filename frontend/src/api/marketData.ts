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

export interface ReconnectStart {
  authorize_url: string
  /** The reconnect link (its state) is valid until then: 10 minutes. */
  state_expires_at: string
}

/** Structured error codes from the reconnect endpoints (ApiError.code); ApiError.message is ready to show. */
export type ReconnectErrorCode =
  | 'not_configured' | 'bad_url' | 'authorization_denied' | 'missing_code' | 'missing_state'
  | 'state_invalid' | 'state_expired' | 'code_expired' | 'schwab_unreachable'

export const marketDataApi = {
  // All admin only (403 otherwise).
  status: () => apiFetch<MarketDataStatus>('/market-data/status'),
  reconnectStart: () => apiFetch<ReconnectStart>('/market-data/reconnect/start', { method: 'POST' }),
  /** Returns the new status (same shape as status()). */
  reconnectComplete: (redirectUrl: string) =>
    apiFetch<MarketDataStatus>('/market-data/reconnect/complete', {
      method: 'POST',
      body: JSON.stringify({ redirect_url: redirectUrl }),
    }),
}
