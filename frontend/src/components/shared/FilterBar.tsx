// frontend/src/components/shared/FilterBar.tsx
// A sticky bar of filter chips. Pages supply the active chips, the inputs that add them (children) and an
// optional notice; adding a filter later means adding a chip and an input, not reworking the page.
import type { ReactNode, Ref } from 'react'
import { X } from 'lucide-react'

export interface FilterChip {
  key: string
  label: string
  value: string
  onRemove: () => void
}

interface Props {
  chips: FilterChip[]
  onClearAll: () => void
  children: ReactNode
  notice?: ReactNode
  barRef?: Ref<HTMLDivElement>
}

export function FilterBar({ chips, onClearAll, children, notice, barRef }: Props) {
  return (
    <div
      ref={barRef}
      role="search"
      className="sticky top-0 z-30 -mx-6 mb-4 flex flex-wrap items-center gap-2 border-b border-gray-200 bg-gray-50/95 px-6 py-2 backdrop-blur"
    >
      {children}
      {chips.map(chip => (
        <span key={chip.key}
          className="inline-flex items-center gap-1 rounded-full border border-blue-200 bg-blue-50 py-0.5 pl-2.5 pr-1 text-xs text-blue-800">
          {chip.label}: <span className="font-semibold">{chip.value}</span>
          <button onClick={chip.onRemove} title={`Remove ${chip.label} filter`} aria-label={`Remove ${chip.label} filter`}
            className="rounded-full p-0.5 hover:bg-blue-100">
            <X size={12} />
          </button>
        </span>
      ))}
      {notice}
      {chips.length > 0 && (
        <button onClick={onClearAll} className="ml-auto text-xs text-gray-500 hover:text-gray-800 hover:underline">
          Clear
        </button>
      )}
    </div>
  )
}
