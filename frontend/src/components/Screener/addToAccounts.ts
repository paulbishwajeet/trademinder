import { screenerApi } from '../../api/screener'
import { ApiError } from '../../api/client'
import type { ScreenerFetchedFields, ScreenerRow } from '../../types'

export interface AddToAccountsResult {
  /** Row from the last successful add (null when nothing was added). */
  row: ScreenerRow | null
  /** Account ids that already had the symbol (409). */
  already: string[]
  failed: { accountId: string; message: string }[]
}

/** Adds a symbol to each account in turn; a 409 means "already there", not a failure. */
export async function addToAccounts(
  base: { symbol: string; category?: string; precomputed?: ScreenerFetchedFields },
  accountIds: string[],
): Promise<AddToAccountsResult> {
  const result: AddToAccountsResult = { row: null, already: [], failed: [] }
  for (const accountId of accountIds) {
    try {
      // Symbol-level fields only matter until the row exists.
      const payload = result.row ? { symbol: base.symbol, account_id: accountId } : { ...base, account_id: accountId }
      const row = await screenerApi.add(payload)
      result.row = row
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) result.already.push(accountId)
      else result.failed.push({ accountId, message: err instanceof ApiError ? err.message : 'Failed to add symbol' })
    }
  }
  return result
}

/** One-line summary of a multi-account add, or null when everything was added cleanly. */
export function summarizeAdd(res: AddToAccountsResult, nameOf: (id: string) => string): string | null {
  const parts: string[] = []
  if (res.already.length) parts.push(`Already in ${res.already.map(nameOf).join(', ')}`)
  if (res.failed.length) parts.push(res.failed.map(f => `${nameOf(f.accountId)}: ${f.message}`).join('; '))
  return parts.length ? parts.join('. ') : null
}
