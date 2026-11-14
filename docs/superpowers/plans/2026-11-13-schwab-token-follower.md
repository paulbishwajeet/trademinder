# Schwab token follower: implementation plan

Spec: `docs/superpowers/specs/2026-11-13-schwab-token-follower-design.md`. Order: settings → production export →
follower logic → status/endpoints → tests → frontend → docs. No commits unless asked.

1. **Settings**
   - `schwab_token_sync_url` and `schwab_token_sync_secret`, with a model validator (length, URL shape, URL needs
     the secret).
   - Properties `token_follower` and `token_export_enabled`.
   - `.env.example`, with comments.
2. **Sync module** `app/services/schwab_token_sync.py`
   - `HEADER`, `pull(url, secret) -> PullResult` (HTTP only, never Schwab), `secret_matches()`, and the outcome
     constants.
3. **Provider** `schwab_client.py`
   - Extract `_refresh_from_schwab_locked()`.
   - `_renew_locked()` dispatches by mode; `_pull_locked(force)` holds the rate limit and the bookkeeping.
   - `_ensure_valid_token(min_access_left)`, plus follower handling of no-row, expired, offline and app-key cases.
   - `_get()`: on a 401, renew once and retry once.
   - `export_tokens()` for production.
   - `pull_now()` for the endpoint.
   - `status()` gains the source and pull fields.
4. **Wiring**
   - `ProviderStatus` and the status schema fields.
   - `sync_router` (export) outside the seam in `main.py`; `POST /sync/pull` on the admin router.
   - The reconnect service returns 409 in follower mode.
   - `get_market_data()` passes the follower config.
5. **CLI:** the warning and confirmation.
6. **Tests:** `tests/test_schwab_token_follower.py` (provider-level with mocked httpx, router-level with
   `client` / `anon_client`), plus settings validation.
7. **Frontend**
   - The `MarketDataStatus` fields and `marketDataApi.pullNow()`.
   - The banner and Settings → Market data in follower mode.
   - Then `npm run build`.
8. **Docs**
   - The master context: §0 open items, §5, §8, §9, §10.
   - The README.
   - The runbook's weekly routine.
   - A `decisions.md` entry.
   - The context checkpoint.
