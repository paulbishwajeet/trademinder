// frontend/src/lib/accountGoals.ts
// Goal and preferences vocabulary for the UI: labels, one-line explanations, limit-source labels and
// percent helpers. The values mirror backend/app/services/account_goals.py; the house default numbers
// come from the API (limits.*.default), never from here.
import type { AssignmentStance, BrokerageAccount, LimitField, LimitSource, Objective } from '../types'
import type { FactChoice } from './accountFacts'

export const OBJECTIVES: FactChoice<Objective>[] = [
  { value: 'income', label: 'Income', hint: 'Collect steady premium; growth is secondary.' },
  { value: 'growth', label: 'Growth', hint: 'Grow the account; premium supports it but isn’t the point.' },
  { value: 'mixed', label: 'Mixed', hint: 'Balance premium income with long-term growth.' },
]

export const ASSIGNMENT_STANCES: FactChoice<AssignmentStance>[] = [
  { value: 'willing', label: 'Willing', hint: 'Happy to own the shares at the strike.' },
  { value: 'selective', label: 'Selective', hint: 'Depends on the ticker: own some, avoid others.' },
  { value: 'unwilling', label: 'Unwilling', hint: 'Avoid assignment: roll or close before it happens.' },
]

export const LIMIT_FIELDS: LimitField[] = ['max_position_pct', 'max_speculative_position_pct', 'max_margin_used_pct']

export const LIMIT_LABELS: Record<LimitField, { label: string; hint: string }> = {
  max_position_pct: { label: 'Max position size', hint: 'The most of the account in one ticker.' },
  max_speculative_position_pct: { label: 'Max speculative position', hint: 'The same, for tickers in the SPECULATIVE category.' },
  max_margin_used_pct: { label: 'Max margin used', hint: 'The most of the account’s margin to use.' },
}

export const SOURCE_LABELS: Record<LimitSource, string> = {
  account: 'your value',
  default: 'default',
  cash_account: 'cash account',
  position_limit: 'capped at position limit',
}

/** "Income · Willing" for the accounts table. */
export function goalsSummary(a: BrokerageAccount): string {
  return [
    OBJECTIVES.find(o => o.value === a.objective)?.label,
    ASSIGNMENT_STANCES.find(s => s.value === a.assignment_stance)?.label,
  ].filter(Boolean).join(' · ')
}

/** A percent input: up to 3 integer digits and 2 decimals, or blank. Range is checked by the server. */
export function isPctInput(value: string): boolean {
  return value === '' || /^\d{1,3}(\.\d{0,2})?$/.test(value)
}

/** "10.00" → "10%"; "2.50" → "2.5%". */
export function formatPct(value: string | null): string {
  if (value === null) return '—'
  const n = parseFloat(value)
  return Number.isNaN(n) ? '—' : `${n}%`
}
