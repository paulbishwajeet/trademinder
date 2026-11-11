// frontend/src/components/Layout/Sidebar.tsx
import { useEffect, useState, type DragEvent } from 'react'
import { Link, NavLink, useMatch, useNavigate } from 'react-router-dom'
import * as Collapsible from '@radix-ui/react-collapsible'
import { ChevronDown, ChevronRight, GripVertical, LayoutDashboard, LogOut, Plus, Settings, Shield, Telescope } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { accountsApi } from '../../api/accounts'
import { useAccounts } from '../../context/AccountsContext'
import { AccountDialog } from '../Accounts/AccountDialog'
import {
  ACCOUNT_PAGES, ACCOUNT_PAGE_LABELS, RESEARCH_PAGES, accountPath, researchPath, type AccountPage,
} from '../../lib/paths'
import type { BrokerageAccount } from '../../types'

function itemClass({ isActive }: { isActive: boolean }): string {
  return `flex items-center gap-2 rounded px-2 py-1.5 text-sm ${
    isActive ? 'bg-blue-600 font-medium text-white' : 'text-gray-700 hover:bg-gray-100'
  }`
}

function GroupLabel({ children }: { children: string }) {
  return <p className="px-2 pb-1 pt-4 text-[11px] font-semibold uppercase tracking-wider text-gray-400">{children}</p>
}

export function Sidebar() {
  const { active, refresh } = useAccounts()
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const match = useMatch('/accounts/:accountId/:page/*')
  const currentAccountId = match?.params.accountId ?? null
  const currentPage = (ACCOUNT_PAGES as readonly string[]).includes(match?.params.page ?? '')
    ? (match!.params.page as AccountPage) : 'wheel'

  const [order, setOrder] = useState<BrokerageAccount[]>(active)
  const [dragId, setDragId] = useState<string | null>(null)
  const [overId, setOverId] = useState<string | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<BrokerageAccount | null>(null)
  const [reorderError, setReorderError] = useState<string | null>(null)

  useEffect(() => { setOrder(active) }, [active])

  function openCreate() { setEditing(null); setDialogOpen(true) }
  function openEdit(account: BrokerageAccount) { setEditing(account); setDialogOpen(true) }

  function handleDragStart(e: DragEvent, id: string) {
    setDragId(id)
    e.dataTransfer.effectAllowed = 'move'
  }

  function handleDragOver(e: DragEvent, id: string) {
    if (!dragId) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    if (overId !== id) setOverId(id)
  }

  async function handleDrop(e: DragEvent, targetId: string) {
    e.preventDefault()
    const sourceId = dragId
    setDragId(null)
    setOverId(null)
    if (!sourceId || sourceId === targetId) return
    const ids = order.map(a => a.id)
    const from = ids.indexOf(sourceId)
    const to = ids.indexOf(targetId)
    const next = [...order]
    const [moved] = next.splice(from, 1)
    next.splice(to, 0, moved)
    setOrder(next)  // optimistic
    try {
      await accountsApi.reorder(next.map(a => a.id))
      setReorderError(null)
    } catch (err) {
      setReorderError(err instanceof Error ? err.message : 'Reorder failed')
    }
    await refresh()
  }

  return (
    <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col border-r border-gray-200 bg-white">
      <div className="px-4 py-4">
        <Link to="/" className="text-base font-bold text-gray-900">TradeMinder</Link>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pb-4">
        <NavLink to="/" end className={itemClass}>
          <LayoutDashboard size={15} /> Dashboard
        </NavLink>

        <GroupLabel>Accounts</GroupLabel>
        <ul className="space-y-0.5">
          {order.map(account => {
            const isCurrent = account.id === currentAccountId
            return (
              <li key={account.id}
                onDragOver={e => handleDragOver(e, account.id)}
                onDrop={e => handleDrop(e, account.id)}
                className={`rounded ${overId === account.id && dragId !== account.id ? 'ring-2 ring-blue-300' : ''} ${dragId === account.id ? 'opacity-50' : ''}`}
              >
                <Collapsible.Root open={isCurrent}>
                  <div className={`group flex items-center rounded ${isCurrent ? 'bg-gray-100' : 'hover:bg-gray-50'}`}>
                    <span
                      draggable
                      onDragStart={e => handleDragStart(e, account.id)}
                      onDragEnd={() => { setDragId(null); setOverId(null) }}
                      title="Drag to reorder"
                      className="cursor-grab px-0.5 text-gray-300 opacity-0 group-hover:opacity-100 active:cursor-grabbing"
                    >
                      <GripVertical size={14} />
                    </span>
                    <button
                      onClick={() => navigate(accountPath(account.id, currentPage))}
                      className="flex min-w-0 flex-1 items-center gap-1 py-1.5 text-left text-sm"
                      aria-expanded={isCurrent}
                    >
                      {isCurrent ? <ChevronDown size={14} className="shrink-0 text-gray-500" /> : <ChevronRight size={14} className="shrink-0 text-gray-400" />}
                      <span className={`truncate ${isCurrent ? 'font-semibold text-gray-900' : 'text-gray-700'}`}>{account.nickname}</span>
                      {account.last_four && <span className="shrink-0 text-xs text-gray-400">····{account.last_four}</span>}
                    </button>
                    <button onClick={() => openEdit(account)} title={`Edit ${account.nickname}`}
                      className="rounded p-1 text-gray-400 hover:bg-gray-200 hover:text-gray-700">
                      <Settings size={13} />
                    </button>
                  </div>
                  <Collapsible.Content>
                    <ul className="mb-1 ml-5 mt-0.5 space-y-0.5 border-l border-gray-200 pl-2">
                      {ACCOUNT_PAGES.map(page => (
                        <li key={page}>
                          <NavLink to={accountPath(account.id, page)} className={itemClass}>
                            {ACCOUNT_PAGE_LABELS[page]}
                          </NavLink>
                        </li>
                      ))}
                    </ul>
                  </Collapsible.Content>
                </Collapsible.Root>
              </li>
            )
          })}
        </ul>
        {reorderError && <p className="px-2 pt-1 text-xs text-red-600">{reorderError}</p>}
        <button onClick={openCreate}
          className="mt-1 flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm text-blue-600 hover:bg-blue-50">
          <Plus size={14} /> Add account
        </button>

        <GroupLabel>Research</GroupLabel>
        <ul className="space-y-0.5">
          {RESEARCH_PAGES.map(page => (
            <li key={page}>
              <NavLink to={researchPath(page)} className={itemClass}>
                <Telescope size={14} /> {ACCOUNT_PAGE_LABELS[page]}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      <div className="border-t border-gray-200 p-2">
        {user?.role === 'admin' && (
          <NavLink to="/admin" className={itemClass}>
            <Shield size={15} /> Admin
          </NavLink>
        )}
        <NavLink to="/settings/accounts" className={itemClass}>
          <Settings size={15} /> Settings
        </NavLink>
        <div className="mt-2 flex items-center gap-2 border-t border-gray-100 px-2 pt-2">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-gray-800">{user?.display_name || user?.email}</p>
            <p className="truncate text-xs text-gray-400">{user?.email}</p>
          </div>
          <button onClick={() => { void logout() }} title="Log out" aria-label="Log out"
            className="rounded p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700">
            <LogOut size={15} />
          </button>
        </div>
      </div>

      <AccountDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        account={editing}
        onSaved={saved => { if (!editing) navigate(accountPath(saved.id, 'wheel')) }}
      />
    </aside>
  )
}
