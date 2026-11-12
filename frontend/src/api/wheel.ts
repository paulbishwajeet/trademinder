import { apiFetch } from './client'
import type {
  WheelSessionSummary, WheelSessionDetail, WheelSlotDetail,
  WheelSlotLegItem, WheelActiveSlot, CCSignalResult, OptionPriceResult,
  Commentary, TechnicalsData, WheelSignalSnapshot, WheelSlotHistoryResponse,
} from '../types'

export interface WheelSessionCreate {
  account_id?: string | null  // omitted → the user's default account
  ticker: string
  total_shares?: number
  opened_at: string
}

export interface WheelSessionUpdate {
  ticker?: string  // only while the wheel has no slots (409 otherwise)
  total_shares?: number
  opened_at?: string
  status?: string
  closed_at?: string | null
}

export interface WheelSlotCreate {
  contracts?: number
  shares_held?: number
  status: string
}

export interface WheelLegLink {
  trade_id: string
  leg_role: string
}

export interface WheelResolveRequest {
  outcome: string
  new_trade_id?: string | null
  buyback_cost?: string | null
  notes?: string | null
}

export const wheelApi = {
  create: (payload: WheelSessionCreate) =>
    apiFetch<WheelSessionSummary>('/wheel', { method: 'POST', body: JSON.stringify(payload) }),

  list: (params?: { status?: string; ticker?: string; account_id?: string }) => {
    const entries = Object.entries(params ?? {}).filter((e): e is [string, string] => e[1] !== undefined)
    const qs = entries.length ? '?' + new URLSearchParams(entries).toString() : ''
    return apiFetch<WheelSessionSummary[]>(`/wheel${qs}`)
  },

  get: (id: string) => apiFetch<WheelSessionDetail>(`/wheel/${id}`),

  update: (id: string, payload: WheelSessionUpdate) =>
    apiFetch<WheelSessionSummary>(`/wheel/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  /** Only a wheel with no slots (409 otherwise). */
  deleteSession: (id: string) =>
    apiFetch<void>(`/wheel/${id}`, { method: 'DELETE' }),

  addSlot: (sessionId: string, payload: WheelSlotCreate) =>
    apiFetch<WheelSlotDetail>(`/wheel/${sessionId}/slots`, { method: 'POST', body: JSON.stringify(payload) }),

  deleteSlot: (slotId: string) =>
    apiFetch<void>(`/wheel/slots/${slotId}`, { method: 'DELETE' }),

  updateSlot: (slotId: string, payload: { contracts: number }) =>
    apiFetch<void>(`/wheel/slots/${slotId}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  linkLeg: (slotId: string, payload: WheelLegLink) =>
    apiFetch<WheelSlotLegItem>(`/wheel/slots/${slotId}/legs`, { method: 'POST', body: JSON.stringify(payload) }),

  resolve: (slotId: string, payload: WheelResolveRequest) =>
    apiFetch<WheelSlotDetail>(`/wheel/slots/${slotId}/resolve`, { method: 'POST', body: JSON.stringify(payload) }),

  activeSlots: (accountId?: string) =>
    apiFetch<WheelActiveSlot[]>(`/wheel/active-slots${accountId ? `?account_id=${accountId}` : ''}`),

  addSlotCommentary: (slotId: string, payload: { note: string; tags?: string[]; rationale?: TechnicalsData | null; signal_snapshot?: WheelSignalSnapshot | null }) =>
    apiFetch<Commentary>(`/wheel/slots/${slotId}/commentary`, { method: 'POST', body: JSON.stringify(payload) }),

  getSlotHistory: (slotId: string, params: { limit: number; offset: number }) => {
    const qs = new URLSearchParams({ limit: String(params.limit), offset: String(params.offset) })
    return apiFetch<WheelSlotHistoryResponse>(`/wheel/slots/${slotId}/history?${qs}`)
  },
}

export const ccSignalApi = {
  get: (ticker: string, refresh = false) =>
    apiFetch<CCSignalResult>(`/market/cc-signal/${encodeURIComponent(ticker)}${refresh ? '?refresh=true' : ''}`),
}

export const spSignalApi = {
  get: (ticker: string, refresh = false) =>
    apiFetch<CCSignalResult>(`/market/sp-signal/${encodeURIComponent(ticker)}${refresh ? '?refresh=true' : ''}`),
}

export const combinedSignalApi = {
  get: (ticker: string, refresh = false, dte?: number) => {
    const params = new URLSearchParams()
    if (refresh) params.set('refresh', 'true')
    if (dte != null) params.set('dte', String(dte))
    const qs = params.toString()
    return apiFetch<{ cc: CCSignalResult; sp: CCSignalResult }>(
      `/market/combined-signal/${encodeURIComponent(ticker)}${qs ? `?${qs}` : ''}`
    )
  },
}

export const ccTimingSignalApi = {
  get: (ticker: string, refresh = false) =>
    apiFetch<CCSignalResult>(`/market/cc-timing-signal/${encodeURIComponent(ticker)}${refresh ? '?refresh=true' : ''}`),
}

export const spTimingSignalApi = {
  get: (ticker: string, refresh = false) =>
    apiFetch<CCSignalResult>(`/market/sp-timing-signal/${encodeURIComponent(ticker)}${refresh ? '?refresh=true' : ''}`),
}

export const optionPriceApi = {
  get: (ticker: string, strike: number, expiry: string, contractType: string) => {
    const qs = new URLSearchParams({ strike: String(strike), expiry, contract_type: contractType })
    return apiFetch<OptionPriceResult>(`/market/option-price/${encodeURIComponent(ticker)}?${qs}`)
  },
}
