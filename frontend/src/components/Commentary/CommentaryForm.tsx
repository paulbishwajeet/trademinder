import { useState } from 'react'
import type { TechnicalsData, WheelSignalSnapshot } from '../../types'
import { TechnicalsPanel } from '../shared/TechnicalsPanel'
import { MarketSnapshotPreview } from './MarketSnapshotPreview'

interface Props {
  ticker: string
  snapshot?: WheelSignalSnapshot | null
  onSubmit: (note: string, tags: string[], rationale: TechnicalsData | null, signalSnapshot: WheelSignalSnapshot | null) => Promise<void>
}

export function CommentaryForm({ ticker, snapshot, onSubmit }: Props) {
  const [note, setNote] = useState('')
  const [tagsInput, setTagsInput] = useState('')
  const [technicals, setTechnicals] = useState<TechnicalsData | null>(null)
  const [techOpen, setTechOpen] = useState(false)
  const [attachSnapshot, setAttachSnapshot] = useState(false)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!note.trim()) return
    setLoading(true)
    try {
      const tags = tagsInput.split(',').map(t => t.trim()).filter(Boolean)
      await onSubmit(note.trim(), tags, technicals, attachSnapshot ? snapshot ?? null : null)
      setNote('')
      setTagsInput('')
      setTechnicals(null)
      setTechOpen(false)
      setAttachSnapshot(false)
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-2">
      <textarea required rows={3} value={note} onChange={e => setNote(e.target.value)}
        className="block w-full border border-gray-300 rounded px-3 py-2 text-sm"
        placeholder="What happened or what did you decide?" />
      <input value={tagsInput} onChange={e => setTagsInput(e.target.value)}
        className="block w-full border border-gray-300 rounded px-3 py-2 text-sm"
        placeholder="Tags: rolled, exit-change, earnings (comma-separated)" />

      <div>
        <button type="button" onClick={() => setTechOpen(o => !o)}
          className="text-xs text-indigo-600 hover:underline">
          {techOpen ? '▲ Hide Technicals' : '▼ Attach Technicals (optional)'}
        </button>
        {techOpen && (
          <div className="mt-2">
            <TechnicalsPanel ticker={ticker} onChange={setTechnicals} />
          </div>
        )}
      </div>

      {snapshot && (
        <div>
          <label className="flex items-center gap-1.5 text-xs text-indigo-600">
            <input type="checkbox" checked={attachSnapshot} onChange={e => setAttachSnapshot(e.target.checked)} />
            Attach Market Snapshot (CC/SP Timing, RSI, MACD, P&L)
          </label>
          {attachSnapshot && (
            <div className="mt-2">
              <MarketSnapshotPreview snapshot={snapshot} />
            </div>
          )}
        </div>
      )}

      <button type="submit" disabled={loading}
        className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50">
        {loading ? 'Adding...' : 'Add Note'}
      </button>
    </form>
  )
}
