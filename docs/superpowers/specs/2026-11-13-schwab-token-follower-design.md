# Schwab token follower: design

**Date:** 2026-11-13 · **Branch:** `feature/schwab-token-follower` · **Context:** `context/feature-schwab-token-follower.md`

## Problem

Reconnecting in dev and then in production created two Schwab grants. A new grant invalidates the previous
refresh token, so one environment failed at its next refresh. The fix is one grant, owned by production. Production
is the only environment that reconnects to Schwab and the only one that refreshes tokens; dev pulls the current
token pair from production on demand.

## READ FIRST findings

- **Migration head:** the master context gives 020, but no migration is needed. The pair is written into the
  existing `schwab_tokens` row (id = 1) with the shared `store_tokens()` upsert, and the follower's bookkeeping
  (last pull time and outcome) is per process, in memory.
- **The provider's refresh:**
  - It refreshes in `SchwabClient._ensure_valid_token()` under `self._lock` (a `threading.Lock`). It refreshes
    when the access token has ≤ 5 minutes left, and goes offline on `invalid_grant`, on a past refresh expiry, or
    when there are no tokens.
  - Offline: it never calls Schwab, and re-reads the row at most once a minute (`_recheck_token_row`).
- **401s:** a 401 on a data call is currently reported as a `SchwabAPIError` at once, with no renewal or retry. The
  prompt asks for one renewal and one retry in both modes, so it's added for both.

## Settings (`backend/app/config.py`, `.env.example`)

| Setting | Dev (follower) | Production |
|---|---|---|
| `SCHWAB_TOKEN_SYNC_URL` | production's origin, e.g. `https://tm.<domain>` | unset |
| `SCHWAB_TOKEN_SYNC_SECRET` | the shared secret | the same secret (enables the export) |

**Validated at startup** (pydantic model validator, so the app refuses to start):
- **Secret length:** a set secret shorter than 32 characters is rejected.
- **Follower needs the secret:** a set URL requires the secret.
- **URL shape:** the URL must be an origin, `https://` or, only for `localhost` / `127.0.0.1`, `http://`.
- **Follower mode** = the URL is set. With it unset, nothing changes from today.

The two Schwab app settings aren't needed in follower mode: dev never calls Schwab's token endpoint, and data calls
need only the bearer token.

## Production export

`POST /api/market-data/sync/tokens`. It's on a separate `sync_router` included **outside** the `get_current_user`
seam, so a session cookie or extension token neither grants nor is needed for access. It isn't in the SPA, and
`/openapi.json` is already off in production.

- **Auth:** only the `X-Token-Sync-Secret` header, compared with `hmac.compare_digest`.
- **Responses:**

| Case | Response |
|---|---|
| No secret configured on this server, or this server is itself a follower | **404** `{"detail": "Not Found"}` (indistinguishable from an unknown route) |
| Header missing or wrong | **401** `{detail, code: "sync_unauthorized"}` |
| Production's provider is offline (refresh token lapsed, invalid grant, no tokens, not configured) | **503** `{detail, code: "upstream_offline"}`, never stale tokens |
| Success | **200** `{access_token, refresh_token, access_expires_at, refresh_expires_at}` |

- **How it gets the tokens:** the endpoint calls `SchwabClient.export_tokens()`. That runs the normal
  `_ensure_valid_token(min_access_left=10 minutes)` under the provider lock, refreshing through Schwab if needed,
  so production stays the only refresher.
- **Logging:** one line per export (outcome only). The response has `Cache-Control: no-store`.

## Follower logic (inside `SchwabClient`, not routers)

`_renew_locked()` replaces the old inline refresh. It calls Schwab's refresh in normal mode and `_pull_locked()` in
follower mode. In follower mode, **every** path that would call Schwab's token endpoint pulls instead:

| Trigger | Normal mode | Follower mode |
|---|---|---|
| Access token has ≤ 5 min left | refresh | pull |
| No token row | offline | pull |
| Local refresh expiry is past | offline | pull (production may have reconnected) |
| A data call returns 401 | renew **once**, retry the call **once** | the same, with a pull |
| Offline, then a later call or status check | re-read the row (≤ 1/min) | pull (≤ 1/min); success comes back online |

- **Single-flight:** every pull runs under `self._lock`. Concurrent callers wait; after the first pull they find a
  fresh token and don't pull again. For 401 renewals, each caller passes the access token it used. If the current
  token already differs, someone else renewed, so the caller just retries.
- **Rate limit:** at most one pull attempt per 60 s (`time.monotonic()`), successful or not.
  - Inside the window, a valid token is used as is.
  - Otherwise the call fails with the last outcome: `MarketDataUnavailable` while offline, or `SchwabAPIError` for
    a 401 with a token that was just pulled.
- **A pull** is an HTTPS `POST {SYNC_URL}/api/market-data/sync/tokens` with the secret header:
  - 15 s timeout;
  - certificate verification on;
  - no redirects;
  - only a 200 with all four fields is accepted.

  The pair is written with `store_tokens()` (the same upsert as the CLI and the reconnect), loaded, and the
  provider comes online.
- **Outcomes:** `ok`, `unreachable` (connection error, timeout or 5xx other than `upstream_offline`),
  `upstream_offline`, `unauthorized` (401), `disabled` (404), `invalid_response`. Every failure enters the existing
  offline mode, whose enter and leave lines are logged once each way as today. The next successful pull recovers.
- **Logging:** one line per pull, `Schwab token pull from production: <outcome>[; access token expires <time>]`.
  Tokens, the secret and response bodies are never logged.

## 401 handling (both modes)

`_get()` sends the call. On a 401 it calls `_renew_after_401(used_token)` once and retries once. A second 401 is
reported as a `SchwabAPIError` as before. In normal mode the renewal is a forced refresh, unless another caller
already renewed.

## Status and "pull now"

- **`GET /api/market-data/status`** adds:
  - `token_source`: `self` | `production`;
  - in follower mode, `last_pull_at` and `last_pull_outcome`.
- **`POST /api/market-data/sync/pull`** (admin, session seam):
  - in follower mode, it forces a pull, subject to the one-minute limit (**429** `pull_rate_limited` with
    `retry_after_seconds`), and returns the status shape;
  - otherwise **409** `not_follower`.
- **Reconnect:** `POST /reconnect/start` and `/reconnect/complete` return **409** `token_follower` in follower mode.

## CLI

When `SCHWAB_TOKEN_SYNC_URL` is set in the `.env` it reads, `scripts/schwab_auth.py` prints a warning and asks for
`yes` before continuing. A reconnect on dev invalidates production's grant.

## Frontend (follower mode)

- **Banner:** Reconnect and the CLI line are hidden. The banner shows "Tokens from production · last pull <time>
  (<outcome>)" and **Pull now** (admin; the banner is admin-only already). Messages say "Reconnect in production".
- **Settings → Market data:** adds "Token source: Production", the last pull and the outcome, with **Pull now** in
  place of Reconnect.
- Tokens are never sent to the browser. The status has only times and outcomes.

## Out of scope

- Dev fetching market data through production's API, or a second Schwab app.
- Showing tokens in the UI.
- Changes to the offline or banner thresholds or to production's reconnect flow.
- Public exposure, Redis, queues, notifications.

## Tests (pytest; Schwab and production are mocked, never called)

- **Export:**
  - rejects a missing or wrong secret (401);
  - is 404 when disabled;
  - refreshes when the access token is near expiry;
  - returns `upstream_offline` when production is offline.
- **Follower:**
  - never calls Schwab's token endpoint;
  - a 401 triggers exactly one pull and one retry;
  - concurrent callers cause one pull;
  - the one-minute rate limit holds;
  - production unreachable puts dev offline, and a later pull recovers it.
- **Endpoints:** reconnect is 409 in follower mode; pull now is 409 in normal mode.
- **Normal mode** still refreshes, and retries after a 401.
- **Logs:** caplog contains no tokens or secret.
- **Settings validation.**

## Manual verification checklist

1. Set `SCHWAB_TOKEN_SYNC_SECRET` on the NAS stack (Portainer) and Pull and redeploy.
2. Configure dev with `SCHWAB_TOKEN_SYNC_URL=https://tm.<domain>` and the same secret, and restart the backend.
3. Blank dev's token row (`DELETE FROM schwab_tokens`).
4. Confirm dev pulls (status: Production, last pull ok) and fetches quotes.
5. Leave both running past at least two access-token lifetimes (30 min each, so over an hour), and confirm both
   keep fetching.
6. Stop the NAS backend briefly: dev goes offline (`unreachable`) and recovers after it's back (within a minute
   of a call or a status check).
7. Confirm Reconnect is hidden on dev, and that the reconnect endpoints return 409.

### Results

**Steps 1–7 on the NAS: pending.** They need this branch released to the NAS, then the secret set in Portainer
and a redeploy. Open item 1 in the master context tracks them.

**Local equivalent (2026-11-13), run.**

**Setup:** two real backends on scratch copies of the dev database:
- **"production"** on :5442, export enabled, holding a fake token pair with 25 minutes left;
- **the follower** on :5441, with `SCHWAB_TOKEN_SYNC_URL=http://localhost:5442` and its token row deleted.

Schwab itself was never called. Everything was torn down afterwards.

| Check | Result |
|---|---|
| Follower with a blank token row pulls at startup: one offline line, then "tokens pulled from production", one ok line; its row equals production's | ✅ |
| Status: `token_source=production`, `last_pull_outcome=ok`, state ok | ✅ |
| Reconnect on the follower → 409 `token_follower`; Settings → Market data shows Token source / Last pull / **Pull now**, with no Reconnect button | ✅ |
| Pull now inside the minute → 429 `pull_rate_limited` (retry in 39 s) | ✅ |
| Export with an admin session cookie but no secret → 401; export on the follower itself → 404 | ✅ |
| Production stopped → pull → `unreachable`, offline (logged once); status within the minute stays offline without pulling | ✅ |
| Production back → the first status check after the minute pulls, and the follower is "back online" | ✅ |
| `scripts/schwab_auth.py` with the sync URL set → warning; anything but `yes` cancels (exit 1) | ✅ |
| Logs of both backends contain no token values and no secret | ✅ |

**Not covered locally (NAS steps 4–5):** real quote fetches, and two access-token lifetimes with real Schwab
tokens.

**Automated:** `test_schwab_token_follower.py` (38) passes. The full suite gives 640 passed plus the 6 known
pre-existing failures. `npm run build` (`tsc -b`) passes, and the changed files have no lint findings.
