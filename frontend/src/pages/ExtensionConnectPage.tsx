// frontend/src/pages/ExtensionConnectPage.tsx
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { extensionApi } from '../api/auth'
import { ApiError } from '../api/client'
import { useAuth } from '../context/AuthContext'

function defaultDeviceName(): string {
  const ua = navigator.userAgent
  const os = /Mac/.test(ua) ? 'Mac' : /Windows/.test(ua) ? 'Windows' : /Linux/.test(ua) ? 'Linux' : 'Computer'
  return `Chrome on ${os}`
}

/**
 * Opened by the extension's Sign in (chrome.identity.launchWebAuthFlow). Requires a portal login
 * (RequireActive sends the user through Google sign-in first). Approving mints a personal token and
 * redirects to the extension's chromiumapp.org URL with the token in the fragment.
 */
export function ExtensionConnectPage() {
  const { user } = useAuth()
  const [params] = useSearchParams()
  const redirectUri = params.get('redirect_uri') ?? ''
  const [deviceName, setDeviceName] = useState(defaultDeviceName)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function approve() {
    setBusy(true)
    setError(null)
    try {
      const { redirect_to } = await extensionApi.connect(redirectUri, deviceName.trim() || defaultDeviceName())
      window.location.href = redirect_to
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not connect the extension')
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-md rounded-xl border border-gray-200 bg-white p-8 shadow-sm">
        <h1 className="text-xl font-semibold text-gray-900">Connect this browser extension?</h1>
        <p className="mt-2 text-sm text-gray-600">
          The TradeMinder extension will act as <b>{user?.email}</b> on the E*TRADE positions page. You can revoke it
          any time in Settings → Connected extensions.
        </p>
        <label className="mt-5 block text-sm">
          <span className="font-medium text-gray-700">Device name</span>
          <input value={deviceName} onChange={e => setDeviceName(e.target.value)} maxLength={100}
            className="mt-1 block w-full rounded border border-gray-300 px-2 py-1.5 text-sm" />
        </label>
        {!redirectUri && <p className="mt-4 text-sm text-red-700">Open this page from the extension's Sign in button.</p>}
        {error && <p className="mt-4 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
        <div className="mt-6 flex justify-end gap-2">
          <button onClick={() => window.close()}
            className="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">Cancel</button>
          <button onClick={() => { void approve() }} disabled={busy || !redirectUri}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
            {busy ? 'Connecting…' : 'Connect'}
          </button>
        </div>
      </div>
    </div>
  )
}
