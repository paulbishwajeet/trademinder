# In-app Schwab reconnect, phase 1 ("paste the redirect URL"): design

**Date:** 2026-11-12 · **Branch:** `feature/schwab-reconnect` · **Context:** `context/feature-schwab-reconnect.md`

## Problem

The Schwab refresh token lives 7 days from the original authorization. Renewing it today takes four steps:
1. run `scripts/schwab_auth.py` on the Mac;
2. log in at Schwab;
3. paste the dead callback URL into the terminal;
4. copy the `schwab_tokens` row from the Mac database to the NAS.

Production (the NAS) has HTTPS, Google sign-in and an admin role, so the same paste-the-URL flow can run inside
the app.

## Constraints

- Schwab allows exactly **one** registered callback URL, and its console rejects a second one. Today's is
  `https://127.0.0.1:8765/callback`, and it stays unchanged. After the Schwab login, the browser fails to load that
  address. The admin copies the URL from the address bar, which carries `code` (and `state`).
- There is no TradeMinder callback route, no new infrastructure and no migration.

## Flow

```
Admin ── POST /api/market-data/reconnect/start ──▶ backend
      ◀── { authorize_url, state_expires_at } ────
Admin opens authorize_url in a new tab (a real <a target=_blank>, so popup blockers don't interfere)
      ── logs in at Schwab, approves ──▶ Schwab redirects to https://127.0.0.1:8765/callback?code=…&state=…
      (that page fails to load: expected)
Admin copies the address bar URL and pastes it into the dialog
      ── POST /api/market-data/reconnect/complete { redirect_url } ──▶ backend:
           1. parse: scheme/host/port/path must equal the registered callback; Schwab "error=" → denied;
              code present; state present
           2. state: signature (AUTH_STATE_SECRET), purpose, user id = caller, not expired,
              and still pending in this process (then consumed, so it can't be used twice)
           3. exchange the code (the CLI's exact POST); classify failures
           4. write the token row under the provider's lock; the provider reloads it and leaves offline mode
      ◀── MarketDataStatusResponse (same shape as GET /status) ──
SPA replaces its status with the response → the banner disappears
```

## Backend

### Modules

**`app/services/schwab_oauth.py` (new, standalone).**
- Uses only stdlib, `httpx` and `asyncpg`; it never imports `app.config` or anything else app-level.
- Holds the constants (`AUTHORIZE_URL`, `TOKEN_URL`, `REDIRECT_URI`) and the `TokenSet` dataclass.
- Functions:
  - `authorize_url(app_key, state=None)` builds exactly the CLI's URL, with `state` appended when one is given.
  - `parse_redirect_url(url)` returns `(code, state)` or raises `RedirectUrlError(reason)`. It URL-decodes the
    code: Schwab codes carry an encoded `@`, and `parse_qs` decodes `%40` → `@`, matching the CLI's
    `parse_qs` + `unquote`.
  - `exchange_code(app_key, app_secret, code)` returns a `TokenSet` (refresh expiry = now + 7 days), or raises
    `CodeRejected(status, error)` or `SchwabUnreachable(reason)`.
  - `store_tokens(db_url, tokens)` is the CLI's exact upsert (`updated_at = NOW()`).

**`scripts/schwab_auth.py`** now imports those functions (it adds `backend/` to `sys.path`). Its prompts, output,
`.env` loading and exit codes are unchanged.
- **Why share rather than duplicate:**
  - the module has no app-settings dependency, so the script still runs standalone with only `.env`'s
    `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET` and `DATABASE_URL`;
  - one copy of the URL, exchange and SQL means the app and the CLI can't drift apart.
- The provider's own access-token refresh (`SchwabClient._save_tokens_to_db`) also uses `store_tokens`, the same
  SQL it had inline.

**`app/services/schwab_reconnect.py` (new, app-aware)** owns the reconnect.
- `start(user_id)` signs the state and returns the URL and the state's expiry.
- `complete(user_id, pasted_url)` validates, exchanges and installs the tokens, then returns the provider status.
  It is synchronous and runs in a thread executor, like every other provider call.
- **Errors.** One typed family, `ReconnectError(code, message, http_status)`:

| code | HTTP | When | Message (shown in the dialog) |
|---|---|---|---|
| `not_configured` | 409 | `SCHWAB_APP_KEY`/`SECRET` unset | Schwab app key and secret aren't configured on the server. |
| `bad_url` | 400 | not a URL; wrong scheme, host, port or path; > 4096 chars | That isn't the Schwab redirect address… |
| `authorization_denied` | 400 | the URL carries `error=` | Schwab didn't authorize the connection… |
| `missing_code` | 400 | no `code` | No authorization code in that address… |
| `missing_state` | 400 | no `state` | That address has no state… start again. |
| `state_invalid` | 409 | bad signature, wrong purpose or user, unknown or already used | This reconnect link isn't valid any more. Start again. |
| `state_expired` | 409 | past its 10 minutes | This reconnect link expired. Start again. |
| `code_expired` | 400 | Schwab answers 400/401 (`invalid_grant` etc.) | Schwab rejected the code; it has probably expired. Start again and paste promptly. |
| `schwab_unreachable` | 502 | network error, timeout, 5xx, or unreadable JSON | Couldn't reach Schwab. Try again in a minute. |

**`SchwabClient.install_tokens(tokens)`.**
- It takes the provider's `_lock` (the same lock refreshes use) and writes the row with `store_tokens`.
- It then reloads it with `_load_tokens_from_db()`, so the `(updated_at, refresh_expires_at)` marker matches the
  row.
- It clears the offline reason, `last_error` and the 24-hour warning marker. So the provider is online
  **immediately**, with no wait for the one-minute recheck.

**`app/services/auth.py`.**
- `sign_state(payload, ttl_seconds=…)` takes an optional TTL (the default is unchanged).
- `read_state(value, allow_expired=False)` lets the reconnect tell an expired state from a forged one. Login
  behaviour is unchanged.

### State

- **Payload:** `{p: "schwab_reconnect", uid, n: nonce, exp}`, HMAC-SHA256 with `AUTH_STATE_SECRET`, base64url,
  like the login state cookie. Login states carry no `p`, so the two can't be swapped.
- **Single use:** `start` records the nonce with its expiry in a process-memory dict (with a lock, pruned on
  each call), and `complete` removes it **before** exchanging the code.
  - The consumed state isn't restored if the exchange then fails. The Schwab code is single-use anyway, so the
    admin starts again.
  - A backend restart forgets pending states (the admin starts again). That is acceptable with a single backend
    process, as the brief allows.
- **Not consumed** by failures that come before the state check (bad URL, missing code), so a re-paste of the right
  URL still works.

### Endpoints (thin, `app/routers/market_data.py`, `require_admin`)

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/market-data/reconnect/start` | none | `{ authorize_url, state_expires_at }` |
| POST | `/api/market-data/reconnect/complete` | `{ redirect_url }` | `MarketDataStatusResponse` |

- Errors are `{detail, code}` at the table's status, the shape `apiFetch` already reads.
- 401 without a session; 403 for non-admins.
- `redirect_url` has no Pydantic length limit, because a 422 would echo the input. The service rejects anything
  over 4096 characters as `bad_url`.
- The status shape is built by one helper shared with `GET /status`.

### Logging

- **Success:** `Schwab reconnected by user <uuid>; refresh token expires <iso>` (WARNING level: the app has no
  logging config, so INFO never reaches the container log; the provider's "back online" line does the same).
- **Failure:** `Schwab reconnect failed for user <uuid>: <code>` (WARNING), plus the HTTP status for `code_expired`
  and `schwab_unreachable`.
- **Never logged or returned:** tokens, the code, the pasted URL, Schwab's response body.
- `httpx`'s own INFO line logs only the token URL; the code travels in the POST body.

## Frontend

- **`src/api/marketData.ts`:** `reconnectStart()` and `reconnectComplete(redirectUrl)`.
- **`MarketDataContext`:** also exposes `refresh()` and `apply(status)`.
- **`components/MarketData/ReconnectSchwabDialog.tsx`** (Radix Dialog, `data-escape-layer` on the content so the
  WHEEL page's shortcuts stand down):
  - **Opening:** calls start, shows a spinner, then **Step 1** is an "Open Schwab login" link (new tab) plus "link
    valid until hh:mm".
  - **Step 2:** a paste field plus an instruction. The page after the Schwab login will fail to load, and that's
    expected. Copy the whole address and paste it here promptly: Schwab's code only lasts a short time.
  - **Submit:** on success, show the new expiry, apply the returned status (the banner disappears) and clear the
    "offline" flag.
  - **Errors:** show the mapped message and a "Start again" button.
- **`ReconnectSchwabButton`** = the button plus the dialog.
- **`MarketDataBanner`:**
  - expiring: "Schwab connection expires in N days." [Reconnect Schwab];
  - critical: the hours, with the same button;
  - offline: "Market data offline." [Reconnect Schwab];
  - each state also has a muted line, "or run scripts/schwab_auth.py".
- **Settings → Market data** (`/settings/market-data`):
  - the tab and the route are admin only; the route sits behind `RequireAdmin`;
  - shows provider, state, refresh expiry, hours remaining, last successful call and last error, plus the
    Reconnect button, so a reconnect works before any banner appears.

## Tests (`backend/tests/test_schwab_reconnect.py`, Schwab mocked)

- **State:** round trip; expiry → `state_expired`; second use → `state_invalid`; another admin's state →
  `state_invalid`; tampered or login-shaped state → `state_invalid`.
- **URL:** wrong host, port or path → `bad_url`; no code; no state; `error=access_denied`; the `%40` code is
  decoded to `@` before the exchange.
- **Exchange plus write:**
  - success writes the row with a fresh `refresh_expires_at` (about 7 days);
  - it takes a provider that was offline (expired row) out of offline mode with no recheck wait;
  - the response is `state: ok`.
- **Error mapping:** Schwab 400 `invalid_grant` → 400 `code_expired`; 500 / `ConnectError` → 502
  `schwab_unreachable`; a missing key → 409 `not_configured`.
- **Access:** non-admin → 403 on both endpoints; anonymous → 401 on both.
- **Logs:** `caplog` holds no token, code or pasted URL on success or failure, and does hold the success line.
- **CLI:** the script imports its functions from the shared module.

## Manual verification checklist (dev)

Run on a copy of the dev database (`trademinder_wftest`), with a test backend on :5441 and Vite on :5440.

1. Force `refresh_expires_at` into the past on the copy, then confirm the red offline banner with the Reconnect
   button and the fallback line.
2. Reconnect through the UI against real Schwab, then confirm the banner clears within seconds and quotes return
   without a restart.
3. Settings → Market data shows state ok and about 168h.
4. Sign in as a non-admin (pilot) user: no banner, no Settings tab; `/settings/market-data` redirects; the APIs
   return 403.
5. Run `scripts/schwab_auth.py` against the copy, then confirm the row updates and the backend recovers.
6. Logs contain only the success and failure lines, with no code or token.

> **Note on 2 and 5:** a new Schwab authorization may invalidate the refresh token that the live dev database
> (and the NAS) holds. The new token is written only to the copy, so after the check, copy it to
> wherever it is needed (or just reconnect production from the app once this ships).

### Results (2026-11-12)

On a DB copy with the token row forced 1h past expiry: test backend :5441, Vite :5440, Playwright. Torn down
afterwards.

| # | Check | Result |
|---|---|---|
| 1 | Offline banner | ✅ red "Market data offline. Reconnect Schwab to restore it." + "or run scripts/schwab_auth.py" + a Reconnect Schwab button |
| 2a | Dialog step 1 | ✅ the link opens in a new tab (`target=_blank`); URL = `api.schwabapi.com/v1/oauth/authorize`, params `response_type, client_id, redirect_uri=https://127.0.0.1:8765/callback, state`; "valid until" shown; Connect disabled until something is pasted |
| 2b | Wrong address pasted | ✅ the `bad_url` message inline; the same link still usable |
| 2c | Right callback, valid state, **fake code** sent to **real Schwab** | ✅ Schwab answered 400 (`unsupported_token_type`), shown as `code_expired` "…has probably expired. Start again…" with Start again + Close |
| 2d | Start again, then replay the used state | ✅ new state issued; the replay gives `state_invalid` |
| 2e | Dialog carries `data-escape-layer` | ✅ |
| 2f | **Real Schwab login → paste → banner clears, quotes return without restart** | ⏳ needs the admin's Schwab login; see below |
| 3 | Settings → Market data | ✅ provider, state (Offline), connection expiry, hours remaining (Expired), last successful call, and the button |
| 4 | Pilot (non-admin) user | ✅ no banner, Settings tabs only Accounts / Connected extensions, `/settings/market-data` → `/`; the API gives 403 (and 401 unauthenticated) |
| 5 | CLI | ✅ imports the shared module without `app.config`; builds a byte-identical authorize URL (tested). ⏳ a real run |
| 6 | Logs | ✅ only `Schwab reconnect failed for user <uuid>: bad_url` / `code_expired (HTTP 400 unsupported_token_type)` / `state_invalid`; no code, state or URL anywhere in the log |

**Remaining (2f, 5):** do these in production right after the release. That is the real use case, and it writes
straight to the NAS row. Click Reconnect Schwab, log in, paste. The banner must clear, and the WHEEL prices must
load without a redeploy. If Schwab doesn't echo `state`, the paste fails with `missing_state`; fall back to the
CLI and report it. A CLI run is only needed if the app path fails.

## Deferred (phase 2)

- A backend callback route (needs a second registered callback or moving the single one).
- Automatic reminders.
- Per-user connections.
