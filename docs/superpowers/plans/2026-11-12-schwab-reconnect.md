# Schwab reconnect (phase 1): plan

Spec: `docs/superpowers/specs/2026-11-12-schwab-reconnect-design.md`. Order: backend service → endpoints → tests →
frontend → docs. No commit until asked.

1. **Shared OAuth primitives.** `backend/app/services/schwab_oauth.py`: constants, `TokenSet`, `authorize_url`,
   `parse_redirect_url`, `exchange_code`, `store_tokens`, with typed errors. No `app.*` imports.
2. **CLI on the shared module.** In `scripts/schwab_auth.py`, add `backend/` to `sys.path` and call the shared
   functions; keep the prompts and output. `SchwabClient._save_tokens_to_db` uses `store_tokens`.
3. **State helpers.** `auth.sign_state(ttl_seconds=)` and `auth.read_state(allow_expired=)`, with the defaults
   unchanged.
4. **Provider install.** `SchwabClient.install_tokens(tokens)`: under `_lock`, store, reload the row, come online,
   and clear `last_error` and the warning marker.
5. **Reconnect service.** `backend/app/services/schwab_reconnect.py`: `ReconnectError` codes, the pending-nonce
   registry, `start`, `complete`, and the sanitized logging.
6. **Endpoints.** In `app/routers/market_data.py`: `POST /reconnect/start` and `POST /reconnect/complete`, plus a
   shared status builder. Add the schemas to `app/schemas/market_data.py`.
7. **Tests.** `backend/tests/test_schwab_reconnect.py`, as in the spec's list; then the full suite (6 known
   failures).
8. **Frontend API and context.** Add the `marketData.ts` wrappers, and `refresh` / `apply` to
   `MarketDataContext`.
9. **Frontend dialog.** `ReconnectSchwabDialog.tsx` and `ReconnectSchwabButton`.
10. **Banner and Settings.** Change the banner text and add the button and fallback line. Add
    `SettingsMarketDataPage.tsx`, the admin-only tab in `SettingsLayout`, and the route in `App.tsx` behind
    `RequireAdmin`.
11. **Build.** Run `npm run build` and check ESLint has no new findings.
12. **Manual checklist.** Run it on the DB copy (the spec's list); real Schwab needs the user's login.
13. **Docs.**
    - Master context §0 (open item 1), §5, §8, §10 and §11 item 12; the README.
    - `docs/deployment/schwab-reconnect.md` (the runbook).
    - A `docs/decisions.md` entry; `_project.md`; the context checkpoint.
