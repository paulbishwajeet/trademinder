import { apiFetch } from './client'

export interface ScanParams {
  type?: 'calls' | 'puts' | 'both'
  min_dte?: number
  min_oi?: number
  max_delta?: number
}

export interface OptionRow {
  type: 'call' | 'put'
  strike: number
  expiration: string
  dte: number
  bid: number
  ask: number
  mid: number
  iv: number
  iv_fitted: number
  iv_excess: number
  delta: number
  ann_yield_pct: number
  open_interest: number
  earnings_count: number
}

export interface ScanResult {
  ticker: string
  spot: number
  scan_ts: string
  lt_close_date: string
  earnings_dates: string[]
  options: OptionRow[]
}

export async function scanOptions(
  ticker: string,
  params: ScanParams = {},
): Promise<ScanResult> {
  const query = new URLSearchParams()
  if (params.type) query.set('type', params.type)
  if (params.min_dte !== undefined) query.set('min_dte', String(params.min_dte))
  if (params.min_oi !== undefined) query.set('min_oi', String(params.min_oi))
  if (params.max_delta !== undefined) query.set('max_delta', String(params.max_delta))
  const qs = query.toString()
  return apiFetch<ScanResult>(
    `/market/options/${encodeURIComponent(ticker)}${qs ? `?${qs}` : ''}`,
  )
}
