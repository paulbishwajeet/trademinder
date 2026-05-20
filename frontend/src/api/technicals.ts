// frontend/src/api/technicals.ts
import { apiFetch } from './client'
import type { TechnicalsData } from '../types'

export const technicalsApi = {
  fetch: (ticker: string) =>
    apiFetch<TechnicalsData>(`/market/technicals/${ticker}`),

  saveTradeRationale: (tradeId: string, data: TechnicalsData) =>
    apiFetch<void>(`/trades/${tradeId}/rationale`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
}
