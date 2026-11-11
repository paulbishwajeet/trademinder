// frontend/src/api/technicals.ts
import { apiFetch } from './client'
import type { TechnicalsData } from '../types'

export interface QuoteData {
  ticker: string
  price: number
  change_pct: number | null
  last_updated: string
}

export const technicalsApi = {
  fetch: (ticker: string) =>
    apiFetch<TechnicalsData>(`/market/technicals/${ticker}`),

  quote: (ticker: string) =>
    apiFetch<QuoteData>(`/market/quote/${ticker}`),

  saveTradeRationale: (tradeId: string, data: TechnicalsData) =>
    apiFetch<void>(`/trades/${tradeId}/rationale`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
}
