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
  ASSIGNMENT_STANCES, LIMIT_LABELS, OBJECTIVES, SOURCE_LABELS, isPctInput,
} from '../../lib/accountGoals'
import {
  KNOWN_BROKERS, type AccountFacts, type AccountGoals, type AccountPurpose, type AssignmentStance,
  type BrokerageAccount, type LimitField, type MarginType, type Objective, type OptionsTier,
  type TaxTreatment,
} from '../../types'

type ProfileField = keyof AccountFacts | keyof AccountGoals
const GOAL_FIELDS: ProfileField[] = [
  'objective', 'assignment_stance', 'monthly_premium_target', 'annual_yield_target_pct', 'max_position_pct',
  'max_speculative_position_pct', 'max_margin_used_pct', 'min_cash_reserve_pct', 'defensive_at_loss_pct',
]

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Edit this account; omit to create a new one. */
  account?: BrokerageAccount | null
  onSaved?: (account: BrokerageAccount) => void
  /** Scrolls to that section on open (from the "Facts incomplete" / "Goal not set" markers). */
  initialSection?: 'facts' | 'goals'
}

/** Shared by "+ Add account" and the gear icon: broker, nickname, last four, categories, default category,
 *  the account facts, and the goal and preferences. */
export function AccountDialog({ open, onOpenChange, account, onSaved, initialSection }: Props) {
  const { accounts, categories, refresh } = useAccounts()
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
  const [objective, setObjective] = useState<Objective | null>(null)
  const [stance, setStance] = useState<AssignmentStance | null>(null)
  const [monthlyTarget, setMonthlyTarget] = useState('')
  const [yieldTarget, setYieldTarget] = useState('')
  const [maxPosition, setMaxPosition] = useState('')
  const [maxSpeculative, setMaxSpeculative] = useState('')
  const [maxMargin, setMaxMargin] = useState('')
  const [cashReserve, setCashReserve] = useState('')
  const [defensiveLoss, setDefensiveLoss] = useState('')
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<ProfileField, string>>>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const factsRef = useRef<HTMLFieldSetElement>(null)
  const goalsRef = useRef<HTMLFieldSetElement>(null)

  useEffect(() => {
    if (!open) return
    setTaxTreatment(account?.tax_treatment ?? null)
    setPurpose(account?.account_purpose ?? null)
    setMarginType(account?.margin_type ?? null)
    setOptionsTier(account?.options_tier ?? null)
    setLevelLabel(account?.options_level_label ?? '')
    setNetLiq(moneyToInput(account?.net_liquidation_value ?? null))
    setCash(moneyToInput(account?.cash_balance ?? null))
    setObjective(account?.objective ?? null)
    setStance(account?.assignment_stance ?? null)
    setMonthlyTarget(moneyToInput(account?.monthly_premium_target ?? null))
    setYieldTarget(moneyToInput(account?.annual_yield_target_pct ?? null))
    setMaxPosition(moneyToInput(account?.max_position_pct ?? null))
    setMaxSpeculative(moneyToInput(account?.max_speculative_position_pct ?? null))
    setMaxMargin(moneyToInput(account?.max_margin_used_pct ?? null))
    setCashReserve(moneyToInput(account?.min_cash_reserve_pct ?? null))
    setDefensiveLoss(moneyToInput(account?.defensive_at_loss_pct ?? null))
    setFieldErrors({})
    setBroker(account?.broker ?? KNOWN_BROKERS[0])
    setNickname(account?.nickname ?? '')
    setLastFour(account?.last_four ?? '')
    setCategoryIds(account ? account.category_ids : categories.map(c => c.id))
    setDefaultCategoryId(account?.default_category_id ?? '')
    setError(null)
  }, [open, account, categories])

  useEffect(() => {
    if (!open || !initialSection) return
    // After the dialog content mounts.
    const id = requestAnimationFrame(() => {
      const section = initialSection === 'facts' ? factsRef.current : goalsRef.current
      section?.scrollIntoView({ block: 'start' })
      section?.querySelector<HTMLElement>('select, button[role="radio"]')?.focus()
    })
    return () => cancelAnimationFrame(id)
  }, [open, initialSection])

  const brokerOptions: string[] = [...KNOWN_BROKERS]
  if (account && !brokerOptions.includes(account.broker)) brokerOptions.unshift(account.broker)

  const lastFourValid = lastFour === '' || /^\d{4}$/.test(lastFour)
  const moneyValid = isMoneyInput(netLiq) && isMoneyInput(cash) && isMoneyInput(monthlyTarget)
  const pctValid = [yieldTarget, maxPosition, maxSpeculative, maxMargin, cashReserve, defensiveLoss].every(isPctInput)
  const canSave = nickname.trim().length > 0 && lastFourValid && moneyValid && pctValid && !saving
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

  const orNull = (v: string) => (v === '' ? null : v)

  function goalsPayload(): AccountGoals {
    return {
      objective,
      assignment_stance: stance,
      monthly_premium_target: orNull(monthlyTarget),
      annual_yield_target_pct: orNull(yieldTarget),
      max_position_pct: orNull(maxPosition),
      max_speculative_position_pct: orNull(maxSpeculative),
      max_margin_used_pct: orNull(maxMargin),
      min_cash_reserve_pct: orNull(cashReserve),
      defensive_at_loss_pct: orNull(defensiveLoss),
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
          ...goalsPayload(),
        })
      } else {
        saved = await accountsApi.create({
          broker, nickname: nickname.trim(), last_four: lastFour || null,
          category_ids: categoryIds, default_category_id: defaultCategoryId || null,
          ...factsPayload(),
          ...goalsPayload(),
        })
      }
      await refresh()
      onOpenChange(false)
      onSaved?.(saved)
    } catch (e) {
      if (e instanceof ApiError && e.fields.length > 0) {
        // Highlight every named field; show the message once, under the last one.
        const errs: Partial<Record<ProfileField, string>> = {}
        e.fields.forEach((f, i) => { errs[f as ProfileField] = i === e.fields.length - 1 ? e.message : '' })
        setFieldErrors(errs)
        const inGoals = GOAL_FIELDS.includes(e.fields[e.fields.length - 1] as ProfileField)
        ;(inGoals ? goalsRef : factsRef).current?.scrollIntoView({ block: 'nearest' })
      } else {
        setError(e instanceof Error ? e.message : 'Save failed')
      }
    } finally {
      setSaving(false)
    }
  }

  const valuesAsOf = account?.values_as_of ?? null
  const valuesStale = valuesAreStale(valuesAsOf)

  // House default numbers come from the API (any account carries them), never from the frontend.
  const limitsSource = account?.limits ?? accounts[0]?.limits
  const defaultOf = (f: LimitField) => (limitsSource ? parseFloat(limitsSource[f].default) : null)
  // What an empty input resolves to, mirroring the server: speculative is capped at the position
  // limit; margin is 0 on a cash account.
  const positionEffective = maxPosition !== '' ? parseFloat(maxPosition) : defaultOf('max_position_pct')
  const specDefault = defaultOf('max_speculative_position_pct')
  const specCapped = specDefault !== null && positionEffective !== null && specDefault > positionEffective
  const isCash = marginType === 'cash'
  const marginValue = maxMargin === '' ? 0 : parseFloat(maxMargin)
  const hideMarginLimit = isCash && marginValue === 0 && fieldErrors.max_margin_used_pct === undefined

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

            <fieldset ref={goalsRef} aria-labelledby="account-goals-heading"
              className="scroll-mt-4 border-t border-gray-200 pt-4 text-sm">
              <h3 id="account-goals-heading" className="font-semibold text-gray-900">Goal and preferences</h3>
              <p className="mt-0.5 text-xs text-gray-500">
                What matters most among the trades this account allows. All optional.
              </p>

              <div className="mt-3 space-y-4">
                <Segmented label="Objective" choices={OBJECTIVES} value={objective}
                  onChange={changeFact(setObjective)} error={fieldErrors.objective} />
                <Segmented label="Assignment stance" choices={ASSIGNMENT_STANCES} value={stance}
                  onChange={changeFact(setStance)} error={fieldErrors.assignment_stance} />

                <div className="grid grid-cols-2 gap-3">
                  <MoneyInput label="Monthly premium target" value={monthlyTarget}
                    onChange={changeFact(setMonthlyTarget)} error={fieldErrors.monthly_premium_target} />
                  <PctInput label="Annual yield target" value={yieldTarget}
                    onChange={changeFact(setYieldTarget)} error={fieldErrors.annual_yield_target_pct} />
                </div>

                <div>
                  <div className="font-medium text-gray-700">Limits</div>
                  <p className="text-xs text-gray-500">Leave blank to use the house default.</p>
                  <div className="mt-2 space-y-3">
                    <LimitInput field="max_position_pct" value={maxPosition} onChange={changeFact(setMaxPosition)} houseDefault={defaultOf('max_position_pct')}
                      emptyLabel="default" emptyValue={defaultOf('max_position_pct')}
                      error={fieldErrors.max_position_pct} />
                    <LimitInput field="max_speculative_position_pct" value={maxSpeculative}
                      onChange={changeFact(setMaxSpeculative)}
                      houseDefault={specDefault}
                      emptyLabel={specCapped ? SOURCE_LABELS.position_limit : 'default'}
                      emptyValue={specCapped ? positionEffective : specDefault}
                      error={fieldErrors.max_speculative_position_pct} />
                    {hideMarginLimit ? (
                      <div>
                        <div className="font-medium text-gray-700">{LIMIT_LABELS.max_margin_used_pct.label}</div>
                        <p className="text-xs text-gray-500">Cash accounts can’t borrow, so margin use is 0.</p>
                      </div>
                    ) : (
                      <LimitInput field="max_margin_used_pct" value={maxMargin} onChange={changeFact(setMaxMargin)} houseDefault={defaultOf('max_margin_used_pct')}
                        emptyLabel={isCash ? SOURCE_LABELS.cash_account : 'default'}
                        emptyValue={isCash ? 0 : defaultOf('max_margin_used_pct')}
                        warning={isCash && marginValue > 0 ? 'A cash account can’t use margin: clear this limit.' : undefined}
                        error={fieldErrors.max_margin_used_pct} />
                    )}
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <PctInput label="Minimum cash reserve" value={cashReserve} onChange={changeFact(setCashReserve)}
                    hint="Of the account, kept in cash." error={fieldErrors.min_cash_reserve_pct} />
                  <PctInput label="Defensive at loss" value={defensiveLoss} onChange={changeFact(setDefensiveLoss)}
                    hint="Unrealized loss on one position that should turn guidance defensive."
                    error={fieldErrors.defensive_at_loss_pct} />
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

function Segmented<T extends string>({ label, choices, value, onChange, error }: {
  label: string
  choices: FactChoice<T>[]
  value: T | null
  onChange: (value: T | null) => void
  error?: string
}) {
  const id = useId()
  const hint = choiceFor(choices, value)?.hint
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span id={id} className="font-medium text-gray-700">{label}</span>
        {value !== null && (
          <button type="button" onClick={() => onChange(null)} className="text-xs text-gray-500 hover:text-gray-700 hover:underline">
            Clear
          </button>
        )}
      </div>
      <div role="radiogroup" aria-labelledby={id} aria-invalid={error !== undefined}
        className={`mt-1 inline-flex w-full overflow-hidden rounded border ${error !== undefined ? 'border-red-400' : 'border-gray-300'}`}>
        {choices.map((c, i) => {
          const selected = c.value === value
          return (
            <button key={c.value} type="button" role="radio" aria-checked={selected}
              onClick={() => onChange(c.value)}
              className={`flex-1 px-2 py-1.5 text-sm ${i > 0 ? 'border-l border-gray-300' : ''} ${selected ? 'bg-blue-600 font-medium text-white' : 'bg-white text-gray-700 hover:bg-gray-50'}`}>
              {c.label}
            </button>
          )
        })}
      </div>
      <p className="mt-1 text-xs text-gray-500">{hint ?? 'Not set yet.'}</p>
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  )
}

function PctField({ id, value, onChange, placeholder, invalid }: {
  id: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  invalid: boolean
}) {
  return (
    <div className="relative">
      <input id={id} value={value} onChange={e => onChange(e.target.value.replace(/[%\s]/g, ''))}
        inputMode="decimal" placeholder={placeholder ?? '—'} aria-invalid={invalid}
        className={`block w-full rounded border py-1.5 pl-2 pr-6 text-sm ${invalid ? 'border-red-400' : 'border-gray-300'}`} />
      <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-gray-400">%</span>
    </div>
  )
}

function PctInput({ label, value, onChange, hint, error }: {
  label: string
  value: string
  onChange: (value: string) => void
  hint?: string
  error?: string
}) {
  const id = useId()
  const badFormat = !isPctInput(value)
  return (
    <div>
      <label htmlFor={id} className="block font-medium text-gray-700">{label}</label>
      <div className="mt-1"><PctField id={id} value={value} onChange={onChange} invalid={badFormat || error !== undefined} /></div>
      {hint && <p className="mt-1 text-xs text-gray-500">{hint}</p>}
      {badFormat && <p className="mt-1 text-xs text-red-600">A percent, up to 2 decimals.</p>}
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  )
}

/** A defaulted limit: blank shows what it resolves to; typing overrides; "Use default" clears it. */
function LimitInput({ field, value, onChange, houseDefault, emptyLabel, emptyValue, warning, error }: {
  field: LimitField
  value: string
  onChange: (value: string) => void
  houseDefault: number | null
  /** What a blank input resolves to, and why. */
  emptyLabel: string
  emptyValue: number | null
  warning?: string
  error?: string
}) {
  const id = useId()
  const { label, hint } = LIMIT_LABELS[field]
  const badFormat = !isPctInput(value)
  const overridden = value !== ''
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={id} className="font-medium text-gray-700">{label}</label>
        <span className="text-xs text-gray-500">
          {overridden
            ? <>Your value{houseDefault !== null && <> · default {houseDefault}%</>}</>
            : <>{emptyValue !== null ? `${emptyValue}%` : '—'} <span className="rounded bg-gray-100 px-1.5 py-0.5 text-gray-600">{emptyLabel}</span></>}
        </span>
      </div>
      <div className="mt-1 flex items-center gap-2">
        <div className="w-28">
          <PctField id={id} value={value} onChange={onChange}
            placeholder={emptyValue !== null ? String(emptyValue) : undefined}
            invalid={badFormat || error !== undefined} />
        </div>
        {overridden && (
          <button type="button" onClick={() => onChange('')}
            className="text-xs text-blue-600 hover:underline">Use default</button>
        )}
      </div>
      <p className="mt-1 text-xs text-gray-500">{hint}</p>
      {warning && <p className="mt-1 text-xs text-amber-700">{warning}</p>}
      {badFormat && <p className="mt-1 text-xs text-red-600">A percent, up to 2 decimals.</p>}
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  )
}
