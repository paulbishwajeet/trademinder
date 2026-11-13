# QNAP upgrade: login (Google sign-in) and HTTPS

This guide takes the QNAP from the **old TradeMinder** (before multi-account) to the current version. The current
version has:
- multi-account (Parts 1–3) and Schwab hardening (Part 4);
- Google sign-in and HTTPS at `https://tm.<domain>` through Traefik (Part 5).

It's written for the owner. Run commands over SSH on the NAS unless a step says otherwise. Replace `<domain>`,
the container names and the paths with yours.

> **Secrets go only into Portainer's stack environment variables. Never commit them to git.**

---

## 0. Already done (for reference — don't redo)

| What | Detail |
|---|---|
| Cloudflare DNS | An `A` record `tm.<domain>` → the QNAP's **LAN IP**, **DNS only** (grey cloud, not proxied). Only reachable on the home Wi-Fi. |
| Cloudflare API token | Permission **Zone → DNS → Edit** on that one domain only. Used by Traefik for the Let's Encrypt DNS-01 challenge (the NAS is never exposed to the internet). |
| Google OAuth client | Google Cloud → Credentials → **OAuth client, type Web application**. Consent screen **External**, left in **Testing**, with the owner's and the pilot user's Gmail as **test users**. Authorized domain: the bare `<domain>`. Authorized redirect URI: `https://tm.<domain>/api/auth/google/callback`. |
| QTS HTTPS port | QTS's own HTTPS admin port moved from 443 to **8443**, so 443 is free for Traefik. |
| Schwab | The callback URL was **not** changed. Since 2026-11-12, re-auth is **Reconnect Schwab** in the app (`schwab-reconnect.md`); the CLI (`scripts/schwab_auth.py`) is the fallback. |

Optional, for local development on the Mac: also add `http://localhost:5430/api/auth/google/callback` as an
authorized redirect URI. Google allows http on localhost.

---

## 1. Back up the database (before touching anything)

Find the container names first:

```sh
docker ps --format '{{.Names}}  {{.Image}}'
# e.g. trademinder-db-1 (postgres:15-alpine), trademinder-backend-1, trademinder-frontend-1
```

Write a full backup to a NAS share, outside any container:

```sh
mkdir -p /share/Container/trademinder-backups
docker exec trademinder-db-1 pg_dump -U trademinder -Fc trademinder \
  > /share/Container/trademinder-backups/pre-login-$(date +%Y%m%d-%H%M).dump
```

Check that the file is **not empty** and is a readable archive:

```sh
ls -lh /share/Container/trademinder-backups/
docker exec -i trademinder-db-1 pg_restore -l < /share/Container/trademinder-backups/pre-login-*.dump | head
# The listing must show TABLE / TABLE DATA entries (trades, categories, …). If it errors or is empty, stop.
```

Also note the git commit the NAS currently runs (in Portainer → the stack → its repository reference, or
`git -C <repo dir> rev-parse HEAD`). You need it to roll back.

---

## 2. Check the database version and the upgrade path

```sh
docker exec trademinder-db-1 psql -U trademinder -d trademinder -Atc "select version_num from alembic_version"
```

The new backend runs `alembic upgrade head` on start and applies every migration after that revision, in order:

| Revision | What it does | Notes |
|---|---|---|
| ≤ 014 | (old version) | The old QNAP is somewhere at or below 014 |
| 015 | `users`, `brokerage_accounts`, account categories, screener memberships; seeds the **owner** from `OWNER_EMAIL` | **Fails clearly if `OWNER_EMAIL` is not set** — set it first (step 4) |
| 016 | `user_id` on every user-owned table, `account_id` on trades/wheels/spreads/screener notes; backfills everything to the owner and a default "E*TRADE" account | All existing data becomes the owner's |
| 017 | E*TRADE link columns on brokerage accounts (Part 3) | Additive |
| 018 | `user_sessions`, `extension_tokens`; `invited_by` / `approved_by` / `approved_at` on users | Additive; no data table touched |

If the revision shown is not in this table (for example empty, or something newer than 018), stop and restore
nothing: the database isn't the one you expect.

---

## 3. If the upgrade fails: restore

1. In Portainer, stop the stack (or at least the backend, so nothing writes).
2. Restore the backup into the database container:

   ```sh
   docker start trademinder-db-1   # if it was stopped
   docker exec -i trademinder-db-1 pg_restore -U trademinder -d trademinder --clean --if-exists \
     < /share/Container/trademinder-backups/pre-login-YYYYMMDD-HHMM.dump
   docker exec trademinder-db-1 psql -U trademinder -d trademinder -Atc "select version_num from alembic_version"
   # → the revision you noted in step 2
   ```
3. Redeploy the stack at the **old commit** (noted in step 1). The old code expects the old schema.

---

## 4. Set the stack environment variables in Portainer

Portainer → Stacks → the TradeMinder stack → **Environment variables**. Keep the existing ones
(`DB_PASSWORD`, `SECRET_KEY`, …) and add:

| Variable | Value |
|---|---|
| `TM_HOSTNAME` | `tm.<domain>` (the stack derives `PUBLIC_BASE_URL=https://tm.<domain>` from it) |
| `OWNER_EMAIL` | **Your Gmail address exactly** — the Google account you'll sign in with. It becomes the admin and owns all existing data |
| `OWNER_DISPLAY_NAME` | Your name |
| `GOOGLE_CLIENT_ID` | From the Google OAuth client |
| `GOOGLE_CLIENT_SECRET` | From the Google OAuth client (secret) |
| `AUTH_STATE_SECRET` | 32+ random characters: `openssl rand -hex 32` (secret) |
| `SESSION_DAYS` | `30` (sliding: any use within 30 days extends it) |
| `EXTENSION_IDS` | Comma-separated Chrome extension IDs allowed to sign in (step 8 explains how to find them). Can be filled in after the first deploy |
| `ACME_EMAIL` | Your email, for Let's Encrypt expiry notices |
| `CF_DNS_API_TOKEN` | The Cloudflare token (secret) |
| `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET` | Same as on the Mac (secrets) |
| `MARKET_DATA_PROVIDER` | `schwab` |
| `GEMINI_API_KEY` | Optional, signal commentary |

The backend **refuses to start** if `PUBLIC_BASE_URL` is https and the Google client id, the client secret or a
32+ character `AUTH_STATE_SECRET` is missing. Check its log if it keeps restarting.

---

## 5. Redeploy and watch the certificate

1. Portainer → the stack → **Pull and redeploy** (or update to the new branch/commit, `develop` after Part 5 is
   merged). The stack now has four services: `traefik`, `db`, `backend` and `frontend`.
2. Watch the backend apply the migrations:

   ```sh
   docker logs -f trademinder-backend-1   # "Running upgrade 014 -> 015 …" … "-> 018", then Uvicorn running
   ```
3. Watch Traefik get the certificate. The first time takes about a minute, mostly waiting for DNS propagation:

   ```sh
   docker logs -f trademinder-traefik-1 2>&1 | grep -iE "acme|certificate|error"
   ```

   It's done when there is no ACME error and `https://tm.<domain>` shows a valid Let's Encrypt certificate in
   the browser. It renews automatically; the certificate is stored on the `traefik-letsencrypt` volume, so
   recreating the container doesn't request a new one.

Only Traefik publishes a host port (443). The backend and frontend have no `ports:` of their own; Traefik reaches
them on the stack's internal network (`backend:5431`, `frontend:80`), so `http://<NAS IP>:5430` and `:5431` don't
answer.

---

## 6. First sign-in as the owner

On a laptop on the home Wi-Fi, open `https://tm.<domain>` and choose **Sign in with Google** with the
`OWNER_EMAIL` account.

- You land in the **existing data** (Dashboard, accounts, trades) as **admin**. The Schwab banner and the
  sidebar's **Admin** link are visible.
- If you see "Waiting for approval" instead, the Gmail you used differs from the email the owner row was seeded
  with (`OWNER_EMAIL` at migration 015). Correct the owner row, remove the pending row the attempt created, and
  sign in again:

  ```sh
  docker exec trademinder-db-1 psql -U trademinder -d trademinder -c "
    delete from users where status = 'pending' and lower(email) = lower('YOUR_GMAIL');
    update users set email = 'YOUR_GMAIL' where role = 'admin' and external_subject is null;"
  ```

  Also set `OWNER_EMAIL` to that Gmail in Portainer, so it stays consistent.

**Market data on the NAS.** The old database has no Schwab token yet, so the app runs in "Market data offline"
mode (Part 4) until it has one. The CLI re-auth isn't part of the image. The simplest way is to copy the token row
from the Mac's database, where `scripts/schwab_auth.py` has run:

```sh
# On the Mac:
docker exec trademinder-db-1 pg_dump -U trademinder --data-only --table=schwab_tokens trademinder > schwab_tokens.sql
# Copy schwab_tokens.sql to the NAS, then on the NAS:
docker exec -i trademinder-db-1 psql -U trademinder -d trademinder < schwab_tokens.sql
```

The backend picks it up within a minute, without a restart. Simpler since 2026-11-12: once the NAS runs a build
with the in-app reconnect, click **Reconnect Schwab** on the banner (admin) instead. No token copy is needed;
see `schwab-reconnect.md`.

---

## 7. The pilot user

Pick one:
- **Invite (approved in advance):** Admin → **Invite by email** → their Gmail. The first time they sign in they're
  active.
- **Approve on request:** they sign in at `https://tm.<domain>` and see "Waiting for approval". You open Admin and
  **Approve** them under "Waiting for approval".

Either way they start with an empty app (their own category library, no accounts) and create their own account
from the sidebar. Neither of you can see the other's trades, wheels, screener notes or accounts. The admin
manages accounts only and can't see the pilot user's data.

---

## 8. Sign the extension in

On each computer:
1. Load or update the unpacked extension (`chrome://extensions` → Developer mode → Load unpacked → the repo's
   `extension/` folder).
2. Copy its **ID** (the 32-letter string on its card). The ID depends on the folder path, so each computer has its
   own. Add every ID to `EXTENSION_IDS` in Portainer, comma-separated, and redeploy the backend.
3. In the extension popup:
   1. Set the **server address** to `https://tm.<domain>` and press **Save** (Chrome asks to allow that site:
      allow).
   2. Press **Sign in**. A window opens on TradeMinder's "Connect this browser extension?" page (sign in with
      Google there if asked).
   3. Keep or edit the device name and press **Connect**. The popup then shows your email.
4. On the E*TRADE positions page, link each account through the link card (Part 3).

Revoking it in **Settings → Connected extensions** signs that extension out at once. It then shows "Signed out —
Sign in again".

---

## 9. Old rollout ports (done)

The first rollout also published `5431` (backend) and `5430` (frontend) on the NAS, as a way to check the stack
before HTTPS worked. Those mappings were removed from `docker-compose.prod.yml` once sign-in through
`https://tm.<domain>` was verified (2026-11-11). Nothing needs doing; if you add a host port back for debugging,
remember it bypasses HTTPS and sign-in for anyone on the Wi-Fi.

---

## Notes from the first deployment (2026-11-10)

- **The stack must be created in Portainer.** If it was started outside Portainer (`docker compose up`,
  Container Station), Portainer marks it *Limited* and has no stack environment variables. Recreate it under
  Stacks → Add stack → Repository. First remove the old containers (keep the volume; never `down -v`), because
  Portainer refuses a name that existing containers already use.
- **Keep the stack name `trademinder`.** The database lives on the volume `<stack name>_pgdata`; another name
  starts an empty database. Keep the old `DB_PASSWORD` too: Postgres keeps the password it was created with.
- **The frontend image type-checks.** `npm run build` runs `tsc -b`, which the dev server doesn't, so an unused
  import that works locally fails the stack build. Run `cd frontend && npm run build` before pushing a deploy.
- **Replacing the NAS data with the Mac's** (what was done): back up both, stop only the backend, restore the Mac
  dump into a scratch database `trademinder_check`, check revision / trade count / owner, truncate
  `user_sessions` and `extension_tokens`, rename it over `trademinder` (old one kept as `trademinder_nas_old`),
  start the backend. The dump carries its schema and `alembic_version`, so no migration runs. From then on the NAS
  holds the real data.
- **Never `pg_restore` straight into a live database.** A failed `--clean` restore leaves a half-old, half-new
  schema. Restore into a scratch database, check it, then swap by renaming.

---

## 10. If `tm.<domain>` doesn't resolve on the Wi-Fi

`tm.<domain>` is a public DNS name pointing at a private (LAN) IP. Many routers block that ("DNS rebinding
protection"), so the name resolves through Cloudflare but not through the router.

```sh
nslookup tm.<domain> 1.1.1.1   # should show the NAS LAN IP (Cloudflare works)
nslookup tm.<domain>           # via the router: empty / NXDOMAIN → the router is filtering it
```

Fixes, on the router:
- **Allow-list** `<domain>` in the router's DNS rebinding protection (OpenWrt/dnsmasq: `rebind_domain`;
  many consumer routers: "DNS rebind protection" exceptions). Or:
- **Add a local DNS entry** (static host / local DNS record) `tm.<domain>` → the NAS LAN IP. This also works if
  the router has no rebind setting.

Then flush the laptop's DNS cache (macOS: `sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder`) and
retry.
