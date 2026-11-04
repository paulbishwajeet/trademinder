// frontend/src/context/AccountsContext.tsx
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { accountsApi } from '../api/accounts'
import { categoriesApi } from '../api/categories'
import type { BrokerageAccount, Category } from '../types'

interface AccountsState {
  /** Every account, archived included, in sort order. */
  accounts: BrokerageAccount[]
  active: BrokerageAccount[]
  defaultAccount: BrokerageAccount | null
  /** The user's whole category library. */
  categories: Category[]
  loading: boolean
  error: string | null
  /** Reload accounts + categories — call after any account mutation. */
  refresh: () => Promise<void>
}

const AccountsContext = createContext<AccountsState | null>(null)

/** Loads the account list once at app start and caches it; refresh() after mutations. */
export function AccountsProvider({ children }: { children: ReactNode }) {
  const [accounts, setAccounts] = useState<BrokerageAccount[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [accts, cats] = await Promise.all([accountsApi.list(true), categoriesApi.list()])
      setAccounts(accts)
      setCategories(cats)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load accounts')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void refresh() }, [refresh])

  const value = useMemo<AccountsState>(() => {
    const active = accounts.filter(a => !a.is_archived)
    return {
      accounts, active, categories, loading, error, refresh,
      defaultAccount: active.find(a => a.is_default) ?? active[0] ?? null,
    }
  }, [accounts, categories, loading, error, refresh])

  return <AccountsContext.Provider value={value}>{children}</AccountsContext.Provider>
}

export function useAccounts(): AccountsState {
  const ctx = useContext(AccountsContext)
  if (!ctx) throw new Error('useAccounts must be used inside <AccountsProvider>')
  return ctx
}

// ── Current account (derived from the URL by AccountLayout) ──────────────

const CurrentAccountContext = createContext<BrokerageAccount | null>(null)

export const CurrentAccountProvider = CurrentAccountContext.Provider

/** The account whose page is open, or null on the Dashboard / Research / Settings. */
export function useCurrentAccount(): BrokerageAccount | null {
  return useContext(CurrentAccountContext)
}

/** For pages that only exist inside an account. */
export function useRequiredAccount(): BrokerageAccount {
  const account = useContext(CurrentAccountContext)
  if (!account) throw new Error('This page must be rendered inside an account route')
  return account
}

/** The categories an account uses (all of the library outside an account). */
export function useAccountCategories(account: BrokerageAccount | null): Category[] {
  const { categories } = useAccounts()
  return useMemo(
    () => (account ? categories.filter(c => account.category_ids.includes(c.id)) : categories),
    [account, categories],
  )
}
