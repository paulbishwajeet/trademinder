import { useState, useEffect } from 'react'
import type { TradeCreate, TechnicalsData } from '../../types'
import { TechnicalsPanel } from '../shared/TechnicalsPanel'

interface Category { id: string; name: string; color: string }

interface Props {
  onSubmit: (payload: TradeCreate, technicals: TechnicalsData | null) => Promise<void>
  onCancel: () => void
}

const STRATEGIES = ['Stock', 'Put', 'Call', 'CoveredCall', 'PutCreditSpread', 'Leap']
const TYPES = ['Buy', 'Sell', 'Assigned']

export function TradeForm({ onSubmit, onCancel }: Props) {
  const today = new Date().toISOString().split('T')[0]
  const [form, setForm] = useState<TradeCreate>({
    type: 'Sell', category: 'WHEEL', strategy: 'Put',
    ticker: '', open_date: today, quantity: 1,
  })
  const [technicals, setTechnicals] = useState<TechnicalsData | null>(null)
  const [techOpen, setTechOpen] = useState(false)
  const [categories, setCategories] = useState<Category[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/categories').then(r => r.json()).then(setCategories).catch(() => {})
  }, [])

  const set = (field: keyof TradeCreate, value: unknown) =>
    setForm(prev => ({ ...prev, [field]: value }))

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      await onSubmit(form, technicals)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create trade')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && <div className="p-3 bg-red-50 text-red-700 rounded text-sm">{error}</div>}

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700">Ticker *</label>
          <input required value={form.ticker} onChange={e => set('ticker', e.target.value.toUpperCase())}
            className="mt-1 block w-full border border-gray-300 rounded px-3 py-2 text-sm uppercase" placeholder="AAPL" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Type *</label>
          <select value={form.type} onChange={e => set('type', e.target.value)} className="mt-1 block w-full border border-gray-300 rounded px-3 py-2 text-sm">
            {TYPES.map(t => <option key={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Strategy *</label>
          <select value={form.strategy} onChange={e => set('strategy', e.target.value)} className="mt-1 block w-full border border-gray-300 rounded px-3 py-2 text-sm">
            {STRATEGIES.map(s => <option key={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Category *</label>
          <select value={form.category} onChange={e => set('category', e.target.value)} className="mt-1 block w-full border border-gray-300 rounded px-3 py-2 text-sm">
            {categories.length === 0
              ? <option value="" disabled>Loading...</option>
              : categories.map(c => <option key={c.id} value={c.name}>{c.name}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Open Date *</label>
          <input type="date" required value={form.open_date} onChange={e => set('open_date', e.target.value)} className="mt-1 block w-full border border-gray-300 rounded px-3 py-2 text-sm" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Expiry Date</label>
          <input type="date" value={form.expiry_date ?? ''} onChange={e => set('expiry_date', e.target.value || null)} className="mt-1 block w-full border border-gray-300 rounded px-3 py-2 text-sm" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Strike Price</label>
          <input type="number" step="0.01" value={form.strike_price ?? ''} onChange={e => set('strike_price', e.target.value ? parseFloat(e.target.value) : null)} className="mt-1 block w-full border border-gray-300 rounded px-3 py-2 text-sm" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Quantity *</label>
          <input type="number" required min="1" value={form.quantity} onChange={e => set('quantity', parseInt(e.target.value))} className="mt-1 block w-full border border-gray-300 rounded px-3 py-2 text-sm" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Premium</label>
          <input type="number" step="0.01" value={form.premium ?? ''} onChange={e => set('premium', e.target.value ? parseFloat(e.target.value) : null)} className="mt-1 block w-full border border-gray-300 rounded px-3 py-2 text-sm" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Collateral</label>
          <input type="number" step="0.01" value={form.collateral ?? ''} onChange={e => set('collateral', e.target.value ? parseFloat(e.target.value) : null)} className="mt-1 block w-full border border-gray-300 rounded px-3 py-2 text-sm" />
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700">Exit Strategy</label>
        <textarea rows={2} value={form.exit_strategy ?? ''} onChange={e => set('exit_strategy', e.target.value || null)} className="mt-1 block w-full border border-gray-300 rounded px-3 py-2 text-sm" placeholder="Close at 50% profit or 21 DTE" />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700">Notes (rationale)</label>
        <textarea rows={2} value={form.rationale_notes ?? ''} onChange={e => set('rationale_notes', e.target.value || null)} className="mt-1 block w-full border border-gray-300 rounded px-3 py-2 text-sm" placeholder="IV rank elevated, earnings in 6 weeks…" />
      </div>

      <div>
        <button
          type="button"
          onClick={() => setTechOpen(o => !o)}
          className="text-sm text-indigo-600 hover:underline"
        >
          {techOpen ? '▲ Hide Technicals' : '▼ Attach Technicals (optional)'}
        </button>
        {techOpen && (
          <div className="mt-2">
            <TechnicalsPanel ticker={form.ticker} onChange={setTechnicals} />
          </div>
        )}
      </div>

      <div className="flex gap-3 pt-2">
        <button type="submit" disabled={loading} className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50">
          {loading ? 'Saving...' : 'Add Trade'}
        </button>
        <button type="button" onClick={onCancel} className="px-4 py-2 border border-gray-300 rounded text-sm hover:bg-gray-50">
          Cancel
        </button>
      </div>
    </form>
  )
}
