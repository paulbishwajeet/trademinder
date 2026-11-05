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
1. **Schwab tokens on the NAS.** The old prod DB has no Schwab token row, and the CLI isn't in the image. The guide
   copies the row from the Mac DB. An in-app reconnect (needs HTTPS, so now possible) is future work.
2. **Extension IDs differ per computer** (unpacked extensions derive the ID from the folder path). Each must be
   added to `EXTENSION_IDS`. A fixed `key` in `manifest.json` would give one stable ID if that becomes annoying.
3. **The local dev app needs Google sign-in after merge.** Add the localhost redirect URI to the OAuth client, and
   set `PUBLIC_BASE_URL` and the Google id/secret in the Mac's `.env`.
4. Margin page's raw `fetch('/api/market/rsi')` doesn't trigger the global 401 → Sign in (it shows its market
   error instead).
5. Not testable before deployment: the real Google round trip, the Traefik certificate, launchWebAuthFlow — the
   post-deployment checklist in the spec.

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

## Current State
**Part 5 is committed on `feature/login-and-https` (not pushed or merged), running locally from the main checkout.
Not deployed to the QNAP.**

- **Branch and checkout:**
  - The main checkout is on `feature/login-and-https` (off `develop` `635f31d`); the worktree was removed.
  - The user's dev servers (uvicorn `--reload` on 5431, Vite on 5430) serve Part 5. The local app now requires
    Google sign-in at http://localhost:5430.
- **Live DB:** revision 018, after a backup in `backups/` (`trademinder-pre-018-*.dump`).
- **Local `.env`:** `PUBLIC_BASE_URL=http://localhost:5430`, the Google client id/secret, `AUTH_STATE_SECRET` and
  `EXTENSION_IDS` (one id) are set. The OAuth client has the localhost callback.
- **Verification:** pytest 476 passed / 6 known; `tsc -b` 2 pre-existing; local run on a DB copy as in the spec.

**Single next action:** the user signs in locally with Google (it should land in the existing data as admin).
Then they sign the extension in from its popup (server `http://localhost:5431`, Save, Sign in). Then deploy to
the QNAP per `docs/deployment/qnap-login-and-https.md` and run the post-deployment checklist. Merge
`feature/login-and-https` → `develop` when satisfied.
