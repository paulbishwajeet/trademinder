// frontend/src/components/shared/PnLDisplay.tsx
import { useMarketDataOffline } from '../../hooks/useMarketDataOffline'
import { MarketDash } from './MarketDash'

export function PnLDisplay({ value }: { value: number | null }) {
  const offline = useMarketDataOffline()
  if (value === null) return <MarketDash offline={offline} />
  const num = Number(value)
  const isPositive = num >= 0
  return (
    <span className={isPositive ? 'text-green-600 font-medium' : 'text-red-600 font-medium'}>
      {isPositive ? '+' : ''}${num.toFixed(2)}
    </span>
  )
}
