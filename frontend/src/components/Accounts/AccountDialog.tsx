// frontend/src/components/Accounts/AccountDialog.tsx
import { useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { accountsApi } from '../../api/accounts'
import { useAccounts } from '../../context/AccountsContext'
import { KNOWN_BROKERS, type BrokerageAccount } from '../../types'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Edit this account; omit to create a new one. */
  account?: BrokerageAccount | null
  onSaved?: (account: BrokerageAccount) => void
}

/** Shared by "+ Add account" and the gear icon: broker, nickname, last four, categories, default category. */
export function AccountDialog({ open, onOpenChange, account, onSaved }: Props) {
  const { categories, refresh } = useAccounts()
  const [broker, setBroker] = useState<string>(KNOWN_BROKERS[0])
  const [nickname, setNickname] = useState('')
  const [lastFour, setLastFour] = useState('')
  const [categoryIds, setCategoryIds] = useState<string[]>([])
  const [defaultCategoryId, setDefaultCategoryId] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setBroker(account?.broker ?? KNOWN_BROKERS[0])
    setNickname(account?.nickname ?? '')
    setLastFour(account?.last_four ?? '')
    setCategoryIds(account ? account.category_ids : categories.map(c => c.id))
    setDefaultCategoryId(account?.default_category_id ?? '')
    setError(null)
  }, [open, account, categories])

  const brokerOptions: string[] = [...KNOWN_BROKERS]
  if (account && !brokerOptions.includes(account.broker)) brokerOptions.unshift(account.broker)

  const lastFourValid = lastFour === '' || /^\d{4}$/.test(lastFour)
  const canSave = nickname.trim().length > 0 && lastFourValid && !saving
  const selectedCategories = categories.filter(c => categoryIds.includes(c.id))

  function toggleCategory(id: string) {
    setCategoryIds(prev => {
      const next = prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
      if (!next.includes(defaultCategoryId)) setDefaultCategoryId('')
      return next
    })
  }

  async function save() {
    setSaving(true)
    setError(null)
    try {
      let saved: BrokerageAccount
      if (account) {
        // Categories first: the server clears a default category that is no longer in the list.
        const sameCats = categoryIds.length === account.category_ids.length
          && categoryIds.every(id => account.category_ids.includes(id))
        if (!sameCats) await accountsApi.setCategories(account.id, categoryIds)
        saved = await accountsApi.update(account.id, {
          broker, nickname: nickname.trim(), last_four: lastFour || null,
          default_category_id: defaultCategoryId || null,
        })
      } else {
        saved = await accountsApi.create({
          broker, nickname: nickname.trim(), last_four: lastFour || null,
          category_ids: categoryIds, default_category_id: defaultCategoryId || null,
        })
      }
      await refresh()
      onOpenChange(false)
      onSaved?.(saved)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/30" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[28rem] max-w-[calc(100vw-2rem)] max-h-[90vh] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg bg-white p-6 shadow-xl">
          <div className="flex items-start justify-between">
            <Dialog.Title className="text-lg font-semibold text-gray-900">
              {account ? `Edit ${account.nickname}` : 'Add account'}
            </Dialog.Title>
            <Dialog.Close className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600" aria-label="Close">
              <X size={16} />
            </Dialog.Close>
          </div>
          <Dialog.Description className="mt-1 text-sm text-gray-500">
            Only the last four digits of the account number are stored.
          </Dialog.Description>

          <div className="mt-4 space-y-4">
            <label className="block text-sm">
              <span className="font-medium text-gray-700">Broker</span>
              <select value={broker} onChange={e => setBroker(e.target.value)}
                className="mt-1 block w-full rounded border border-gray-300 px-2 py-1.5 text-sm">
                {brokerOptions.map(b => <option key={b} value={b}>{b}</option>)}
              </select>
            </label>
            <label className="block text-sm">
              <span className="font-medium text-gray-700">Nickname</span>
              <input value={nickname} onChange={e => setNickname(e.target.value)} maxLength={50}
                placeholder="e.g. E*TRADE Wheel"
                className="mt-1 block w-full rounded border border-gray-300 px-2 py-1.5 text-sm" />
            </label>
            <label className="block text-sm">
              <span className="font-medium text-gray-700">Last four digits</span>
              <input value={lastFour} onChange={e => setLastFour(e.target.value.replace(/\D/g, '').slice(0, 4))}
                inputMode="numeric" placeholder="1234"
                className={`mt-1 block w-28 rounded border px-2 py-1.5 text-sm ${lastFourValid ? 'border-gray-300' : 'border-red-400'}`} />
              {!lastFourValid && <span className="mt-1 block text-xs text-red-600">Enter exactly four digits, or leave blank.</span>}
            </label>

            <fieldset className="text-sm">
              <legend className="font-medium text-gray-700">Categories this account uses</legend>
              <div className="mt-2 grid grid-cols-2 gap-1">
                {categories.map(c => (
                  <label key={c.id} className="flex items-center gap-2 rounded px-1 py-0.5 hover:bg-gray-50">
                    <input type="checkbox" checked={categoryIds.includes(c.id)} onChange={() => toggleCategory(c.id)} />
                    <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: c.color }} />
                    <span className="text-gray-700">{c.name}</span>
                  </label>
                ))}
              </div>
            </fieldset>

            <label className="block text-sm">
              <span className="font-medium text-gray-700">Default category for new trades</span>
              <select value={defaultCategoryId} onChange={e => setDefaultCategoryId(e.target.value)}
                className="mt-1 block w-full rounded border border-gray-300 px-2 py-1.5 text-sm">
                <option value="">None</option>
                {selectedCategories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </label>
          </div>

          {error && <p className="mt-4 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

          <div className="mt-6 flex justify-end gap-2">
            <Dialog.Close className="rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50">
              Cancel
            </Dialog.Close>
            <button onClick={save} disabled={!canSave}
              className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
              {saving ? 'Saving…' : account ? 'Save' : 'Add account'}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
