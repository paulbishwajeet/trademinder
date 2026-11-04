// frontend/src/api/dashboard.ts
import { apiFetch } from './client'
import type { DashboardSummary } from '../types'

export const dashboardApi = {
  summary: () => apiFetch<DashboardSummary>('/dashboard/summary'),
}
