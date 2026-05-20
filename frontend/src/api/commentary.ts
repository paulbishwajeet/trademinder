// frontend/src/api/commentary.ts
import { apiFetch } from './client'
import type { Commentary, TechnicalsData } from '../types'

export const commentaryApi = {
  list: (tradeId: string) =>
    apiFetch<Commentary[]>(`/trades/${tradeId}/commentary`),

  add: (tradeId: string, payload: { note: string; tags?: string[]; rationale?: TechnicalsData | null }) =>
    apiFetch<Commentary>(`/trades/${tradeId}/commentary`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  delete: (commentId: string) =>
    apiFetch<void>(`/commentary/${commentId}`, { method: 'DELETE' }),
}
