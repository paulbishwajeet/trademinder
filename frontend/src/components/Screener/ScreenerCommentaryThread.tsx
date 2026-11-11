import { useState } from 'react'
import type { ScreenerCommentary } from '../../types'
import { screenerApi } from '../../api/screener'
import { useAccounts, useCurrentAccount } from '../../context/AccountsContext'
import { accountLabel } from '../../lib/paths'
import { AccountBadge } from './AccountPicker'

interface Props {
  symbol: string
  entries: ScreenerCommentary[]
  onRefresh: () => void
}

function CommentaryEntry({ entry, onRefresh, showAccount }: { entry: ScreenerCommentary; onRefresh: () => void; showAccount: boolean }) {
  const [editing, setEditing] = useState(false)
  const [note, setNote] = useState(entry.note)
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    if (!note.trim()) return
    setSaving(true)
    try {
      await screenerApi.commentary.update(entry.id, { note: note.trim(), tags: entry.tags ?? undefined })
      setEditing(false)
      onRefresh()
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!confirm('Delete this note?')) return
    await screenerApi.commentary.remove(entry.id)
    onRefresh()
  }

  return (
    <div className="bg-gray-50 rounded p-3 text-sm">
      <div className="flex justify-between items-start">
        <span className="flex items-center gap-2 text-gray-400 text-xs">
          {entry.created_at.slice(0, 10)}{entry.updated_at ? ' (edited)' : ''}
          {showAccount && (
            <AccountBadge accountId={entry.account_id} nickname={entry.account?.nickname} lastFour={entry.account?.last_four} />
          )}
        </span>
        <div className="space-x-2">
          {!editing && (
            <button onClick={() => setEditing(true)} className="text-blue-500 hover:text-blue-700 text-xs">Edit</button>
          )}
          <button onClick={handleDelete} className="text-red-400 hover:text-red-600 text-xs">×</button>
        </div>
      </div>
      {editing ? (
        <div className="mt-1 space-y-2">
          <textarea
            value={note}
            onChange={e => setNote(e.target.value)}
            rows={3}
            className="w-full border border-gray-300 rounded px-2 py-1 text-sm"
          />
          <div className="space-x-2">
            <button
              onClick={handleSave}
              disabled={saving}
              className="text-xs px-2 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:bg-gray-300"
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button
              onClick={() => { setEditing(false); setNote(entry.note) }}
              className="text-xs px-2 py-1 text-gray-500 hover:text-gray-700"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <p className="mt-1 text-gray-800 whitespace-pre-wrap">{entry.note}</p>
      )}
      {entry.tags && entry.tags.length > 0 && (
        <div className="flex gap-1 mt-1">
          {entry.tags.map(tag => (
            <span key={tag} className="px-1.5 py-0.5 bg-blue-100 text-blue-600 rounded text-xs">{tag}</span>
          ))}
        </div>
      )}
    </div>
  )
}

export function ScreenerCommentaryThread({ symbol, entries, onRefresh }: Props) {
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const account = useCurrentAccount()
  const { active, defaultAccount } = useAccounts()
  // Research only: which account the new note belongs to (defaults to the default account).
  const [picked, setPicked] = useState<string | null>(null)
  const targetAccountId = account?.id ?? picked ?? defaultAccount?.id

  const handleAdd = async () => {
    if (!note.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      await screenerApi.commentary.add(symbol, { note: note.trim(), account_id: targetAccountId })
      setNote('')
      onRefresh()
    } catch {
      setError('Failed to add note. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-gray-700">Commentary</h3>
      {error && <p className="text-red-500 text-xs">{error}</p>}
      <div className="space-y-2">
        <textarea
          value={note}
          onChange={e => setNote(e.target.value)}
          rows={2}
          placeholder="Add a note…"
          className="w-full border border-gray-300 rounded px-2 py-1 text-sm"
        />
        <div className="flex items-center gap-2">
          <button
            onClick={handleAdd}
            disabled={submitting || !note.trim()}
            className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:bg-gray-300"
          >
            {submitting ? 'Adding…' : 'Add Note'}
          </button>
          {!account && (
            <label className="flex items-center gap-1 text-xs text-gray-500">
              to
              <select
                value={targetAccountId ?? ''}
                onChange={e => setPicked(e.target.value)}
                className="border border-gray-300 rounded px-1 py-0.5 text-xs"
              >
                {active.map(a => <option key={a.id} value={a.id}>{accountLabel(a)}</option>)}
              </select>
            </label>
          )}
        </div>
      </div>
      <div className="space-y-3 mt-4">
        {entries.length === 0 && <p className="text-gray-400 text-sm">No notes yet.</p>}
        {entries.map(entry => (
          <CommentaryEntry key={entry.id} entry={entry} onRefresh={onRefresh} showAccount={!account} />
        ))}
      </div>
    </div>
  )
}
