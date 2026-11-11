// frontend/src/api/screener.ts
import { apiFetch } from './client'
import type { ScreenerRow, ScreenerPreview, ScreenerCommentary, ScreenerJobStatus, ScreenerFetchedFields } from '../types'

export const screenerApi = {
  // accountId omitted → all of the user's symbols (Research)
  list: (accountId?: string) => apiFetch<ScreenerRow[]>(`/screener${accountId ? `?account_id=${accountId}` : ''}`),

  preview: (ticker: string) => apiFetch<ScreenerPreview>(`/screener/preview/${ticker}`),

  // Adds a membership in account_id (default account when omitted); creates the symbol row if needed.
  add: (payload: { symbol: string; category?: string; precomputed?: ScreenerFetchedFields; account_id?: string }) =>
    apiFetch<ScreenerRow>('/screener', { method: 'POST', body: JSON.stringify(payload) }),

  fetchOne: (symbol: string) =>
    apiFetch<ScreenerRow>(`/screener/${symbol}/fetch`, { method: 'POST' }),

  fetchAll: () =>
    apiFetch<ScreenerJobStatus>('/screener/fetch-all', { method: 'POST' }),

  getJobStatus: (jobId: string) =>
    apiFetch<ScreenerJobStatus>(`/screener/jobs/${jobId}`),

  // With accountId: remove only that membership. Without: remove the symbol from every account.
  remove: (symbol: string, accountId?: string) =>
    apiFetch<void>(`/screener/${symbol}${accountId ? `?account_id=${accountId}` : ''}`, { method: 'DELETE' }),

  patch: (symbol: string, payload: { sector?: string; category?: string }) =>
    apiFetch<ScreenerRow>(`/screener/${symbol}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  commentary: {
    // accountId omitted → notes from every account, each labeled with its account
    list: (symbol: string, accountId?: string) =>
      apiFetch<ScreenerCommentary[]>(`/screener/${symbol}/commentary${accountId ? `?account_id=${accountId}` : ''}`),

    add: (symbol: string, payload: { note: string; tags?: string[]; account_id?: string }) =>
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
