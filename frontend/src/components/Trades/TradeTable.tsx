// frontend/src/components/Trades/TradeTable.tsx
import { Link } from 'react-router-dom'
import type { Trade } from '../../types'
import { StatusBadge } from '../shared/StatusBadge'
import { PnLDisplay } from '../shared/PnLDisplay'

interface Props {
  trades: Trade[]
  onDelete: (id: string) => void
}

export function TradeTable({ trades, onDelete }: Props) {
  if (trades.length === 0) {
    return <p className="text-gray-500 text-center py-8">No trades yet. Add your first trade.</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead className="bg-gray-50">
          <tr>
            {['Ticker', 'Strategy', 'Type', 'Strike', 'Expiry', 'Qty', 'Premium', 'P&L', 'Status', ''].map(h => (
              <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {trades.map(trade => (
            <tr key={trade.id} className="hover:bg-gray-50">
              <td className="px-4 py-3 font-semibold">
                <Link to={`/trades/${trade.id}`} className="text-blue-600 hover:underline">
                  {trade.ticker}
                </Link>
              </td>
              <td className="px-4 py-3">{trade.strategy}</td>
              <td className="px-4 py-3">{trade.type}</td>
              <td className="px-4 py-3">{trade.strike_price ?? '—'}</td>
              <td className="px-4 py-3">{trade.expiry_date ?? '—'}</td>
              <td className="px-4 py-3">{trade.quantity}</td>
              <td className="px-4 py-3">{trade.premium !== null ? `$${trade.premium}` : '—'}</td>
              <td className="px-4 py-3"><PnLDisplay value={trade.unrealized_pnl} /></td>
              <td className="px-4 py-3"><StatusBadge status={trade.status} /></td>
              <td className="px-4 py-3">
                <div className="flex items-center gap-3">
                  {trade.strategy === 'Stock' && trade.status === 'open' && (
                    <Link
                      to={`/scanner?ticker=${trade.ticker}`}
                      className="text-blue-500 hover:text-blue-700 text-xs"
                    >
                      Scan →
                    </Link>
                  )}
                  <button
                    onClick={() => onDelete(trade.id)}
                    className="text-red-500 hover:text-red-700 text-xs"
                  >
                    Delete
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
