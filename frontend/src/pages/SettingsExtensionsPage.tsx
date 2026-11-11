// frontend/src/pages/SettingsExtensionsPage.tsx
import { useCallback, useEffect, useState } from 'react'
import { extensionApi, type ExtensionTokenInfo } from '../api/auth'
import { ApiError } from '../api/client'

function fmt(ts: string | null): string {
  return ts ? new Date(ts).toLocaleString() : 'Never'
}

/** Settings → Connected extensions: the user's extension tokens, with Revoke. */
export function SettingsExtensionsPage() {
  const [tokens, setTokens] = useState<ExtensionTokenInfo[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setTokens(await extensionApi.tokens())
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load')
    }
  }, [])
  useEffect(() => { void load() }, [load])

  async function revoke(t: ExtensionTokenInfo) {
    setBusy(t.id)
    try {
      await extensionApi.revoke(t.id)
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Revoke failed')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div>
      <p className="text-sm text-gray-500">
        Browser extensions signed in as you. Revoking one signs that extension out immediately.
        To add one, press Sign in in the TradeMinder extension's popup.
      </p>
      {error && <p className="mt-4 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      <div className="mt-4 overflow-x-auto rounded-lg border border-gray-200 bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
            <tr><th className="px-4 py-2">Device</th><th className="px-4 py-2">Created</th><th className="px-4 py-2">Last used</th><th className="px-4 py-2" /></tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {tokens.length === 0 && (
              <tr><td colSpan={4} className="px-4 py-6 text-center text-gray-400">No extensions connected.</td></tr>
            )}
            {tokens.map(t => (
              <tr key={t.id}>
                <td className="px-4 py-2"><div className="font-medium text-gray-900">{t.device_name}</div>
                  <div className="font-mono text-xs text-gray-400">{t.token_prefix}…</div></td>
                <td className="px-4 py-2 text-gray-600">{fmt(t.created_at)}</td>
                <td className="px-4 py-2 text-gray-600">{fmt(t.last_used_at)}</td>
                <td className="px-4 py-2 text-right">
                  <button disabled={busy === t.id} onClick={() => { void revoke(t) }}
                    className="text-xs text-red-600 hover:underline disabled:opacity-40">Revoke</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
