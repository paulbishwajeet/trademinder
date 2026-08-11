// frontend/src/api/screener.ts
import { apiFetch } from './client'
import type { ScreenerRow, ScreenerPreview, ScreenerCommentary, ScreenerJobStatus, ScreenerFetchedFields } from '../types'

export const screenerApi = {
  list: () => apiFetch<ScreenerRow[]>('/screener'),

  preview: (ticker: string) => apiFetch<ScreenerPreview>(`/screener/preview/${ticker}`),

  add: (payload: { symbol: string; category?: string; precomputed?: ScreenerFetchedFields }) =>
    apiFetch<ScreenerRow>('/screener', { method: 'POST', body: JSON.stringify(payload) }),

  fetchOne: (symbol: string) =>
    apiFetch<ScreenerRow>(`/screener/${symbol}/fetch`, { method: 'POST' }),

  fetchAll: () =>
    apiFetch<ScreenerJobStatus>('/screener/fetch-all', { method: 'POST' }),

  getJobStatus: (jobId: string) =>
    apiFetch<ScreenerJobStatus>(`/screener/jobs/${jobId}`),

  remove: (symbol: string) =>
    apiFetch<void>(`/screener/${symbol}`, { method: 'DELETE' }),

  patch: (symbol: string, payload: { sector?: string; category?: string }) =>
    apiFetch<ScreenerRow>(`/screener/${symbol}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  commentary: {
    list: (symbol: string) => apiFetch<ScreenerCommentary[]>(`/screener/${symbol}/commentary`),

    add: (symbol: string, payload: { note: string; tags?: string[] }) =>
      apiFetch<ScreenerCommentary>(`/screener/${symbol}/commentary`, {
        method: 'POST',
        body: JSON.stringify(payload),
      }),

    update: (commentId: string, payload: { note: string; tags?: string[] }) =>
      apiFetch<ScreenerCommentary>(`/screener/commentary/${commentId}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      }),

    remove: (commentId: string) =>
      apiFetch<void>(`/screener/commentary/${commentId}`, { method: 'DELETE' }),
  },
}
