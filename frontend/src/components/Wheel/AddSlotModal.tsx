import { useState } from 'react'
import { wheelApi } from '../../api/wheel'

interface Props {
  sessionId: string
  onClose: () => void
  onCreated: () => void
}

const INITIAL_STATUSES = [
  { value: 'awaiting_cc', label: 'Awaiting CC — I have shares, need to sell a call' },
  { value: 'awaiting_sold_put', label: 'Awaiting Sold Put — No shares, need to sell a put' },
]

export function AddSlotModal({ sessionId, onClose, onCreated }: Props) {
  const [contracts, setContracts] = useState(1)
  const [status, setStatus] = useState('awaiting_cc')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const sharesHeld = status === 'awaiting_cc' ? contracts * 100 : 0

  async function handleCreate() {
    setSaving(true)
    setError(null)
    try {
      await wheelApi.addSlot(sessionId, { contracts, shares_held: sharesHeld, status })
      onCreated()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to add slot')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg w-full max-w-sm p-6 shadow-xl" onClick={e => e.stopPropagation()}>
        <h2 className="text-lg font-bold text-gray-900 mb-4">Add Slot</h2>
        {error && <p className="text-sm text-red-600 mb-3">{error}</p>}
        <div className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Contracts</label>
            <input
              type="number"
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
              value={contracts}
              onChange={e => setContracts(parseInt(e.target.value) || 1)}
              min={1}
            />
            <p className="text-xs text-gray-400 mt-1">{contracts} contract = {contracts * 100} shares</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Starting Phase</label>
            <select
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
              value={status}
              onChange={e => setStatus(e.target.value)}
            >
              {INITIAL_STATUSES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
        </div>
        <div className="flex gap-2 justify-end mt-5">
          <button onClick={onClose} className="px-4 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50">Cancel</button>
          <button onClick={handleCreate} disabled={saving} className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
            {saving ? 'Adding...' : 'Add Slot'}
          </button>
        </div>
      </div>
    </div>
  )
}
