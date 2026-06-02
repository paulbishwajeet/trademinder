# E*TRADE ↔ Backend Reconciliation Design

**Date:** 2026-06-01
**Status:** Approved
**Branch:** (new, off develop)

---

## Problem

Trades accumulate in E*TRADE and the TradeMinder backend independently. Three concrete mismatches arise:

1. A new position opened in E*TRADE was never entered in the backend.
2. A position closed in E*TRADE was never marked closed in the backend (stale backend record).
3. Historical bulk state: many trades exist in only one system, requiring an initial cleanup pass.

---

## Goal

- Chrome extension: visually flag E*TRADE positions that have no backend record so the user can add them.
- Frontend (TradesPage): visually flag backend open trades that are no longer visible in E*TRADE so the user can mark them closed.

No automated sync. All actions remain manual and user-initiated.

---

## Approach

**Reconciliation endpoint with ephemeral comparison.**

On each E*TRADE positions page load, the extension sends all visible positions to `POST /api/positions/reconcile` in a single batch. The backend diffs this snapshot against open trades, updates a `last_etrade_seen` timestamp on matched trades, and returns two lists:

- `unmatched_etrade`: positions visible in E*TRADE with no matching backend record
- `stale_backend`: open backend trades that were previously seen in E*TRADE but are no longer present

No persistent snapshot table. The `last_etrade_seen` column on the `trades` table is the only stored state.

---

## Architecture & Data Flow

```
Extension (E*TRADE positions page load)
  → parse all visible rows → collect positions[]
  → POST /api/positions/reconcile { positions: [...] }
  ← { unmatched_etrade: [...], stale_backend: [...] }
  → badge each unmatched row with "Add" pill (extension ignores stale_backend)

Backend (reconcile handler)
  → query all open trades
  → match submitted positions against open trades (ticker+type for stock; ticker+strike+expiry+option_type for options)
  → UPDATE trades SET last_etrade_seen = now() WHERE matched
  → return unmatched_etrade + stale_backend

Frontend (TradesPage)
  → GET /api/trades (existing call, now includes last_etrade_seen)
  → render "Stale" badge on open trades where last_etrade_seen IS NOT NULL AND last_etrade_seen < now - 1 day
  → "Mark Closed" quick action on stale rows → PATCH /api/trades/{id} { status: "closed", closed_date: today }
```

---

## Schema

**New Alembic migration** — one column added to `trades`:

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `last_etrade_seen` | DateTime (with tz) | Yes | Null = never matched via reconcile; never flagged stale |

**New index:** `(status, last_etrade_seen)` to support the stale query efficiently.

---

## Backend

### `POST /api/positions/reconcile`

**Request body:**
```json
{
  "positions": [
    { "ticker": "AAPL", "full_symbol": null, "strike": null, "expiry": null, "option_type": null, "quantity": 100 },
    { "ticker": "AAPL", "full_symbol": "AAPL250620C00200000", "strike": 200.0, "expiry": "2025-06-20", "option_type": "C", "quantity": 1 }
  ]
}
```

**Response:**
```json
{
  "unmatched_etrade": [
    { "ticker": "NVDA", "full_symbol": "NVDA250718P00120000", "strike": 120.0, "expiry": "2025-07-18", "option_type": "P" }
  ],
  "stale_backend": [
    { "id": "uuid", "ticker": "META", "type": "stock", "quantity": 50, "open_date": "2025-01-10", "last_etrade_seen": "2025-05-20T10:00:00Z" }
  ]
}
```

**Matching logic** (reuses existing logic from `/api/positions/status`):
- Stock: match on `ticker` + `type = "stock"` + `status = "open"`
- Option: match on `ticker` + `strike` + `expiry` + `option_type` + `status = "open"`

**Stale definition:**
Open trades where `last_etrade_seen IS NOT NULL AND last_etrade_seen < now() - interval '1 day'` and not matched in the current reconcile call.

The null guard ensures trades that were only ever manually tracked (never matched via reconcile) are never flagged stale.

### `GET /api/trades` — minor addition

Add optional `?stale=true` query param that applies the stale filter above, enabling the frontend to fetch a count or filtered list without client-side computation.

---

## Extension

**New reconcile call on page load:**

1. After MutationObserver collects all visible rows into `seenPositions[]`, fire `POST /api/positions/reconcile` with the full list alongside the existing `POST /api/positions/status` flow. The two calls are independent.
2. Store `unmatched_etrade` results in a new `reconcileCache` Map keyed by `full_symbol || ticker`.
3. After `applyTMToRow` runs per row, call new `applyReconcilePillToRow` — if the row's key is in `reconcileCache`, inject an "Add" pill.

**"Add" pill:**
- Orange/amber color, labeled `+ Add` or `? Not tracked`
- Visually distinct from the existing WHEEL pill and status badges
- Clicking it opens the existing inline add-trade modal, pre-filled with parsed position data (ticker, strike, expiry, option_type, quantity)
- Reuses the existing modal — no new UI needed

**Unchanged:** The existing `POST /api/positions/status` call, DTE/RSI/commentary badges, and WHEEL pill are untouched.

---

## Frontend

**TradesPage — stale indicator:**

- `last_etrade_seen` is included in the existing `GET /api/trades` response.
- Open trades with `last_etrade_seen` not null and older than 1 day render an amber `Not in E*TRADE` badge in their row.
- A `Mark Closed` inline button fires `PATCH /api/trades/{id}` with `{ status: "closed", closed_date: today }` — same endpoint used today for closing trades.

**Stale filter banner (for bulk cleanup):**

- Dismissible banner at top of TradesPage: `X open trades not seen in E*TRADE — review stale trades`
- Banner includes a toggle to filter the table to stale-only rows
- No new page, no new API call — filter state is local to the TradesPage component

---

## Out of Scope

- Automated sync or status transitions
- E*TRADE trade history (closed trades feed) — positions page only
- Quantity mismatch detection (only presence/absence is compared)
- Bulk "close all stale" action

---

## Open Questions

- None at design time. The 1-day stale threshold can be made configurable later if needed.
