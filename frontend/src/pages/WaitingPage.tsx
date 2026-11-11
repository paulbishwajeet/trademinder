// frontend/src/pages/WaitingPage.tsx
import { Navigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

/** Pending users see only this until an admin approves them. */
export function WaitingPage() {
  const { user, loading, refresh, logout } = useAuth()
  if (loading) return null
  if (!user) return <Navigate to="/signin" replace />
  if (user.status !== 'pending') return <Navigate to="/" replace />
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-md rounded-xl border border-gray-200 bg-white p-8 text-center shadow-sm">
        <h1 className="text-xl font-semibold text-gray-900">Waiting for approval</h1>
        <p className="mt-2 text-sm text-gray-600">
          You're signed in as <b>{user.email}</b>. The admin needs to approve your account before you can use
          TradeMinder.
        </p>
        <div className="mt-6 flex justify-center gap-2">
          <button onClick={() => { void refresh() }}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">
            Check again
          </button>
          <button onClick={() => { void logout() }}
            className="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">
            Sign out
          </button>
        </div>
      </div>
    </div>
  )
}
