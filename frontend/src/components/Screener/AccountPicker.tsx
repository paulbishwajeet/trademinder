import { accountLabel } from '../../lib/paths'
import { useAccounts } from '../../context/AccountsContext'

/** Small nickname pill for an account (Research view). */
export function AccountBadge({ accountId, nickname, lastFour }: { accountId?: string; nickname?: string; lastFour?: string | null }) {
  const { accounts } = useAccounts()
  const acct = accountId ? accounts.find(a => a.id === accountId) : undefined
  const name = nickname ?? acct?.nickname ?? 'Unknown'
  const title = accountLabel({ nickname: name, last_four: lastFour ?? acct?.last_four ?? null })
  return (
    <span title={title} className="px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded text-[10px] font-medium whitespace-nowrap">
      {name}
    </span>
  )
}

/** Checkbox list of the user's active accounts. `disabledIds` are shown checked + disabled (already members). */
export function AccountMultiSelect({
  selected,
  onChange,
  disabledIds = [],
}: {
  selected: string[]
  onChange: (ids: string[]) => void
  disabledIds?: string[]
}) {
  const { active } = useAccounts()
  const toggle = (id: string) =>
    onChange(selected.includes(id) ? selected.filter(x => x !== id) : [...selected, id])
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-600">
      <span className="text-gray-500">Add to:</span>
      {active.map(a => {
        const isMember = disabledIds.includes(a.id)
        return (
          <label key={a.id} className={`flex items-center gap-1 ${isMember ? 'text-gray-400' : 'cursor-pointer'}`} title={isMember ? 'Already in this account' : undefined}>
            <input
              type="checkbox"
              checked={isMember || selected.includes(a.id)}
              disabled={isMember}
              onChange={() => toggle(a.id)}
            />
            {accountLabel(a)}
          </label>
        )
      })}
    </div>
  )
}
