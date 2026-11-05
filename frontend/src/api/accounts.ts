// frontend/src/api/accounts.ts
import { apiFetch } from './client'
import type { BrokerageAccount, BrokerageAccountCreate, BrokerageAccountUpdate } from '../types'

export const accountsApi = {
  // Sorted by sort_order; archived accounts only when asked.
  list: (includeArchived = false) =>
    apiFetch<BrokerageAccount[]>(`/accounts${includeArchived ? '?include_archived=true' : ''}`),

  create: (payload: BrokerageAccountCreate) =>
    apiFetch<BrokerageAccount>('/accounts', { method: 'POST', body: JSON.stringify(payload) }),

  update: (id: string, payload: BrokerageAccountUpdate) =>
    apiFetch<BrokerageAccount>(`/accounts/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  setCategories: (id: string, categoryIds: string[]) =>
    apiFetch<BrokerageAccount>(`/accounts/${id}/categories`, {
      method: 'PUT',
      body: JSON.stringify({ category_ids: categoryIds }),
    }),

  archive: (id: string) => apiFetch<BrokerageAccount>(`/accounts/${id}/archive`, { method: 'POST' }),

  restore: (id: string) => apiFetch<BrokerageAccount>(`/accounts/${id}/restore`, { method: 'POST' }),

  // Full ordered list of active account ids (archived ones may be included).
  reorder: (accountIds: string[]) =>
    apiFetch<BrokerageAccount[]>('/accounts/order', { method: 'PUT', body: JSON.stringify({ account_ids: accountIds }) }),

  // Only for empty accounts — no trades, wheels, spreads, screener symbols or notes (409 otherwise).
  delete: (id: string) => apiFetch<void>(`/accounts/${id}`, { method: 'DELETE' }),
}
