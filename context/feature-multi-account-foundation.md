# Feature: Multi-Account & Multi-User Foundation (Part 1 of 5)

**Status:** Complete — merged to `master`

## Goal
Introduce users and brokerage accounts (user → account → trades / wheels / spreads) and a single
current-user seam (`app/deps.py::get_current_user`) in front of every user-owned query, so Part 5
(Google login) only changes that function. The app must look and behave exactly as before for the owner.

## Scope
In: migrations 015 + 016, models, schemas, ownership/accounts services, accounts API, account-aware list/create
rules, screener memberships + per-account notes, extension endpoints pinned to the default account, scheduler
writes `user_id`, cache audit, pytest isolation/migration/account suites, frontend types + `src/api/accounts.ts`,
docs.
Out: login/OAuth/sessions/tokens/admin pages (Part 5), navigation/account pages/pickers (Part 2), extension
account detection + dropdown linking + disabling Reconcile in all-accounts view (Part 3), Schwab banner /
provider abstraction / SchwabClient / schwab_tokens (Part 4), RLS, Redis, queues, cloud, signal scoring,
wheel state machine, E*TRADE DOM handling.

## Key Files
- Spec: `docs/superpowers/specs/2026-11-04-multi-account-foundation-design.md`
- Plan: `docs/superpowers/plans/2026-11-04-multi-account-foundation.md`
- `backend/alembic/versions/015_users_and_accounts.py`, `016_ownership_backfill.py`
- `backend/app/models/user.py`, `backend/app/models/brokerage_account.py`
- `backend/app/deps.py` (current-user seam)
- `backend/app/services/ownership.py`, `backend/app/services/accounts.py`
- `backend/app/routers/accounts.py` + every router touching user data
- `backend/tests/test_isolation.py`, `test_accounts.py`, `test_migration_multi_account.py`
- `frontend/src/types/index.ts`, `frontend/src/api/accounts.ts`; `account_id` added to create types in
  `frontend/src/api/wheel.ts`, `frontend/src/api/sessions.ts`
- Routers changed: `trades.py`, `wheel.py`, `sessions.py` (spreads), `positions.py` (status/reconcile/dashboard),
  `screener.py` (rewritten: memberships, per-account notes, owner-only jobs), `commentary.py` (summary cache fix),
  `alerts.py`, `signals.py`, `categories.py`, `market.py`; `backend/app/main.py` registers `accounts`
- Scheduler services: `backend/app/services/alert_engine.py`, `signal_engine.py`, `price_fetcher.py`
- Test infra: `backend/tests/conftest.py` (owner + default-account fixtures, `act_as(user)` switch),
  `test_reconcile.py` (account-scoping tests)
- Config: `backend/app/config.py` (`owner_email`, `owner_display_name`), `.env.example`, `docker-compose.prod.yml`
  (`OWNER_EMAIL` required), `.gitignore` (`backups/`)
- Docs: `README.md`, `docs/TradeMinder-Context.md` (now tracked; was untracked before this branch)
- Live-DB backup: `backups/trademinder-pre-016-20261103-2122.dump` (git-ignored, pg_dump custom format)

## Technical Approach
- UUID ids throughout (matches codebase). `user_id` on every user-owned table; `account_id` only on the
  account-scoped parents (trades, wheel_sessions, trade_sessions) and on screener_commentary. Children
  inherit their account through the parent.
- Every per-id lookup goes through `services/ownership.py`, which filters by `user_id` and 404s on
  missing *or foreign* ids (never 403). `resolve_account()` returns the named account or the default.
- List endpoints: optional `account_id`; absent = all accounts (today's UI unchanged).
  Create endpoints: optional `account_id`; absent = default account.
- `positions/status` and `positions/reconcile` resolve to the default account for now.
  **Part 3 replaces this with explicit account linking** (`brokerage_accounts.external_ref`).

## Decisions Made
| Decision | Reason |
|---|---|
| Ownership hierarchy: user → brokerage account → trades, wheels, spreads | An account is the container for positions, cash and margin |
| Tenant key is internal user id; Google identity later as separate nullable `external_subject`; email never the key | Identities and emails change, tenant keys must not |
| One wheel per ticker per account | Same ticker in two accounts = two separate wheels |
| Categories are a per-user library; each account picks its categories and has a default category | Shared vocabulary per user; per-account relevance |
| Screener: one symbol row per user; symbol belongs to ≥1 accounts; notes are per account | Market data fetched once; notes reflect an account's situation (IRA vs taxable) |
| Market data (Schwab, quotes, technicals, signal caches) stays app-level and shared | Not user data; expensive to fetch |
| Admin manages accounts only, never reads another user's data; no admin features now | Privacy |
| New migrations are 015/016, not 013/014 | Head was already 014 (BUY_WRITE committed, SPECULATIVE uncommitted but applied to DB) |
| No wheel uniqueness constraint added | None existed; prod has 18 tickers with 2 active wheel sessions, an index would break the migration |
| `daily_briefings` date uniqueness rescoped per user | Was globally unique; table is user-owned |
| Data access stays in routers, but every per-id lookup goes through `services/ownership.py` | Full router→service refactor out of scope; the ownership service is the single enforcement point |
| Foreign ids → 404 | Don't reveal existence of other users' rows |
| Cross-account links (wheel leg in another account, etc.) → 400 | A wheel's legs must live in the wheel's account |
| New categories auto-link to all of the user's active accounts | Matches today's "every category everywhere" behaviour |
| Migration 016 downgrade refuses when non-owner data exists | Restoring global uniqueness would collide/lose data |
| One-open-trade-per-E*TRADE-symbol rescoped per account | Same contract can be open in two accounts; other users must never collide |
| Child lists (trade commentary / signals / alerts) keep returning `[]` for unknown or foreign trades | Existing contract (pinned by a test); user filter makes unknown and foreign indistinguishable |
| Manual market/signal refresh endpoints run for the caller only; scheduler runs for everyone | Counts would otherwise reveal other users' trade volume |
| Owner email is the owner's Gmail address (set in `.env` as `OWNER_EMAIL`, seeded in `users`) | The address the user will sign in with via Google in Part 5 |
| Live DB migrated to 016 only after a full `pg_dump` backup and explicit user approval | It is the only copy of real data; migration was first proven on `createdb -T trademinder` copies |
| SPECULATIVE category committed separately, before the feature | Unrelated work that was uncommitted in the working tree; keeps history reviewable |
| `docs/TradeMinder-Context.md` committed as part of the feature | The brief treats it as the in-repo master context and it was updated for multi-user |

## Open Questions
> Still-open items were carried to `docs/TRADEMINDER_MASTER_CONTEXT.md` §0 Open items in the 2026-11-12 audit.

1. Merge the duplicate active wheels so `(account_id, ticker) WHERE status <> 'closed'` can be enforced?
2. Require a trade's category to be in its account's category list? (not enforced in Part 1)
3. Unarchive endpoint (needed by Part 2 UI).
4. Category-library seeding for a newly signed-up user (Part 5).
5. ~~Uncommitted SPECULATIVE work~~ — resolved: committed as `92447f1`.
6. The E*TRADE extension overlay and Reconcile have NOT been exercised in a real browser against the migrated live
   DB (only via API parity tests on a copy). Needs a manual check.
7. Wheel/spread/dashboard lists have no tie-breaking sort key, so rows with equal ticker / open_date /
   triggered_at may come back in a different order than before the migration rewrote the rows. Add `id` as a
   secondary ORDER BY if the UI order matters.
8. `docker-compose.prod.yml` now fails to start without `OWNER_EMAIL` — the QNAP deployment's env must be updated
   before this ships there.

## Progress Log
- 2026-11-03: Branch created off develop. Inventory done (see spec). Spec + plan written.
- 2026-11-03: Migrations 015/016, models, schemas, `app/deps.py` seam, `services/ownership.py`,
  `services/accounts.py`, `/api/accounts`, all routers scoped, scheduler writes `user_id`, cache fixes
  (AI-summary cache checked ownership *after* returning; screener job status had no owner).
- 2026-11-03: Found and rescoped an undeclared global unique index (`idx_trades_etrade_symbol_open`, migration 003).
- 2026-11-03: Tests: `test_isolation.py` (9), `test_accounts.py` (27), `test_migration_multi_account.py` (1),
  2 reconcile-scoping tests. Isolation and reconcile tests mutation-checked (they fail when the filter is removed).
  Full suite: 362 passed, only the 6 known pre-existing failures (test_cc_signal ×4, test_market_router_p2,
  test_schwab_client).
- 2026-11-03: Migrations verified on a copy of the live DB: upgrade backfills every row, downgrade restores a
  byte-identical schema, re-upgrade works. Owner parity old-vs-new code on live data: identical apart from tie order.
- 2026-11-03: Frontend types + `src/api/accounts.ts` (tsc: no new errors; 2 pre-existing unused-var errors remain).
  README + docs/TradeMinder-Context.md updated.
- 2026-11-03: Live dev DB backed up (`backups/trademinder-pre-016-20261103-2122.dump`) and migrated 014 → 016 with
  `OWNER_EMAIL` set to the owner's Gmail; API verified: 440 trades, 65 wheels, 39 screener rows, 12 categories, 833 alerts.
- 2026-11-03: Committed `92447f1` (SPECULATIVE category) and `c7c2893` (this feature) on
  `feature/multi-account-foundation`. Not pushed.
- 2026-11-12: Context audit: marked Complete; code verified on `master`.

## Current State (Resume Here)
COMPLETE — merged to `master` (`develop` 67a5a4d → `master` 8b60b68 (multi-user release, 2026-11-11)). Part 1 of the multi-user plan. Nothing pending here.
