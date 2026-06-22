# Feature: WHEEL Strategy Dashboard
**Status:** Implementation Complete — branch `strategy-sessions` ready to push/merge
**Branch:** strategy-sessions
**Created:** 2026-05-31

## Goal
A dedicated WHEEL Strategy page in the frontend that shows every active WHEEL instance grouped by ticker, split into "Needs Action" (called_away, shares_sitting) and "Monitoring" (put_open, cc_open) sections. Replaces the current problem of having 80+ trades with no strategy grouping and no way to know what needs attention at a glance.

## Scope
- In scope:
  - New `trade_sessions` table (generic, supports future strategies)
  - `session_id` nullable FK added to `trades` table
  - Sessions CRUD API + lookup endpoint
  - `WheelDashboardPage` with "Needs Action" / "Monitoring" sections
  - `WheelSessionCard` component — collapsed + expanded with leg history and rotation chain
  - `NewWheelModal` — create session + optionally link existing trades (for migrating active positions)
  - Chrome extension: read-only WHEEL status pill added to E*TRADE row badges
  - Manual status updates (user marks CC as called away, etc.)
- Out of scope:
  - Automated state transitions from E*TRADE
  - Iron Condor / spread session UI (schema supports it, UI deferred)
  - Multi-WHEEL per ticker
  - Bulk migration tool for historical trades
  - Removing `wheel_id` from trades table

## Key Files / Modules Involved
- `backend/alembic/versions/006_trade_sessions.py` — new migration
- `backend/app/models/trade_session.py` — new SQLAlchemy model
- `backend/app/schemas/session.py` — new Pydantic schemas; `SessionLegItem.etrade_symbol` added (2026-06-09)
- `backend/app/routers/sessions.py` — router (GET list, POST create, GET detail, PATCH, GET lookup, **GET /active** added 2026-06-09)
- `backend/app/schemas/trade.py` — add session_id to TradeCreate/TradeUpdate
- `backend/tests/test_sessions.py` — new tests
- `frontend/src/pages/WheelDashboardPage.tsx` — new page
- `frontend/src/components/Wheel/WheelSessionCard.tsx` — multi-leg display; **called_away technical-signal badge + auto-close option leg on called_away transition** (2026-06-10)
- `frontend/src/components/Wheel/NewWheelModal.tsx` — **rewritten step 2 to multi-select checkbox linking** (2026-06-09), so stock + CC can both be linked as legs
- `frontend/src/api/sessions.ts` — API wrapper
- `frontend/src/api/technicals.ts` — used by WheelSessionCard called_away badge (2026-06-10)
- `frontend/src/types/index.ts` — add Session types
- `frontend/src/App.tsx` — add /wheel route
- `frontend/src/components/Wheel/LinkLegModal.tsx` — **new** (2026-06-18): modal for selecting an unlinked open trade to attach as a leg before status transition
- `extension/content.js` — **rewritten pill matching: `etrade_symbol`-exact via `/api/sessions/active` + `etradeSymbolIndex`** (2026-06-09); index now only includes `status === 'open'` legs (2026-06-10); **60s TTL refresh replaces once-per-page-load fetch** (2026-06-18)

## Technical Approach
- `trade_sessions` table: id, ticker, strategy, status, rotation_number, parent_session_id (self-ref), opened_at, closed_at, metadata JSONB
- `trades.session_id` nullable FK → session status updated manually via PATCH /api/sessions/{id}
- Rotation chain: each WHEEL rotation = one session; new rotation = new session with parent_session_id pointing to completed one
- Dashboard calls GET /api/sessions?strategy=WHEEL; card expansion fetches GET /api/sessions/{id} on demand
- Extension: batched GET /api/sessions/lookup per visible ticker; result shown as status pill on existing badge

## WHEEL State Machine
```
put_open → (assigned) → shares_sitting → (sell CC) → cc_open → (called away) → called_away
    ↑                                                                                  │
    └──────────────────────── new rotation (new session) ─────────────────────────────┘

shares_sitting can also start from: direct Buy (Buy Write)
```

## Decisions Made
| Decision | Chosen | Reason |
|----------|--------|--------|
| Generic sessions table | `trade_sessions` with `strategy` column | Avoids second migration for Iron Condor etc. |
| session_id nullable | Nullable FK | Opportunistic/standalone trades must not require a session |
| Status transitions | Manual only (PATCH session) | No automation trigger exists yet |
| Rotation model | One session per rotation, parent_session_id chain | Enables per-rotation P&L and performance audit |
| wheel_id | Left unchanged | Separate concern; no active UI uses it |
| Extension role | Read-only display | Entry flow automation is future scope |
| Pill matching | Exact `etrade_symbol` match via client-side `etradeSymbolIndex` (built from `GET /api/sessions/active`) | Ticker/strategy heuristics couldn't distinguish a standalone sold put from an active wheel CC on the same ticker, and broke with parallel wheel sessions on the same ticker |
| `/api/sessions/active` | Single bulk endpoint, `status NOT IN ('completed','closed')`, no ticker/strategy filter | Replaces N per-ticker `/lookup` calls; client builds one index for both pill matching and spread price lookups |
| NewWheelModal linking | Multi-select checkboxes (was single-select dropdown) | A wheel session needs BOTH the stock and the CC linked as legs (each via its own `etrade_symbol`); single-select left one trade with `session_id = NULL`, breaking pill matching for that leg |
| `called_away` transition | Auto-`POST /trades/{id}/close` on the open option leg (CC); stock leg left untouched | The CC is gone from E*TRADE once assigned/expired; the stock may still be carried into another wheel rotation, so it must not be auto-closed |
| Extension leg index filter | `etradeSymbolIndex` only includes legs with `status === 'open'` | Once a leg is closed in TradeMinder (e.g. via the called_away auto-close above), its E*TRADE row (even if still showing as a stale position) should stop getting a WHL pill |
| `called_away` dashboard signal | Live `GET /api/market/technicals/{ticker}` fetched client-side per called_away `WheelSessionCard`, badge derived from RSI/Bollinger/sentiment | User has no E*TRADE reminder to watch for a put-selling setup after a CC is called away; reuses the existing technicals endpoint rather than persisting new state |
| Leg linking on status transition | `LinkLegModal` — in-context modal to select+link an existing trade before moving to `put_open`/`cc_open` (replaces navigating to `/trades`) | Streamlines the reinstatement flow; user shouldn't have to leave the Wheel dashboard to link a new leg |
| `shares_sitting` auto-close | Auto-close open option legs on `shares_sitting` transition (same as `called_away`) | When shares are assigned from a put, the put contract is gone — its trade should be closed |
| Extension session refresh | 60s TTL (`ACTIVE_SESSIONS_TTL`) instead of once-per-page-load | Pills were stale after status changes; periodic refresh keeps them current without requiring a full page reload |

## Open Questions / Blockers
- [ ] Alembic migration 006 not yet applied to QNAP production DB (pre-existing blocker — need to run `alembic upgrade head` on prod)
- [ ] 4 minor spec gaps identified in final review (not blocking, can be follow-up):
  1. `metadata` field missing from `SessionUpdate` schema
  2. List endpoint does not sort by status priority (called_away/shares_sitting first); sorts by ticker only
  3. `leg_count` missing from `SessionSummary` list response (requires a JOIN/subquery)
  4. "+ New Put" / "+ Sell CC" action buttons don't pre-fill the trade form (links to `/trades` only)
- [ ] **"Continue Wheel (New Rotation)" feature** — proposed but not implemented/confirmed: when a `called_away` session is ready to restart (new put sold), mark it `completed`, create a new session with `rotation_number + 1` and `parent_session_id` pointing at the old one, then link the new put trade. `SessionCreate`/`sessionsApi.create` already support `rotation_number`/`parent_session_id`; `NewWheelModal` doesn't expose them yet.
- [ ] **called_away signal badge fetches yfinance live on every render/expand** of a called_away `WheelSessionCard`. Fine for a handful of sessions; if the user accumulates many parallel called_away wheels this could get slow/rate-limited. Possible follow-up: cache server-side via the existing `technical_signals` table instead of a client-side live fetch.

## Progress Log
- 2026-05-30 — Design discussion: user described problem (80 trades, no grouping), WHEEL lifecycle, opportunistic Put distinction
- 2026-05-31 — Brainstormed multi-leg strategy patterns (Iron Condor, spreads, butterfly); agreed on generic sessions table
- 2026-05-31 — Spec written and approved: `docs/superpowers/specs/2026-05-31-wheel-dashboard-design.md`
- 2026-05-31 — Implementation plan written: `docs/superpowers/plans/2026-05-31-wheel-dashboard.md`
- 2026-05-31 — All 8 tasks implemented via subagent-driven development (8 implementers + spec + quality reviews each). 12 commits on `strategy-sessions`. 124 backend tests pass, TypeScript 0 errors. Branch kept as-is for user to push/merge when ready.
- 2026-06-09 — Fixed strategy-pill mismatch bug (e.g. a standalone sold put showing "WHL: CC Open"): replaced ticker-based `/lookup` matching with exact `etrade_symbol` leg matching via a new bulk `GET /api/sessions/active` endpoint and client-side `etradeSymbolIndex`. Also fixed `NewWheelModal` so creating a wheel can link multiple existing trades (stock + CC) via checkboxes, not just one — confirmed working end-to-end after a fresh-DB test.
- 2026-06-10 — Added a `called_away` "watch for a put-selling setup" signal badge to `WheelSessionCard` (RSI/Bollinger/sentiment via `/api/market/technicals`). Also: marking a session `called_away` now auto-closes its open option leg (CC) via `POST /trades/{id}/close` while leaving the stock leg open (may belong to another rotation); extension `etradeSymbolIndex` now skips non-`open` legs so a closed CC's stale E*TRADE row stops showing a WHL pill.
- 2026-06-18 — Added `LinkLegModal` for wheel session reinstatement: "+" New Put" and "+ Sell CC" buttons now open a modal to select and link an existing unlinked open trade before transitioning status (replaces plain navigation to `/trades`). Also: extension active-sessions fetch changed from once-per-page-load to 60s TTL refresh; `shares_sitting` transition now auto-closes open option legs (same as `called_away`); `WheelDashboardPage.handleStatusUpdate` re-fetches session detail after optimistic update to refresh leg state.

## Current State (Resume Here)
Branch `feature/strategyupdate`. All wheel session reinstatement changes committed (`9a332f5`). The `LinkLegModal` flow replaces the old "navigate to /trades" buttons with an in-context modal that lets the user pick an existing unlinked trade to attach as a leg before transitioning status.

**What's implemented but not yet end-to-end tested in browser:**
- `LinkLegModal` — selecting an unlinked trade, linking it to the session, and transitioning status (put_open / cc_open)
- `shares_sitting` auto-close of option legs (parallels the existing `called_away` auto-close)
- Extension 60s TTL refresh of active sessions (was once-per-page-load)
- Dashboard leg refresh after status update (re-fetches session detail)

**Next action:** Start the frontend dev server and backend, open the Wheel dashboard, and test the `LinkLegModal` flow:
1. From a `called_away` session, click "+ New Put" → verify modal shows unlinked open trades for that ticker → select one → confirm it links and transitions to `put_open`.
2. From a `shares_sitting` session, click "+ Sell CC" → same flow → transitions to `cc_open`.
3. Verify the "Skip" path works (transitions status without linking a trade).
4. Reload the Chrome extension and confirm pills refresh within 60s without a full page reload.
