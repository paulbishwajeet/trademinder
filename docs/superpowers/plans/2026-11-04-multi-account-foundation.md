# Multi-Account Foundation (Part 1) — Implementation Plan

Spec: `docs/superpowers/specs/2026-11-04-multi-account-foundation-design.md`
Order is fixed: migrations → models → schemas → services → routers → scheduler → tests → frontend types → docs.
No commits unless asked.

- [x] 1. Settings: `owner_email`, `owner_display_name` in `app/config.py`; `.env.example`; compose envs.
- [x] 2. Migration `015_users_and_accounts.py`: users (+ owner seed, fail if `OWNER_EMAIL` unset),
      brokerage_accounts, account_categories, screener_account_memberships; FK indexes; downgrade.
- [x] 3. Migration `016_ownership_backfill.py`: default account; `user_id` on 14 tables; `account_id` on
      trades / wheel_sessions / trade_sessions / screener_commentary; memberships; account_categories;
      scoped uniqueness (categories, screener, daily_briefings); FK indexes; guarded downgrade.
- [x] 4. Models: `user.py`, `brokerage_account.py` (+ AccountCategory, ScreenerAccountMembership);
      `user_id` / `account_id` / relationships on existing models; `models/__init__.py`.
- [x] 5. Schemas: `schemas/account.py`; `account_id` + `account` on trade / wheel / session responses;
      optional `account_id` on creates; `TradeCreate.category` optional; screener commentary + rows.
- [x] 6. Seam: `app/deps.py::get_current_user` (cached owner lookup).
- [x] 7. Services: `services/ownership.py` (scoped getters, `resolve_account`), `services/accounts.py`.
- [x] 8. Routers: trades, commentary (cache fix), alerts, signals, categories, positions (status,
      reconcile, dashboard), sessions, wheel, screener, market refresh, new `accounts` router; `main.py`.
- [x] 9. Scheduler services: alert_engine / signal_engine write `user_id`; price_fetcher unchanged.
- [x] 10. Tests: conftest owner/default-account fixtures + dependency override; fix direct-model tests;
       `test_migration_multi_account.py`, `test_isolation.py`, `test_accounts.py`, reconcile scoping.
- [x] 11. Migrations on a copy of the live DB (`createdb -T trademinder`): upgrade, verify, downgrade, upgrade.
- [x] 12. Frontend: `src/types` additions, `src/api/accounts.ts`; `tsc -b` adds no errors (2 pre-existing unused-var errors remain).
- [x] 13. Docs: README, `docs/TradeMinder-Context.md`, context file Progress Log / Current State.
