import type { ScreenerRow } from '../../types'

export function ScreenerDetailRow({ row, colSpan }: { row: ScreenerRow; colSpan: number }) {
  return (
    <tr className="bg-gray-50 border-t border-gray-100">
      <td colSpan={colSpan} className="px-6 py-3">
        <div className="grid grid-cols-4 gap-x-6 gap-y-2 text-xs">
          <div><span className="text-gray-400">Bollinger Upper: </span><span className="font-medium">{row.bollinger_upper ?? '—'}</span></div>
          <div><span className="text-gray-400">Bollinger Mid: </span><span className="font-medium">{row.bollinger_mid ?? '—'}</span></div>
          <div><span className="text-gray-400">Bollinger Lower: </span><span className="font-medium">{row.bollinger_lower ?? '—'}</span></div>
          <div><span className="text-gray-400">MACD Daily: </span><span className="font-medium">{row.macd_daily_signal ?? '—'}</span></div>
          <div><span className="text-gray-400">Next Earnings: </span><span className="font-medium">{row.next_earnings_date ?? '—'}</span></div>
          <div><span className="text-gray-400">Sector: </span><span className="font-medium">{row.sector ?? '—'}</span></div>
          <div><span className="text-gray-400">Category: </span><span className="font-medium">{row.category ?? '—'}</span></div>
          <div><span className="text-gray-400">Fetch Status: </span><span className="font-medium">{row.fetch_status ?? '—'}{row.fetch_error ? ` (${row.fetch_error})` : ''}</span></div>
        </div>
        {row.volume_spikes && row.volume_spikes.length > 0 && (
          <div className="mt-3">
            <div className="text-gray-400 text-xs mb-1">Volume Spikes</div>
            <table className="text-xs">
              <thead>
                <tr className="text-gray-400">
                  <th className="pr-4 text-left font-normal">Date</th>
                  <th className="pr-4 text-left font-normal">Volume</th>
                  <th className="pr-4 text-left font-normal">Avg</th>
                  <th className="text-left font-normal">Ratio</th>
                </tr>
              </thead>
              <tbody>
                {row.volume_spikes.map(spike => (
                  <tr key={spike.date}>
                    <td className="pr-4">{spike.date}</td>
                    <td className="pr-4">{spike.volume.toLocaleString()}</td>
                    <td className="pr-4">{spike.avg_volume.toLocaleString()}</td>
                    <td>{spike.ratio}x</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </td>
    </tr>
  )
}
