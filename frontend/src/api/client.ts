// frontend/src/api/client.ts
const BASE_URL = '/api'

export class ApiError extends Error {
  status: number
  /** Structured error code from the backend, e.g. 'market_data_offline' (HTTP 503). */
  code: string | null
  /** Request fields the error is about, when the backend names them (e.g. account-fact rules). */
  fields: string[]
  constructor(status: number, message: string, code: string | null = null, fields: string[] = []) {
    super(message)
    this.status = status
    this.code = code
    this.fields = fields
  }
}

export const MARKET_DATA_OFFLINE = 'market_data_offline'

/** True for the 503 a pure market endpoint returns while market data is offline. */
export function isMarketDataOffline(err: unknown): boolean {
  return err instanceof ApiError && err.code === MARKET_DATA_OFFLINE
}

/** Response-level flag set by endpoints that mix database rows with live market fields. */
export interface MarketDataFlag {
  market_data_offline?: boolean
}

// ── Market data offline state, learned from responses ──────────────────────
// Mixed endpoints send `X-Market-Data-Offline: true|false`; pure market endpoints answer 503 with
// code 'market_data_offline'. Components read the latest value via useMarketDataOffline().
export const MARKET_DATA_HEADER = 'X-Market-Data-Offline'
let marketDataOffline = false
const offlineListeners = new Set<() => void>()

export function setMarketDataOffline(value: boolean) {
  if (value === marketDataOffline) return
  marketDataOffline = value
  offlineListeners.forEach(fn => fn())
}

export function getMarketDataOffline(): boolean {
  return marketDataOffline
}

export function subscribeMarketDataOffline(fn: () => void): () => void {
  offlineListeners.add(fn)
  return () => { offlineListeners.delete(fn) }
}

// ── 401 handling ──────────────────────────────────────────────────────────
// AuthContext registers a handler; any 401 from the API (session expired, logged out elsewhere,
// user disabled) sends the app back to Sign in.
let onUnauthorized: (() => void) | null = null

export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler
}

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const flag = response.headers.get(MARKET_DATA_HEADER)
  if (flag !== null) setMarketDataOffline(flag === 'true')
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: 'Unknown error' }))
    const detail = typeof body.detail === 'string' ? body.detail : 'Request failed'
    const code = typeof body.code === 'string' ? body.code : null
    const fields = Array.isArray(body.fields) ? body.fields.filter((f: unknown): f is string => typeof f === 'string') : []
    if (code === MARKET_DATA_OFFLINE) setMarketDataOffline(true)
    if (response.status === 401) onUnauthorized?.()
    throw new ApiError(response.status, detail, code, fields)
  }
  if (response.status === 204) return undefined as T
  return response.json()
}
