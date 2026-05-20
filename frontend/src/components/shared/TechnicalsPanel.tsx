// frontend/src/components/shared/TechnicalsPanel.tsx
import { useState } from 'react'
import { technicalsApi } from '../../api/technicals'
import type { TechnicalsData } from '../../types'

interface Props {
  ticker: string
  onChange: (data: TechnicalsData | null) => void
}

const SELECT_FIELDS: Record<string, string[]> = {
  macd_signal: ['bullish', 'bearish', 'neutral'],
  rsi_result: ['rsi_oversold', 'rsi_overbought'],
  price_vs_ma200: ['above', 'below'],
  price_vs_ma50: ['above', 'below'],
  bollinger_position: ['above_upper', 'near_upper', 'mid', 'near_lower', 'below_lower'],
  day_color: ['green', 'red'],
  sentiment: ['bullish', 'bearish', 'neutral'],
}

const FIELD_LABELS: Record<string, string> = {
  macd_signal: 'MACD Signal', macd_notes: 'MACD Notes', rsi_14: 'RSI-14',
  rsi_result: 'RSI Result', ma_200d: 'MA 200D', ma_50d: 'MA 50D',
  price_vs_ma200: 'Price vs MA200', price_vs_ma50: 'Price vs MA50',
  bollinger_upper: 'BB Upper', bollinger_mid: 'BB Mid', bollinger_lower: 'BB Lower',
  bollinger_position: 'BB Position', day_color: 'Day Color', price_action: 'Price',
  sentiment: 'Sentiment', next_earnings_date: 'Next Earnings', notes: 'Notes',
}

const FIELD_ORDER = [
  'price_action', 'day_color', 'rsi_14', 'rsi_result',
  'macd_signal', 'macd_notes', 'ma_200d', 'ma_50d',
  'price_vs_ma200', 'price_vs_ma50', 'bollinger_upper', 'bollinger_mid',
  'bollinger_lower', 'bollinger_position', 'sentiment', 'next_earnings_date', 'notes',
]

export function TechnicalsPanel({ ticker, onChange }: Props) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<TechnicalsData | null>(null)

  const handleFetch = async () => {
    if (!ticker.trim()) { setError('Enter a ticker first'); return }
    setLoading(true)
    setError(null)
    try {
      const result = await technicalsApi.fetch(ticker.trim().toUpperCase())
      if (result.fetch_status === 'error') {
        setError(result.fetch_error ?? 'Fetch failed')
        return
      }
      setData(result)
      setOpen(true)
      onChange(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Fetch failed')
    } finally {
      setLoading(false)
    }
  }

  const handleClear = () => {
    setData(null)
    setOpen(false)
    onChange(null)
  }

  const handleChange = (field: string, value: string) => {
    if (!data) return
    const updated = { ...data, [field]: value || null }
    setData(updated)
    onChange(updated)
  }

  return (
    <div className="border border-gray-200 rounded-lg p-3 bg-gray-50">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={handleFetch}
          disabled={loading}
          className="px-3 py-1.5 bg-indigo-600 text-white rounded text-xs hover:bg-indigo-700 disabled:opacity-50"
        >
          {loading ? 'Fetching…' : '📊 Fetch Technicals'}
        </button>
        {data && (
          <button type="button" onClick={handleClear} className="text-xs text-gray-400 hover:text-red-500">
            Clear
          </button>
        )}
        {data && (
          <button
            type="button"
            onClick={() => setOpen(o => !o)}
            className="text-xs text-indigo-600 hover:underline ml-auto"
          >
            {open ? 'Collapse ▲' : 'Expand ▼'}
          </button>
        )}
      </div>

      {error && <p className="text-red-500 text-xs mt-1">{error}</p>}

      {data && open && (
        <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2">
          {FIELD_ORDER.map(field => {
            const label = FIELD_LABELS[field] ?? field
            const value = (data as unknown as Record<string, unknown>)[field]
            const strValue = value != null ? String(value) : ''
            const isSelect = field in SELECT_FIELDS

            return (
              <div key={field} className={field === 'notes' ? 'col-span-2' : ''}>
                <label className="block text-xs text-gray-500">{label}</label>
                {field === 'notes' ? (
                  <textarea
                    rows={2}
                    value={strValue}
                    onChange={e => handleChange(field, e.target.value)}
                    className="mt-0.5 block w-full border border-gray-300 rounded px-2 py-1 text-xs"
                  />
                ) : isSelect ? (
                  <select
                    value={strValue}
                    onChange={e => handleChange(field, e.target.value)}
                    className="mt-0.5 block w-full border border-gray-300 rounded px-2 py-1 text-xs"
                  >
                    <option value="">—</option>
                    {SELECT_FIELDS[field].map(opt => (
                      <option key={opt} value={opt}>{opt}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={strValue}
                    onChange={e => handleChange(field, e.target.value)}
                    className="mt-0.5 block w-full border border-gray-300 rounded px-2 py-1 text-xs"
                  />
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
