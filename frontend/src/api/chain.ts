// frontend/src/api/chain.ts
import { apiFetch } from './client'

export interface ChainFactor {
  name: string
  points: number
  max: number
  detail: string
}

export interface ChainCandidate {
  strike: number
  delta: number
  last: number
  bid: number
  ask: number
  spread_pct: number
  volume: number
  open_interest: number
  arr_pct: number
  breakeven: number
  downside_cushion_pct: number
  capital_required: number
  score: number
  factors: ChainFactor[]
}

export interface ChainExpiry {
  expiration_date: string
  dte: number
  day_of_week: string
  earnings_in_window: boolean
  earnings_date: string | null
  candidates: ChainCandidate[]
}

export interface SpTimingSignalSummary {
  ticker: string
  score: number
  grade: string
  iv_percentile: number | null
  atm_iv: number | null
  spot_price: number | null
  factors: ChainFactor[]
  commentary: string | null
  strike_hint: string | null
  caution: string | null
  cached_at: string
  fetch_status: string
  fetch_error: string | null
}

export interface ChainScreenResult {
  ticker: string
  spot: number | null
  strategy: string
  sp_timing_signal: SpTimingSignalSummary | null
  iv_percentile: number | null
  fetched_at: string
  expiries: ChainExpiry[]
}

export interface ChainScreenParams {
  strategy: string
  num_expiries?: number
  candidates_per_expiry?: number
  target_delta?: number
  delta_tolerance?: number
  min_arr_pct?: number
  min_volume?: number
  min_oi?: number
}

export async function screenChain(ticker: string, params: ChainScreenParams): Promise<ChainScreenResult> {
  const query = new URLSearchParams()
  query.set('strategy', params.strategy)
  if (params.num_expiries != null) query.set('num_expiries', String(params.num_expiries))
  if (params.candidates_per_expiry != null) query.set('candidates_per_expiry', String(params.candidates_per_expiry))
  if (params.target_delta != null) query.set('target_delta', String(params.target_delta))
  if (params.delta_tolerance != null) query.set('delta_tolerance', String(params.delta_tolerance))
  if (params.min_arr_pct != null) query.set('min_arr_pct', String(params.min_arr_pct))
  if (params.min_volume != null) query.set('min_volume', String(params.min_volume))
  if (params.min_oi != null) query.set('min_oi', String(params.min_oi))
  return apiFetch<ChainScreenResult>(`/chain/${encodeURIComponent(ticker)}?${query.toString()}`)
}
