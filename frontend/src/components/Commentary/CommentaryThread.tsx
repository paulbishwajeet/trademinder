import { useState } from 'react'
import type { Commentary, Rationale, TechnicalsData } from '../../types'
import { commentaryApi } from '../../api/commentary'
import { CommentaryForm } from './CommentaryForm'

interface Props {
  tradeId: string
  ticker: string
  entries: Commentary[]
  onRefresh: () => void
}

const RATIONALE_LABELS: Record<string, string> = {
  rsi_14: 'RSI', macd_signal: 'MACD', sentiment: 'Sentiment',
  bollinger_position: 'BB Pos', price_vs_ma50: 'vs MA50', price_vs_ma200: 'vs MA200',
  ma_50d: 'MA50', ma_200d: 'MA200', day_color: 'Day', price_action: 'Price',
  next_earnings_date: 'Earnings', notes: 'Notes',
}

function RationaleChip({ rationale }: { rationale: Rationale }) {
  const [expanded, setExpanded] = useState(false)
  const fields = Object.entries(RATIONALE_LABELS)
    .map(([k, label]) => ({ key: k, label, value: (rationale as unknown as Record<string, unknown>)[k] }))
    .filter(({ value }) => value != null && value !== '')

  return (
    <div className="mt-1">
      <button type="button" onClick={() => setExpanded(o => !o)}
        className="text-xs px-2 py-0.5 bg-indigo-50 text-indigo-600 rounded hover:bg-indigo-100">
        📊 Technicals {expanded ? '▲' : '▼'}
      </button>
      {expanded && (
        <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs bg-white border border-gray-100 rounded p-2">
          {fields.map(({ key, label, value }) => (
            <div key={key}>
              <span className="text-gray-400">{label}: </span>
              <span className="text-gray-700 font-medium">{String(value)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function CommentaryThread({ tradeId, ticker, entries, onRefresh }: Props) {
  const [error, setError] = useState<string | null>(null)

  const handleAdd = async (note: string, tags: string[], rationale: TechnicalsData | null) => {
    setError(null)
    try {
      await commentaryApi.add(tradeId, {
        note,
        tags: tags.length > 0 ? tags : undefined,
        rationale: rationale ?? undefined,
      })
      onRefresh()
    } catch {
      setError('Failed to add note. Please try again.')
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this note?')) return
    setError(null)
    try {
      await commentaryApi.delete(id)
      onRefresh()
    } catch {
      setError('Failed to delete note. Please try again.')
    }
  }

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-gray-700">Journal</h3>
      {error && <p className="text-red-500 text-xs">{error}</p>}
      <CommentaryForm ticker={ticker} onSubmit={handleAdd} />
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
            {entry.rationale && <RationaleChip rationale={entry.rationale} />}
          </div>
        ))}
      </div>
    </div>
  )
}
