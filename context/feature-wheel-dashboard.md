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
- `backend/app/schemas/session.py` — new Pydantic schemas
- `backend/app/routers/sessions.py` — new router (GET list, POST create, GET detail, PATCH, GET lookup)
- `backend/app/schemas/trade.py` — add session_id to TradeCreate/TradeUpdate
- `backend/tests/test_sessions.py` — new tests
- `frontend/src/pages/WheelDashboardPage.tsx` — new page
- `frontend/src/components/Wheel/WheelSessionCard.tsx` — new component
- `frontend/src/components/Wheel/NewWheelModal.tsx` — new component
- `frontend/src/api/sessions.ts` — new API wrapper
- `frontend/src/types/index.ts` — add Session types
- `frontend/src/App.tsx` — add /wheel route
- `extension/content.js` — session lookup + WHEEL status pill

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

## Open Questions / Blockers
- [ ] Alembic migration 006 not yet applied to QNAP production DB (pre-existing blocker — need to run `alembic upgrade head` on prod)
- [ ] 4 minor spec gaps identified in final review (not blocking, can be follow-up):
  1. `metadata` field missing from `SessionUpdate` schema
  2. List endpoint does not sort by status priority (called_away/shares_sitting first); sorts by ticker only
  3. `leg_count` missing from `SessionSummary` list response (requires a JOIN/subquery)
  4. "+ New Put" / "+ Sell CC" action buttons don't pre-fill the trade form (links to `/trades` only)

## Progress Log
- 2026-05-30 — Design discussion: user described problem (80 trades, no grouping), WHEEL lifecycle, opportunistic Put distinction
- 2026-05-31 — Brainstormed multi-leg strategy patterns (Iron Condor, spreads, butterfly); agreed on generic sessions table
- 2026-05-31 — Spec written and approved: `docs/superpowers/specs/2026-05-31-wheel-dashboard-design.md`
- 2026-05-31 — Implementation plan written: `docs/superpowers/plans/2026-05-31-wheel-dashboard.md`
- 2026-05-31 — All 8 tasks implemented via subagent-driven development (8 implementers + spec + quality reviews each). 12 commits on `strategy-sessions`. 124 backend tests pass, TypeScript 0 errors. Branch kept as-is for user to push/merge when ready.

## Current State (Resume Here)
All 8 tasks are complete on branch `strategy-sessions`. The branch has **not been pushed** and has **not been merged to master**.

**Next action:** Push the branch and open a PR, or merge locally:
```bash
# Option A: push + PR
git push -u origin strategy-sessions
gh pr create --title "feat: add WHEEL Strategy Dashboard with sessions API and extension pills"

# Option B: merge locally
git checkout master && git merge strategy-sessions
```

Before deploying, apply the Alembic migration on the production QNAP DB:
```bash
cd backend && alembic upgrade head
```

The 4 minor spec gaps above can be addressed as a quick follow-up before or after merging.
