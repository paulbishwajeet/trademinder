// frontend/src/pages/LegacyRedirects.tsx
// Old flat URLs (/trades, /wheel, /screener?…) → their account / Research equivalents, query string kept.
import { useEffect, useState } from 'react'
import { Navigate, useLocation, useParams } from 'react-router-dom'
import { tradesApi } from '../api/trades'
import { useAccounts } from '../context/AccountsContext'
import { NotFound } from '../components/Layout/NotFound'
import { accountPath, researchPath, tradePath, type AccountPage, type ResearchPage } from '../lib/paths'

/** /trades, /wheel, /spreads, /margin → the default account's page. */
export function LegacyAccountRedirect({ page }: { page: AccountPage }) {
  const { defaultAccount, loading } = useAccounts()
  const { search } = useLocation()
  if (loading) return null
  if (!defaultAccount) return <NotFound title="No account" message="Create an account to get started." />
  return <Navigate to={accountPath(defaultAccount.id, page, search)} replace />
}

/** /screener, /chain, /scanner → Research. */
export function LegacyResearchRedirect({ page }: { page: ResearchPage }) {
  const { search } = useLocation()
  return <Navigate to={researchPath(page, search)} replace />
}

/** /trades/:id → that trade's account. */
export function LegacyTradeRedirect() {
  const { tradeId } = useParams()
  const [target, setTarget] = useState<string | null>(null)
  const [missing, setMissing] = useState(false)

  useEffect(() => {
    if (!tradeId) return
    tradesApi.get(tradeId)
      .then(t => setTarget(tradePath(t.account_id, t.id)))
      .catch(() => setMissing(true))
  }, [tradeId])

  if (missing) return <NotFound title="Trade not found" />
  return target ? <Navigate to={target} replace /> : null
}
