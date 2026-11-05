// frontend/src/components/shared/MarketDash.tsx
export const MARKET_OFFLINE_TOOLTIP = 'Market data offline'

/** Placeholder for a market-derived value that isn't available. */
export function MarketDash({ offline, className = 'text-gray-400' }: { offline?: boolean; className?: string }) {
  return (
    <span className={className} title={offline ? MARKET_OFFLINE_TOOLTIP : undefined}>—</span>
  )
}

/** Tooltip for a cached value served while offline ("Market data offline · as of …"). */
export function staleTooltip(asOf: string | null | undefined): string {
  if (!asOf) return MARKET_OFFLINE_TOOLTIP
  const when = new Date(asOf)
  const label = Number.isNaN(when.getTime()) ? asOf : when.toLocaleString()
  return `${MARKET_OFFLINE_TOOLTIP} · as of ${label}`
}
