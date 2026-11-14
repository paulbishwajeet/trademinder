# Feature: Schwab token follower (dev follows production's tokens)

**Status:** Complete
**Branch:** feature/schwab-token-follower
**Created:** 2026-11-13

## Goal
One Schwab grant, owned by production. Production is the only environment that reconnects and the only one that
refreshes; dev pulls the current token pair from production on demand ("token follower" mode).

## Scope
**In:**
- settings (sync URL + shared secret);
- a production export service and a secret-authenticated endpoint;
- follower logic in the Schwab provider (pull instead of refresh, single-flight, one-minute rate limit, one retry,
  offline integration);
- a 401 → renew-once-and-retry path in both modes;
- the status additions and an admin "pull now";
- reconnect disabled in follower mode (409, UI hidden);
- the CLI confirmation;
- tests, frontend and docs.

**Out:** dev fetching market data through production's API; a second Schwab app; showing tokens in the UI;
changes to the offline or banner thresholds or to production's reconnect flow; public exposure, Redis, queues,
notifications.

## Key Files / Modules Involved
- `backend/app/config.py` — `SCHWAB_TOKEN_SYNC_URL`, `SCHWAB_TOKEN_SYNC_SECRET`, startup validation
- `backend/app/services/schwab_client.py` — refresh/pull paths, 401 retry, export, status fields
- `backend/app/services/schwab_token_sync.py` — the export service and the follower's HTTP pull (no Schwab calls)
- `backend/app/routers/market_data.py` — `sync_router` (secret-only export, outside the session seam), pull now,
  status
- `backend/app/services/schwab_reconnect.py` — 409 in follower mode
- `scripts/schwab_auth.py` — warning and confirmation in follower mode
- `backend/app/services/market_data.py` — `ProviderStatus` fields, provider protocol, follower config wiring
- `backend/app/schemas/market_data.py` — status fields, `TokenExportResponse`
- `backend/tests/test_schwab_token_follower.py` — 38 tests; `backend/tests/test_auth.py` — EXEMPT entry
- `.env.example` — the two settings; `docker-compose.prod.yml` — passes `SCHWAB_TOKEN_SYNC_SECRET` to the backend
- `frontend/src/components/MarketData/PullTokensButton.tsx`, `frontend/src/lib/tokenSync.ts` — follower UI
- `docs/deployment/schwab-reconnect.md` — weekly routine and one-time setup
- `frontend/src/components/MarketData/*`, `frontend/src/pages/SettingsMarketDataPage.tsx`,
  `frontend/src/api/marketData.ts`

## Technical Approach
- **Production:**
  - `POST /api/market-data/sync/tokens` is mounted outside the `get_current_user` seam and authenticated only by
    the `X-Token-Sync-Secret` header (`hmac.compare_digest`). It returns 404 unless the secret is configured.
  - Under the provider lock it makes sure the access token has ≥ 10 minutes left (refreshing via the normal path
    if not), then returns the pair and both expiries.
  - When production is offline it returns 503 `upstream_offline`.
- **Dev:**
  - With `SCHWAB_TOKEN_SYNC_URL` set, every place the provider would call Schwab's token endpoint calls
    `_pull_locked()` instead. That happens when the token is near expiry, on a forced renewal after a 401, when
    there are no tokens, or when the local refresh expiry is past.
  - Every pull runs under the provider lock, which makes it single-flight. It's rate-limited to one attempt a
    minute, writes the pair into `schwab_tokens` with `store_tokens`, and comes online.
  - Failures enter the existing offline mode, and a later successful pull leaves it.

## Decisions Made
| Decision | Chosen | Reason |
|---|---|---|
| One grant | Production owns it; dev follows | Two reconnects made two grants; a new grant invalidated the other environment's refresh token (given) |
| Mode selection | Dev sets the production base URL plus the shared secret (≥ 32 chars, else refuse to start); URL unset = today's behavior; production's export is 404 unless the secret is set | Given; nothing changes for an environment that sets neither |
| Export auth | Secret header only, constant-time compare; outside the session/extension-token seam; not in the SPA | Given: server-to-server |
| Only production refreshes | Export ensures ≥ 10 min left under the normal refresh lock | Given |
| Follower never calls Schwab's token endpoint | Every refresh path → pull; single-flight; ≤ 1 pull/min; one retry of the original call | Given |
| Failures | Production unreachable / upstream offline → existing offline mode; logged once each way; a later pull recovers | Given |
| Reconnect in follower mode | Endpoints 409, UI hidden, CLI asks for confirmation | Given: a dev reconnect would invalidate production's grant |
| Logging | One line per pull: outcome + new access expiry; never tokens, the secret or bodies | Given |
| Transport | HTTPS with normal verification; plain http only for localhost | Given |
| Setting names | `SCHWAB_TOKEN_SYNC_URL`, `SCHWAB_TOKEN_SYNC_SECRET` | Match the `SCHWAB_*` group |
| Export route | `POST /api/market-data/sync/tokens` on a separate `sync_router`, outside the `get_current_user` seam | A session/extension token must neither grant nor be needed for access; POST avoids caching and URL logging |
| Disabled export | 404 `Not Found`, identical to an unknown route; also 404 when the server is itself a follower | Don't advertise the endpoint; no chained followers |
| Single-flight | All pulls under the provider's existing `threading.Lock`; 401 renewals pass the token they used and skip if it already changed | Reuses the refresh lock; no second lock to order |
| Rate limit | ≤ 1 pull attempt / 60 s (success or failure), including "Pull now" (429 `pull_rate_limited`) | Given (≤ 1/min); one rule everywhere |
| Recovery while offline | In follower mode, an offline call or a status check attempts a pull (rate-limited) | "Recovers on a later successful pull" without waiting for a row change |
| 401 in both modes | Renew once, retry once; a second 401 is a SchwabAPIError | Previously no retry at all; the prompt asks for it in both modes |
| App key in follower mode | Not required | Dev never calls the token endpoint; data calls need only the bearer token |
| Status fields | `token_source` (`self`/`production`), `last_pull_at`, `last_pull_outcome` | Given; outcomes are short codes, never tokens |
| Export error on a transient refresh failure | 502 `upstream_error` (follower treats 5xx as `unreachable`, retries after a minute) | Distinct from `upstream_offline` (no valid grant); doesn't hand out stale tokens |
| Boundary rule | `PullRateLimited` re-exported from `app.services.market_data`; the export route added to `test_auth.py`'s EXEMPT list with a comment | Existing conventions: only the boundary imports the Schwab module; the exempt route has its own secret auth (tested) |
| Prod compose | `SCHWAB_TOKEN_SYNC_SECRET` added to the backend's environment in `docker-compose.prod.yml` | The stack passes variables explicitly; without it the NAS export would stay 404 |
| Migration | None | The pair goes into the existing `schwab_tokens` row; follower state is in memory |

## Open Questions / Blockers
- [ ] (Moved to master context §0 open item 1) NAS checklist (spec steps 1–7): needs the release, the Portainer secret and a redeploy. Tracked in master
  context open item 1.

## Progress Log
- 2026-11-13: Branch and worktree created off develop `fa0187e`. READ FIRST done: the provider refreshes inside
  `_ensure_valid_token` under `self._lock`; a 401 on a data call is currently just a `SchwabAPIError` (no renewal or
  retry), to be added for both modes. Spec and plan written. Backend done: settings + validation, `.env.example`,
  `schwab_token_sync.py`, provider follower logic (`_renew_locked`, `_pull_locked`, 401 retry, `export_tokens`,
  `pull_now`, status fields), export router outside the seam, `/sync/pull`, reconnect 409, CLI confirmation.
  38 new tests; suite 640 passed + 6 known failures. Frontend done (status type, `pullNow`, `PullTokensButton`,
  `lib/tokenSync.ts`, banner + Settings in follower mode); build + lint clean. Local two-backend check passed (spec
  Results); `docker-compose.prod.yml` now passes `SCHWAB_TOKEN_SYNC_SECRET`. Docs: master context §0, §5, §8, §9,
  §10; README; runbook (weekly routine + one-time setup); decisions entry.

- 2026-11-13: Committed `2e08f53`; merged to develop and released to master together with account facts and
  goals. The user set `SCHWAB_TOKEN_SYNC_SECRET` in Portainer and dev's `.env`; the NAS redeploy and checklist
  remain.

## Current State (Resume Here)
COMPLETE — merged to develop and master (2026-11-13). Remaining ops (master context open item 1): Pull and redeploy
the NAS (the secret is already in Portainer), restart dev with `SCHWAB_TOKEN_SYNC_URL=https://tm.<domain>`, run the
spec's NAS checklist.
