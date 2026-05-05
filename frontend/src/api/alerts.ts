// frontend/src/api/alerts.ts
import { apiFetch } from './client'
import type { Alert } from '../types'

export const alertsApi = {
  list: () => apiFetch<Alert[]>('/alerts'),

  forTrade: (tradeId: string) =>
    apiFetch<Alert[]>(`/alerts/trade/${tradeId}`),

  markRead: (alertId: string) =>
    apiFetch<Alert>(`/alerts/${alertId}/read`, { method: 'POST' }),

  dismiss: (alertId: string) =>
    apiFetch<Alert>(`/alerts/${alertId}/dismiss`, { method: 'POST' }),
}
