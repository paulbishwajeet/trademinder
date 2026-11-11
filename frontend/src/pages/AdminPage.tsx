// frontend/src/pages/AdminPage.tsx
import { useCallback, useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { adminApi, type AdminUser, type Role } from '../api/auth'
import { ApiError } from '../api/client'
import { useAuth } from '../context/AuthContext'

function fmt(ts: string | null): string {
  return ts ? new Date(ts).toLocaleDateString() : '—'
}

const STATUS_STYLE: Record<AdminUser['status'], string> = {
  pending: 'bg-amber-100 text-amber-800',
  active: 'bg-green-100 text-green-700',
  disabled: 'bg-gray-200 text-gray-600',
}

/** Account management only — the admin never sees anyone's trading data. */
export function AdminPage() {
  const { user: me } = useAuth()
  const [users, setUsers] = useState<AdminUser[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [inviteOpen, setInviteOpen] = useState(false)

  const load = useCallback(async () => {
    try {
      setUsers(await adminApi.list())
      setError(null)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load users')
    }
  }, [])

  useEffect(() => { void load() }, [load])

  async function act(u: AdminUser, fn: () => Promise<unknown>) {
    setBusy(u.id)
    setError(null)
    try {
      await fn()
      await load()
    } catch (e) {
      setError(`${u.email}: ${e instanceof ApiError ? e.message : 'failed'}`)
    } finally {
      setBusy(null)
    }
  }

  const pending = users.filter(u => u.status === 'pending')
  const others = users.filter(u => u.status !== 'pending')
  const btn = 'text-xs hover:underline disabled:opacity-40'

  return (
    <div className="max-w-5xl p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Admin · Users</h1>
        <button onClick={() => setInviteOpen(true)}
          className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700">Invite by email</button>
      </div>
      <p className="mt-1 text-sm text-gray-500">Approve sign-ups and manage access. You can't see other users' data.</p>
      {error && <p className="mt-4 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <h2 className="mt-6 text-sm font-semibold uppercase tracking-wide text-gray-500">Waiting for approval ({pending.length})</h2>
      {pending.length === 0 ? (
        <p className="mt-2 text-sm text-gray-400">Nobody is waiting.</p>
      ) : (
        <ul className="mt-2 divide-y divide-gray-100 rounded-lg border border-amber-200 bg-amber-50/40">
          {pending.map(u => (
            <li key={u.id} className="flex items-center justify-between px-4 py-2 text-sm">
              <span><b>{u.display_name}</b> <span className="text-gray-500">{u.email}</span>
                <span className="ml-2 text-xs text-gray-400">signed in {fmt(u.created_at)}</span></span>
              <span className="space-x-3">
                <button disabled={busy === u.id} onClick={() => act(u, () => adminApi.approve(u.id))}
                  className={`${btn} font-medium text-green-700`}>Approve</button>
                <button disabled={busy === u.id} onClick={() => act(u, () => adminApi.reject(u.id))}
                  className={`${btn} text-red-600`}>Reject</button>
              </span>
            </li>
          ))}
        </ul>
      )}

      <h2 className="mt-8 text-sm font-semibold uppercase tracking-wide text-gray-500">Users</h2>
      <div className="mt-2 overflow-x-auto rounded-lg border border-gray-200 bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
            <tr>
              <th className="px-4 py-2">User</th><th className="px-4 py-2">Role</th><th className="px-4 py-2">Status</th>
              <th className="px-4 py-2">Last sign-in</th><th className="px-4 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {others.map(u => {
              const isMe = u.id === me?.id
              return (
                <tr key={u.id}>
                  <td className="px-4 py-2">
                    <div className="font-medium text-gray-900">{u.display_name}{isMe && <span className="ml-1 text-xs text-gray-400">(you)</span>}</div>
                    <div className="text-xs text-gray-500">{u.email}{!u.has_signed_in && (u.invited_by ? ' · invited, not signed in yet' : ' · not signed in with Google yet')}</div>
                  </td>
                  <td className="px-4 py-2 capitalize">{u.role}</td>
                  <td className="px-4 py-2"><span className={`rounded px-2 py-0.5 text-xs ${STATUS_STYLE[u.status]}`}>{u.status}</span></td>
                  <td className="px-4 py-2 text-gray-600">{fmt(u.last_login_at)}</td>
                  <td className="space-x-3 whitespace-nowrap px-4 py-2 text-right">
                    {u.status === 'active' ? (
                      <button disabled={isMe || busy === u.id} title={isMe ? "You can't disable yourself" : undefined}
                        onClick={() => act(u, () => adminApi.disable(u.id))} className={`${btn} text-red-600`}>Disable</button>
                    ) : (
                      <button disabled={busy === u.id} onClick={() => act(u, () => adminApi.enable(u.id))}
                        className={`${btn} text-green-700`}>Re-enable</button>
                    )}
                    <button disabled={isMe || busy === u.id}
                      title={isMe ? "You can't change your own role" : undefined}
                      onClick={() => act(u, () => adminApi.setRole(u.id, u.role === 'admin' ? 'user' : 'admin'))}
                      className={`${btn} text-blue-600`}>{u.role === 'admin' ? 'Make user' : 'Make admin'}</button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <InviteDialog open={inviteOpen} onOpenChange={setInviteOpen} onInvited={load} />
    </div>
  )
}

function InviteDialog({ open, onOpenChange, onInvited }: { open: boolean; onOpenChange: (o: boolean) => void; onInvited: () => Promise<void> }) {
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<Role>('user')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const valid = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())

  async function submit() {
    setSaving(true)
    setError(null)
    try {
      await adminApi.invite(email.trim(), role)
      await onInvited()
      setEmail('')
      onOpenChange(false)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Invite failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/30" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-96 max-w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 rounded-lg bg-white p-6 shadow-xl">
          <div className="flex items-start justify-between">
            <Dialog.Title className="text-lg font-semibold text-gray-900">Invite by email</Dialog.Title>
            <Dialog.Close className="rounded p-1 text-gray-400 hover:bg-gray-100" aria-label="Close"><X size={16} /></Dialog.Close>
          </div>
          <Dialog.Description className="mt-1 text-sm text-gray-500">
            The person is approved in advance and becomes active the first time they sign in with this Google account.
            No email is sent — tell them the address of the app.
          </Dialog.Description>
          <label className="mt-4 block text-sm">
            <span className="font-medium text-gray-700">Google email</span>
            <input value={email} onChange={e => setEmail(e.target.value)} type="email" placeholder="name@gmail.com"
              className="mt-1 block w-full rounded border border-gray-300 px-2 py-1.5 text-sm" />
          </label>
          <label className="mt-3 block text-sm">
            <span className="font-medium text-gray-700">Role</span>
            <select value={role} onChange={e => setRole(e.target.value as Role)}
              className="mt-1 block w-full rounded border border-gray-300 px-2 py-1.5 text-sm">
              <option value="user">User</option>
              <option value="admin">Admin</option>
            </select>
          </label>
          {error && <p className="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
          <div className="mt-6 flex justify-end gap-2">
            <Dialog.Close className="rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50">Cancel</Dialog.Close>
            <button onClick={() => { void submit() }} disabled={!valid || saving}
              className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
              {saving ? 'Inviting…' : 'Invite'}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
