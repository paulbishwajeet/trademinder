# Login and HTTPS — Part 5 of 5 (Design)

**Date:** 2026-11-05 · **Branch:** `feature/login-and-https` (off `develop` at `635f31d`, which has Parts 1–4)

## Goal
- Google sign-in, admin approval and server-side sessions.
- The extension's one-button Sign in.
- HTTPS on the QNAP through Traefik (Let's Encrypt DNS-01 via Cloudflare). Every API route requires a session or
  an extension token.
- Not in scope: in-app Schwab reconnect (Schwab stays on the CLI), public access, RLS, Redis, MFA, passwords,
  email.

## Repo reality vs. the brief
1. **Built in the worktree `.claude/worktrees/login-and-https`.** Changing the seam makes every route 401, and the
   user's dev backend reloads from the main checkout against the live DB.
2. **Users model.** It already has `role`, `status` (pending/active/disabled), a unique `external_subject` and
   `last_login_at`. Part 1 didn't add `invited_by`, `approved_by` or `approved_at`, so migration 018 adds them.
3. **`GET /api/me` exists (Part 4).** It now also returns `status` and works for pending users.
4. **Prod stack:**
   - `docker-compose.prod.yml` builds from source. The backend runs `alembic upgrade head && uvicorn … --port
     5431`.
   - The frontend is the nginx `prod` target: `try_files … /index.html` SPA fallback, plus its own `/api/` proxy
     to `backend:5431`.
   - With Traefik, `/api` goes straight to the backend. The nginx proxy stays only for the 5430 port during
     rollout.
   - The compose file had no Schwab or market data env vars (the stack predates Parts 1–4), so they're added.
5. **New users had no categories.** Categories are a per-user library seeded only for the owner (migration 016).
   Activating a user (approve, or first sign-in of an invite) now seeds the default library (the 12 system
   categories), so they can create accounts and trades.
6. **shadcn is not installed.** The UI uses Tailwind, Radix Dialog and lucide-react, like Parts 2 and 4.
7. **Local dev with real Google sign-in.** It needs `http://localhost:5430/api/auth/google/callback` added to the
   OAuth client's redirect URIs (Google allows http on localhost), and `PUBLIC_BASE_URL=http://localhost:5430`.
   There is deliberately no login bypass.
8. **`cryptography` cap.** `google-auth` needs it, and 46+ wheels fail to load on the macOS dev venv (OpenSSL
   symbol mismatch). It's capped at `<46` (45.x works on macOS and in `python:3.13-slim`).

## Decisions (given)
| Decision | Reason |
|---|---|
| Google is only an identity check; the backend issues its own session | Google's Testing-mode token limits don't matter |
| Tenant key = internal user id; the Google `sub` is linked once and never replaced; email is never the key | Identity can't move data between tenants |
| Sign-in rules: match `sub` → else an email match on a row with no `sub` (the seeded owner or an invite) binds `sub` → else create pending. Disabled is refused, pending sees only a waiting page, an invite is pre-approved | Owner lands in existing data; strangers wait |
| Sessions are Postgres rows: random token in an httpOnly, Secure, SameSite=Lax cookie; only the hash is stored; 30-day sliding expiry; disabling kills sessions and extension tokens; no JWT, no Redis | Revocable, simple, no extra infrastructure |
| Admin = an extra permission on the owner's normal account; it manages accounts only and never reads others' data | Isolation from Parts 1–3 holds for the admin too |
| Extension Sign in via `chrome.identity.launchWebAuthFlow` → portal `/extension/connect` (requires a portal login) → "Connect this browser extension?" with a device name → token in the fragment of `https://<id>.chromiumapp.org/` → bearer on every bgFetch; tokens hashed, revocable, with last used | One button, no secrets in URLs sent to servers |
| Traefik in the stack on 443, LE DNS-01 via Cloudflare, `/api` → backend, everything else → frontend | The NAS is never exposed to the internet |

## Decisions (made here)
| Decision | Reason |
|---|---|
| ID token verified with `google-auth` (`id_token.verify_oauth2_token`: signature, `iss` ∈ {accounts.google.com, https://accounts.google.com}, `aud`, `exp`), then `nonce` and `email_verified` checked by us | A maintained library for the crypto; the nonce and verified-email checks are ours by OIDC design |
| PKCE S256 verifier, state and nonce in a 10-minute HMAC-SHA256-signed cookie `tm_login` (path `/api/auth`, httpOnly, SameSite=Lax, Secure on https), single use | A stdlib HMAC is enough for a 10-minute value; Lax still sends it on Google's top-level GET redirect back |
| Code exchange with httpx to `https://oauth2.googleapis.com/token` (client secret + `code_verifier`); scopes `openid email profile` only | Minimal scopes |
| Redirect URI built from `PUBLIC_BASE_URL`, never from the request Host | No Host-header tricks |
| `next` after login accepts only same-site relative paths (`/…`, not `//…`), default `/`; a pending user lands on `/waiting` | Open-redirect protection |
| Session cookie `tm_session`, 32 random bytes (`secrets.token_urlsafe`), stored as SHA-256 hex. Slides at most once a minute (bumps `last_seen_at`, `expires_at = now + SESSION_DAYS`, re-issues the cookie with a new Max-Age) | Sliding without a write on every request |
| The seam returns two dependencies: `get_signed_in_user` (any non-disabled user; used by `/api/me` and `/api/auth/logout`) and `get_current_user` (active only; everything else). 401 = no or invalid credentials, 403 = pending or disabled | "A pending user may only call me" |
| Extension token `tme_<43 chars>`, SHA-256 stored, display prefix = first 8 characters, `last_used_at` updated at most once a minute; revoke = `revoked_at` | Same pattern as sessions; visible in Settings |
| Token issuance needs a cookie session, not a bearer token; the redirect URI must equal exactly `https://<id>.chromiumapp.org/` with `<id>` matching `^[a-p]{32}$` and on `EXTENSION_IDS` | An extension can't mint more tokens, and nothing else receives one |
| Extension Sign out = `DELETE /api/extension/tokens/current` (bearer), then the token is cleared locally | Revoked server-side first |
| Invite creates the user `active` with `invited_by` / `approved_by` / `approved_at` and no `sub`; they can't sign in as anyone else, and the first Google sign-in with that email binds the `sub`. Invite of an existing email → 409 | "Becomes active on first sign-in" with nothing extra to store |
| Approve/enable → `active` (+ category library if missing); reject/disable → `disabled` + delete sessions + revoke tokens | Immediate cut-off |
| Admin guards: never on yourself (disable/reject/demote); never leave zero active admins | Lock-out protection |
| CORS: no wildcard. `allow_origins = chrome-extension://<id>` for each allow-listed id, no credentials (bearer only), `X-Market-Data-Offline` exposed. The SPA is same-origin | Exactly the brief |
| Proxy headers: uvicorn `--proxy-headers --forwarded-allow-ips='*'` (only Traefik/nginx can reach the backend on the stack network). Cookies' Secure flag and redirect URIs come from `PUBLIC_BASE_URL` | Correct even if a header is missing |
| Startup fail-fast: `PUBLIC_BASE_URL` https → `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and a non-default `AUTH_STATE_SECRET` required | Misconfigured prod refuses to start |
| OpenAPI docs disabled when `PUBLIC_BASE_URL` is https | Every route behind auth includes the schema |
| Traefik `v3.1.6` (pinned), Docker provider limited to labelled containers (`exposedByDefault=false`), the docker socket mounted read-only, `acme.json` on the named volume `traefik-letsencrypt`, port 443 only, `CF_DNS_API_TOKEN` | Small, commented, no port 80 |

## Endpoints
| Method / path | Auth | Purpose |
|---|---|---|
| GET `/health` | none | liveness |
| GET `/api/auth/google/login?next=` | none | start OIDC, set state cookie, 302 to Google |
| GET `/api/auth/google/callback` | none (state cookie) | verify, apply rules, create session, 302 to `next` / `/waiting` / `/signin?error=` |
| POST `/api/auth/logout` | none (deletes the cookie's session if any) | 204, cookie cleared |
| GET `/api/me` | signed in (pending ok) | id, email, display_name, role, status |
| GET `/api/admin/users?status=` | admin | list (management fields only) |
| POST `/api/admin/users/invite` | admin | `{email, role?}` |
| POST `/api/admin/users/{id}/approve` · `/reject` · `/disable` · `/enable` | admin | status changes |
| PATCH `/api/admin/users/{id}/role` | admin | `{role}` |
| POST `/api/extension/connect` | cookie session, active | `{redirect_uri, device_name}` → `{redirect_to}` |
| GET `/api/extension/tokens` · DELETE `/api/extension/tokens/{id}` · DELETE `/api/extension/tokens/current` | active (cookie or bearer) | list / revoke |
| everything else | active | unchanged; `GET /api/market-data/status` stays admin |

## Manual verification checklist (after deployment)
1. `https://tm.<domain>` loads with a valid Let's Encrypt certificate on a laptop on the home Wi-Fi.
2. The owner signs in with Google and lands in all existing data as admin; the Schwab banner is visible.
3. The pilot user signs in, sees "Waiting for approval", gets approved from Admin, reloads and sees an empty app
   (with categories).
4. Each user creates an account and links E*TRADE through their own extension (Sign in in the popup).
5. Neither user can see the other's trades, wheels, screener notes or accounts (SPA and extension).
6. Revoking an extension token in Settings → Connected extensions signs that extension out ("Signed out — Sign in
   again").
7. Logout works (back to Sign in; the old cookie gives 401).
8. The Schwab banner shows only for the admin.

## Pre-deployment verification (2026-11-05)

**pytest:** 476 passed, 6 known failures (`test_cc_signal.py` ×4, `test_market_router_p2.py::test_prefetch_still_501`,
`test_schwab_client.py::test_schwab_alias_maps_spx`). The new `tests/test_auth.py` adds 26 tests (Google mocked):
- **Sign-in rules:** the owner's first sign-in binds the subject and keeps existing data visible; a different
  Google account with the owner's email is refused; an invite becomes active on first sign-in with 12 seeded
  categories and an empty app; an unknown user is pending and gets 403 on data routes.
- **Rejected logins:** an unverified email, a nonce mismatch and a forged state are refused. A disabled user is
  refused at sign-in. Open-redirect `next` values are blocked.
- **Sessions:** logout kills the session; sliding re-issues the cookie for 30 days; an expired session gives 401
  and its row is deleted; only hashes are stored.
- **Extension tokens:** eight non-allow-listed or malformed redirect URIs are rejected; the allow-listed one gets
  a `tme_` token in the fragment. A bearer token works and records last use, can't mint tokens, and stops working
  after revoke (by id and by `current`).
- **Admin:** disabling kills sessions and tokens immediately, and re-enable doesn't revive them;
  approve/reject; self and last-admin protection; admin responses contain exactly the management fields; a
  non-admin gets 403.
- **The boundary:** every registered route (>80 method/path pairs) returns 401 without credentials, except
  `/health`, `/api/auth/*` and the dev-only docs. This test found the market routers (quote, technicals, signals,
  …) had no user dependency. All routers are now mounted behind the seam in `main.py`.

Existing tests now authenticate through the real seam: the `client` fixture sends a real session cookie for the
acting user, and `anon_client` sends none.

**Migration 018:** upgrade, downgrade to 017 and upgrade again ran clean on a copy of the live DB (446 trades
intact). The migration test also runs `upgrade head` and `downgrade 014` through it.

**Local run** on that copy (backend :5472 with `PUBLIC_BASE_URL=http://127.0.0.1:5474`, SPA :5474):
- `/api/*` gave 401 without credentials; `/health` 200.
- `/api/auth/google/login` returned a 302 to Google with `scope=openid email profile`, S256 PKCE, state and nonce,
  and set a `tm_login` cookie (HttpOnly, Path=/api/auth, Max-Age=600).
- CORS preflight was allowed from the allow-listed `chrome-extension://` origin and refused from another origin.
- **SPA signed out:** `/accounts` → `/signin?next=%2Faccounts`, and the Google button links to the backend login
  route.
- **SPA with an owner session:**
  - existing data, the name in the sidebar and the Admin link were shown, along with the admin-only Schwab
    banner (offline in the sandbox: no keys);
  - Admin had your own Disable button disabled, and inviting a pilot email worked;
  - the connect page showed "Connect this browser extension?" with "Chrome on Mac";
  - connect returned the `chromiumapp.org#token=tme_…` redirect, and a foreign redirect gave 400;
  - Connected extensions listed the token by prefix, and Revoke removed it;
  - Logout went to `/signin`, deleted the session row, and the old cookie then gave 401.
- The copy was dropped afterwards; the live DB is untouched (still 017).

**Not testable before deployment:**
- the real Google round trip (it needs the OAuth client's credentials and redirect URI);
- the Traefik certificate (it needs the NAS, DNS and the Cloudflare token);
- `chrome.identity.launchWebAuthFlow` (it needs the real extension).

These are the post-deployment checklist above.
