// frontend/src/components/Commentary/CommentaryForm.tsx
import { useState } from 'react'

interface Props {
  onSubmit: (note: string, tags: string[]) => Promise<void>
}

export function CommentaryForm({ onSubmit }: Props) {
  const [note, setNote] = useState('')
  const [tagsInput, setTagsInput] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!note.trim()) return
    setLoading(true)
    const tags = tagsInput.split(',').map(t => t.trim()).filter(Boolean)
    await onSubmit(note.trim(), tags)
    setNote('')
    setTagsInput('')
    setLoading(false)
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-2">
      <textarea
        required
        rows={3}
        value={note}
        onChange={e => setNote(e.target.value)}
        className="block w-full border border-gray-300 rounded px-3 py-2 text-sm"
        placeholder="What happened or what did you decide?"
      />
      <input
        value={tagsInput}
        onChange={e => setTagsInput(e.target.value)}
        className="block w-full border border-gray-300 rounded px-3 py-2 text-sm"
        placeholder="Tags: rolled, exit-change, earnings (comma-separated)"
      />
      <button type="submit" disabled={loading} className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50">
        {loading ? 'Adding...' : 'Add Note'}
      </button>
    </form>
  )
}
