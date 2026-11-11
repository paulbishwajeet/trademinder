// frontend/src/components/Layout/AccountLayout.tsx
import { Outlet, useParams } from 'react-router-dom'
import { CurrentAccountProvider, useAccounts } from '../../context/AccountsContext'
import { NotFound } from './NotFound'

/** Resolves :accountId from the URL. Unknown, foreign or archived ids get a not-found state. */
export function AccountLayout() {
  const { accountId } = useParams()
  const { active, loading } = useAccounts()
  if (loading) return <div className="p-6 text-sm text-gray-500">Loading account…</div>
  const account = active.find(a => a.id === accountId)
  if (!account) return <NotFound title="Account not found" message="This account doesn't exist, isn't yours, or has been archived." />
  return (
    <CurrentAccountProvider value={account}>
      {/* keyed so every account page remounts — no state (e.g. a Margin CSV) carries across accounts */}
      <Outlet key={account.id} />
    </CurrentAccountProvider>
  )
}
