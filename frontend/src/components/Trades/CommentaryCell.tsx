import { useCallback, useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import type { Commentary } from '../../types'
import { commentaryApi } from '../../api/commentary'
import { CommentaryThread } from '../Commentary/CommentaryThread'

interface Props {
  tradeId: string
  ticker: string
}

export function CommentaryCell({ tradeId, ticker }: Props) {
  const [open, setOpen] = useState(false)
  const [entries, setEntries] = useState<Commentary[]>([])
  const [loading, setLoading] = useState(true)

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

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button className="flex items-center gap-1 text-gray-500 hover:text-blue-600">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="h-4 w-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
            />
          </svg>
          <span className="text-xs font-medium">
            {loading ? '…' : entries.length}
          </span>
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40 z-40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-[560px] max-h-[80vh] bg-white rounded-lg shadow-xl flex flex-col">
          <div className="flex items-center justify-between px-5 py-4 border-b">
            <Dialog.Title className="text-sm font-semibold text-gray-800">
              Commentary — {ticker}
            </Dialog.Title>
            <Dialog.Description className="sr-only">
              Commentary entries for {ticker}
            </Dialog.Description>
            <Dialog.Close className="text-gray-400 hover:text-gray-600 text-xl leading-none">
              ×
            </Dialog.Close>
          </div>
          <div className="overflow-y-auto flex-1 px-5 py-4">
            <CommentaryThread
              tradeId={tradeId}
              ticker={ticker}
              entries={entries}
              onRefresh={fetchEntries}
            />
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
