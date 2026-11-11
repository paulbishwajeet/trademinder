# Feature: Login and HTTPS (multi-user Part 5 of 5)

## Goal
- Google sign-in, admin approval and server-side sessions.
- The extension's one-button Sign in.
- HTTPS on the QNAP through Traefik (Let's Encrypt DNS-01 via Cloudflare).
- Every API route needs a session or an extension token.

## Scope
**In:**
- settings, migration 018;
- the sessions, extension tokens, Google OIDC and user-admin services;
- auth, admin and extension routers; the seam;
- CORS and proxy headers;
- SPA auth (sign in, waiting, guard, admin, connected extensions, connect page, logout);
- extension sign in/out;
- Traefik in the stack; the deployment guide;
- tests, docs.

**Out:** in-app Schwab reconnect, public access / tunnels, RLS, Redis, queues, MFA, passwords, email, signal or
wheel or DOM changes.

## Key Files
- **Spec / plan:**
  - `docs/superpowers/specs/2026-11-05-login-and-https-design.md` (decisions, endpoints, checklists, results)
  - `docs/superpowers/plans/2026-11-05-login-and-https.md`
- **Deployment guide:** `docs/deployment/qnap-login-and-https.md`
- **Backend, config and schema:**
  - `app/config.py`: public_base_url, google_*, session_days, auth_state_secret, extension_ids, https fail-fast,
    `secure_cookies`
  - `alembic/versions/018_sessions_and_extension_tokens.py`
  - new `app/models/auth.py` (UserSession, ExtensionToken); `app/models/user.py` (audit columns)
- **Backend, services:**
  - new `app/services/auth.py` (tokens, sessions, signed state cookie, extension tokens, redirect allow-list)
  - new `app/services/google_oidc.py` (PKCE / state / nonce, google-auth verification, sign-in rules)
  - new `app/services/user_admin.py` (activation + default categories, invite / approve / reject / disable /
    enable / role, guards)
- **Backend, routes and wiring:**
  - `app/deps.py`: the seam — `get_signed_in_user`, `get_current_user`, `require_session_user`, `require_admin`
  - new routers `auth.py`, `admin.py`, `extension.py`; `me.py` (pending allowed); schemas `auth.py`, `user.py`
  - `app/main.py`: every router mounted behind the seam; CORS allow-list; docs off on https
  - `pyproject.toml` / `uv.lock`: google-auth, requests, `cryptography<46` (macOS venv load issue)
- **Tests:**
  - `tests/conftest.py`: authenticated `client` (a real session cookie per acting user), `anon_client`; owner =
    admin
  - new `tests/test_auth.py`; `tests/test_market_data_provider.py` (role change in the DB)
- **Frontend:**
  - API and auth: `src/api/auth.ts`, `src/api/client.ts` (401 handler), `src/context/AuthContext.tsx` (guards),
    `MarketDataContext.tsx` (admin from auth)
  - Pages: `SignInPage`, `WaitingPage`, `ExtensionConnectPage`, `AdminPage`, `SettingsExtensionsPage`;
    `components/Layout/SettingsLayout.tsx`
  - `Sidebar.tsx` (Admin link, user + Logout), `App.tsx`, `SettingsAccountsPage.tsx`
- **Extension:** `manifest.json` (identity), `background.js` (signIn / signOut / bearer / 401),
  `popup/popup.{html,js,css}`, `content.js` (signed-out state, re-resolve on sign-in)
- **Stack:** `docker-compose.prod.yml` (Traefik + labels + env), `.env.example`
- **Docs:** `README.md` (Sign-in and multi-user, QNAP Deployment), `docs/TradeMinder-Context.md`

## Decisions Made
| Decision | Reason |
|---|---|
| Google is only an identity check; backend-issued sessions | Testing-mode token limits don't matter |
| Tenant key = internal user id; the Google sub is linked once, never replaced; email never the key | Identity can't move data between tenants |
| Sign-in rules: sub → email match on a row without a sub (owner / invite), bind → pending. Disabled refused; pending sees only waiting; invite = pre-approved | Owner lands in existing data; strangers wait |
| Server-side session rows, hashed token in an httpOnly / Secure / Lax cookie, 30-day sliding, kill on disable; no JWT or Redis | Revocable and simple |
| Admin = an extra permission on the owner's account; manages accounts only | Isolation holds for the admin too |
| Extension Sign in via launchWebAuthFlow → portal connect page → token in the chromiumapp.org fragment → bearer on every call; hashed, revocable, last used | One button |
| Traefik on 443 with LE DNS-01 via Cloudflare; `/api` → backend, else → frontend | Never exposed to the internet |
| Built in a worktree off `develop` (`635f31d`) | The seam change would 401 the user's live dev app mid-edit |
| google-auth verifies the signature / iss / aud / exp; nonce + email_verified checked by us; HMAC-signed 10-minute state cookie; redirect URI from PUBLIC_BASE_URL; `next` relative-only | A maintained library for the crypto; no open redirect; no Host-header trust |
| Two seam layers: `get_signed_in_user` (pending ok, only /api/me) and `get_current_user` (active only); a detached user snapshot | "Pending may only call me"; services that `expire_all()` keep working |
| All routers mounted behind the seam in `main.py` | The route test found the market routers had no auth at all |
| Slide / last-used writes at most once a minute; the slide re-issues the cookie | No write per request; activity keeps the cookie alive |
| Token issuance only from a cookie session; the redirect must equal `https://<allow-listed id>.chromiumapp.org/` | Bearer tokens can't mint tokens; nothing else receives one |
| Invite creates an `active` user without a sub (pre-approved); activation seeds the 12 default categories | New users can create accounts and trades (categories are per user) |
| CORS only for `chrome-extension://<allow-listed id>`, no credentials | SPA and API are same-origin |
| uvicorn `--proxy-headers`; Secure flag and redirect URIs from PUBLIC_BASE_URL | Correct on https even if a header is missing |
| Docs/OpenAPI off on https | Every route is behind auth |
| `ACME_EMAIL` added (Let's Encrypt account) | Needed by Traefik's ACME resolver |
| No login bypass for local dev; add the localhost redirect URI to the OAuth client instead | No back door |
| `cryptography<46` | 46+ wheels fail to load in the macOS dev venv; 45.x works on macOS and in Docker |

## Open Questions
1. **Extension IDs differ per computer** (unpacked extensions derive the ID from the folder path). Each must be
   added to `EXTENSION_IDS`. A fixed `key` in `manifest.json` would give one stable ID if that becomes annoying.
2. Margin page's raw `fetch('/api/market/rsi')` doesn't trigger the global 401 → Sign in (it shows its market
   error instead).
3. **Schwab re-auth on the NAS.** The NAS got the Mac's token row with the data (valid to 2026-11-17). The CLI
   isn't in the image, so re-auth means: re-auth on the Mac, then copy the `schwab_tokens` row to the NAS. Both
   DBs now hold the same refresh token. An in-app reconnect (possible now that there's HTTPS) is future work.
4. Resolved: the real Google round trip, the Traefik certificate and the extension's launchWebAuthFlow all work on
   the NAS (2026-11-10/11).

## Progress Log
- 2026-11-05:
  - Branch `feature/login-and-https` + worktree off `develop`.
  - Settings, migration 018, services, routers, seam, CORS / proxy, SPA, extension, Traefik stack, deployment
    guide, docs.
  - 26 new auth tests; existing tests on an authenticated client.
  - Suite 476 passed / 6 known failures. `tsc` has only the 2 pre-existing errors.
  - Local run on a DB copy: boundary, Google redirect, CORS, SPA sign in / admin / invite / connect / revoke /
    logout all as designed. Sandbox dropped; live DB untouched at 017.
- 2026-11-05: The user added the localhost callback to the Google OAuth client and the login settings to the Mac's
  `.env` (checked: all set, `PUBLIC_BASE_URL=http://localhost:5430`, one extension ID). Committed Part 5, backed
  up the live DB and migrated it to 018, and switched the main checkout to `feature/login-and-https`.

- 2026-11-05 (later): Local extension sign-in failed with "Authorization page could not be loaded": the popup's
  server address was the backend (`:5431`), but `/extension/connect` is an SPA page; locally it must be
  `http://localhost:5430`. On the NAS there's one address.
- 2026-11-10:
  - Pushed `feature/login-and-https`. The NAS had no Traefik because only `develop` (Parts 1–4) was on GitHub.
  - The user's Portainer stack was *Limited* (no stack env vars); they removed the old containers (volume kept)
    and created a Portainer Git stack `trademinder` at `refs/heads/feature/login-and-https`.
  - The stack build failed at `npm run build`: two pre-existing unused names (`WheelSlotCard` `ticker`,
    `WheelDashboardPage` `WheelSessionSummary`). Fixed in `ce09fd7`; checked by building both images for amd64.
  - Local DB incident: the user restored an 11/04 dump over the live DB; it failed halfway (revision 016 with some
    018 tables). Restored `backups/trademinder-pre-018-20261105-1338.dump` into a scratch DB, swapped it in,
    migrated to 018 (446 trades). Changes after 11/05 13:38 were lost; the broken copy was dropped.
  - Deployed: Let's Encrypt certificate for `tm.aipathstudio.com`. The Mac DB
    (`backups/trademinder-for-nas-20261110-1502.dump`, 018, 446 trades, Schwab token valid to 11/17) replaced the
    NAS data via a scratch DB and rename. The user signed in on the NAS and the data is there.
- 2026-11-11: The extension signed in to the NAS; `trademinder_nas_old` dropped. Removed the rollout host ports
  (`5430`, `5431`) from `docker-compose.prod.yml` (only Traefik's 443 is published) and `FRONTEND_PORT` from
  `.env.example`; added the deployment notes to the guide (`bb05cad`). Merged into `develop` (`3f045fc`), then
  `develop` into `master` (`8b60b68`, Parts 1–5; master's tree == develop's). The user switched the Portainer stack
  to `refs/heads/master` and redeployed; checked from the Mac: 5430/5431 closed, 443 open, https `/` 200,
  `/api/me` 401, `/extension/connect` 200.

## Current State
**The 5-part multi-user plan is complete, released on `master` and running in production on the QNAP.**

- **Production:** https://tm.aipathstudio.com (LAN only); Portainer Git stack `trademinder` at
  `refs/heads/master` (volume `trademinder_pgdata`); Traefik + Let's Encrypt (renews automatically, cert to
  2027-02-08); only port 443 published. The NAS holds the real data (since 2026-11-10); the owner and the extension
  are signed in.
- **Branches:** `master` = `develop` (`8b60b68` / `3f045fc`), both pushed. The five feature branches are on origin.
  The main checkout is still on `feature/login-and-https` (clean; same code as develop minus the merge commit).
- **Local:** the Mac DB is development only (018, 446 trades; diverges from the NAS). Dev servers on 5430/5431;
  sign in at http://localhost:5430; local extension address `http://localhost:5430`. Latest Mac backup:
  `backups/trademinder-20261110-1222.dump`.
- **Verification:** pytest 476 passed / 6 known failures; `npm run build` (incl. `tsc -b`) clean; both prod images
  build for amd64.

**Next actions (user's choice):**
1. Re-authorise Schwab before **2026-11-17** (on the Mac, then copy the `schwab_tokens` row to the NAS).
2. Invite the pilot user (guide step 7; their Gmail must be a test user on the Google consent screen).
3. Back up the NAS DB regularly (`docker exec trademinder-db-1 pg_dump -U trademinder -Fc trademinder > …`).
4. Future ideas: in-app Schwab reconnect; a fixed extension `key` for one stable ID; the margin page's raw fetch
   bypassing the 401 handler.
