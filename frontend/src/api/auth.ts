// frontend/src/api/auth.ts
import { apiFetch } from './client'

export type Role = 'admin' | 'user'
export type UserStatus = 'pending' | 'active' | 'disabled'

export interface CurrentUser {
  id: string
  email: string
  display_name: string | null
  role: Role
  status: UserStatus
}

export interface AdminUser {
  id: string
  email: string
  display_name: string
  role: Role
  status: UserStatus
  created_at: string
  last_login_at: string | null
  has_signed_in: boolean
  invited_by: string | null
  approved_by: string | null
  approved_at: string | null
}

export interface ExtensionTokenInfo {
  id: string
  device_name: string
  token_prefix: string
  created_at: string
  last_used_at: string | null
}

/** Full-page navigation target for "Sign in with Google" (the backend redirects to Google). */
export function googleLoginUrl(next: string): string {
  return `/api/auth/google/login?next=${encodeURIComponent(next)}`
}

export const authApi = {
  me: () => apiFetch<CurrentUser>('/me'),
  logout: () => apiFetch<void>('/auth/logout', { method: 'POST' }),
}

export const adminApi = {
  list: (status?: UserStatus) => apiFetch<AdminUser[]>(`/admin/users${status ? `?status=${status}` : ''}`),
  invite: (email: string, role: Role) =>
    apiFetch<AdminUser>('/admin/users/invite', { method: 'POST', body: JSON.stringify({ email, role }) }),
  approve: (id: string) => apiFetch<AdminUser>(`/admin/users/${id}/approve`, { method: 'POST' }),
  reject: (id: string) => apiFetch<AdminUser>(`/admin/users/${id}/reject`, { method: 'POST' }),
  disable: (id: string) => apiFetch<AdminUser>(`/admin/users/${id}/disable`, { method: 'POST' }),
  enable: (id: string) => apiFetch<AdminUser>(`/admin/users/${id}/enable`, { method: 'POST' }),
  setRole: (id: string, role: Role) =>
    apiFetch<AdminUser>(`/admin/users/${id}/role`, { method: 'PATCH', body: JSON.stringify({ role }) }),
}

export const extensionApi = {
  tokens: () => apiFetch<ExtensionTokenInfo[]>('/extension/tokens'),
  revoke: (id: string) => apiFetch<void>(`/extension/tokens/${id}`, { method: 'DELETE' }),
  connect: (redirectUri: string, deviceName: string) =>
    apiFetch<{ redirect_to: string }>('/extension/connect', {
      method: 'POST', body: JSON.stringify({ redirect_uri: redirectUri, device_name: deviceName }),
    }),
}
