import { apiFetch } from './client'
import type {
  WheelSessionSummary, WheelSessionDetail, WheelSlotDetail,
  WheelSlotLegItem, WheelActiveSlot, CCSignalResult, OptionPriceResult,
} from '../types'

export interface WheelSessionCreate {
  ticker: string
  total_shares?: number
  opened_at: string
}

export interface WheelSessionUpdate {
  total_shares?: number
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

  list: (params?: { status?: string; ticker?: string }) => {
    const entries = Object.entries(params ?? {}).filter((e): e is [string, string] => e[1] !== undefined)
    const qs = entries.length ? '?' + new URLSearchParams(entries).toString() : ''
    return apiFetch<WheelSessionSummary[]>(`/wheel${qs}`)
  },

  get: (id: string) => apiFetch<WheelSessionDetail>(`/wheel/${id}`),

  update: (id: string, payload: WheelSessionUpdate) =>
    apiFetch<WheelSessionSummary>(`/wheel/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  addSlot: (sessionId: string, payload: WheelSlotCreate) =>
    apiFetch<WheelSlotDetail>(`/wheel/${sessionId}/slots`, { method: 'POST', body: JSON.stringify(payload) }),

  deleteSlot: (slotId: string) =>
    apiFetch<void>(`/wheel/slots/${slotId}`, { method: 'DELETE' }),

  linkLeg: (slotId: string, payload: WheelLegLink) =>
    apiFetch<WheelSlotLegItem>(`/wheel/slots/${slotId}/legs`, { method: 'POST', body: JSON.stringify(payload) }),

  resolve: (slotId: string, payload: WheelResolveRequest) =>
    apiFetch<WheelSlotDetail>(`/wheel/slots/${slotId}/resolve`, { method: 'POST', body: JSON.stringify(payload) }),

  activeSlots: () => apiFetch<WheelActiveSlot[]>('/wheel/active-slots'),
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
  get: (ticker: string, refresh = false) =>
    apiFetch<{ cc: CCSignalResult; sp: CCSignalResult }>(`/market/combined-signal/${encodeURIComponent(ticker)}${refresh ? '?refresh=true' : ''}`),
}

export const optionPriceApi = {
  get: (ticker: string, strike: number, expiry: string, contractType: string) => {
    const qs = new URLSearchParams({ strike: String(strike), expiry, contract_type: contractType })
    return apiFetch<OptionPriceResult>(`/market/option-price/${encodeURIComponent(ticker)}?${qs}`)
  },
}
