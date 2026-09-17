import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { Commentary } from '../../types'
import { commentaryApi } from '../../api/commentary'
import { CommentaryThread } from './CommentaryThread'

interface Props {
  tradeId: string
  ticker: string
}

const PANEL_WIDTH = 400
const MARGIN = 8

export function CommentaryPopover({ tradeId, ticker }: Props) {
  const [open, setOpen] = useState(false)
  const [entries, setEntries] = useState<Commentary[]>([])
  const [loading, setLoading] = useState(true)
  const [style, setStyle] = useState<React.CSSProperties>({})
  const buttonRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  const fetchEntries = useCallback(async () => {
    setLoading(true)
    try {
      const data = await commentaryApi.list(tradeId)
      setEntries(data)
    } finally {
      setLoading(false)
    }
  }, [tradeId])

  useEffect(() => {
    fetchEntries()
  }, [fetchEntries])

  const positionPanel = useCallback(() => {
    const btn = buttonRef.current
    if (!btn) return
    const rect = btn.getBoundingClientRect()
    const left = Math.max(MARGIN, Math.min(rect.left, window.innerWidth - PANEL_WIDTH - MARGIN))
    const spaceBelow = window.innerHeight - rect.bottom - MARGIN
    const spaceAbove = rect.top - MARGIN

    if (spaceBelow >= spaceAbove || spaceBelow >= 200) {
      setStyle({
        position: 'fixed', left, top: rect.bottom + 4,
        maxHeight: Math.min(600, spaceBelow), width: PANEL_WIDTH,
      })
    } else {
      setStyle({
        position: 'fixed', left, bottom: window.innerHeight - rect.top + 4,
        maxHeight: Math.min(600, spaceAbove), width: PANEL_WIDTH,
      })
    }
  }, [])

  useEffect(() => {
    if (!open) return
    positionPanel()

    const handleOutside = (e: MouseEvent) => {
      if (panelRef.current?.contains(e.target as Node)) return
      if (buttonRef.current?.contains(e.target as Node)) return
      setOpen(false)
    }
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', handleOutside)
    document.addEventListener('keydown', handleEsc)
    window.addEventListener('resize', positionPanel)
    window.addEventListener('scroll', positionPanel, true)
    return () => {
      document.removeEventListener('mousedown', handleOutside)
      document.removeEventListener('keydown', handleEsc)
      window.removeEventListener('resize', positionPanel)
      window.removeEventListener('scroll', positionPanel, true)
    }
  }, [open, positionPanel])

  return (
    <>
      <button
        ref={buttonRef}
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1 text-gray-500 hover:text-blue-600"
        title="Commentary"
      >
        <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
        </svg>
        <span className="text-xs font-medium">{loading ? '…' : entries.length}</span>
      </button>

      {open && createPortal(
        <div
          ref={panelRef}
          style={style}
          className="z-50 bg-white border border-gray-200 rounded-lg shadow-xl flex flex-col overflow-hidden"
        >
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 shrink-0">
            <span className="text-sm font-semibold text-gray-800">{ticker} · Commentary</span>
            <button onClick={() => setOpen(false)} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
          </div>
          <div className="overflow-y-auto px-4 py-3">
            <CommentaryThread tradeId={tradeId} ticker={ticker} entries={entries} onRefresh={fetchEntries} />
          </div>
        </div>,
        document.body
      )}
    </>
  )
}
