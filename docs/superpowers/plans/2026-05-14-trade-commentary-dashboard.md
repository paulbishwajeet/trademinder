# Trade Commentary on Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Commentary column to the `/trades` table where each row shows an icon + count badge that opens a Radix Dialog containing the full commentary thread and add form.

**Architecture:** A new `CommentaryCell` component owns fetch state, the badge, and the Radix Dialog. It fetches entries on mount for the count, re-fetches after mutations, and renders the existing `CommentaryThread` (unchanged) inside the dialog. `TradeTable` gains one new column header and one new cell per row.

**Tech Stack:** React 19 + TypeScript, Tailwind CSS, Radix UI Dialog (`@radix-ui/react-dialog` ^1.1.15), existing `commentaryApi` client, existing `CommentaryThread` / `CommentaryForm` components.

> **Note:** No test framework (Vitest/Jest) is configured in this project. TDD steps are omitted; manual verification steps are provided instead.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `frontend/src/components/Trades/CommentaryCell.tsx` | Badge button + Radix Dialog wrapping `CommentaryThread` |
| Modify | `frontend/src/components/Trades/TradeTable.tsx` | Add "Commentary" column header + `CommentaryCell` cell |

---

### Task 1: Create `CommentaryCell` component

**Files:**
- Create: `frontend/src/components/Trades/CommentaryCell.tsx`

- [ ] **Step 1: Create the file with the full component**

  Create `frontend/src/components/Trades/CommentaryCell.tsx` with this exact content:

  ```tsx
  import { useEffect, useState } from 'react'
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

    const fetchEntries = async () => {
      const data = await commentaryApi.list(tradeId)
      setEntries(data)
      setLoading(false)
    }

    useEffect(() => {
      fetchEntries()
    }, [tradeId])

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
              <Dialog.Close className="text-gray-400 hover:text-gray-600 text-xl leading-none">
                ×
              </Dialog.Close>
            </div>
            <div className="overflow-y-auto flex-1 px-5 py-4">
              <CommentaryThread
                tradeId={tradeId}
                entries={entries}
                onRefresh={fetchEntries}
              />
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    )
  }
  ```

- [ ] **Step 2: Verify TypeScript compiles**

  Run from `frontend/`:
  ```bash
  npx tsc --noEmit
  ```
  Expected: no errors. If you see "Cannot find module '@radix-ui/react-dialog'", run `npm install` first.

- [ ] **Step 3: Commit**

  ```bash
  git add frontend/src/components/Trades/CommentaryCell.tsx
  git commit -m "feat: add CommentaryCell badge + dialog component"
  ```

---

### Task 2: Wire `CommentaryCell` into `TradeTable`

**Files:**
- Modify: `frontend/src/components/Trades/TradeTable.tsx`

- [ ] **Step 1: Add import at the top of `TradeTable.tsx`**

  In `frontend/src/components/Trades/TradeTable.tsx`, add the import after the existing imports (currently lines 1–5):

  ```tsx
  import { CommentaryCell } from './CommentaryCell'
  ```

- [ ] **Step 2: Add "Commentary" to the column headers array**

  Find line 22:
  ```tsx
  {['Ticker', 'Strategy', 'Type', 'Strike', 'Expiry', 'Qty', 'Premium', 'P&L', 'Status', ''].map(h => (
  ```

  Replace with:
  ```tsx
  {['Ticker', 'Strategy', 'Type', 'Strike', 'Expiry', 'Qty', 'Premium', 'P&L', 'Status', 'Commentary', ''].map(h => (
  ```

- [ ] **Step 3: Add the Commentary cell in each row**

  Find lines 44–45 (after the Status cell, before the actions cell):
  ```tsx
              <td className="px-4 py-3"><StatusBadge status={trade.status} /></td>
              <td className="px-4 py-3">
  ```

  Replace with:
  ```tsx
              <td className="px-4 py-3"><StatusBadge status={trade.status} /></td>
              <td className="px-4 py-3">
                <CommentaryCell tradeId={trade.id} ticker={trade.ticker} />
              </td>
              <td className="px-4 py-3">
  ```

- [ ] **Step 4: Verify TypeScript compiles**

  Run from `frontend/`:
  ```bash
  npx tsc --noEmit
  ```
  Expected: no errors.

- [ ] **Step 5: Manual smoke test**

  Start the dev server (`npm run dev` from `frontend/`) and navigate to `/trades`:
  - Each trade row shows a chat icon with a number badge
  - Clicking the badge opens a modal titled "Commentary — {TICKER}"
  - The modal shows the commentary thread and add form
  - Adding a note re-fetches and the count badge increments
  - Deleting a note re-fetches and the count badge decrements
  - ESC key and clicking outside the modal closes it

- [ ] **Step 6: Commit**

  ```bash
  git add frontend/src/components/Trades/TradeTable.tsx
  git commit -m "feat: add Commentary column to trades dashboard table"
  ```
