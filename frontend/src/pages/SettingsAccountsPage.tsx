// frontend/src/pages/SettingsAccountsPage.tsx
import { useState } from 'react'
import { Link } from 'react-router-dom'
import * as Dialog from '@radix-ui/react-dialog'
import { accountsApi } from '../api/accounts'
import { useAccounts } from '../context/AccountsContext'
import { AccountDialog } from '../components/Accounts/AccountDialog'
import { accountPath } from '../lib/paths'
import { factsSummary, formatMoney, valuesAreStale } from '../lib/accountFacts'
import type { BrokerageAccount } from '../types'

export function SettingsAccountsPage() {
  const { accounts, categories, refresh } = useAccounts()
  const [editing, setEditing] = useState<BrokerageAccount | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [dialogSection, setDialogSection] = useState<'facts' | undefined>(undefined)
  const [confirmDelete, setConfirmDelete] = useState<BrokerageAccount | null>(null)
  const [confirmUnlink, setConfirmUnlink] = useState<BrokerageAccount | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const categoryName = (id: string | null) => categories.find(c => c.id === id)?.name ?? '—'

  function openEditor(account: BrokerageAccount | null, section?: 'facts') {
    setEditing(account)
    setDialogSection(section)
    setDialogOpen(true)
  }

  async function run(account: BrokerageAccount, action: () => Promise<unknown>) {
    setBusyId(account.id)
    setError(null)
    try {
      await action()
      await refresh()
    } catch (e) {
      setError(`${account.nickname}: ${e instanceof Error ? e.message : 'failed'}`)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div>
      <p className="text-sm text-gray-500">
        Accounts that hold trades, wheels, spreads or screener symbols can only be archived. Empty accounts can be deleted.
      </p>

      {error && <p className="mt-4 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <div className="mt-4 overflow-x-auto rounded-lg border border-gray-200 bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
            <tr>
              <th className="px-4 py-2">Account</th>
              <th className="px-4 py-2">Broker</th>
              <th className="px-4 py-2">Last four</th>
              <th className="px-4 py-2">Categories</th>
              <th className="px-4 py-2">Default category</th>
              <th className="px-4 py-2">Facts</th>
              <th className="px-4 py-2">Value</th>
              <th className="px-4 py-2">E*TRADE link</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {accounts.map(a => (
              <tr key={a.id} className={a.is_archived ? 'bg-gray-50 text-gray-500' : ''}>
                <td className="px-4 py-2 font-medium">
                  {a.is_archived ? a.nickname : <Link to={accountPath(a.id, 'wheel')} className="text-blue-600 hover:underline">{a.nickname}</Link>}
                </td>
                <td className="px-4 py-2">{a.broker}</td>
                <td className="px-4 py-2">{a.last_four ?? '—'}</td>
                <td className="px-4 py-2">{a.category_ids.length}</td>
                <td className="px-4 py-2">{categoryName(a.default_category_id)}</td>
                <td className="px-4 py-2">
                  {a.facts_complete
                    ? <span className="text-gray-700">{factsSummary(a)}</span>
                    : (
                      <button onClick={() => openEditor(a, 'facts')} disabled={busyId === a.id}
                        title={factsSummary(a) || 'No facts set yet'}
                        className="whitespace-nowrap rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-800 hover:bg-amber-200 disabled:opacity-50">
                        Facts incomplete
                      </button>
                    )}
                </td>
                <td className="whitespace-nowrap px-4 py-2">
                  {a.net_liquidation_value === null && a.cash_balance === null
                    ? <span className="text-gray-400">—</span>
                    : (
                      <div className={valuesAreStale(a.values_as_of) ? 'text-gray-400' : 'text-gray-800'}>
                        <div>{formatMoney(a.net_liquidation_value)}</div>
                        <div className="text-xs">
                          cash {formatMoney(a.cash_balance)}
                          {a.values_as_of && <> · as of {new Date(a.values_as_of).toLocaleDateString()}</>}
                        </div>
                      </div>
                    )}
                </td>
                <td className="px-4 py-2">
                  {a.link ? (
                    <div className="flex items-start gap-2">
                      <div>
                        <div className="text-gray-800">{a.link.label ?? 'Linked'}</div>
                        {a.link.last_seen_at && (
                          <div className="text-xs text-gray-400">
                            seen {new Date(a.link.last_seen_at).toLocaleDateString()}
                          </div>
                        )}
                      </div>
                      <button onClick={() => setConfirmUnlink(a)}
                        className="text-xs text-gray-500 hover:text-red-600 hover:underline disabled:opacity-50"
                        disabled={busyId === a.id}>Unlink</button>
                    </div>
                  ) : <span className="text-gray-400">—</span>}
                </td>
                <td className="px-4 py-2">
                  {a.is_archived
                    ? <span className="rounded bg-gray-200 px-2 py-0.5 text-xs">Archived</span>
                    : a.is_default
                      ? <span className="rounded bg-blue-100 px-2 py-0.5 text-xs text-blue-700">Default</span>
                      : <span className="rounded bg-green-100 px-2 py-0.5 text-xs text-green-700">Active</span>}
                </td>
                <td className="space-x-2 whitespace-nowrap px-4 py-2 text-right">
                  <button onClick={() => openEditor(a)}
                    className="text-blue-600 hover:underline disabled:opacity-50" disabled={busyId === a.id}>Edit</button>
                  {a.is_archived
                    ? <button onClick={() => run(a, () => accountsApi.restore(a.id))}
                        className="text-green-700 hover:underline disabled:opacity-50" disabled={busyId === a.id}>Restore</button>
                    : <button onClick={() => run(a, () => accountsApi.archive(a.id))}
                        className="text-amber-700 hover:underline disabled:opacity-50" disabled={busyId === a.id}>Archive</button>}
                  {a.can_delete && (
                    <button onClick={() => setConfirmDelete(a)}
                      className="text-red-600 hover:underline disabled:opacity-50" disabled={busyId === a.id}>Delete</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <button onClick={() => openEditor(null)}
        className="mt-4 rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700">
        + Add account
      </button>

      <AccountDialog open={dialogOpen} onOpenChange={setDialogOpen} account={editing} initialSection={dialogSection} />

      <Dialog.Root open={confirmUnlink !== null} onOpenChange={o => { if (!o) setConfirmUnlink(null) }}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-black/30" />
          <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-96 max-w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 rounded-lg bg-white p-6 shadow-xl">
            <Dialog.Title className="text-lg font-semibold text-gray-900">Unlink {confirmUnlink?.nickname}?</Dialog.Title>
            <Dialog.Description className="mt-2 text-sm text-gray-600">
              The extension will stop matching E*TRADE &ldquo;{confirmUnlink?.link?.label}&rdquo; to this account and will
              ask you to link it again next time you open it. No trades are changed.
            </Dialog.Description>
            <div className="mt-6 flex justify-end gap-2">
              <Dialog.Close className="rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50">Cancel</Dialog.Close>
              <button
                onClick={() => {
                  const target = confirmUnlink
                  setConfirmUnlink(null)
                  if (target) void run(target, () => accountsApi.unlink(target.id))
                }}
                className="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700">
                Unlink
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      <Dialog.Root open={confirmDelete !== null} onOpenChange={o => { if (!o) setConfirmDelete(null) }}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-black/30" />
          <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-96 max-w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 rounded-lg bg-white p-6 shadow-xl">
            <Dialog.Title className="text-lg font-semibold text-gray-900">Delete {confirmDelete?.nickname}?</Dialog.Title>
            <Dialog.Description className="mt-2 text-sm text-gray-600">
              This account is empty. Deleting it is permanent.
            </Dialog.Description>
            <div className="mt-6 flex justify-end gap-2">
              <Dialog.Close className="rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50">Cancel</Dialog.Close>
              <button
                onClick={() => {
                  const target = confirmDelete
                  setConfirmDelete(null)
                  if (target) void run(target, () => accountsApi.delete(target.id))
                }}
                className="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700">
                Delete
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  )
}
