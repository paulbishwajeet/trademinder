# Feature: WHEEL Strategy Dashboard v2
**Status:** Implementation Complete — on branch `feature/wheelv2`, user testing in progress
**Branch:** feature/wheelv2
**Created:** 2026-05-31 (v1), **Redesigned:** 2026-06-22 (v2)

## Goal
A slot-based WHEEL strategy system that supports multi-contract parallel wheels per ticker, per-slot state machines with a resolve flow for ITM/OTM/buyback/roll outcomes, a premium audit trail, and a compact dashboard grouped by slot status.

## Scope
- In scope (v2):
  - New data model: `wheel_sessions` → `wheel_slots` → `wheel_slot_legs` (join to `trades`) + `wheel_premium_logs`
  - Each slot is an independent state machine: `awaiting_cc` → `cc_active` → resolve → `awaiting_sold_put` → `sold_put_active` → resolve
  - `needs_action` boolean flag preserves slot status context (doesn't replace status)
  - Multi-contract slots (variable `contracts` per slot, e.g. 2 contracts = 200 shares)
  - Resolve flow: 8 outcomes (CC expired OTM/ITM, bought back, rolled; Put expired OTM, assigned, bought back, rolled)
  - Premium audit trail with signed amounts (sells positive, buybacks negative)
  - Compact dashboard: four status-grouped table sections (Needs Action, Awaiting CC, Awaiting Sold Put, Active)
  - Extension pills from `/api/wheel/active-slots` with GOOG/GOOGL ticker aliasing
  - Old `trade_sessions` table preserved for spread strategies (IC, PBWB) — zero changes to spread code
- Out of scope:
  - Automated `needs_action` detection (e.g. watching for trade closures) — user resolves manually
  - Migration of old `trade_sessions` WHEEL data into new tables (old data was cleared)
  - Removing old `trade_sessions` table (still used by spreads)

## Key Files / Modules Involved

### Backend — Models
- `backend/app/models/wheel_session.py` — WheelSession (per ticker)
- `backend/app/models/wheel_slot.py` — WheelSlot (per contract unit, independent state machine)
- `backend/app/models/wheel_slot_leg.py` — WheelSlotLeg (join table: slot ↔ trade with leg_role + rotation_number)
- `backend/app/models/wheel_premium_log.py` — WheelPremiumLog (append-only audit trail)
- `backend/app/models/trade.py` — added `wheel_slot_legs` relationship
- `backend/app/models/__init__.py` — registers all 4 new models

### Backend — Schema + Router
- `backend/app/schemas/wheel.py` — all Pydantic schemas (create/update/detail/resolve/active-slot)
- `backend/app/routers/wheel.py` — all endpoints under `/api/wheel/`
- `backend/app/main.py` — registers wheel router

### Backend — Migration + Tests
- `backend/alembic/versions/008_wheel_v2.py` — creates 4 new tables
- `backend/tests/test_wheel_models.py` — model import test
- `backend/tests/test_wheel_schemas.py` — schema validation tests
- `backend/tests/test_wheel_crud.py` — 12 CRUD endpoint tests
- `backend/tests/test_wheel_resolve.py` — 9 resolve outcome tests

### Frontend
- `frontend/src/api/wheel.ts` — wheelApi client
- `frontend/src/types/index.ts` — WheelSessionDetail, WheelSlotDetail, WheelActiveSlot, etc.
- `frontend/src/pages/WheelDashboardPage.tsx` — compact status-grouped table dashboard
- `frontend/src/components/Wheel/WheelSessionCardV2.tsx` — session card with nested slots
- `frontend/src/components/Wheel/WheelSlotCard.tsx` — individual slot card
- `frontend/src/components/Wheel/NewWheelModalV2.tsx` — create wheel session
- `frontend/src/components/Wheel/AddSlotModal.tsx` — add slot to session
- `frontend/src/components/Wheel/ResolveModal.tsx` — resolve outcomes (OTM/ITM/buyback/roll)
- `frontend/src/components/Wheel/LinkLegModalV2.tsx` — link trade as leg to slot

### Extension
- `extension/content.js` — wheel pills via `/api/wheel/active-slots`, ticker alias map, stock-only pill fallback

### Docs
- `docs/superpowers/plans/2026-06-22-wheel-v2.md` — full implementation plan (10 tasks)

## Technical Approach (v2)
- `wheel_sessions`: id, ticker, total_shares, status (active/closed), opened_at, closed_at
- `wheel_slots`: id, session_id FK, slot_number, contracts, shares_held, status (awaiting_cc/cc_active/awaiting_sold_put/sold_put_active), needs_action (bool), rotation_number
- `wheel_slot_legs`: id, slot_id FK, trade_id FK, leg_role (stock/covered_call/sold_put), rotation_number — thin join table, Trade stays generic
- `wheel_premium_logs`: id, slot_id FK, leg_id FK, rotation_number, premium_amount (signed), event_type, event_date, notes
- Linking a trade auto-transitions slot status and logs premium
- Resolve endpoint handles all 8 outcomes: updates slot status, shares_held, rotation_number, session total_shares, and logs premium events
- Extension fetches `/api/wheel/active-slots` (60s TTL), renders pills per ticker with combined slot statuses

## WHEEL State Machine (v2)
```
awaiting_cc ──sell CC──→ cc_active ──expire OTM──→ awaiting_cc
                                   ──expire ITM──→ awaiting_sold_put (rotation++)
                                   ──bought back──→ awaiting_cc
                                   ──rolled──→ cc_active (new leg linked)

awaiting_sold_put ──sell put──→ sold_put_active ──expire OTM──→ awaiting_sold_put
                                                ──assigned──→ awaiting_cc (rotation++)
                                                ──bought back──→ awaiting_sold_put
                                                ──rolled──→ sold_put_active (new leg linked)
```

## Decisions Made
| Decision | Chosen | Reason |
|----------|--------|--------|
| Slot-per-contract model | Each slot independently tracks its own 100×contracts shares | Solves multi-contract problem — never need to figure out "which 100 of 900 shares were called away" |
| `needs_action` as boolean | Boolean field, not a status value | Preserves slot status context (user sees "CC Active — Action Required" not just "Needs Action") |
| `wheel_slot_legs` join table | Thin join with leg_role + rotation_number | Keeps Trade table generic; wheel-specific metadata lives in the join |
| Premium log with signed amounts | Sells positive, buybacks negative, SUM gives net | Natural accounting — no special logic for net premium queries |
| Resolve as explicit user action | User picks outcome from dropdown | System can't guess ITM vs OTM or whether shares were actually called away |
| Roll = buyback + new sale | Single resolve action logs both entries | Matches broker reality; premium log shows the debit and credit separately |
| Ticker aliases (GOOG/GOOGL) | Client-side alias map in extension | GOOG shares + GOOGL options are the same underlying; extension needs to match across share classes |
| Stock-only pill fallback | Extension pills on stock rows match by ticker; option rows require explicit etrade_symbol match | Prevents unrelated options from showing wheel pills |
| Dashboard layout | Flat status-grouped tables instead of nested session→slot cards | 19+ wheels need to be scannable at a glance; one row per slot is much more compact |
| Old trade_sessions preserved | Not dropped or modified | IC and PBWB spread strategies still use it; zero-risk migration |

## Open Questions / Blockers
- [ ] **Automated `needs_action` detection** — currently manual. Could watch for trade closures (via extension sync or a background job) and auto-set `needs_action=true` when a linked leg's trade gets closed. Deferred.
- [ ] **Premium log edge case:** when a trade has `premium=0` (e.g. stock leg), the link-leg endpoint skips logging. If a stock purchase has a meaningful cost basis that should be tracked, the log schema supports it but the endpoint doesn't capture it.
- [ ] **Closing a wheel session** — UI has no "Close Wheel" button yet on the dashboard. The PATCH endpoint supports it (`status: "closed"`), but no frontend trigger exists. Low priority — user can do it via API.
- [ ] **Add Slot from dashboard** — the `WheelSessionCardV2` has the "+ Slot" button but the new flat dashboard doesn't surface it. Need to decide if adding slots belongs on a session detail page or a global action.
- [ ] **Production migration** — `alembic upgrade head` needs to run on prod DB to create the 4 new tables (migration 008).

## Progress Log
- 2026-05-30 — v1 design discussion and spec
- 2026-05-31 — v1 implemented (8 tasks, `strategy-sessions` branch)
- 2026-06-09 — v1 extension pill fix (etrade_symbol matching), NewWheelModal multi-select
- 2026-06-10 — v1 called_away signal badge, auto-close option legs
- 2026-06-18 — v1 LinkLegModal, extension 60s TTL refresh
- 2026-06-22 — **v2 complete redesign**: new slot-based data model (WheelSession/WheelSlot/WheelSlotLeg/WheelPremiumLog), alembic migration 008, full CRUD + resolve router with 25 tests, frontend rewrite with 7 new components, extension pills from `/api/wheel/active-slots`, old WHEEL sessions cleared from DB, compact status-grouped dashboard layout. Bugs fixed: stock-only pill fallback, GOOG/GOOGL alias.

## Current State (Resume Here)
Branch `feature/wheelv2` with 12 commits on top of `master` (base: `70df503`). All backend tests pass (25/25). TypeScript compiles clean. Migration 008 applied to local Docker PostgreSQL.

User has created 19 wheel sessions with slots and is actively testing. Old WHEEL `trade_sessions` data was cleared from the DB (31 sessions unlinked + deleted). Spread sessions (IC, PBWB) remain on the old `trade_sessions` table and are unaffected.

**What works end-to-end:**
- Creating wheels, adding slots (with variable contracts), linking trades as legs
- Auto-status transition on leg link (awaiting_cc → cc_active, awaiting_sold_put → sold_put_active)
- Premium logging on link and resolve
- Extension pills showing per-ticker wheel status with GOOG/GOOGL alias
- Compact dashboard with four status-grouped sections

**What has NOT been tested yet:**
- Resolve flow (OTM/ITM/buyback/roll) — endpoints pass tests but not yet exercised in browser
- Multi-contract slot behavior (e.g. 2-contract CC called away)
- Premium log display and totals in the expanded slot view

**Next action:** Continue real-world testing of the resolve flow. When a CC expires or gets bought back, use the Resolve button on the dashboard to test each outcome path. Then verify premium totals accumulate correctly across rotations.
