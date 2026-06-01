# WHEEL Strategy Dashboard — Design Spec

**Date:** 2026-05-31
**Status:** Approved
**Branch:** feature/wheel-dashboard

---

## Goal

Add a dedicated WHEEL Strategy page to the frontend that shows every active WHEEL instance grouped by ticker, with a clear "needs attention" vs "monitoring" split. The user should be able to open this page and immediately know which positions require an action (find a new Put entry, sell a Covered Call) and which are running without intervention.

Secondary goal: add a lightweight session indicator to the Chrome extension so E*TRADE position rows are labelled with their WHEEL status.

---

## The Problem Being Solved

The portfolio has grown to ~80 trades across multiple strategies. E*TRADE has no concept of strategy grouping. The user cannot tell at a glance:
- Which WHEEL positions are "called away" and waiting for a new Put entry
- Which stocks are sitting unoptimised (no CC sold yet)
- What the full history of a WHEEL rotation looks like for performance review

---

## WHEEL State Machine

A WHEEL instance on a ticker is always in exactly one of five states:

```
                    ┌─────────────────────────────────────┐
                    │                                     │
           expires worthless                     expires worthless
                    │                                     │
[START] ──► PUT_OPEN ──► assigned ──► SHARES_SITTING ──► CC_OPEN
  │                                        │                  │
  │ (buy write)                            │              called away
  └────────────────────────────────────────┘                  │
                                                              ▼
                                                       CALLED_AWAY
                                                              │
                                                  open new Put (new rotation)
                                                              │
                                                         [NEW SESSION]
```

**State definitions:**

| Status | Meaning | Needs action? |
|---|---|---|
| `put_open` | Active Sold Put position | No — wait for expiry or assignment |
| `shares_sitting` | Own stock, no active CC | Yes — sell a Covered Call |
| `cc_open` | Active Covered Call on the stock | No — wait for expiry or call-away |
| `called_away` | CC was exercised, shares called away, cash in hand | Yes — look for next Put entry |
| `completed` | Rotation closed out intentionally | No — archived |

**Starting points:**
- Classic entry: Sell a Put → `put_open`
- Buy Write entry: Buy 100 shares directly → `shares_sitting`

**Rotation chain:**
Each full cycle (Put → Assignment → CC → Called Away) is one *rotation*. When the user starts the next rotation, a new session is created with `parent_session_id` pointing to the completed one. This builds a chain of rotations that can be traversed for performance audit.

---

## Data Model

### New table: `trade_sessions`

```sql
CREATE TABLE trade_sessions (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ticker            VARCHAR(10)  NOT NULL,
  strategy          VARCHAR(30)  NOT NULL,   -- "WHEEL", future: "IRON_CONDOR" etc.
  status            VARCHAR(30)  NOT NULL,   -- strategy-specific; see state machine above
  rotation_number   INTEGER      NOT NULL DEFAULT 1,
  parent_session_id UUID         REFERENCES trade_sessions(id) ON DELETE SET NULL,
  opened_at         DATE         NOT NULL,
  closed_at         DATE,
  metadata          JSONB,                   -- reserved for future multi-leg strategies
  created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_trade_sessions_ticker_strategy ON trade_sessions(ticker, strategy);
CREATE INDEX idx_trade_sessions_status          ON trade_sessions(status);
CREATE INDEX idx_trade_sessions_parent          ON trade_sessions(parent_session_id)
  WHERE parent_session_id IS NOT NULL;
```

### Modified table: `trades`

Add one nullable column:

```sql
ALTER TABLE trades
  ADD COLUMN session_id UUID REFERENCES trade_sessions(id) ON DELETE SET NULL;

CREATE INDEX idx_trades_session_id ON trades(session_id)
  WHERE session_id IS NOT NULL;
```

**All existing columns are unchanged.** `wheel_id` is left as-is — it is not migrated or removed.

**The session_id rule:**
- `session_id = NULL` — standalone / opportunistic trade (not part of any strategy session)
- `session_id = <uuid>` — a leg of a strategy session

A standalone Sold Put (opportunistic) and a WHEEL Sold Put are both `Sell Put` trades. The only distinction is whether `session_id` is set.

### Alembic migration: `006_trade_sessions.py`

Creates `trade_sessions` table and adds `session_id` to `trades`. Reversible (down removes both).

---

## Backend API

### New router: `/api/sessions`

**`GET /api/sessions`**
- Query params: `strategy` (optional, default `WHEEL`), `status` (optional), `ticker` (optional)
- Returns: `list[SessionSummary]` — id, ticker, strategy, status, rotation_number, opened_at, closed_at, leg_count
- Default: returns all WHEEL sessions ordered by status priority (called_away and shares_sitting first), then ticker

**`POST /api/sessions`**
- Body: `SessionCreate` — ticker, strategy, status, opened_at, parent_session_id (optional)
- Returns: `SessionResponse`
- Creates a new session. Does not create trades.

**`GET /api/sessions/{session_id}`**
- Returns: `SessionWithLegs` — full session fields + `legs: list[TradeListItem]` (all trades with this session_id, ordered by open_date asc) + `rotation_chain: list[SessionSummary]` (ancestor sessions via parent_session_id, oldest first)

**`PATCH /api/sessions/{session_id}`**
- Body: `SessionUpdate` — status (optional), closed_at (optional), metadata (optional)
- Returns: `SessionResponse`
- Used for manual status updates (e.g. mark as `called_away` after CC is exercised)

**`GET /api/sessions/lookup`**
- Query params: `ticker` (required), `strategy` (required)
- Returns: `{ ticker, strategy, has_existing: bool, sessions: list[SessionSummary] }`
- Returns all non-completed sessions for this ticker+strategy
- Used by: Chrome extension session picker; new session creation flow

### Modified: `POST /api/trades`

Add `session_id: Optional[UUID] = None` to `TradeCreate` schema. When provided, the created trade is linked to that session. The session's `status` is NOT automatically updated — status changes are always manual via `PATCH /api/sessions/{id}`.

### Modified: `PATCH /api/trades/{trade_id}`

Add `session_id: Optional[UUID] = None` to `TradeUpdate` schema. Allows linking an existing trade to a session retroactively (used during initial setup / migration of existing positions).

---

## Frontend

### New page: `WheelDashboardPage`

**Route:** `/wheel`
**Nav:** Add "WHEEL" link to sidebar/nav between "Trades" and next item.

**Layout:**

```
┌────────────────────────────────────────────────────────────────┐
│  WHEEL Strategy                                  + New Wheel   │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  ⚠ NEEDS ACTION  (2)                                          │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ NVDA   Called Away / Waiting Cash          [+ New Put]   │ │
│  │        CC $120 exp May 30 — called away                  │ │
│  │        Rotation 2  ·  started Apr 1                      │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │ AAPL   Shares Sitting                      [+ Sell CC]   │ │
│  │        100 shares @ $182.40 (assigned May 16)            │ │
│  │        Rotation 1  ·  started Apr 15                     │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                │
│  ✓ MONITORING  (2)                                            │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ SPY    CC Open   $520 exp Jun 20   $2.30 prem            │ │
│  │        Rotation 3  ·  $12.80 total collected             │ │
│  ├──────────────────────────────────────────────────────────┤ │
│  │ TSLA   Put Open  $240 exp Jun 13   $1.80 prem            │ │
│  │        Rotation 1  ·  started May 20                     │ │
│  └──────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

**Section logic:**
- "Needs Action": sessions with status `called_away` or `shares_sitting`
- "Monitoring": sessions with status `put_open` or `cc_open`
- "Completed" / archived: hidden by default; toggle to show

### Component: `WheelSessionCard`

**File:** `frontend/src/components/Wheel/WheelSessionCard.tsx`

**Props:**
```ts
interface Props {
  session: SessionWithLegs
  onStatusUpdate: (id: string, status: string) => void
}
```

**Collapsed state (default view):**
- Left accent bar colored by status (amber = needs action, blue = monitoring, green = completed)
- Ticker (bold), status label, rotation number, started date
- One-line summary of the active leg: "CC $520 exp Jun 20 · $2.30 prem" or "100 shares @ $182 (assigned)"
- Action button (contextual):
  - `called_away` → `+ New Put` (links to `/trades` with new trade form pre-filled)
  - `shares_sitting` → `+ Sell CC` (links to `/trades` with new trade form pre-filled)
  - `put_open` / `cc_open` → `Mark Status` dropdown (manual status override)

**Expanded state (click to expand):**
- Full list of trade legs for the current rotation, newest first:
  ```
  ▼ Current Rotation (Rotation 2)
    May 30  Sell CC  $120  exp May 30  assigned  $2.00 prem   →  [view]
    May 17  Stock    100 shares        open       $118.50/sh   →  [view]
    May 16  Sell Put $115  exp May 16  assigned   $1.80 prem   →  [view]
  ```
- Collapsible rotation history (oldest rotations):
  ```
  ▶ Rotation 1  (Apr 1 – May 16)  $4.30 collected
  ```
- "Edit Status" button: inline dropdown to manually change session status
- Premium total: sum of all premium collected in current rotation (and grand total across rotations)

**Status change flow (manual):**
User clicks "Edit Status" → inline dropdown with valid next states → confirm → `PATCH /api/sessions/{id}` → card re-renders with new status and moves to correct section.

### Component: `NewWheelModal`

Triggered by "+ New Wheel" button.

**Step 1 — Session setup:**
- Ticker input
- Starting phase: `Put Open` / `Shares Sitting (Buy Write)` / `Shares Sitting (Assigned)`
- Opened date (defaults to today)

**Step 2 — Link first leg:**
- Option A: "Link existing trade" — searchable dropdown of existing trades for that ticker with no session_id
- Option B: "I'll add trades later" — creates the session only

On submit: `POST /api/sessions` → if Option A, `PATCH /api/trades/{id}` to set session_id.

### Data loading

`WheelDashboardPage` makes a single call:
```
GET /api/sessions?strategy=WHEEL
```

For each session card expansion, fetch on demand:
```
GET /api/sessions/{session_id}   (returns legs + rotation chain)
```

No polling. User refreshes manually or after making changes.

---

## Chrome Extension

### Session indicator on E*TRADE rows

The extension already calls `/api/positions/status` for visible rows. Add a parallel call to session lookup:

**New call:** `GET /api/sessions/lookup?ticker={ticker}&strategy=WHEEL` (batched per visible ticker, one call per unique ticker)

**If session found:** Append a small pill to the existing badge:
```
[DTE 22] [RSI 54] [WHEEL: CC Open]
```

**Status pill colors:**
- `called_away`, `shares_sitting` → amber background (matches "needs action")
- `put_open`, `cc_open` → blue background (matches "monitoring")

This is read-only. The extension does not update session state.

**Batching:** Collect all unique tickers from visible rows, make one lookup per ticker, cache results in `sessionCache: Map<ticker, SessionSummary | null>` for the page session. Cache is cleared on full row reprocess.

---

## Status Color System

| Status | Label | Color | Section |
|---|---|---|---|
| `called_away` | Called Away / Waiting Cash | Amber `#F59E0B` | Needs Action |
| `shares_sitting` | Shares Sitting | Amber `#F59E0B` | Needs Action |
| `put_open` | Put Open | Blue `#3B82F6` | Monitoring |
| `cc_open` | CC Open | Blue `#3B82F6` | Monitoring |
| `completed` | Completed | Green `#10B981` | Archived (hidden) |

---

## Migration Path for Existing Positions

No automated migration. User manually links their active WHEEL positions on day one:

1. Click "+ New Wheel" for each active WHEEL ticker
2. Set the current status and opening date
3. In Step 2, link the most recent trades for that wheel via "Link existing trade"
4. Historical completed rotations remain as standalone trades

Expected setup time: ~2 minutes per active WHEEL. For a portfolio with 8 active WHEELs: ~15 minutes total.

---

## Out of Scope

- Automated session status transitions from E*TRADE (future)
- Iron Condor / spread session UI (future — schema already supports it)
- Multi-WHEEL per ticker (future)
- Bulk migration tool for historical trades
- Per-session P&L calculation (total premium is a sum of trade premiums; net P&L including cost basis is a future enhancement)
- Removing or renaming `wheel_id` from the trades table

---

## Files Changed

| File | Change |
|---|---|
| `backend/alembic/versions/006_trade_sessions.py` | **New** — creates `trade_sessions`, adds `session_id` to `trades` |
| `backend/app/models/trade_session.py` | **New** — SQLAlchemy `TradeSession` model |
| `backend/app/schemas/session.py` | **New** — `SessionCreate`, `SessionUpdate`, `SessionResponse`, `SessionWithLegs`, `SessionSummary`, `SessionLookupResponse` |
| `backend/app/routers/sessions.py` | **New** — GET list, POST create, GET detail, PATCH update, GET lookup |
| `backend/app/main.py` | Register sessions router |
| `backend/app/schemas/trade.py` | Add `session_id: Optional[UUID] = None` to `TradeCreate` and `TradeUpdate` |
| `backend/app/routers/trades.py` | Handle `session_id` on create and update |
| `backend/tests/test_sessions.py` | **New** — CRUD tests + lookup endpoint tests |
| `frontend/src/types/index.ts` | Add `Session`, `SessionSummary`, `SessionWithLegs` types |
| `frontend/src/api/sessions.ts` | **New** — `sessionsApi.list()`, `.get()`, `.create()`, `.update()`, `.lookup()` |
| `frontend/src/pages/WheelDashboardPage.tsx` | **New** — main dashboard page |
| `frontend/src/components/Wheel/WheelSessionCard.tsx` | **New** — session card (collapsed + expanded) |
| `frontend/src/components/Wheel/NewWheelModal.tsx` | **New** — session creation + existing trade linking |
| `frontend/src/App.tsx` | Add `/wheel` route |
| `extension/content.js` | Add session lookup + WHEEL status pill to badge |

---

## Decisions Made

| Decision | Chosen | Reason |
|---|---|---|
| Generic `trade_sessions` table (not `wheel_sessions`) | Generic | Adding `strategy` column costs nothing; avoids a second migration when Iron Condor is added |
| `session_id` nullable | Nullable | Standalone/opportunistic trades must not be forced into sessions |
| Session status updated manually | Manual only | No reliable automated trigger exists yet; extension automation is a future layer |
| Rotation = one session, not a counter on one session | One session per rotation | Enables per-rotation P&L, performance audit, and `parent_session_id` chain |
| `wheel_id` left unchanged | Keep as-is | Removing it is a separate migration; no active UI uses it; avoid scope creep |
| Extension is read-only for sessions | Read-only | Manual state management is the MVP; extension entry flow is future |
| Premium total shown on card | Sum of `trade.premium` for legs in session | Simple derivation; no new backend field needed |
