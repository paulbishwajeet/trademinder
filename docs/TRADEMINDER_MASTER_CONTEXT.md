# TradeMinder — Master Project Context
> Drop this file at the start of every new Claude session. It is the single source of truth for what TradeMinder is, how it is built, what works, what doesn't, and where the leverage is.
>
> **Accurate as of:** 2026-11-12, `master` `19c7008` (= `develop` `07a3a99` in content). Edited in place; the history behind each change is in `docs/decisions.md`, and the repo-root `CLAUDE.md` says when both must be updated. Full detail of the multi-user release: `trademinder-5-part-handoff.md` in the project files.

---

## 0. Current State (2026-11-13)

The 5-part multi-user plan was **released on `master` on 2026-11-11**, and two WHEEL improvements followed on 2026-11-12. Production runs `master` on the QNAP at **https://tm.aipathstudio.com**: LAN only, HTTPS via Traefik, Google sign-in required. **The QNAP holds the real data; the Mac is development only.**

**Since the release (2026-11-12, `master` `19c7008`, no migration):**
- **WHEEL symbol filter:** a sticky filter bar with a Symbol combobox. The state lives in `?symbol=`, filtering happens at render time only, and an "N other slots need action" notice guards hidden action items. See section 4.1.
- **NEW — NEEDS SLOT:** the section is collapsed by default, and each row has edit (ticker, shares, start date) and delete. Delete uses the new `DELETE /api/wheel/{id}` and only works for wheels with no slots.

**Released 2026-11-12 (`feature/schwab-reconnect`, `0300319`; no migration): in-app Schwab reconnect, phase 1.**
- The admin clicks **Reconnect Schwab** (on the banner, or in the new admin-only Settings → Market data), logs in at Schwab in a new tab, and pastes the address of the page that fails to load (Schwab's single registered callback, unchanged).
- The backend checks a signed, single-use, 10-minute state, exchanges the code, and writes the token row under the provider's lock. The provider is online again immediately: no restart, no token copy to the NAS.
- The CLI remains the fallback and shares the same code (`app/services/schwab_oauth.py`). See section 5 and `docs/deployment/schwab-reconnect.md`.

**On `develop` (2026-11-13, `11e5039`, migration 019; not yet released to `master`): account facts, part 1 of the account profile.**
- Each brokerage account gets editable facts in Settings → Accounts:
  - tax treatment and purpose;
  - margin type;
  - a broker-neutral options tier plus the broker's own label for it;
  - optional net liquidation value and cash, with an as-of date.
- Existing accounts start unset and show **Facts incomplete**.
- Impossible combinations are rejected with 422 `{detail, code, fields}`.
- The API exposes `account_tax_status` and `account_purpose` with the KB's spellings, plus `facts_complete` and
  `facts_updated_at`.
- Nothing reads the facts yet. See section 3.6.

**In progress (2026-11-13, `feature/account-goals`, migration 020, not yet merged): account goal and preferences, part 2 of the account profile.**
- Each account gets:
  - an editable objective and assignment stance;
  - optional targets: monthly premium and annual yield;
  - risk limits: max position, max speculative position and max margin used (these three default to house
    values), plus minimum cash reserve and defensive-at-loss.
- **Defaults:** an unset limit means the house default (`app/services/house_defaults.py`: 10% / 3% / 30%; to be
  sourced from the KB later), never "no limit". The API returns stored, effective and source for each.
- **Rules:** a cash account can't have a margin limit above 0, in either edit order, and a speculative limit can't
  exceed the effective position limit.
- **Display:** "Goal not set" appears next to "Facts incomplete".
- Nothing reads these yet. See section 3.6.

| Part | What shipped | Migration |
|---|---|---|
| 1. Accounts and ownership | `users`, `brokerage_accounts`, account categories, screener-account memberships. `user_id` on every user-owned table; `account_id` on trades, wheels, spreads and screener notes. Existing data assigned to the owner (seeded from `OWNER_EMAIL`) and one default "E*TRADE" account. Every query scoped through one seam, `get_current_user`; isolation holds for the admin too. A SPECULATIVE category was added. | 015–016 |
| 2. Account container UI | Left sidebar of accounts; account-scoped Trades, WHEEL, Spreads, Margin, Screener, Chain, Scanner; Research pages spanning accounts; rebuilt cross-account Dashboard; Settings → Accounts (create, edit, reorder, restore, guarded delete); old URLs redirect. | none |
| 3. Extension account awareness | Server address configurable in the popup; E*TRADE account detected from the page's account dropdown; linking by SHA-256 fingerprint (full account number never stored or sent); link card, "All accounts" chips, account-scoped calls; Reconcile only for a single linked account; unlinking in the web app; toolbar filters dim rather than hide rows. | 017 |
| 4. Schwab hardening | Market-data provider boundary and offline detection. Offline: market endpoints return 503 `market_data_offline`, mixed endpoints return null fields plus a flag, stale caches used where possible, scheduled market jobs skip (logged once on entering and leaving offline). Amber/red expiry banner, dashes in the UI, notice in the extension, admin-only status endpoint. Non-market features keep working; CLI re-auth recovers without a restart. | none |
| 5. Login | Google OIDC (PKCE, state, nonce) as identity check only; backend-issued server-side sessions (httpOnly, Secure, Lax cookie holding a hashed token, 30-day sliding; no JWT, no Redis). Sign-in: known Google subject → in; else email match on an invited or owner row binds it; else **pending** until admin approval; invites are pre-approved. Admin page: invite, approve, reject, disable, enable, change role, with self and last-admin guards. Extension: one-button sign-in via `/extension/connect`, revocable hashed bearer token, listed under Settings → Connected extensions, allow-listed extension IDs only. Every API route needs a session or extension token; CORS allows only those extension origins. HTTPS: Traefik on 443, Let's Encrypt via Cloudflare DNS-01 (NAS never exposed to the internet); `/api` → backend, everything else → frontend; only 443 published. | 018 |

**Alembic head is 019 on `develop` (018 on `master` until the next release); `feature/account-goals` adds 020 (next 021 once merged).**

**Deployment learnings (do not relearn these; history in `docs/decisions.md`):**
- The Portainer stack must be a **Git stack** (a "Limited" stack has no environment variables) and must be named **`trademinder`**, because the database volume is `trademinder_pgdata`.
- The production frontend build type-checks (`tsc -b`); unused-name errors break the NAS build.
- **Never `pg_restore` over a live database.** Restore into a scratch database, verify, then swap by renaming. (Neel lost days of local edits learning this.)
- The NAS data was replaced with the Mac database (carrying its own schema and migration version), so no migration ran on the NAS.
- Only Traefik publishes a host port (443); the rollout `5430`/`5431` ports were removed. The stack tracks `refs/heads/master` and is updated with Portainer's **Pull and redeploy**.
- Releases: `develop` is merged into `master` inside the `../trademinder-release` worktree. The production Chrome profile loads the extension from that folder, and the NAS `EXTENSION_IDS` lists that copy's ID; an unpacked extension's ID comes from its folder path.
- Locally, the extension's server address is `http://localhost:5430` (Vite), not `:5431`: `/extension/connect` is an SPA page.

**Open items:**
1. Schwab tokens still expire every 7 days (Schwab's rule). Next deadline: **2026-11-17**.
   - Re-auth is now **Reconnect Schwab** in the production app (under a minute; runbook `docs/deployment/schwab-reconnect.md`); the CLI is the fallback.
   - Still open: **Pull and redeploy** the NAS, then do the first real reconnect there (spec checklist 2f), which also confirms Schwab echoes `state` (assumed; the flow rejects a URL without it). If it fails, use the CLI plus a row copy and report the error code.
   - Phase 2 (a backend callback route) would need Schwab's single callback moved.
2. The pilot user hasn't been invited yet; their Gmail must also be a test user on the Google consent screen (Testing mode).
3. Extension IDs differ per computer; a fixed `key` in the manifest would give one stable ID for the allow-list.
4. NAS backups are manual; a scheduled `pg_dump` would help.
5. Small: the Margin page's raw fetch (`MarginDashboardPage.tsx`, `/api/market/rsi`) bypasses the global "signed out" handling.
6. Still out of scope: public internet access or tunnels, MFA, password login, email notifications, Postgres RLS, task queues.
7. WHEEL follow-ups:
   - With a symbol filter on, a section's Fetch button still fetches the whole section.
   - The "other slots need action" notice ignores new wheels that have no slot.
   - Wheels that have slots have no edit UI, although `PATCH /api/wheel/{id}` allows changing shares and date.
8. Account facts: `cash_balance` can't be negative (per the part-1 prompt), but a margin debit is negative cash. Decide whether to allow negative cash on margin types.
9. Unmerged work predating the release:
   - `fix/day-color-regular-session` (2026-10-29, build the daily bar from the regular session);
   - `fix/earnings-date-cache` (2026-10-29, cache the earnings date and stop swallowing lookup failures);
   - `feature/commentaryfromextension` (2026-05, extension commentary panel; probably superseded).

   Decide whether to merge or drop each.

---

## 1. What It Is

TradeMinder is a **personal trading assistant (multi-user since 2026-11, for a small LAN pilot)** for an options income trader running the **Wheel strategy** (sell cash-secured puts → get assigned → sell covered calls → repeat) across ~20–40 tickers, plus a side book of defined-risk spreads and LEAPS.

It solves three compounding problems:

1. **Fragile memory** — why did I sell that strike? What was my exit rule? TradeMinder keeps an append-only journal per position and per wheel slot, with the full technical snapshot at the moment each note was written attached to it.
2. **Position-to-share accounting** — with 9 contracts of covered calls at different strikes and expiries, "which 100 shares got called away?" has no good answer in a brokerage UI. TradeMinder models each 100-share unit as an independent **slot** with its own state machine.
3. **Entry timing under pressure** — the app turns the trader's own technical heuristics (RSI, MACD, Bollinger, IV percentile, day color) into explicit, weighted, auditable scores so the decision is repeatable and reviewable after the fact.

**It is not a broker and places no orders.** Every state transition is a deliberate user action. It runs on the user's LAN: the Mac for development, and the QNAP NAS (a Portainer stack, Docker) for production.

---

## 2. Stack

| Layer | Choice | Notes |
|---|---|---|
| Backend | FastAPI, Python 3.13 (Docker image; `pyproject` allows ≥3.11) | async throughout |
| ORM | SQLAlchemy 2.0 async (`Mapped[]` style) | asyncpg driver |
| Migrations | Alembic | `001` → `018` (next: `019`) |
| Database | PostgreSQL 15 | JSONB for flexible snapshot payloads |
| Market data | **Schwab REST API** (primary), yfinance (residual) | yfinance only for earnings calendar + LEAPS scanner |
| LLM | Gemini 2.5 Flash (signal commentary), Claude Haiku 4.5 (commentary summaries) | both optional, degrade gracefully |
| Frontend | React 19, Vite, TypeScript strict, Tailwind, React Router 7, Radix (Dialog, Collapsible, Popover), cmdk, lucide | shadcn-style primitives hand-written in `src/components/ui/`; the shadcn CLI isn't set up |
| Extension | Chrome MV3, vanilla JS, no build step | overlays E*TRADE positions page |
| Scheduler | APScheduler in-process | market-hours-gated jobs |
| Deploy | Docker Compose as a Portainer Git stack (`trademinder`, tracks `master`), `linux/amd64` images for QNAP TS-251+ | Production: only Traefik `:443`. Dev on the Mac: frontend `:5430`, backend `:5431`, postgres `:5432` |
| Auth | Google OIDC + backend server-side sessions; extension bearer tokens | Traefik + Let's Encrypt (Cloudflare DNS-01) |

```
Chrome Extension (E*TRADE overlay) ─┐
                                    ├─► FastAPI backend ─┬─► PostgreSQL
React SPA ──────────────────────────┘                    ├─► Schwab REST
                                                         ├─► yfinance
                                                         ├─► Gemini 2.5 Flash
                                                         └─► Claude Haiku 4.5
```

**Repo layout:**
```
backend/           FastAPI app — app/models, app/schemas, app/routers, app/services, alembic/, tests/
frontend/          React SPA — src/pages, src/components, src/api, src/types
extension/         Chrome MV3 — content.js, background.js, popup/, manifest.json
stockpile-main/    Older Python workspace (options scanner, partly superseded)
docs/              TRADEMINDER_MASTER_CONTEXT.md (this file), decisions.md, deployment/, superpowers/ (dated specs + plans)
context/           Working notes: _active.md, _project.md, feature-*.md (rules in the repo-root CLAUDE.md)
```

---

## 3. Data Model

### 3.1 Core tables

**`trades`** — one row per transaction leg (Buy, Sell, Assigned are separate rows).
Key fields: `type`, `strategy` (Stock/Put/Call/CoveredCall/PutCreditSpread/Skip/Leap), `ticker`, `open_date`, `expiry_date`, `closed_date`, `strike_price`, `quantity`, `premium`, `collateral`, `exit_strategy`, `signal_action`, `status`, `current_price`, `unrealized_pnl`, `category_id` FK, `etrade_symbol`, `last_etrade_seen`, `wheel_id`, `session_id`.

**`rationale`** — one technical snapshot per trade (and optionally per commentary note via `commentary_id`). ~19 indicator fields, auto-fetched at entry. Only `notes` is user-written.

**`commentary`** — append-only journal. Polymorphic: parent is either `trade_id` **or** `slot_id` (XOR constraint, migration 012). Carries `signal_snapshot` JSONB (migration 011) — the full signal state at the moment the note was written, opt-in per note.

**`categories`** — strategy labels (WHEEL, LEAP, HOLD, SPECULATIVE, …), color + icon + sort order; a per-user library (12 defaults seeded on activation), and each account picks the ones it uses. Drive row tinting everywhere.

**`alerts`** — severity-flagged alert rows evaluated by the alert engine against open trades.

**`technical_signals`** — computed signal hits per trade (macd_bullish, rsi_oversold, etc.), active/deactivated by the signal engine.

**`daily_briefings`** — stub table; nothing writes to it yet (briefing endpoint returns 501).

### 3.2 Wheel v2 — the heart of the app (migration 008)

```
wheel_sessions (per ticker)
  └─ wheel_slots (per 100-share unit — independent state machine)
       ├─ wheel_slot_legs (join: slot ↔ trade, with leg_role + rotation_number)
       └─ wheel_premium_logs (append-only, signed premium amounts)
```

- `wheel_slots`: `slot_number`, `contracts`, `shares_held`, `status`, `needs_action` (bool flag, not a status), `rotation_number`.
- `leg_role` ∈ `stock | covered_call | sold_put`
- `wheel_premium_logs.premium_amount` is **signed** — sells positive, buybacks negative — so `SUM()` is net premium with no special logic.

**Slot state machine:**
```
awaiting_cc ──sell CC──► cc_active ──expire OTM──► awaiting_cc
                                   ──expire ITM──► awaiting_sold_put (rotation++)
                                   ──bought back─► awaiting_cc
                                   ──rolled──────► cc_active (new leg linked)

awaiting_sold_put ──sell put──► sold_put_active ──expire OTM──► awaiting_sold_put
                                                ──assigned────► awaiting_cc (rotation++)
                                                ──bought back─► awaiting_sold_put
                                                ──rolled──────► sold_put_active (new leg linked)
```

8 resolve outcomes, all explicit user choices. A roll = buyback + new sale, logged as two signed premium entries.

### 3.3 Spreads (legacy, still live)

**`trade_sessions`** — older grouping table. Wheel migrated off it; **Iron Condors and Put Broken-Wing Flies still use it** and it was deliberately left untouched.

### 3.4 Screener

**`screener`** — persisted watchlist: price, change%, IV percentile, RSI, MACD, MAs, Bollinger, earnings, volume spikes. **`screener_commentary`** — editable notes per symbol (unlike trade commentary, which is append-only).

### 3.5 Auth

**`users`** — internal id is the tenant key; Google subject linked once; role (admin/user), status (pending/active/disabled); `invited_by` / `approved_by` / `approved_at`. **`user_sessions`** (server-side sessions; only the SHA-256 of the cookie token is stored) and **`extension_tokens`** (hashed bearer tokens, revocable) — migration 018. Market data, including `schwab_tokens`, stays app-level and shared across users.

**`schwab_tokens`** — single row (`id=1`) with Schwab OAuth access + refresh tokens and expiries. Refresh token has a **fixed 7-day life from original auth** — refreshing the access token does NOT extend it, so `refresh_expires_at` is preserved on every refresh.

### 3.6 Accounts and ownership (migrations 015–017, 019, 020)

User → brokerage accounts → trades, wheels, spreads. **`brokerage_accounts`** per user (several per broker allowed). Categories are a per-user library; each account picks the categories it uses and a default one. Screener: one symbol row per user, linked to accounts via memberships; screener notes are per account. One wheel per ticker **per account**. E*TRADE dropdown entries link to accounts by SHA-256 fingerprint.

**Account facts (migration 019).** These are per-account gates, meaning what the account is allowed to do, for
later guidance. They're stored per account because an IRA and a taxable account at the same broker differ.
- **Nullable:** every column is nullable, and null means "not set". The migration set nothing on existing accounts.
- **Enumerations:** strings with named `CHECK` constraints:
  - `tax_treatment`: `taxable`, `traditional_ira`, `roth_ira`, `other_tax_advantaged`;
  - `account_purpose`: `trading`, `long_term` (the KB's spelling);
  - `margin_type`: `cash`, `limited_margin` (restricted IRA margin), `margin`, `portfolio_margin`;
  - `options_tier`: broker-neutral and cumulative: `none`, `covered` (covered calls), `cash_secured_and_long`
    (adds CSPs and long options), `spreads` (adds defined-risk spreads), `uncovered` (adds naked/undefined-risk).
    The broker's own name for the level goes in `options_level_label` (free text, ≤ 40).
- **Balances:** `net_liquidation_value` and `cash_balance` are `numeric(14,2)`, ≥ 0, and entered by hand; no other
  source stores balances. `values_as_of` is set by the service when either value changes.
- **`facts_updated_at`:** set by the service only when one of the five fact fields actually changes. Edits to the
  nickname, sort order or money values don't move it. There's no audit table.
- **Derived in the API:**
  - `account_tax_status`: `taxable` / `tax_advantaged` / null, the KB key;
  - `facts_complete`: tax treatment, purpose, margin type and options tier all set.
- **Rules (service, on the merged stored + request values):**
  - a tax-advantaged account can't have `margin`/`portfolio_margin` (`tax_advantaged_margin`);
  - `uncovered` needs `margin`/`portfolio_margin` (`uncovered_requires_margin`);
  - money can't be negative (`negative_value`) or out of range (`invalid_value`).

  Merely unusual combinations are allowed.

**Goal and preferences (migration 020).** These are per-account weights (what's best among the allowed moves) for
later guidance. The assignment stance, for example, drives "roll versus take assignment".
- **Nullable:** every column is nullable, and null means "not set". The migration set nothing.
- **Enumerations:**
  - `objective`: `income`, `growth`, `mixed`;
  - `assignment_stance`: `willing` (happy to own at the strike), `selective` (depends on the ticker), `unwilling`
    (avoid assignment).
- **Targets:** `monthly_premium_target` (`numeric(12,2)`, ≥ 0) and `annual_yield_target_pct` (0–100).
- **Limits,** all `numeric(5,2)` percent values (10 = 10%), range-checked in the DB:
  - `max_position_pct` (> 0, ≤ 100);
  - `max_speculative_position_pct` (> 0, ≤ 100; tickers in the SPECULATIVE category);
  - `max_margin_used_pct` (0–100);
  - `min_cash_reserve_pct` (0–100);
  - `defensive_at_loss_pct` (> 0, ≤ 100; the unrealized loss on one position at which guidance turns defensive).
- **Stored versus effective:** an unset position, speculative or margin limit means the **house default**
  (`app/services/house_defaults.py`: 10 / 3 / 30; a later feature sources them from the KB), never "no limit".
  Defaults are never written into the row, so changing one reaches every account that didn't override it.
  - The API's `limits.<field>` = `{stored, effective, source, default}`.
  - `source` is `account`, `default`, `cash_account` (the margin limit on a cash account: 0), or `position_limit`
    (the speculative default capped at a tighter position limit).
- **Rules (service; facts and goals merged and validated together, so every edit order holds):**
  - `cash_account_margin`: `margin_type = cash` with a stored margin limit > 0. Setting the limit, or switching
    the margin type, both fail.
  - `speculative_above_position`: a stored speculative limit above the effective position limit. Raising one, or
    lowering or clearing the other, both fail.
  - `out_of_range`, `negative_value`, `invalid_value`.
  - Merely unusual combinations pass.
- **`goals_updated_at`:** moves only when a goal or preference actually changes. It's independent of
  `facts_updated_at`, in both directions.
- **`goals_complete`:** `objective` and `assignment_stance` are both set.

---

## 4. Features (what exists today)

> **Since 2026-11-11 the SPA is organized around accounts** (see section 0): a cross-account Dashboard; per-account Trades, WHEEL, Spreads, Margin, Screener, Chain and Scanner; Research versions of Screener, Chain and Scanner; Settings (Accounts, Connected extensions); an Admin page. Page descriptions below still describe each page's internals.

SPA pages: **Dashboard** (cross-account) · per account: **Trades · WHEEL · Spreads · Margin · Screener · Chain · Scanner** (routes `/accounts/:accountId/<page>`; the old `/wheel`-style URLs redirect) · **Research** (Screener, Chain, Scanner across accounts) · **Settings** (Accounts, Connected extensions) · **Admin** · plus Sign in, Waiting (pending approval) and the extension Connect page.

### 4.1 WHEEL Dashboard (`/accounts/:accountId/wheel`) — primary workspace

Flat, status-grouped tables (not nested cards) because ~19+ wheels need to be scannable.

Sections: **NEW — NEEDS SLOT** (wheels with no slot; collapsed by default; each row has + Add Slot, edit and delete) · **NEEDS ACTION** (any slot with `needs_action=true`) · **AWAITING CC** · **AWAITING SOLD PUT** · **ACTIVE COVERED CALLS / ACTIVE SOLD PUTS**

**Filter bar** (sticky, a generic chip container; v1 has Symbol):
- **Symbol box:** a combobox over the account's wheel tickers, with prefix match and the GOOG↔GOOGL alias.
- **State:** lives in `?symbol=` only, so Back exits, deep links work, and a later visit starts unfiltered.
- **Render-only:** no refetch.
- **Sections:** show "n of N", and a muted line when the filter empties them.
- **Safety notice:** "N other slots need action" when the filter hides a slot that needs action.
- **Ways out:** ×, Clear, Escape or Back.
- **Shortcuts:** clicking a row's ticker filters to it; "/" focuses the symbol box.
- **Account switch:** keeps the symbol.

Per row: ticker with `1x100 R1` subscript, expiry, strike, premium, live P&L%, signal badges with expandable factor breakdown, Notes pill, inline contracts editing (Awaiting slots only — editing while a leg is open corrupts assignment accounting).

**Commentary:** Notes pill opens an anchored popover. Reads `GET /api/wheel/slots/{id}/history` — a merged, interleaved view of slot-level and trade-level notes across all rotations, each tagged with `origin`. Writes go to slot endpoint (Awaiting) or trade endpoint (Active).

**Market Snapshot:** opt-in checkbox per note captures full signal objects into `commentary.signal_snapshot` JSONB — so a future AI agent can read back the complete "why" with all factor values, not just a grade.

**Fetch throttling:** 4 concurrent requests max — unthrottled batch of 150–200 calls caused WAF 403s from Schwab.

**Caching:** signals 4h server-side / 1h client-side (module-level records, survives SPA navigation).

### 4.2 Signals

**A. CC Signal / SP Signal** (`cc_signal.py`, computed in one pass to avoid double-fetching)
Optimizes overall wheel P&L — rewards bullish MACD for CCs (you want the stock to appreciate too).

| Factor | Max |
|---|---|
| IV Percentile | 25 |
| RSI Momentum | 15 |
| Bollinger Position | 15 |
| Price vs MAs | 15 |
| MACD Trend | 10 |
| Momentum Exhaustion (CC) / Initiation (SP) | 10 |
| Strike Safety | 10 |
| Day Color | 5 |
| **Total** | **105** |

Grades: `strong ≥80`, `moderate ≥70`, `weak ≥60`, else `wait`. If IV unavailable, non-IV/non-Strike subtotal renormalized to 100.

**B. CC Timing / SP Timing** (`cc_timing_signal.py`, `sp_timing_signal.py`)
Answers: "will a contract sold right now likely expire OTM?" — deliberately opposite philosophy to CC Signal for CC (rewards bearish weekly MACD).

| Factor | Max |
|---|---|
| MACD(W) | 30 |
| RSI(D) Level | 25 |
| Day Color | 20 |
| Bollinger %B (continuous) | 15 |
| RSI(D) Trend | 10 |
| **Total** | **100** (+10 confluence bonus, capped) |

Grades: `strong ≥80`, `moderate ≥60`, `weak ≥40`, else `wait`.
Non-scoring gates: IV Percentile < 20 caps at `moderate`; MACD `fading_near_flip` appends caution.

**Signal design principles (preserve in any new signal):**
- Piecewise continuous curves, never flat cutoffs
- Partial credit below thresholds
- Never return an empty result
- Separate scoring from gating
- Crossover freshness vocabulary: `expanding / holding_strong / squeezing / fading_near_flip`

Each signal calls **Gemini 2.5 Flash** for 1–2 sentence plain-language commentary + strike hint + optional caution, returned as JSON, null on failure.

**C. MACD Trend** — three pills (Daily / 3-Day / Weekly). 3-Day is a positional resample of daily closes (every 3rd trading day) because Schwab has no 3-day candle frequency.

### 4.3 Chain Screener (`/chain`)

Given symbol + strategy, pulls next N Friday expiries from Schwab, scores every strike in the delta band.

| Criterion | Max |
|---|---|
| Delta fit | 25 |
| ARR (annualized return) | 25 |
| Spread tightness | 20 |
| Volume | 15 |
| Open Interest | 15 |

All 7 thresholds user-adjustable. Earnings-flagged expiries. Deep-linkable (`?symbol=&strategy=sell_put`).
**Only `sell_put` is implemented.** Four more strategies are visible-but-disabled.

### 4.4 Screener (`/screener`)

Persisted watchlist grid with full technical snapshot. Refresh always user-triggered (single row or sequential Fetch All, frontend polls every 2s, "Fetching…" derived client-side from `last_fetched_at` vs job start — no backend change needed). Editable per-symbol commentary.

### 4.5 Margin Dashboard (`/margin`)

CSV import, analyzed entirely client-side. Black-Scholes assignment probability via `N(−d1)` (Abramowitz & Stegun, no dependencies). Risk-free rate 4.5%. Two-pass spread-aware parser caps obligation at spread width for verticals/butterflies/condors, matching on `ticker||expiry` (excluding quantity). Missing data → `prob=1` so exposure is never under-stated.

### 4.6 Scanner (`/scanner`)

LEAPS IV surface — yfinance-based, fits IV surface, ranks contracts by IV excess vs surface. Deliberately not merged with Chain.

### 4.7 Spreads (`/spreads`)

Iron Condor and Put Broken-Wing Fly on the legacy `trade_sessions` model.

### 4.8 Trades (`/trades`)

Collapsible sections by category, accent-bar headers, drag-to-reorder groups (persisted to localStorage), status filter. Trade detail with full commentary thread, entry-time rationale as oldest entry, AI summary (Claude Haiku 4.5, 1h cache) returning `{summary, inferred_actions}`.

### 4.9 Chrome Extension

Injects into E*TRADE positions page (`https://*.etrade.com/*`), four stages independently toggleable:

1. **Category badges** + filter toolbar above the grid
2. **Hover commentary panel** — AI summary, inferred actions, recent notes, inline add-note with optional technicals attachment
3. **Alert-based row coloring** — severity tint overrides category tint; typed badge per alert type
4. **Technical signal dots** appended to badge

Plus: **wheel pills** from `/api/wheel/active-slots` (60s TTL), GOOG/GOOGL ticker alias map, add-trade modal, edit modal, session picker, **Reconcile**.

Since the multi-user release, the extension also has:
- a **server address** setting in the popup;
- one-button **Sign in** (a bearer token; signed-out state in the account bar);
- an **account bar** that detects the E*TRADE account and links it by fingerprint;
- account-scoped calls, with Reconcile only for a single linked account;
- toolbar filters that **dim** non-matching rows rather than hide them.

**E*TRADE DOM facts (do not guess these):**
- Grid is `#rdt_3` — a div-based virtual scroll list, NOT a `<table>`
- Only ~32 rows in DOM at a time; row IDs recycled on scroll
- Ticker: `aria-label` on `.SymbolCellRenderer---content---mcwCT` (strip at first comma for ITM options)
- Option symbol regex: `/^([A-Z]+)-{1,4}(\d{6})([CP])(\d{8})$/` — ticker+dashes always 6 chars, strike = 8-digit field ÷ 1000
- Extension uses `MutationObserver` (150ms debounce) + two-level cache (`rowId → cacheKey`, `cacheKey → status`)
- **All extension network calls go through `bgFetch` relay to the service worker** — direct `fetch()` from content script is silently blocked by Chrome's Local Network Access policy
- **Reconcile** scrolls the entire page to accumulate all positions (naive `querySelectorAll` only ever sees ~50 rows), sends complete snapshot, backend backdates absent positions as closed

---

## 5. Market Data Layer

**Schwab REST API is the backbone.** `SchwabClient` singleton: tokens in Postgres, direct `httpx` calls (no wrapper), thread-safe token refresh, 30s read timeout. Methods: `get_quotes` (batch), `get_price_history`, `get_option_chain`, `get_instrument_fundamentals`.

**Hard-won operational details:**
- `contractType=ALL` on large ETFs (QQQ) → 502 TooBigBody from Schwab → always two separate CALL + PUT calls with `strikeCount=30`
- Trades entered from IST store expiry as Thursday; Schwab uses Friday → option price lookups match chain keys within ±3 days
- Non-optionable tickers → `SchwabAPIError` → signal column shows `—`
- Live intraday price appended as last daily bar before computing RSI/MACD/day color — keeps "live price" and "previous close" consistent with indicators
- **Refresh token expires 7 days after original auth.** Refreshing the access token does NOT extend it. **This is the single most common cause of total app failure.** Since Part 4 a lapse puts the app into a labeled offline mode instead of a blackout (see section 0), and an admin-only banner warns before expiry. The backend logs a warning within 24h.
- **Re-auth: reconnect in the app; the CLI is the fallback.**
  - **In the app:** the admin clicks **Reconnect Schwab** on the banner or in Settings → Market data, logs in at Schwab, and pastes the dead `https://127.0.0.1:8765/callback?code=…&state=…` address.
    - `app/services/schwab_reconnect.py` checks the state: HMAC-signed with `AUTH_STATE_SECRET`, bound to the admin, 10 minutes, single use, with pending nonces in process memory, so a restart forgets them.
    - It exchanges the code and calls `SchwabClient.install_tokens()`. That writes the row under the provider's lock and reloads it, so the provider is online at once.
    - Only one sanitized log line is written per attempt; codes, tokens and the URL are never logged.
  - **Fallback:** `python scripts/schwab_auth.py` writes the row of whichever DB `DATABASE_URL` names; the provider notices a changed row within a minute.
  - **Shared code:** the authorize URL, exchange and row write live in the standalone `app/services/schwab_oauth.py` (no app settings), used by the CLI, the reconnect and the provider's refresh write.
  - **Constraint:** Schwab allows exactly one registered callback (its console rejects a second), so there is no TradeMinder callback route.

**Indicator library** (`technicals_fetcher.py`, ~500 lines): RSI(14) + signal-line crossover state, MACD daily/3-day/weekly + crossover state (`cross_date`, `periods_since_cross`, `strength_score`, `trend`), Bollinger (5-zone bucket), MAs (20/50/100/200) with price-vs-MA flags, day color, volume-spike detection (2× 20-day baseline over 10-day lookback), IV percentile from live chain, sentiment, next earnings.

**yfinance residual uses:** earnings calendar only, LEAPS scanner only.

---

## 6. What Is Stubbed, Stale, or Known-Broken

Read this before proposing any work. The README oversells current state.

| Thing | Reality |
|---|---|
| **Morning Briefing** | `/api/briefing/*` returns **501 Not Implemented**. `daily_briefings` table exists, nothing writes to it. Dashboard says "coming in Phase 3." |
| **Dashboard page** | Rebuilt in Part 2 as a cross-account summary: one card per account (open trades, active wheels, slots needing action, legs expiring ≤7d, net premium this month) from `GET /api/dashboard/summary`. No briefing content; WHEEL is still the real working screen. |
| **Alert engine** | Implemented and scheduled, but only evaluates `trades` — **wheel slots are not covered by alerts at all**. |
| **Signal engine** | Implemented; writes `technical_signals`, deactivates when conditions lapse. Drives extension dots only. |
| **README** | Partly stale. The sign-in and QNAP deployment sections are current, but the architecture/stack tables still describe yfinance as the price source and list Phase 3/4 as pending. |
| **`test_prefetch_still_501`** | Broken on `master` — stale test for a removed route. Delete before next merge. |
| **Pre-existing test failures** | In `test_cc_signal.py`, `test_market_router_p2.py`, `test_schwab_client.py` — present before recent work, not regressions. |
| **Frontend tests** | None. No test suite configured. The production build (`tsc -b && vite build`) is the only type gate; ESLint has pre-existing errors (`react-hooks/set-state-in-effect`, `exhaustive-deps`) in older pages. |
| **Frontend bundle** | One ~593 KB chunk (Vite warns above 500 KB); no code-splitting. |
| **WHEEL first load** | Fetches signals for every ticker (~65 tickers × 5 endpoints, 4 at a time); the network stays busy for over a minute. Cached afterwards. |
| **Margin page fetch** | Calls `/api/market/rsi` with a raw `fetch`, so a 401 doesn't trigger the global "signed out" flow. |
| **Unmerged fix branches** | `fix/day-color-regular-session` and `fix/earnings-date-cache` (2026-10-29) were never merged; their fixes are not on `master`. |
| **Dead code** | `WheelSlotCard.tsx` / `WheelSessionCardV2.tsx` have a "Past Rotations" section but are not imported by `WheelDashboardPage.tsx`. |
| **Decimal serialization** | Pydantic serializes `Decimal` as JSON **strings** (`"195.50"`). Any new numeric field must be typed as `string \| null` in TypeScript with explicit `parseFloat`. |
| **Call-side margin risk** | Margin dashboard tracks put obligation only; iron condor call wing is invisible to it. |
| **Chain screener** | Holiday-shifted Friday expiries silently skipped. `ChainPage` uses `?symbol=`, `ScannerPage` uses `?ticker=` — inconsistent. |
| **Scheduler** | Jobs are market-hours-gated (9:30–16:00 ET, weekdays only). Nothing runs pre-market or after hours. |

---

## 7. Development Conventions

**Do not deviate from these without a documented reason.**

- **Branching:** feature branches off `develop`; only `develop` merges to `master`. In practice (since 2026-11) merges are `--no-ff`, feature branches are pushed and kept, and `develop` → `master` happens inside the `../trademinder-release` worktree. Work is done in `.claude/worktrees/<name>` so the user's dev servers (which run from the main checkout against the dev DB) aren't disturbed; verification runs on a copy of the dev DB.
- **Per-feature workflow:** brainstorm → design spec (`docs/superpowers/specs/YYYY-MM-DD-<name>-design.md`) → task plan (`docs/superpowers/plans/`) → implement task-by-task → whole-branch review → merge. Review findings bundled into one fix dispatch, never one commit per finding.
- **Context files:** `context/_active.md` points at the live feature (or says none); each feature has `context/feature-*.md` (template in `context/README.md`: Status / Branch / Created / Goal / Scope / Key Files / Technical Approach / **Decisions Made (with reasons)** / Open Questions / Progress Log / Current State). Claude keeps them current automatically — see the repo-root `CLAUDE.md`.
- **Docs sync:** before committing a behaviour change, update `docs/decisions.md` (deviations, schema, endpoints, conventions, deferrals, ops lessons) and this file (edited in place). Rules in `CLAUDE.md`.
- **Commits:** granular and conventional (`feat(wheel):`, `fix(technicals):`, `refactor(wheel):`). **Never commit unless explicitly asked.**
- **Backend:** routers thin, services hold logic, Pydantic schemas are the contract. pytest. uv for deps.
- **Structured errors:** a machine-readable failure is `{detail, code}`, plus `fields` when it is about specific
  inputs. For example: 503 `market_data_offline`, the reconnect codes, and 422 account-fact rules with `fields`.
  The SPA's `ApiError` exposes `.code` and `.fields`.
- **Money:** `Numeric` in the database, JSON strings in the API, `string | null` in TS with an explicit `parseFloat`.
- **Frontend:** TypeScript strict, functional components, Tailwind utilities only (no custom CSS), typed fetch wrappers in `src/api/`. Shared primitives in `src/components/ui/` (shadcn-style, hand-written). Page filter state lives in URL search params, not localStorage. Page-level keyboard shortcuts listen in the capture phase and stand down while an element with `data-escape-layer` (open popover, Notes panel) exists. Run `npm run build` before pushing anything the NAS deploys.
- **Ticker aliases:** the GOOG↔GOOGL map exists in three places — `backend/app/routers/wheel.py`, `extension/content.js`, `frontend/src/lib/tickers.ts` — keep them in step.
- **Extension:** vanilla JS, no build step, all network calls via `bgFetch` through the service worker.

---

## 8. API Surface

All routes under `/api`. Everything except `auth` and `me` is mounted behind the `get_current_user` seam (401 without a session cookie or extension bearer token; 403 for pending/disabled users) and scoped to the current user and account.

| Domain | Endpoints |
|---|---|
| auth | `GET /auth/google/login`, `GET /auth/google/callback`, `POST /auth/logout` |
| me | `GET /me` (allowed while pending; returns status) |
| admin | `/admin/users`: list, invite, approve, reject, disable, enable, change role (admin only) |
| extension | `/extension/connect` (cookie session only; mints a token for an allow-listed extension), `/extension/tokens`, `/extension/tokens/current`, `/extension/tokens/{id}` |
| accounts | list, create, reorder, patch, categories, archive, restore, delete; E*TRADE links (`/links/resolve`, `/links`, `/{id}/link`). Create, patch and list carry the account facts (section 3.6): every fact is optional on create and patch, and an explicit `null` on patch clears it. Responses add `account_tax_status`, `facts_complete`, `facts_updated_at` and `values_as_of`; money is JSON strings. The same endpoints carry the goal and preferences (migration 020). Responses add `limits` (`{stored, effective, source, default}` per defaulted limit), `goals_complete` and `goals_updated_at`; an explicit `null` on patch returns a limit to the house default. Rule violations: 422 `{detail, code, fields}` |
| dashboard | `GET /dashboard/summary` (per-account cards) |
| market-data | `GET /market-data/status` (admin only; Schwab token status). `POST /market-data/reconnect/start` → `{authorize_url, state_expires_at}` and `POST /market-data/reconnect/complete` `{redirect_url}` → the status shape (admin only; errors `{detail, code}`: 400 `bad_url`/`authorization_denied`/`missing_code`/`missing_state`/`code_expired`, 409 `state_invalid`/`state_expired`/`not_configured`, 502 `schwab_unreachable`) |
| trades | CRUD, close, category assign, rationale, wheel-by-id |
| commentary | CRUD per trade, AI summary (Claude Haiku 4.5, 1h cache) |
| alerts | read, dismiss, snooze |
| categories | CRUD |
| positions | POST /status (extension core call), POST /reconcile, GET /dashboard/today |
| market | quote, rsi, options, technicals, macd-crossover, rsi-crossover, volume-spikes, cc-signal, sp-signal, combined-signal, cc-timing-signal, sp-timing-signal, option-price, refresh |
| wheel | sessions (create, list, get, `PATCH` incl. ticker/opened_at, `DELETE` only without slots), slots, legs, resolve, active-slots, slot commentary, slot history |
| sessions | spreads (Iron Condor, Put Broken-Wing Fly) |
| screener | 13 endpoints incl. fetch-all job + commentary CRUD |
| chain | `/{ticker}` — strike scoring for sell_put |
| signals | per-trade active signals, manual refresh |
| briefing | **501 Not Implemented** |

---

## 9. Environment Variables

Names only — values live in the git-ignored repo-root `.env` (dev) or the Portainer stack's environment (production), never in git. `.env.example` lists them.

| Group | Variables |
|---|---|
| Database | `DATABASE_URL` (dev), `DB_PASSWORD` (prod stack builds the URL) |
| App | `SECRET_KEY`, `OWNER_EMAIL` (seeds the owner/admin, migration 015), `OWNER_DISPLAY_NAME` |
| Login (Part 5) | `PUBLIC_BASE_URL` (dev; prod derives it from `TM_HOSTNAME`), `TM_HOSTNAME`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `AUTH_STATE_SECRET` (≥32 chars), `SESSION_DAYS`, `EXTENSION_IDS` (comma-separated allow-list) |
| HTTPS (prod only) | `ACME_EMAIL`, `CF_DNS_API_TOKEN` |
| Market data | `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`, `MARKET_DATA_PROVIDER` (only `schwab`) |
| LLMs (optional) | `ANTHROPIC_API_KEY` (commentary summaries), `GEMINI_API_KEY` (signal commentary; read via `os.environ`, not pydantic Settings) |
| Scheduler | `ALERT_ENGINE_INTERVAL_MINUTES`, `PRICE_REFRESH_INTERVAL_MINUTES`, `MARKET_HOURS_START`, `MARKET_HOURS_END`, `BRIEFING_GENERATE_TIME` |

With `PUBLIC_BASE_URL` on https, the backend refuses to start unless the Google client id/secret and a 32+ character `AUTH_STATE_SECRET` are set.

---

## 10. Running It

```bash
# Start database
docker compose up db -d

# Backend (dev) — uv-managed venv at backend/.venv
cd backend && source .venv/bin/activate
alembic upgrade head              # back up the DB first (pg_dump -Fc) whenever this will migrate
uvicorn app.main:app --reload --port 5431

# Frontend (dev)
cd frontend && npm run dev        # http://localhost:5430, proxies /api → :5431
                                  # sign in with Google: needs PUBLIC_BASE_URL=http://localhost:5430 + the Google
                                  # client in .env, and that callback registered on the OAuth client

# Production type gate (the NAS runs this)
cd frontend && npm run build

# Tests
cd backend && pytest tests/ -q    # 6 known pre-existing failures (section 6)

# Schwab re-auth (every 7 days): Reconnect Schwab in the app (admin): banner or Settings → Market data
# Fallback, for the DB in .env's DATABASE_URL:
python scripts/schwab_auth.py     # paste-URL OAuth flow (shares backend/app/services/schwab_oauth.py)
```

---

## 11. Roadmap — Ordered by Trading Leverage

### Tier 1 — Close the loop on what's built

1. **Realized P&L and wheel-cycle analytics.** Data is already in `wheel_premium_logs` (signed, per rotation) and `trades.closed_date` — nothing reads it back. Per-ticker annualized return on capital, premium captured vs assignments, win rate by entry-signal grade. **Highest-value missing piece: signals can never be validated without it.**

2. **Signal backtesting / score calibration.** `commentary.signal_snapshot` JSONB already captures full signal state at entry when trader opts in. Join against outcomes: do `strong` CC Timing entries actually expire OTM more often? Which factor has predictive power?

3. **Morning briefing, aimed at the wheel.** Not prose — an **action queue**: slots needing resolve, legs at ≤7 DTE, assignment-risk puts, earnings inside open expiry window, awaiting-CC slots whose Timing just turned `strong`. Requires lifting the pre-market scheduler gate (currently blocks before 9:30).

4. **Extend alerting to wheel slots.** Alert engine only sees `trades` today. Slots awaiting action, stale rotations, and assignment-risk-by-slot are invisible.

### Tier 2 — Deepen the edge

5. **Finish Chain screener strategies.** Sell Calls is nearly free (mirror sell_put, use CALL chain, pair with CC Timing). LEAPS-buying needs different criteria (extrinsic-per-day, breakeven move, IV percentile *low* = good).

6. **Roll decision support.** Rolling is most frequent and least-supported wheel action. A "roll candidates" view — chain-screener scoring on next 2–4 expiries at/above current strike, with net credit/debit, new ARR, breakeven shift.

7. **Assignment probability everywhere.** Black-Scholes `N(−d1)` already exists client-side. Delta is already in every chain response. Surface per-leg assignment probability on WHEEL ACTIVE boxes. Follow-on: portfolio-level expected-assignment capital requirement.

8. **Position sizing / capital allocator.** Tracks positions but never asks "should this trade exist given everything else?" Concentration by ticker/sector (sector already fetched), correlated-assignment clustering on same expiry, free-capital vs obligation headroom.

9. **Earnings as a first-class concern.** Currently a private yfinance call, surfaced only as a Chain flag. Earnings inside an expiry window is the highest-impact fact for a premium seller — belongs on the wheel dashboard and in alerts.

### Tier 3 — Structural

10. **Unify scanning philosophies.** Port LEAPS IV-surface work onto Schwab to remove last meaningful yfinance dependency besides earnings.

11. **AI analyst over the journal.** `signal_snapshot` JSONB anticipates this. "Review my last 30 wheel decisions" agent correlating stated reasoning against outcomes.

12. **Schwab token resilience.** Part 4 made a lapse a labeled offline mode, with an admin expiry banner. Phase 1 of the in-app reconnect (paste the redirect URL, 2026-11-12) removes the Mac, the CLI and the token-row copy. The 7-day login itself is Schwab's rule and stays manual. Possible phase 2: a backend callback route, which needs Schwab's single callback moved to `https://tm.<domain>/…`.

13. **Reduce manual-resolve burden.** Reconcile snapshot already knows which positions vanished from E*TRADE — enough to *propose* a resolve (never auto-apply; ITM/OTM/assigned distinction needs a human).

### Explicit non-goals — do not propose these

Order placement or any broker write path · SaaS / public sign-up · public internet exposure (for now) · cloud hosting (AWS migration parked, see `aws/`) · task queue / Redis / heavyweight infra · automatic state transitions that a human should own · server-side sort/filter for a watchlist of a few dozen rows.

---

## 12. Key Architectural Decisions and Why

| Decision | Choice | Reason |
|---|---|---|
| One row per trade leg, not per position | Individual `trades` rows with `wheel_id` grouping | Supports mixed Buy/Sell/Assigned accounting without nullable mess |
| Slots, not just sessions | `wheel_slots` with independent state machines | Unambiguous per-100-share assignment and call-away accounting |
| `needs_action` as a bool flag | Separate from slot status | UI can say "CC Active — Action Required" without losing state context |
| Signed premium logs | `premium_amount` positive for sells, negative for buybacks | `SUM()` is net premium with no special-case logic |
| No auto state transitions | All resolves are explicit user choices | ITM/OTM/assigned distinction genuinely needs a human |
| `bgFetch` relay in extension | All network through service worker | Direct `fetch()` from content script silently blocked by Chrome Local Network Access policy |
| Virtual scroll handling | MutationObserver + two-level cache | E*TRADE only renders ~32 rows; naive querySelectorAll misses most positions |
| Schwab over yfinance | Schwab for all prices/chains | yfinance rate-limits at ~19 tickers — exactly this book's size |
| 4-concurrent Schwab fetch limit | Throttle bulk signal fetches | Unthrottled `Promise.allSettled` of 150+ calls triggered WAF 403s |
| JSONB for `signal_snapshot` | Captures full signal state per note | Future AI agent can read the complete "why" — not just a grade |
| `Decimal` → JSON string | Pydantic serializes as `"195.50"` | Preserves precision; frontend must use `string \| null` + explicit `parseFloat` |
| No Redis, no task queue | In-memory caches, sequential scheduler | A small LAN app for a handful of users; complexity not justified |
| ~~No auth~~ → Multi-user with Google sign-in (2026-11) | Internal user id as tenant key, one `get_current_user` seam, server-side sessions | Pilot with a second trader on the home LAN; seam meant login changed one function, not every query |
| Accounts as containers | user → brokerage account → trades/wheels/spreads | Different accounts (IRA, taxable, hold vs. wheel) need separate positions, notes and categories |
| Admin manages accounts only | Admin cannot read other users' data | Isolation that exempts the admin isn't isolation |
| Shared market data | One app-level Schwab connection behind a provider boundary | Fetch once; a future provider swap; Neel accepted the Schwab terms risk for the pilot |
| HTTPS via Traefik + Cloudflare DNS-01 | Real cert on a LAN-only subdomain | Google requires HTTPS and a public-TLD host; nothing exposed to the internet |
