// frontend/src/components/shared/SymbolCombobox.tsx
// Symbol input for a filter bar: a combobox over a fixed list of tickers. Prefix match while typing
// (either spelling of an aliased share class matches); Enter or click commits; free text that matches no
// option shows a message and never commits.
import { useRef, useState, type Ref } from 'react'
import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from '../ui/command'
import { Popover, PopoverAnchor, PopoverContent } from '../ui/popover'
import { matchSymbols } from '../../lib/tickers'

export interface SymbolOption {
  ticker: string
  /** Shown beside the ticker, e.g. "3 slots". */
  hint?: string
}

interface Props {
  options: SymbolOption[]
  onCommit: (ticker: string) => void
  inputRef?: Ref<HTMLInputElement>
  /** Wording for the no-match message: "No wheel for XYZ in this account". */
  noMatchLabel: (query: string) => string
  emptyLabel: string
}

export function SymbolCombobox({ options, onCommit, inputRef, noMatchLabel, emptyLabel }: Props) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const anchorRef = useRef<HTMLDivElement>(null)

  const q = query.trim().toUpperCase()
  const matches = q
    ? options.filter(o => [...matchSymbols(o.ticker)].some(t => t.startsWith(q)))
    : options

  function commit(ticker: string) {
    onCommit(ticker)
    setQuery('')
    setOpen(false)
  }

  return (
    // `label` names the input for screen readers (cmdk points the input's aria-labelledby at it).
    <Command label="Filter by symbol" shouldFilter={false} loop className="relative">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverAnchor asChild>
          <div ref={anchorRef}>
            <CommandInput
              ref={inputRef}
              value={query}
              onValueChange={v => { setQuery(v); setOpen(true) }}
              onFocus={() => setOpen(true)}
              onKeyDown={e => {
                if (e.key !== 'Escape') return
                // First Escape closes the list, the next clears typed text; only an Escape with nothing left
                // to close reaches the page (which then clears the filter).
                if (open || query) {
                  e.stopPropagation()
                  setOpen(false)
                  setQuery('')
                }
              }}
              placeholder="Symbol…"
              className="w-36 rounded border border-gray-300 bg-white px-2 py-1 text-sm focus:border-blue-400"
            />
          </div>
        </PopoverAnchor>
        <PopoverContent
          className="w-56"
          // Keep focus in the input while the list is open.
          onOpenAutoFocus={e => e.preventDefault()}
          onInteractOutside={e => {
            if (anchorRef.current?.contains(e.target as Node)) e.preventDefault()
          }}
        >
          <CommandList>
            <CommandEmpty>{q ? noMatchLabel(q) : emptyLabel}</CommandEmpty>
            {matches.map(o => (
              <CommandItem key={o.ticker} value={o.ticker} onSelect={() => commit(o.ticker)}>
                <span className="font-semibold">{o.ticker}</span>
                {o.hint && <span className="text-xs text-gray-400">{o.hint}</span>}
              </CommandItem>
            ))}
          </CommandList>
        </PopoverContent>
      </Popover>
    </Command>
  )
}
