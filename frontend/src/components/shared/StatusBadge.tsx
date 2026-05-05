// frontend/src/components/shared/StatusBadge.tsx
const STATUS_COLORS: Record<string, string> = {
  open: 'bg-green-100 text-green-800',
  closed: 'bg-gray-100 text-gray-800',
  expired: 'bg-yellow-100 text-yellow-800',
  assigned: 'bg-blue-100 text-blue-800',
}

export function StatusBadge({ status }: { status: string }) {
  const colors = STATUS_COLORS[status] ?? 'bg-gray-100 text-gray-600'
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${colors}`}>
      {status}
    </span>
  )
}
