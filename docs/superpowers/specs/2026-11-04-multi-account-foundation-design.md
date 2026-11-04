# Multi-Account & Multi-User Foundation — Part 1 of 5 (Design)

**Date:** 2026-11-04
**Branch:** `feature/multi-account-foundation` (off `develop`)
**Scope:** schema + backend + frontend types only. No login, no new UI.

## Goal

Lay the data foundation for "one user → many brokerage accounts → trades / wheels / spreads", and put a
single *current-user seam* in front of every user-owned query, so Part 5 (Google login) changes the body
of one function and nothing else. After this part the app behaves exactly as today for the owner.

## Decisions (given)

| Decision | Reason |
|---|---|
| Ownership is user → brokerage account → trades / wheels / spreads | An account is the container for positions, cash and margin |
| Tenant key is an internal user id (UUID). Google identity is a separate nullable `external_subject`; email is never the key | Identity providers and emails change; the tenant key must not |
| One wheel per ticker per account | The same ticker wheeled in two accounts is two independent wheels |
| Categories are a per-user library; each account picks the categories it uses and has a default category for new trades | Users share a vocabulary across their accounts, but an IRA may not use e.g. SPECULATIVE |
| Screener has one symbol row per user; each symbol belongs to ≥1 accounts; screener notes are per account | Market data is fetched once per user, but a note reflects one account's situation (IRA vs taxable) |
| Market data (Schwab connection, quotes, technicals, signal caches) stays app-level and shared | It is not user data and is expensive to fetch |
| The admin manages accounts only and can never read another user's data; no admin features in this part | Privacy |

## Repo reality vs. the brief (flags)

1. **Alembic head is 014, not 012.** `013_buy_write_category.py` is committed on develop and an
   uncommitted `014_speculative_category.py` (SPECULATIVE category, already applied to the local DB) sits
   in the working tree. The new migrations are therefore **015** (new tables) and **016** (ownership +
   backfill). The SPECULATIVE work (014 + `extension/content.js` + `categories.ts`) is carried in the
   working tree untouched; it should be committed on its own before this branch merges.
2. **No one-wheel-per-ticker rule exists today**, and production data has **18 tickers with two active
   wheel sessions each** (AMD, AVGO, BE, DRAM, GLW, HOOD, INTC, MP, NBIS, NFLX, NVDA, PLTR, SOFI, TNA,
   TSLA …). A unique `(account_id, ticker)` index would make migration 016 fail on real data, so **no wheel
   uniqueness constraint is added**. See Open Questions.
3. **`daily_briefings.briefing_date` is globally unique** (`uq_daily_briefings_date`). Not mentioned in
   the brief; it is user-owned, so it is rescoped to `(user_id, briefing_date)`.
4. **"Spreads" = `trade_sessions`** (served by `/api/sessions`, used by the Spreads dashboard and the
   extension's `/api/sessions/active`). Account-scoping rules for "spreads" apply to the sessions router.
5. Most data access lives in routers, not services (wheel, trades, positions, screener). Moving all of it
   into services is out of scope; instead a new `app/services/ownership.py` owns every user-scoped lookup
   (`get_trade`, `get_wheel_session`, `get_slot`, … `resolve_account`) and routers must go through it or
   add the `user_id` filter themselves. The isolation suite tests both the service functions and routers.
6. Production `docker-compose.prod.yml` runs `alembic upgrade head` at container start, so
   `OWNER_EMAIL` / `OWNER_DISPLAY_NAME` are added to the compose backend environment.

## Table inventory

| Table | Classification | Account scope | Notes |
|---|---|---|---|
| `users` (new) | identity | — | |
| `brokerage_accounts` (new) | user-owned | is the account | |
| `account_categories` (new) | user-owned via account | via account | join table |
| `screener_account_memberships` (new) | user-owned via account | via account | join table |
| `trades` | user-owned | **account_id** | parent |
| `wheel_sessions` | user-owned | **account_id** | parent |
| `trade_sessions` (spreads) | user-owned | **account_id** | parent |
| `wheel_slots` | user-owned | via session | |
| `wheel_slot_legs` | user-owned | via slot | |
| `wheel_premium_logs` | user-owned | via slot | |
| `rationale` | user-owned | via trade | |
| `commentary` | user-owned | via trade or slot | |
| `alerts` | user-owned | via trade | written by scheduler |
| `technical_signals` | user-owned | via trade | written by scheduler |
| `categories` | user-owned (library) | linked via `account_categories` | |
| `screener` | user-owned | linked via memberships | one row per user per symbol |
| `screener_commentary` | user-owned | **account_id** | per-account notes |
| `daily_briefings` | user-owned | — | feature is 501 today; flag #3 |
| `schwab_tokens` | **shared, app-level** | — | untouched |
| `alembic_version` | infra | — | |

Nothing else exists. Everything fits the given classification except the `daily_briefings` uniqueness flag.

## Schema

### Migration 015 — new tables

- `users`: `id` UUID PK, `email` (unique index on `lower(email)`), `display_name`, `role` (`admin`|`user`,
  CHECK), `status` (`pending`|`active`|`disabled`, CHECK), `external_subject` (nullable, unique), `created_at`,
  `last_login_at` (nullable). Seeds one `active` `admin` from `OWNER_EMAIL` / `OWNER_DISPLAY_NAME`. Fails with
  a `RuntimeError` explaining how to set `OWNER_EMAIL` if it is empty.
- `brokerage_accounts`: `id` UUID PK, `user_id` FK → users CASCADE, `broker` (free text, max 30), `nickname`
  (max 50), `last_four` (nullable, CHECK `^[0-9]{4}$`), `external_ref` (nullable, Part 3), `default_category_id`
  FK → categories SET NULL, `is_default` bool, `sort_order` int, `is_archived` bool, `created_at`. Partial unique
  index `(user_id) WHERE is_default` enforces one default per user. Full account numbers are never stored —
  the only number column is a 4-digit CHECK-constrained `last_four`.
- `account_categories`: `id`, `account_id` FK CASCADE, `category_id` FK CASCADE, unique `(account_id, category_id)`.
- `screener_account_memberships`: `id`, `screener_id` FK CASCADE, `account_id` FK CASCADE, unique pair.
- Every FK indexed.

### Migration 016 — ownership columns + backfill (single migration)

1. Insert the default account for the owner: nickname `E*TRADE`, broker `E*TRADE`, `is_default = true`.
2. Add nullable `user_id` to all 14 user-owned tables, backfill to the owner, set NOT NULL, FK → users
   (CASCADE), index `idx_<table>_user`.
3. Add nullable `account_id` to `trades`, `wheel_sessions`, `trade_sessions`, `screener_commentary`, backfill
   to the default account, NOT NULL, FK → brokerage_accounts (RESTRICT — accounts with data cannot be
   hard-deleted), index `idx_<table>_account`.
4. Membership rows: every screener row → default account. `account_categories`: every category → default account.
5. Uniqueness changes (inspected from `pg_constraint` / `pg_indexes` on the live DB):

| Before | After |
|---|---|
| `categories_name_key` UNIQUE(`name`) | `uq_categories_user_name` UNIQUE(`user_id`, `name`) |
| `idx_screener_symbol` UNIQUE(`symbol`) | `idx_screener_user_symbol` UNIQUE(`user_id`, `symbol`) |
| `uq_daily_briefings_date` UNIQUE(`briefing_date`) | `uq_daily_briefings_user_date` UNIQUE(`user_id`, `briefing_date`) |
| `idx_trades_etrade_symbol_open` UNIQUE(`etrade_symbol`) WHERE open (migration 003; not declared in the model, found via `pg_indexes`) | `idx_trades_account_etrade_symbol_open` UNIQUE(`account_id`, `etrade_symbol`) WHERE open — now also declared on the model so tests enforce it |
| `idx_rationale_trade_entry` UNIQUE(`trade_id`) WHERE commentary_id IS NULL | unchanged (already per trade) |
| one-wheel-per-ticker | none exists; none added (flag #2) |

6. `schwab_tokens` untouched.
7. Downgrade reverses everything. It refuses (clear `RuntimeError`) if any row belongs to a user other than
   the seeded owner, because restoring global uniqueness would then lose or collide data.

## Backend

- **Settings:** `owner_email`, `owner_display_name` (seed only). Documented in `.env.example`.
- **Models:** `User`, `BrokerageAccount`, `AccountCategory`, `ScreenerAccountMembership`; `user_id` on all
  user-owned models; `account_id` + `account` (selectin) on `Trade`, `WheelSession`, `TradeSession`,
  `ScreenerCommentary`; `WheelSlot.account_id` / `.account` are properties through `session`.
- **Seam:** `app/deps.py::get_current_user` — returns the seeded owner (looked up by `owner_email` once,
  cached in-process). Comment: Part 5 replaces its body with session/token resolution.
- **`app/services/ownership.py`:** every per-id lookup of a user-owned row filters by `user_id` and raises
  404 for missing *or foreign* rows. `resolve_account(db, user, account_id)` → that account (404 if foreign
  or archived) or the user's default when `account_id` is None.
- **`app/services/accounts.py`:** list/create/update/set-categories/archive/delete.
- **Account rules:** list endpoints (trades, wheel sessions, wheel active-slots, sessions list/active/lookup)
  accept optional `account_id`; absent → all of the user's accounts. Create endpoints accept optional
  `account_id`; absent → default account. Trade `category` becomes optional on create; absent → the account's
  default category, else 422. Cross-account links (wheel leg/roll/assignment trade in another account, trade
  attached to a spread session in another account, child spread in another account) are rejected with 400.
- **Accounts API `/api/accounts`:** `GET` (`include_archived`), `POST`, `PATCH /{id}` (nickname, broker,
  last_four, sort_order, default_category_id, is_default=true moves the default), `PUT /{id}/categories`,
  `POST /{id}/archive`, `DELETE /{id}` (409 if it has trades/wheels/spreads; 400 if it is the last active
  account). Archiving the default moves the default to the next active account. Default category must be in
  the account's category list (400). New categories created via `/api/categories` are linked to all of the
  user's active accounts (so they show up everywhere, as today).
- **Screener:** list `?account_id=`; add with `account_id` (default account when absent) creates the user's
  row if needed plus the membership (409 only if already a member of that account); `DELETE /{symbol}` with
  `account_id` removes the membership and deletes the row when no memberships remain; without `account_id`
  deletes the row (today's behaviour). Commentary reads take optional `account_id` (absent → all accounts,
  each entry carries `account_id` + `account`); writes take optional `account_id` (absent → default).
  Fetch-all fetches the requesting user's symbols once each; job status is owner-only (404 otherwise).
- **Extension endpoints:** `positions/status` and `positions/reconcile` resolve to the user's default account.
  Reconcile loads only open trades with that `user_id` **and** `account_id`; trades in other accounts are
  never touched. (Part 3 replaces this with explicit account linking.) `dashboard/today` is user-scoped across
  accounts.
- **Scheduler:** alert engine, signal engine and price refresh still process every open trade (all users);
  every `Alert` / `TechnicalSignal` row is written with `user_id = trade.user_id`.

## Refinements made during implementation

- **Child lists keep their old contract.** `GET /api/trades/{id}/commentary`, `/signals` and `/api/alerts/trade/{id}`
  returned `200 []` for an unknown trade (an existing test pins this). They still do, for unknown *and* foreign
  trades — the `user_id` filter makes the two indistinguishable, so nothing leaks. Every per-id read and every write
  is a 404.
- **Manual refresh endpoints are user-scoped.** `POST /api/market/refresh` and `/api/market/signals/refresh` run
  the engines for the caller's trades only (their counts would otherwise reveal other users' trade volume). The
  scheduler still processes every user's open trades.
- **Hard delete also refuses accounts that hold screener notes** (`screener_commentary.account_id` is RESTRICT),
  and removes symbols that would be left in no account.
- **Owner parity on live data** (copy of the production DB, old code vs new code): 1,950 read responses identical
  after stripping the new account fields, except four whose *order* differs among tied sort keys (wheel sessions by
  ticker, spread legs by open date, alerts by `triggered_at`, and the dashboard built from them). Reconcile on the
  same snapshot produced identical unmatched / stale lists and identical per-trade seen flags.

## Cache audit

| Cache | Key | Depends on a user's position? | Verdict |
|---|---|---|---|
| `cc_signal._combined_signal_cache` | ticker (bypassed when `dte` is given) | No — Strike Safety uses the ~0.30-delta *standard* strike, not the trade's strike | shared, keep |
| `cc_signal._option_chain_cache` | ticker + contract type | No (raw chain; strike filtering happens after) | shared, keep |
| `cc_timing_signal._cc_timing_cache` | ticker | No | shared, keep |
| `sp_timing_signal._sp_timing_cache` | ticker | No | shared, keep |
| `schwab_client` singleton | — | No (app-level connection) | shared, keep |
| `commentary._summary_cache` (AI summary) | trade_id | **Yes** (per-trade notes) | key is the trade (globally unique). **Bug fixed:** it returned the cached summary *before* checking the trade exists, so any caller with a trade id got it. Ownership is now verified first; key becomes `user_id:trade_id` |
| `screener._jobs` (fetch-all job status) | job_id | **Yes** (lists a user's symbols/errors) | stores `user_id`; other users get 404 |

## Frontend

`src/types`: `AccountSummary`, `BrokerageAccount`, `KNOWN_BROKERS`; `account_id` + `account` on `Trade`,
`WheelSession*`, `WheelSlot*`, `Session*`; `account_id`/`account` on screener commentary, `account_ids` on
screener rows. `src/api/accounts.ts` typed fetchers. No visual change.

## Tests

- `test_migration_multi_account.py`: fresh DB → `alembic upgrade 014` → realistic rows in every table →
  `upgrade head` → backfill/membership/category-link/uniqueness assertions → `downgrade 014` → data intact,
  columns gone → `upgrade head` again. Plus a manual run against a copy of the live DB.
- `test_isolation.py`: user B + account B created in a fixture; service-level and router-level 404s for every
  owned resource.
- `test_accounts.py`: list filters, default-account creation, default category, archive rules, single default.
- `test_reconcile.py`: reconcile touches only the resolved account.

## Open questions

1. **Wheel uniqueness**: should the existing duplicate active wheels be merged so a partial unique index
   `(account_id, ticker) WHERE status <> 'closed'` can enforce the decision? Today it is unenforced.
2. Should a trade's category be required to be in its account's category list? Not enforced in Part 1.
3. Unarchiving an account has no endpoint yet (Part 2 UI will need one).
4. Seeding the category library for a brand-new user (Part 5 sign-up) is not done here.
