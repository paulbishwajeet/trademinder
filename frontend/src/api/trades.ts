// frontend/src/api/trades.ts
import { apiFetch } from './client'
import type { Trade, TradeCreate } from '../types'

export const tradesApi = {
  list: (params?: { status?: string; ticker?: string }) => {
    const qs = params ? '?' + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined) as [string, string][]).toString() : ''
    return apiFetch<Trade[]>(`/trades${qs}`)
  },

  get: (id: string) => apiFetch<Trade>(`/trades/${id}`),

  create: (payload: TradeCreate) =>
    apiFetch<Trade>('/trades', { method: 'POST', body: JSON.stringify(payload) }),

  update: (id: string, payload: Partial<Pick<Trade, 'exit_strategy' | 'signal_action' | 'status'>>) =>
    apiFetch<Trade>(`/trades/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  close: (id: string) =>
    apiFetch<Trade>(`/trades/${id}/close`, { method: 'POST', body: JSON.stringify({}) }),

  delete: (id: string) =>
    apiFetch<void>(`/trades/${id}`, { method: 'DELETE' }),
}
