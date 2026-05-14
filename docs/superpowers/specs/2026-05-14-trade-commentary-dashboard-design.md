# Trade Commentary on Dashboard — Design Spec

**Date:** 2026-05-14
**Branch:** feature/rsicolumn
**Status:** Approved

---

## Overview

Add a Commentary column to the `/trades` dashboard table. Each row shows an icon + count badge indicating how many commentary entries exist for that trade. Clicking the badge opens a modal containing the full commentary thread and an add form, allowing the user to read and write running commentary without leaving the dashboard.

---

## Data & API

No backend changes required. All necessary infrastructure already exists:

- **DB model:** `Commentary` — fields: `id`, `trade_id` (FK), `entry_date`, `note`, `tags` (PG array), `created_at`
- **API routes:**
  - `GET /api/trades/{trade_id}/commentary` — list entries for a trade
  - `POST /api/trades/{trade_id}/commentary` — add entry (`note` + optional `tags`)
  - `DELETE /api/commentary/{comment_id}` — delete single entry
- **Frontend client:** `commentaryApi` in `/frontend/src/api/commentary.ts`

Comment count is derived from the `commentaryApi.list(tradeId)` response fetched on `CommentaryCell` mount. No dedicated count endpoint or bulk pre-fetch with the trades list — avoids over-fetching on page load.

---

## Component Architecture

### New: `CommentaryCell` (`/frontend/src/components/Trades/CommentaryCell.tsx`)

- **Props:** `tradeId: string`, `ticker: string`
- **Local state:** `open: boolean`, `comments: Commentary[]`, `loading: boolean`
- **On mount:** fetches `commentaryApi.list(tradeId)` to populate count badge
- **Renders:**
  - Button: chat icon + count badge (always clickable, shows "0" when empty)
  - Radix `Dialog.Root / Dialog.Portal / Dialog.Content` triggered by button click
  - Dialog header: trade ticker symbol
  - Dialog body: `<CommentaryThread tradeId={tradeId} />` (existing component, unchanged)
  - After add or delete inside the thread, re-fetches comments to sync badge count
- **Close:** Radix Dialog handles ESC + outside-click dismiss natively

### Modified: `TradeTable.tsx` (`/frontend/src/components/Trades/TradeTable.tsx`)

- Add "Commentary" column header (second-to-last, before Delete)
- Render `<CommentaryCell tradeId={trade.id} ticker={trade.ticker} />` in each row

### Unchanged

- `CommentaryThread.tsx` — used as-is inside the dialog
- `CommentaryForm.tsx` — used as-is inside `CommentaryThread`
- All backend models, migrations, and API routes

---

## UI / UX Details

| Element | Spec |
|---|---|
| Badge | Chat/message icon + numeric count; "0" shown when no entries (same click behavior) |
| Column position | Second-to-last column, after P&L, before Delete |
| Column header | "Commentary" |
| Modal width | ~560px fixed, centered |
| Modal scroll | Thread area scrolls; add form pinned at bottom |
| Modal header | Trade ticker symbol |
| Tags input | Comma-separated text field (matches existing `CommentaryForm` behavior) |
| Loading | Spinner while initial fetch on mount; re-fetch (not optimistic) after mutations |
| Dismiss | ESC key or outside-click via Radix Dialog primitives |

---

## Modal Library

**Radix UI Dialog** (`@radix-ui/react-dialog`) — already in `package.json`, not yet used elsewhere. This feature introduces it as the project's first modal pattern.

Styling: Tailwind classes matching existing dark/neutral palette. No new CSS files.

---

## Out of Scope

- AI commentary summary (endpoint exists at `/api/trades/{trade_id}/commentary/summary` — not surfaced in this feature)
- Editing existing commentary entries (delete + re-add is sufficient for now)
- Bulk comment pre-fetch with trades list
- Pagination of commentary thread in modal
