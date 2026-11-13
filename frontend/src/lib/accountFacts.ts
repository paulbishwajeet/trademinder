// frontend/src/lib/accountFacts.ts
// Account facts vocabulary for the UI: labels, one-line explanations, and display helpers.
// The values mirror backend/app/services/account_facts.py.
import type { AccountPurpose, BrokerageAccount, MarginType, OptionsTier, TaxTreatment } from '../types'

export interface FactChoice<T extends string> {
  value: T
  label: string
  hint: string
}

export const TAX_TREATMENTS: FactChoice<TaxTreatment>[] = [
  { value: 'taxable', label: 'Taxable', hint: 'A regular brokerage account: gains and premium are taxed each year.' },
  { value: 'traditional_ira', label: 'Traditional IRA', hint: 'Tax-deferred: taxed when you withdraw, not when you trade.' },
  { value: 'roth_ira', label: 'Roth IRA', hint: 'Tax-free growth: qualified withdrawals are not taxed.' },
  { value: 'other_tax_advantaged', label: 'Other tax-advantaged', hint: 'Another sheltered account, such as a 401(k), HSA or SEP.' },
]

export const ACCOUNT_PURPOSES: FactChoice<AccountPurpose>[] = [
  { value: 'trading', label: 'Trading', hint: 'Active income trading, such as the wheel or spreads.' },
  { value: 'long_term', label: 'Long term', hint: 'Mostly buy-and-hold; options only around long-term holdings.' },
]

export const MARGIN_TYPES: FactChoice<MarginType>[] = [
  { value: 'cash', label: 'Cash', hint: 'No borrowing: every trade is fully paid for or fully secured.' },
  { value: 'limited_margin', label: 'Limited margin', hint: 'Restricted margin some brokers allow in IRAs: no borrowing, but no settlement waits.' },
  { value: 'margin', label: 'Margin', hint: 'Standard (Reg T) margin: you can borrow against the account.' },
  { value: 'portfolio_margin', label: 'Portfolio margin', hint: 'Risk-based margin on the whole portfolio, usually the lowest requirements.' },
]

// Cumulative: each tier allows everything above it in this list.
export const OPTIONS_TIERS: FactChoice<OptionsTier>[] = [
  { value: 'none', label: 'None', hint: 'No options trading.' },
  { value: 'covered', label: 'Covered', hint: 'Covered calls only, against shares you own.' },
  { value: 'cash_secured_and_long', label: 'Cash-secured and long', hint: 'Adds cash-secured puts and buying calls and puts.' },
  { value: 'spreads', label: 'Spreads', hint: 'Adds defined-risk spreads, such as verticals and iron condors.' },
  { value: 'uncovered', label: 'Uncovered', hint: 'Adds naked or undefined-risk options. Needs a margin account.' },
]

export function choiceFor<T extends string>(choices: FactChoice<T>[], value: T | null): FactChoice<T> | undefined {
  return choices.find(c => c.value === value)
}

export function labelFor<T extends string>(choices: FactChoice<T>[], value: T | null): string | null {
  return choiceFor(choices, value)?.label ?? null
}

/** "Roth IRA · Cash · Covered (Level 1)" for the accounts table. */
export function factsSummary(a: BrokerageAccount): string {
  const tier = labelFor(OPTIONS_TIERS, a.options_tier)
  return [
    labelFor(TAX_TREATMENTS, a.tax_treatment),
    labelFor(ACCOUNT_PURPOSES, a.account_purpose),
    labelFor(MARGIN_TYPES, a.margin_type),
    tier && (a.options_level_label ? `${tier} (${a.options_level_label})` : tier),
  ].filter(Boolean).join(' · ')
}

export const STALE_VALUES_DAYS = 7

export function valuesAreStale(valuesAsOf: string | null, now: Date = new Date()): boolean {
  if (!valuesAsOf) return false
  return now.getTime() - new Date(valuesAsOf).getTime() > STALE_VALUES_DAYS * 24 * 60 * 60 * 1000
}

export function formatMoney(value: string | null): string {
  if (value === null) return '—'
  const n = parseFloat(value)
  if (Number.isNaN(n)) return '—'
  return n.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
}

/** A money input: digits with at most two decimals, or blank. */
export function isMoneyInput(value: string): boolean {
  return value === '' || /^\d{1,12}(\.\d{0,2})?$/.test(value)
}

/** Stored "1234.50" → input "1234.5"; null → "". */
export function moneyToInput(value: string | null): string {
  if (value === null) return ''
  const n = parseFloat(value)
  return Number.isNaN(n) ? '' : String(n)
}
