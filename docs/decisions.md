# TradeMinder — Decision Log

Why the project is the way it is. **Newest entries first.**
- `docs/TRADEMINDER_MASTER_CONTEXT.md` describes the current state. This file holds the history behind it.
- Per-feature detail lives in `context/feature-*.md`.
- When to add an entry is in the repo-root `CLAUDE.md` ("Keeping docs/ current").
- Keep entries to a few lines, and never put secrets, tokens, account numbers or personal emails here.

**Entry template**

```markdown
### YYYY-MM-DD — Short title
- **Area:** backend | frontend | extension | infra | data | strategy
- **Type:** deviation | schema | endpoint | convention | deferred | ops learning | decision
- **What changed:**
- **Why:**
- **Impact:** what a reader of the master context needs to know (incl. migration number, if any)
- **Links:** branch · commit/PR · context/feature-<name>.md
```

---

### 2026-11-13 — Account goal and preferences, part 2 of the account profile (migration 020)
- **Area:** backend, frontend, data
- **Type:** schema, endpoint, convention, deviation
- **What changed:**
  - **Migration 020:** nullable columns on `brokerage_accounts`:
    - `objective`, `assignment_stance`;
    - `monthly_premium_target`, `annual_yield_target_pct`;
    - `max_position_pct`, `max_speculative_position_pct`, `max_margin_used_pct`;
    - `min_cash_reserve_pct`, `defensive_at_loss_pct`;
    - `goals_updated_at`.

    There are enum and range `CHECK`s, existing accounts stay unset, and the downgrade is clean.
  - **House defaults:** `app/services/house_defaults.py` holds the KB's house rules: max position 10%, max
    speculative position 3% (the top of 1–3%), max margin used 30%. They're planned to move to the imported KB.
  - **Stored versus effective:** an unset limit means the house default, never "no limit", and defaults are never
    written to the row. The accounts responses carry `limits.<field> = {stored, effective, source, default}`,
    plus `goals_complete` and `goals_updated_at`; an explicit `null` reverts a limit to the default. There are no
    new endpoints.
  - **Rules:** `cash_account_margin` and `speculative_above_position` are 422 `{detail, code, fields}`. Facts and
    goals are now validated in one pass, so both edit orders fail.
  - **UI:** Settings → Accounts gets a "Goal and preferences" dialog section with segmented choices, optional
    targets, and limit inputs labelled `default` with **Use default**. The margin limit is hidden on cash
    accounts. A "Goal not set" marker sits next to "Facts incomplete" in a renamed "Profile" column.
- **Why:**
  - Guidance will weigh moves by goal and preferences, after gating them by facts.
  - Keeping defaults out of the row lets a later KB import change them for every account that didn't override
    them.
- **Deviation:** the prompt named `source` as `account` or `default`. Two more values say why when neither
  applies:
  - `cash_account`: the margin limit on a cash account is 0;
  - `position_limit`: the speculative default is capped at a tighter position limit, so tightening one limit
    doesn't force setting a second.
- **Impact:**
  - **Limited margin:** `limited_margin` gets no margin rule; that's an open question.
  - **`default` field:** each limit object carries the house default, so the UI never duplicates the constants.
  - **Unused for now:** nothing reads these fields yet.
- **Links:** `feature/account-goals` · `context/feature-account-goals.md` ·
  `docs/superpowers/specs/2026-11-13-account-goals-design.md`

### 2026-11-13 — Account facts, part 1 of the account profile (migration 019)
- **Area:** backend, frontend, data
- **Type:** schema, endpoint, convention
- **What changed:**
  - **Migration 019:** nullable columns on `brokerage_accounts`:
    - `tax_treatment`, `account_purpose`, `margin_type`, `options_tier`, `options_level_label`;
    - `net_liquidation_value`, `cash_balance`, `values_as_of`;
    - `facts_updated_at`.

    The enumerations are strings with named `CHECK`s, and money also has `≥ 0` checks. Existing accounts are left
    unset, and the downgrade drops everything.
  - **Options tier vocabulary:** broker-neutral and cumulative: `none` → `covered` → `cash_secured_and_long` →
    `spreads` → `uncovered`. The broker's own name for the level goes in `options_level_label`.
  - **KB-aligned spellings:** `account_purpose` (`trading` / `long_term`) is stored. `account_tax_status`
    (`taxable` / `tax_advantaged`) is derived from `tax_treatment`.
  - **Endpoint shape (no new endpoints):**
    - The accounts create, patch and list (and create-and-link) carry the facts.
    - Responses add `account_tax_status`, `facts_complete`, `facts_updated_at` and `values_as_of`.
    - Rule violations return 422 `{detail, code, fields}` (`tax_advantaged_margin`, `uncovered_requires_margin`,
      `negative_value`, `invalid_value`), checked on the merged stored + request values.
  - **UI:** Settings → Accounts gets an "Account facts" dialog section, a Facts column with a **Facts
    incomplete** marker that opens the dialog on that section, and a Value column that is muted when older than 7
    days.
  - **Convention:** `fields` joins the structured-error body; `ApiError.fields` in the SPA.
- **Why:**
  - Later KB-powered guidance needs account-level gates.
  - Facts are per account, because an IRA and a taxable account at the same broker differ.
  - Brokers number option levels differently, hence a neutral tier.
  - No balance source existed: the Margin page parses an upload in the browser and stores nothing, and the
    extension's status/reconcile payloads carry positions only. So the balances are entered by hand.
- **Impact:**
  - **Timestamps:** `facts_updated_at` moves only when one of the five facts actually changes. Money edits move
    `values_as_of` instead, so daily balance updates don't make guidance stale. This is a choice the prompt left
    open.
  - **Negative cash:** `cash_balance` can't be negative, although a margin debit is negative cash in reality. This
    is an open question for later.
  - **Unused for now:** nothing reads the facts yet.
- **Links:** `feature/account-facts` · `11e5039` · `context/feature-account-facts.md` ·
  `docs/superpowers/specs/2026-11-13-account-facts-design.md`

### 2026-11-12 — In-app Schwab reconnect, phase 1: paste the redirect URL
- **Area:** backend, frontend, infra
- **Type:** endpoint, convention, deferred
- **What changed:**
  - New admin-only `POST /api/market-data/reconnect/start` → `{authorize_url, state_expires_at}`.
  - New admin-only `POST /api/market-data/reconnect/complete` `{redirect_url}` → the `GET /status` shape.
    Errors are `{detail, code}` (400/409/502).
  - **Reconnect Schwab** appears on every banner state, and in a new admin-only Settings → **Market data** tab,
    a tab rather than a section because Settings is a tabbed layout.
  - The authorize URL, code exchange and token-row write moved into the standalone
    `backend/app/services/schwab_oauth.py`, shared by the CLI, the reconnect and the provider's refresh write.
  - `SchwabClient.install_tokens()` writes under the provider lock and comes online at once.
- **Why:**
  - Re-auth meant the Mac, the CLI and copying the token row to the NAS. Schwab accepts exactly one callback
    URL, so the app can't receive the redirect; the admin pastes it.
  - Sharing rather than duplicating keeps the CLI and the app identical. The module needs no app settings, so the
    CLI still runs standalone from `.env`.
- **Impact:**
  - **No migration** (head stays 018).
  - The state is signed with `AUTH_STATE_SECRET`, bound to the admin, lasts 10 minutes, and is single-use in
    process memory. A backend restart forgets pending states, so the admin starts again.
  - Schwab's 400/401/403 on the exchange is always reported as `code_expired`.
  - The success and failure lines log at WARNING. The app has no logging config, so INFO never reaches the
    container log; the provider's "back online" line already did this.
  - **Deferred:**
    - a backend callback route (phase 2, needs Schwab's callback moved);
    - automatic re-auth;
    - per-user connections.
  - The end-to-end check against real Schwab is still to do; see the spec's checklist.
- **Links:** `feature/schwab-reconnect` · 0300319 · `context/feature-schwab-reconnect.md`

### 2026-11-11 — Wheels without a slot can be deleted and edited
- **Area:** backend, frontend
- **Type:** endpoint
- **What changed:**
  - New `DELETE /api/wheel/{id}`: 204, or 409 if the wheel has any slot.
  - `PATCH /api/wheel/{id}` now accepts `ticker` (normalised, 1–10 of `[A-Z0-9./-]`) and `opened_at`;
    `total_shares` must be ≥ 0. Changing the ticker of a wheel that has slots returns 409.
  - The WHEEL page's NEW — NEEDS SLOT section starts collapsed and has ✎ (edit dialog) and × (delete) per row.
- **Why:** Mistaken or abandoned wheels could only be added, never removed or corrected. Deleting is limited to
  wheels with no slot, because those have no legs, premium logs or notes to lose. Slot legs are tied to trades in
  the original ticker, so the ticker is fixed once a slot exists.
- **Impact:** No migration (head stays 018). Wheels with slots still have no edit UI.
- **Links:** `feature/wheel-new-wheel-actions` · ed1a9b8 · `context/feature-wheel-new-wheel-actions.md`

### 2026-11-11 — WHEEL symbol filter keeps its state in the URL and hides non-matching rows
- **Area:** frontend
- **Type:** decision
- **What changed:**
  - A sticky filter bar sits on the account-scoped WHEEL page: a generic chip container with one filter in v1,
    Symbol.
  - The filter is stored only in `?symbol=`, never in localStorage.
  - Filtering happens at render time only: no refetch, and the throttle and caches are untouched.
  - Sections show "n of N" counts and a muted line when the filter empties them.
  - An amber "N other slots need action" notice appears when the filter hides any slot that needs action.
  - The sidebar's account switch keeps `symbol` on the WHEEL page.
- **Why:** Back exits the filter, a filtered view can be deep-linked, and a later visit starts unfiltered. A filter
  must never silently hide an action item. Unlike the extension's toolbar, which dims non-matching rows, this page
  hides them, as asked.
- **Impact:**
  - A section's Fetch button still fetches the whole section while a filter is on.
  - The notice ignores new wheels that have no slot.
  - Future filters (status, DTE, grade, earnings) should be added as more chips.
- **Links:** `feature/wheel-filter-bar` · 2281724 · `context/feature-wheel-filter-bar.md`

### 2026-11-11 — Hand-written shadcn-style UI primitives, and how page shortcuts handle overlays
- **Area:** frontend
- **Type:** convention, deviation
- **What changed:**
  - The plan asked for a shadcn combobox, but shadcn isn't set up in this repo. I added `cmdk` and
    `@radix-ui/react-popover` and wrote `src/components/ui/{command,popover}.tsx` plus `src/lib/utils.ts` (`cn`) in
    shadcn style.
  - Page-level keyboard shortcuts listen in the **capture** phase and stand down while any element with
    `data-escape-layer` exists. Open popovers and the Notes panel carry that marker.
  - The GOOG↔GOOGL alias map now has a third copy, in `src/lib/tickers.ts`.
- **Why:**
  - shadcn's Command and Popover are thin wrappers over exactly those two packages.
  - Overlays close themselves on the same Escape keypress, and a bubbling listener only ran after the overlay had
    already unmounted (found in testing).
- **Impact:**
  - New UI primitives go in `src/components/ui/`.
  - The production bundle grew from 493 KB to 593 KB.
  - The alias map now lives in three places, which must be kept in step: `backend/app/routers/wheel.py`,
    `extension/content.js` and `frontend/src/lib/tickers.ts`.
- **Links:** `feature/wheel-filter-bar` · 2281724 · `context/feature-wheel-filter-bar.md`

### 2026-11-11 — Release flow: a `master` worktree feeds production, plus separate Chrome profiles
- **Area:** infra, extension
- **Type:** ops learning, convention
- **What changed:**
  - **`../trademinder-release`** is a git worktree permanently on `master`. `develop` is merged into `master`
    inside it, so it only changes on a release.
  - **Production Chrome profile ("Trading"):** loads the unpacked extension from the release worktree, with server
    address `https://tm.<domain>`.
  - **Dev profile:** loads it from the main checkout, with server address `http://localhost:5430`.
  - **Extension IDs:** an unpacked extension's ID comes from its folder path, so the NAS stack's `EXTENSION_IDS`
    lists the release copy's ID.
- **Why:** Production uses only released extension code, and dev edits never reach it.
- **Impact:**
  - Moving either folder changes its extension ID, so `EXTENSION_IDS` would need updating.
  - Locally, the extension must point at Vite (`:5430`), not the backend: `/extension/connect` is an SPA page.
- **Source:** the profile and ID details come only from the 2026-11-11 session transcript; the worktree is also
  mentioned in `context/feature-wheel-new-wheel-actions.md`.
- **Links:** `context/feature-login-and-https.md` (local extension address)

### 2026-11-11 — Google OIDC identity, server-side sessions; no JWT, no Redis
- **Area:** backend, frontend, extension
- **Type:** decision, schema, endpoint
- **What changed:**
  - **Google OIDC** (PKCE, state, nonce) is used as the identity check only. The backend issues its own sessions:
    an httpOnly, Secure, Lax cookie holding a hashed token, with a 30-day sliding expiry.
  - **Sign-in rules:** a known Google subject signs in; otherwise an email match binds an invited or owner row;
    otherwise the user is pending until approved.
  - **Admin page:** invite, approve, reject, disable, enable and change role.
  - **Extension:** signs in through `/extension/connect` and gets a revocable, hashed bearer token. Only
    allow-listed extension IDs can sign in.
  - **Routes:** every API route needs a session or an extension token.
- **Why:** Revocable sessions without extra infrastructure. Google's testing-mode token limits don't matter
  because Google is only the identity check.
- **Impact:** Migration **018** (`user_sessions`, `extension_tokens`, invite/approval columns on `users`).
  New routers: `/api/auth`, `/api/me`, `/api/admin/users` and `/api/extension`.
- **Links:** `feature/login-and-https` · 07a1936 · `context/feature-login-and-https.md`

### 2026-11-11 — Per-user and per-account scoping through one current-user seam
- **Area:** backend, data
- **Type:** decision, schema
- **What changed:**
  - `users` and `brokerage_accounts` were added. `user_id` is on every user-owned table, and `account_id` on
    trades, wheels, spreads and screener notes.
  - Existing data was assigned to the owner (seeded from `OWNER_EMAIL`) and one default "E*TRADE" account.
  - Every query is scoped through `get_current_user`, and isolation holds for the admin too.
  - Market data, including `schwab_tokens`, stays app-level and shared.
- **Why:** A pilot with a second trader on the home LAN. With one seam, adding login meant changing one function
  rather than every query.
- **Impact:** Migrations **015–016**. One wheel per ticker per account. Categories are a per-user library.
- **Links:** `feature/multi-account-foundation` · c7c2893 · `context/feature-multi-account-foundation.md`

### 2026-11-11 — The extension links E*TRADE accounts by SHA-256 fingerprint
- **Area:** extension, backend
- **Type:** decision, schema
- **What changed:**
  - The extension detects the E*TRADE account from the page's account dropdown and links it to a TradeMinder
    account by SHA-256 fingerprint.
  - Calls are scoped to the account. Reconcile is allowed only for a single linked account, and unlinking happens
    in the web app.
- **Why:** The full account number is never stored or sent.
- **Impact:** Migration **017** (link columns on `brokerage_accounts`).
- **Links:** `feature/extension-account-awareness` · 00eb5cc · `context/feature-extension-account-awareness.md`

### 2026-11-11 — Schwab outage becomes a labelled offline mode; CLI re-auth kept on purpose
- **Area:** backend, frontend, extension
- **Type:** decision, deferred
- **What changed:**
  - Market data sits behind a provider boundary with offline detection.
  - When offline, market endpoints return 503 `market_data_offline`, mixed endpoints return null fields plus a
    flag, stale caches are used where possible, and scheduled market jobs skip.
  - An amber/red expiry banner appears, plus an admin-only status endpoint.
  - Schwab re-auth stays a CLI step (`scripts/schwab_auth.py`), and the callback flow is unchanged.
- **Why:** The 7-day refresh token used to cause a total blackout. Non-market features must keep working, and a
  CLI re-auth recovers without a restart.
- **Impact:** No migration. An in-app reconnect is deferred; it's feasible now that HTTPS exists, but Schwab
  allows only one callback URL.
- **Links:** `feature/schwab-hardening` · c6e4601 · `context/feature-schwab-hardening.md`

### 2026-11-11 — HTTPS through Traefik on the LAN only
- **Area:** infra
- **Type:** decision
- **What changed:**
  - Traefik runs on 443, with Let's Encrypt via the Cloudflare DNS-01 challenge.
  - `https://tm.<domain>` resolves to the NAS's LAN IP.
  - `/api` goes to the backend and everything else to the frontend.
  - The NAS is never exposed to the internet.
- **Why:** Google sign-in requires HTTPS and a public-TLD host. DNS-01 needs no open port.
- **Impact:** Production values (Cloudflare token, Google client, `AUTH_STATE_SECRET`) live only in the Portainer
  stack's environment.
- **Links:** `feature/login-and-https` · 07a1936 · `docs/deployment/qnap-login-and-https.md`

### 2026-11-11 — Out of scope for the multi-user release
- **Area:** infra, backend
- **Type:** deferred
- **What changed:** Deliberately not built:
  - public internet access or tunnels;
  - MFA, password login;
  - email notifications;
  - Postgres RLS;
  - task queues or Redis;
  - in-app Schwab reconnect.
- **Why:** A small LAN pilot doesn't need them, and isolation is enforced in the application seam.
- **Impact:** Don't assume any of these exist.
- **Links:** `context/feature-login-and-https.md`

### 2026-11-11 — Only Traefik publishes a host port
- **Area:** infra
- **Type:** ops learning
- **What changed:** Removed the rollout `5430`/`5431` host ports from `docker-compose.prod.yml` and `FRONTEND_PORT`
  from `.env.example`. Only 443 is published.
- **Why:** The direct ports bypassed HTTPS and sign-in for anyone on the Wi-Fi.
- **Impact:** On the NAS, the app is reachable only at `https://tm.<domain>`. Dev ports are unchanged on the Mac.
- **Links:** bb05cad · `docs/deployment/qnap-login-and-https.md` step 9

### 2026-11-10 — The production frontend build type-checks
- **Area:** frontend, infra
- **Type:** ops learning
- **What changed:** Removed two unused names (`WheelSlotCard` `ticker`, `WheelDashboardPage` `WheelSessionSummary`)
  that failed the NAS build.
- **Why:** `npm run build` runs `tsc -b`, which the Vite dev server doesn't, so the errors only showed up when the
  stack built the production image.
- **Impact:** Run `cd frontend && npm run build` before pushing anything the NAS will deploy.
- **Links:** ce09fd7

### 2026-11-10 — First NAS deployment: Portainer Git stack, and Mac data replaced NAS data
- **Area:** infra, data
- **Type:** ops learning
- **What changed:**
  - The stack was recreated in Portainer as a Git stack named `trademinder`; it now tracks `refs/heads/master`.
  - The Mac database, already at 018, replaced the NAS data: it was restored into a scratch database, checked, and
    renamed into place. No migration ran on the NAS.
  - From then on, the NAS holds the real data and the Mac is development only.
- **Why:**
  - A "Limited" stack (started outside Portainer) has no stack environment variables.
  - The database volume is `<stack name>_pgdata`, so the stack must keep that name.
  - Postgres keeps the original `DB_PASSWORD`.
- **Impact:** Keep the stack name and `DB_PASSWORD`. Back up the NAS database before any deploy that migrates.
- **Links:** `docs/deployment/qnap-login-and-https.md` ("Notes from the first deployment") ·
  `context/feature-login-and-https.md`

### 2026-11-10 — Never `pg_restore` over a live database
- **Area:** data
- **Type:** ops learning
- **What changed:** A failed `--clean` restore of an older dump over the live Mac database left a half-old,
  half-new schema. It was recovered from the pre-018 backup, and changes made after that backup were lost.
- **Why:** A failed restore can't be rolled back once it has gone over a live database.
- **Impact:** Always restore into a scratch database, check it, then swap by renaming the databases. This applies
  on the NAS too.
- **Links:** `context/feature-login-and-https.md` (Progress Log, 2026-11-10)
