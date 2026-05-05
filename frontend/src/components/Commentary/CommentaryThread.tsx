// frontend/src/components/Commentary/CommentaryThread.tsx
import type { Commentary } from '../../types'
import { commentaryApi } from '../../api/commentary'
import { CommentaryForm } from './CommentaryForm'

interface Props {
  tradeId: string
  entries: Commentary[]
  onRefresh: () => void
}

export function CommentaryThread({ tradeId, entries, onRefresh }: Props) {
  const handleAdd = async (note: string, tags: string[]) => {
    await commentaryApi.add(tradeId, { note, tags: tags.length > 0 ? tags : undefined })
    onRefresh()
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this note?')) return
    await commentaryApi.delete(id)
    onRefresh()
  }

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-gray-700">Journal</h3>
      <CommentaryForm onSubmit={handleAdd} />
      <div className="space-y-3 mt-4">
        {entries.length === 0 && <p className="text-gray-400 text-sm">No notes yet.</p>}
        {entries.map(entry => (
          <div key={entry.id} className="bg-gray-50 rounded p-3 text-sm">
            <div className="flex justify-between items-start">
              <span className="text-gray-400 text-xs">{entry.entry_date}</span>
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
          </div>
        ))}
      </div>
    </div>
  )
}
