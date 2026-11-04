// frontend/src/lib/paths.ts
// Route builders — the URL is the only source of the current account.

export const ACCOUNT_PAGES = ['trades', 'wheel', 'spreads', 'margin', 'screener', 'chain', 'scanner'] as const
export type AccountPage = (typeof ACCOUNT_PAGES)[number]

export const RESEARCH_PAGES = ['screener', 'chain', 'scanner'] as const
export type ResearchPage = (typeof RESEARCH_PAGES)[number]

export const ACCOUNT_PAGE_LABELS: Record<AccountPage, string> = {
  trades: 'Trades', wheel: 'WHEEL', spreads: 'Spreads', margin: 'Margin',
  screener: 'Screener', chain: 'Chain', scanner: 'Scanner',
}

function withQuery(path: string, query?: Record<string, string | undefined> | string): string {
  if (!query) return path
  if (typeof query === 'string') return query ? `${path}${query.startsWith('?') ? '' : '?'}${query}` : path
  const entries = Object.entries(query).filter((e): e is [string, string] => e[1] !== undefined && e[1] !== '')
  return entries.length ? `${path}?${new URLSearchParams(entries).toString()}` : path
}

export function accountPath(accountId: string, page: AccountPage, query?: Record<string, string | undefined> | string): string {
  return withQuery(`/accounts/${accountId}/${page}`, query)
}

export function tradePath(accountId: string, tradeId: string): string {
  return `/accounts/${accountId}/trades/${tradeId}`
}

export function researchPath(page: ResearchPage, query?: Record<string, string | undefined> | string): string {
  return withQuery(`/research/${page}`, query)
}

/** Screener/Chain/Scanner link that stays inside the current account, or goes to Research outside one. */
export function scopedResearchPath(
  accountId: string | null | undefined, page: ResearchPage, query?: Record<string, string | undefined>,
): string {
  return accountId ? accountPath(accountId, page, query) : researchPath(page, query)
}

export function accountLabel(a: { nickname: string; last_four: string | null }): string {
  return a.last_four ? `${a.nickname} ····${a.last_four}` : a.nickname
}
