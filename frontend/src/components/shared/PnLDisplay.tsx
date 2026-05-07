// frontend/src/components/shared/PnLDisplay.tsx
export function PnLDisplay({ value }: { value: number | null }) {
  if (value === null) return <span className="text-gray-400">—</span>
  const num = Number(value)
  const isPositive = num >= 0
  return (
    <span className={isPositive ? 'text-green-600 font-medium' : 'text-red-600 font-medium'}>
      {isPositive ? '+' : ''}${num.toFixed(2)}
    </span>
  )
}
