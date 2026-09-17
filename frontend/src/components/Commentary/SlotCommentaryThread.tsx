import { useState } from 'react'
import type { TechnicalsData, WheelSignalSnapshot, WheelSlotHistoryEntry } from '../../types'
import { CommentaryForm } from './CommentaryForm'
import { RationaleChip, SnapshotChip } from './CommentaryThread'

interface Props {
  ticker: string
  entries: WheelSlotHistoryEntry[]
  total: number
  hasMore: boolean
  loadingMore: boolean
  snapshot?: WheelSignalSnapshot | null
  onLoadMore: () => void
  onAdd: (note: string, tags: string[], rationale: TechnicalsData | null, signalSnapshot: WheelSignalSnapshot | null) => Promise<void>
  onDelete: (id: string) => Promise<void>
}

function OriginTag({ entry }: { entry: WheelSlotHistoryEntry }) {
  if (entry.origin === 'slot') {
    return <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-gray-100 text-gray-500">Slot</span>
  }
  const roleLabel = entry.leg_role === 'covered_call' ? 'CC' : entry.leg_role === 'sold_put' ? 'SP' : entry.leg_role ?? '—'
  const pillClass = entry.leg_role === 'sold_put' ? 'bg-blue-100 text-blue-700' : 'bg-amber-100 text-amber-700'
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${pillClass}`}>
      {roleLabel}{entry.rotation_number != null ? ` · R${entry.rotation_number}` : ''}
    </span>
  )
}

export function SlotCommentaryThread({ ticker, entries, total, hasMore, loadingMore, snapshot, onLoadMore, onAdd, onDelete }: Props) {
  const [error, setError] = useState<string | null>(null)

  const handleAdd = async (note: string, tags: string[], rationale: TechnicalsData | null, signalSnapshot: WheelSignalSnapshot | null) => {
    setError(null)
    try {
      await onAdd(note, tags, rationale, signalSnapshot)
    } catch {
      setError('Failed to add note. Please try again.')
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this note?')) return
    setError(null)
    try {
      await onDelete(id)
    } catch {
      setError('Failed to delete note. Please try again.')
    }
  }

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-gray-700">Journal {total > 0 && <span className="text-gray-400 font-normal">({total})</span>}</h3>
      {error && <p className="text-red-500 text-xs">{error}</p>}
      <CommentaryForm ticker={ticker} snapshot={snapshot} onSubmit={handleAdd} />
      <div className="space-y-3 mt-4">
        {entries.length === 0 && <p className="text-gray-400 text-sm">No notes yet.</p>}
        {entries.map(entry => (
          <div key={entry.id} className="bg-gray-50 rounded p-3 text-sm">
            <div className="flex justify-between items-start">
              <div className="flex items-center gap-1.5">
                <OriginTag entry={entry} />
                <span className="text-gray-400 text-xs">{entry.entry_date}</span>
              </div>
              <button onClick={() => handleDelete(entry.id)} className="text-red-400 hover:text-red-600 text-xs">×</button>
            </div>
            <p className="mt-1 text-gray-800">{entry.note}</p>
            {entry.tags && entry.tags.length > 0 && (
              <div className="flex gap-1 mt-1">
                {entry.tags.map(tag => (
                  <span key={tag} className="px-1.5 py-0.5 bg-blue-100 text-blue-600 rounded text-xs">{tag}</span>
                ))}
              </div>
            )}
            {entry.rationale && <RationaleChip rationale={entry.rationale} />}
            {entry.signal_snapshot && <SnapshotChip snapshot={entry.signal_snapshot} />}
          </div>
        ))}
        {hasMore && (
          <button
            onClick={onLoadMore}
            disabled={loadingMore}
            className="w-full text-xs text-center py-1.5 text-indigo-600 hover:bg-indigo-50 rounded disabled:opacity-50"
          >
            {loadingMore ? 'Loading…' : 'Load more'}
          </button>
        )}
      </div>
    </div>
  )
}
