// frontend/src/api/sessions.ts
import { apiFetch } from './client'
import type { SessionSummary, SessionWithLegs, SessionLookupResponse } from '../types'

export interface SessionCreate {
  ticker: string
  strategy: string
  status: string   // broadened: was a narrow union; IC/PBWB use 'open', WHEEL uses put_open etc.
  opened_at: string
  rotation_number?: number
  parent_session_id?: string | null
}

export interface SessionUpdate {
  status?: string
  closed_at?: string | null
}

export const sessionsApi = {
  list: (params?: { strategy?: string; status?: string; ticker?: string }) => {
    const entries = Object.entries(params ?? {}).filter((e): e is [string, string] => e[1] !== undefined)
    const qs = entries.length ? '?' + new URLSearchParams(entries).toString() : ''
    return apiFetch<SessionSummary[]>(`/sessions${qs}`)
  },

  get: (id: string) => apiFetch<SessionWithLegs>(`/sessions/${id}`),

  create: (payload: SessionCreate) =>
    apiFetch<SessionSummary>('/sessions', { method: 'POST', body: JSON.stringify(payload) }),

  update: (id: string, payload: SessionUpdate) =>
    apiFetch<SessionSummary>(`/sessions/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  lookup: (ticker: string, strategy?: string) => {
    const qs = strategy ? `&strategy=${encodeURIComponent(strategy)}` : ''
    return apiFetch<SessionLookupResponse>(`/sessions/lookup?ticker=${encodeURIComponent(ticker)}${qs}`)
  },

  // Fetch open sessions for a spread strategy (IC or PBWB)
  listSpreads: (strategy: 'IRON_CONDOR' | 'PUT_B_W_FLY', status = 'open') =>
    apiFetch<SessionSummary[]>(`/sessions?strategy=${strategy}&status=${status}`),
}
