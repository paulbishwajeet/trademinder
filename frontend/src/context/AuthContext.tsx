// frontend/src/context/AuthContext.tsx
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { ApiError, setUnauthorizedHandler } from '../api/client'
import { authApi, type CurrentUser } from '../api/auth'

interface AuthState {
  /** null = signed out (after loading). */
  user: CurrentUser | null
  loading: boolean
  refresh: () => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

/** Loads /api/me once at startup; any later 401 from the API signs the app out. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      setUser(await authApi.me())
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  const logout = useCallback(async () => {
    try { await authApi.logout() } finally { setUser(null) }
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null))
    void refresh()
    return () => setUnauthorizedHandler(null)
  }, [refresh])

  return <AuthContext.Provider value={{ user, loading, refresh, logout }}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth outside AuthProvider')
  return ctx
}

function Loading() {
  return <div className="flex min-h-screen items-center justify-center text-sm text-gray-400">Loading…</div>
}

function signInTarget(pathname: string, search: string): string {
  return `/signin?next=${encodeURIComponent(pathname + search)}`
}

/** Everything from Parts 2–4: only active users. Signed out → Sign in; pending → waiting page. */
export function RequireActive({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <Loading />
  if (!user) return <Navigate to={signInTarget(location.pathname, location.search)} replace />
  if (user.status === 'pending') return <Navigate to="/waiting" replace />
  return <>{children}</>
}

export function RequireAdmin({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  if (user?.role !== 'admin') return <Navigate to="/" replace />
  return <>{children}</>
}
