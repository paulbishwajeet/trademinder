// frontend/src/components/Accounts/AccountDialog.tsx
import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { accountsApi } from '../../api/accounts'
import { ApiError } from '../../api/client'
import { useAccounts } from '../../context/AccountsContext'
import {
  ACCOUNT_PURPOSES, MARGIN_TYPES, OPTIONS_TIERS, TAX_TREATMENTS, choiceFor, isMoneyInput, moneyToInput,
  valuesAreStale, type FactChoice,
} from '../../lib/accountFacts'
import {
  KNOWN_BROKERS, type AccountFacts, type AccountPurpose, type BrokerageAccount, type MarginType, type OptionsTier,
  type TaxTreatment,
} from '../../types'

type FactField = keyof AccountFacts

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Edit this account; omit to create a new one. */
  account?: BrokerageAccount | null
  onSaved?: (account: BrokerageAccount) => void
  /** 'facts' scrolls to the Account facts section on open (from the "Facts incomplete" marker). */
  initialSection?: 'facts'
}

/** Shared by "+ Add account" and the gear icon: broker, nickname, last four, categories, default category,
 *  and the account facts. */
export function AccountDialog({ open, onOpenChange, account, onSaved, initialSection }: Props) {
  const { categories, refresh } = useAccounts()
  const [broker, setBroker] = useState<string>(KNOWN_BROKERS[0])
  const [nickname, setNickname] = useState('')
  const [lastFour, setLastFour] = useState('')
  const [categoryIds, setCategoryIds] = useState<string[]>([])
  const [defaultCategoryId, setDefaultCategoryId] = useState('')
  const [taxTreatment, setTaxTreatment] = useState<TaxTreatment | null>(null)
  const [purpose, setPurpose] = useState<AccountPurpose | null>(null)
  const [marginType, setMarginType] = useState<MarginType | null>(null)
  const [optionsTier, setOptionsTier] = useState<OptionsTier | null>(null)
  const [levelLabel, setLevelLabel] = useState('')
  const [netLiq, setNetLiq] = useState('')
  const [cash, setCash] = useState('')
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<FactField, string>>>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const factsRef = useRef<HTMLFieldSetElement>(null)

  useEffect(() => {
    if (!open) return
    setTaxTreatment(account?.tax_treatment ?? null)
    setPurpose(account?.account_purpose ?? null)
    setMarginType(account?.margin_type ?? null)
    setOptionsTier(account?.options_tier ?? null)
    setLevelLabel(account?.options_level_label ?? '')
    setNetLiq(moneyToInput(account?.net_liquidation_value ?? null))
    setCash(moneyToInput(account?.cash_balance ?? null))
    setFieldErrors({})
    setBroker(account?.broker ?? KNOWN_BROKERS[0])
    setNickname(account?.nickname ?? '')
    setLastFour(account?.last_four ?? '')
    setCategoryIds(account ? account.category_ids : categories.map(c => c.id))
    setDefaultCategoryId(account?.default_category_id ?? '')
    setError(null)
  }, [open, account, categories])

  useEffect(() => {
    if (!open || initialSection !== 'facts') return
    // After the dialog content mounts.
    const id = requestAnimationFrame(() => {
      factsRef.current?.scrollIntoView({ block: 'start' })
      factsRef.current?.querySelector<HTMLSelectElement>('select')?.focus()
    })
    return () => cancelAnimationFrame(id)
  }, [open, initialSection])

  const brokerOptions: string[] = [...KNOWN_BROKERS]
  if (account && !brokerOptions.includes(account.broker)) brokerOptions.unshift(account.broker)

  const lastFourValid = lastFour === '' || /^\d{4}$/.test(lastFour)
  const moneyValid = isMoneyInput(netLiq) && isMoneyInput(cash)
  const canSave = nickname.trim().length > 0 && lastFourValid && moneyValid && !saving
  const selectedCategories = categories.filter(c => categoryIds.includes(c.id))

  function toggleCategory(id: string) {
    setCategoryIds(prev => {
      const next = prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
      if (!next.includes(defaultCategoryId)) setDefaultCategoryId('')
      return next
    })
  }

  function changeFact<T>(set: (v: T) => void) {
    return (value: T) => {
      set(value)
      // A rule names two fields; editing any fact clears the message.
      setFieldErrors(prev => (Object.keys(prev).length > 0 ? {} : prev))
    }
  }

  function factsPayload(): AccountFacts {
    return {
      tax_treatment: taxTreatment,
      account_purpose: purpose,
      margin_type: marginType,
      options_tier: optionsTier,
      options_level_label: levelLabel.trim() || null,
      net_liquidation_value: netLiq === '' ? null : netLiq,
      cash_balance: cash === '' ? null : cash,
    }
  }

  async function save() {
    setSaving(true)
    setError(null)
    setFieldErrors({})
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
          ...factsPayload(),
        })
      } else {
        saved = await accountsApi.create({
          broker, nickname: nickname.trim(), last_four: lastFour || null,
          category_ids: categoryIds, default_category_id: defaultCategoryId || null,
          ...factsPayload(),
        })
      }
      await refresh()
      onOpenChange(false)
      onSaved?.(saved)
    } catch (e) {
      if (e instanceof ApiError && e.fields.length > 0) {
        // Highlight every named field; show the message once, under the last one.
        const errs: Partial<Record<FactField, string>> = {}
        e.fields.forEach((f, i) => { errs[f as FactField] = i === e.fields.length - 1 ? e.message : '' })
        setFieldErrors(errs)
        factsRef.current?.scrollIntoView({ block: 'nearest' })
      } else {
        setError(e instanceof Error ? e.message : 'Save failed')
      }
    } finally {
      setSaving(false)
    }
  }

  const valuesAsOf = account?.values_as_of ?? null
  const valuesStale = valuesAreStale(valuesAsOf)

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/30" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[32rem] max-w-[calc(100vw-2rem)] max-h-[90vh] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg bg-white p-6 shadow-xl">
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

            <fieldset ref={factsRef} aria-labelledby="account-facts-heading"
              className="scroll-mt-4 border-t border-gray-200 pt-4 text-sm">
              <h3 id="account-facts-heading" className="font-semibold text-gray-900">Account facts</h3>
              <p className="mt-0.5 text-xs text-gray-500">
                What this account is allowed to do. Change them whenever your broker does.
              </p>

              <div className="mt-3 space-y-4">
                <FactSelect label="Tax treatment" choices={TAX_TREATMENTS} value={taxTreatment}
                  onChange={changeFact(setTaxTreatment)} error={fieldErrors.tax_treatment} />
                <FactSelect label="Purpose" choices={ACCOUNT_PURPOSES} value={purpose}
                  onChange={changeFact(setPurpose)} error={fieldErrors.account_purpose} />
                <FactSelect label="Margin type" choices={MARGIN_TYPES} value={marginType}
                  onChange={changeFact(setMarginType)} error={fieldErrors.margin_type} />
                <FactSelect label="Options tier" choices={OPTIONS_TIERS} value={optionsTier}
                  onChange={changeFact(setOptionsTier)} error={fieldErrors.options_tier}
                  beside={
                    <input value={levelLabel} onChange={e => setLevelLabel(e.target.value)} maxLength={40}
                      placeholder="Broker's name, e.g. Level 2" aria-label="Broker's name for the options level"
                      className="block w-44 rounded border border-gray-300 px-2 py-1.5 text-sm" />
                  }
                  footer={
                    <details className="mt-1 text-xs text-gray-500">
                      <summary className="cursor-pointer select-none hover:text-gray-700">What each tier allows</summary>
                      <ul className="mt-1 space-y-0.5">
                        {OPTIONS_TIERS.map(t => (
                          <li key={t.value} className={t.value === optionsTier ? 'font-medium text-gray-800' : ''}>
                            {t.label}: {t.hint}
                          </li>
                        ))}
                      </ul>
                    </details>
                  } />

                <div>
                  <div className="grid grid-cols-2 gap-3">
                    <MoneyInput label="Net liquidation value" value={netLiq}
                      onChange={changeFact(setNetLiq)} error={fieldErrors.net_liquidation_value} />
                    <MoneyInput label="Cash" value={cash}
                      onChange={changeFact(setCash)} error={fieldErrors.cash_balance} />
                  </div>
                  <p className={`mt-1 text-xs ${valuesStale ? 'text-gray-400' : 'text-gray-500'}`}>
                    {valuesAsOf
                      ? `As of ${new Date(valuesAsOf).toLocaleDateString()}${valuesStale ? ' (more than 7 days old)' : ''}. Updated whenever you change either value.`
                      : 'Optional. Dated when you enter them.'}
                  </p>
                </div>
              </div>
            </fieldset>
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

function FactSelect<T extends string>({ label, choices, value, onChange, error, beside, footer }: {
  label: string
  choices: FactChoice<T>[]
  value: T | null
  onChange: (value: T | null) => void
  /** '' highlights the field without a message (the message shows under a sibling field). */
  error?: string
  beside?: ReactNode
  footer?: ReactNode
}) {
  const id = useId()
  const hint = choiceFor(choices, value)?.hint
  const invalid = error !== undefined
  return (
    <div>
      <label htmlFor={id} className="block font-medium text-gray-700">{label}</label>
      <div className="mt-1 flex gap-2">
        <select id={id} value={value ?? ''} onChange={e => onChange((e.target.value || null) as T | null)}
          aria-invalid={invalid}
          className={`block w-full rounded border px-2 py-1.5 text-sm ${invalid ? 'border-red-400' : 'border-gray-300'} ${value === null ? 'text-gray-500' : ''}`}>
          <option value="">Not set</option>
          {choices.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
        {beside}
      </div>
      <p className="mt-1 text-xs text-gray-500">{hint ?? 'Not set yet.'}</p>
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
      {footer}
    </div>
  )
}

function MoneyInput({ label, value, onChange, error }: {
  label: string
  value: string
  onChange: (value: string) => void
  error?: string
}) {
  const invalid = error !== undefined || !isMoneyInput(value)
  return (
    <label className="block">
      <span className="font-medium text-gray-700">{label}</span>
      <div className="relative mt-1">
        <span className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-gray-400">$</span>
        <input value={value} onChange={e => onChange(e.target.value.replace(/[,\s$]/g, ''))}
          inputMode="decimal" placeholder="—" aria-invalid={invalid}
          className={`block w-full rounded border py-1.5 pl-5 pr-2 text-sm ${invalid ? 'border-red-400' : 'border-gray-300'}`} />
      </div>
      {!isMoneyInput(value) && <span className="mt-1 block text-xs text-red-600">Dollars, up to 2 decimals.</span>}
      {error && <span className="mt-1 block text-xs text-red-600">{error}</span>}
    </label>
  )
}
