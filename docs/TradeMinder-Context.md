# TradeMinder — Complete Project Context

> **Purpose of this document:** a single, self-contained briefing on TradeMinder — what it is, what it does today, how it is built, what it deliberately does *not* do, and where the real leverage is for the next round of work. Written so an LLM (or a new human collaborator) with no access to the repo can reason about the product, its trading logic, and its roadmap.
>
> **Accurate as of:** 2026-10-13, branch `develop`, commit `a99629f`.

---

## 1. What TradeMinder Is

TradeMinder is a **personal (single-user) trading assistant for an options income trader** — specifically someone running the **Wheel strategy** (sell cash-secured puts → get assigned → sell covered calls → get called away → repeat) at scale across ~20–40 tickers, plus a side book of defined-risk spreads and LEAPS.

It exists to solve three problems that compound as a wheel book grows:

1. **Fragile memory.** Three weeks after entry, you no longer remember *why* you sold that strike, what your exit rule was, or what you told yourself last Thursday. TradeMinder keeps an append-only journal per position and per wheel slot, with the technical snapshot that existed *at the moment the note was written* attached to the note.
2. **Position-to-share accounting.** With 9 contracts of covered calls on one ticker across different strikes and expiries, "which 100 of my 900 shares got called away?" has no good answer in a brokerage UI. TradeMinder models each 100-share unit as an independent **slot** with its own state machine.
3. **Entry timing is a judgment call made under time pressure.** The app turns the trader's own technical heuristics (RSI, MACD across timeframes, Bollinger position, IV percentile, day color) into **explicit, weighted, auditable scores** so the decision is repeatable and reviewable after the fact, rather than re-derived from scratch each morning.

It is explicitly **not** a broker and not an auto-trader. It is becoming **multi-user and multi-account** (in progress, see §3.0). Nothing places orders. Every state transition is a deliberate user action. It runs on the user's LAN (Mac for dev, a QNAP NAS in Container Station for "production").

**Who uses it:** today one trader, who is also the developer. That shapes most architectural decisions — in-memory caches instead of Redis, localStorage instead of user preferences tables, sequential background jobs instead of a task queue. Multi-user is in progress: there is no login yet, but every user-owned query already goes through a single current-user seam (`app/deps.py::get_current_user`, which returns the seeded owner until Google login replaces its body).

---

## 2. Stack and Topology

| Layer | Choice | Notes |
|---|---|---|
| Backend | FastAPI, Python 3.13/3.14 | async throughout |
| ORM | SQLAlchemy 2.0 async (`Mapped[]` style) | asyncpg driver |
| Migrations | Alembic | 12 migrations, `001` → `012` |
| DB | PostgreSQL 15 | JSONB used for flexible snapshot payloads |
| Market data | **Schwab REST API** (primary), yfinance (residual) | see §5 |
| LLM | Google Gemini 2.5 Flash (signal commentary), Anthropic Claude Haiku 4.5 (commentary summaries) | both optional; absence degrades gracefully |
| Frontend | React 19, Vite, TypeScript (strict), Tailwind, shadcn/ui + Radix, React Router 7 | |
| Extension | Chrome MV3, vanilla JS, no build step | overlays the E\*TRADE positions page |
| Scheduler | APScheduler in-process | market-hours-gated jobs |
| Deploy | Docker Compose; `linux/amd64` images for the QNAP TS-251+ | frontend `:5430`, backend `:5431`, postgres `:5432` |

```
Chrome Extension (E*TRADE overlay) ─┐
                                    ├─► FastAPI backend ─┬─► PostgreSQL
React SPA (8 pages) ────────────────┘                    ├─► Schwab REST (quotes, price history, option chains, fundamentals)
                                                         ├─► yfinance (earnings calendar, LEAPS scanner)
                                                         ├─► Gemini 2.5 Flash (signal commentary)
                                                         └─► Claude Haiku 4.5 (commentary thread summary)
```

**Repo layout**

```
backend/     FastAPI app (app/models, app/schemas, app/routers, app/services, alembic/, tests/)
frontend/    React SPA (src/pages, src/components, src/api, src/types)
extension/   Chrome MV3 (content.js, background.js, popup/, sidebar/)
stockpile-main/  Older Python workspace — options scanner, positions tracker, cost-basis charts (partly superseded)
docs/superpowers/{specs,plans}/   Per-feature design spec + implementation plan, one pair per feature, dated
context/     Per-feature working-context files (_project.md, _active.md, feature-*.md)
```

---

## 3. Data Model

### 3.0 Users and brokerage accounts (migrations 015–016)

Ownership is **user → brokerage account → trades / wheels / spreads**. `users` is the tenant root (internal UUID key; email unique case-insensitively but never a key; nullable `external_subject` for the future Google link; seeded from `OWNER_EMAIL`). `brokerage_accounts` belong to a user — several may be at the same broker — with `broker`, `nickname`, `last_four` (never a full account number), `external_ref`, `default_category_id`, one `is_default` per user, `sort_order`, `is_archived`. Categories are a per-user library linked to accounts via `account_categories`; screener symbols are one row per user, linked to accounts via `screener_account_memberships`, and screener notes are per account. Every user-owned table has `user_id`; `trades`, `wheel_sessions`, `trade_sessions` and `screener_commentary` also have `account_id` (children inherit through their parent). List endpoints take an optional `account_id` (absent = all accounts); creates take an optional `account_id` (absent = default account). The extension's `positions/status` and `positions/reconcile` are pinned to the default account until explicit account linking lands. Market data stays app-level and shared.

### 3.1 Core trade records

**`trades`** — one row per transaction leg, not per position. Buy, Sell, and Assigned are each their own row.
Fields: `type` (Buy/Sell/Assigned), `strategy` (Stock/Put/Call/CoveredCall/PutCreditSpread/Skip/Leap), `ticker`, `open_date`, `expiry_date`, `closed_date`, `strike_price`, `quantity`, `premium`, `collateral`, `exit_strategy`, `signal_action`, `status`, `current_price`, `unrealized_pnl`, `category_id` FK, `etrade_symbol`, `last_etrade_seen`, `wheel_id`, `session_id`.

**`rationale`** — one technical snapshot per trade (and optionally per commentary note via `commentary_id`), auto-fetched at entry. ~19 indicator fields. Only `notes` is user-written.

**`commentary`** — append-only journal. Polymorphic parent: either `trade_id` **or** `slot_id` (XOR constraint, migration 012). Carries `signal_snapshot` JSONB (migration 011) — a full "Market Snapshot" of the signals as they stood when the note was written, optionally attached per note.

**`categories`** — user-defined strategy labels (WHEEL, LEAP, HOLD, …), color + icon + sort order; drive row tinting everywhere.

**`alerts`**, **`technical_signals`**, **`daily_briefings`** — see §6.

### 3.2 Wheel v2 (the heart of the app)

Four tables, migration `008`:

```
wheel_sessions (per ticker)
  └─ wheel_slots (per 100-share unit — independent state machine)
       ├─ wheel_slot_legs (thin join: slot ↔ trade, with leg_role + rotation_number)
       └─ wheel_premium_logs (append-only, signed amounts)
```

- `wheel_slots`: `slot_number`, `contracts`, `shares_held`, `status`, `needs_action` (bool), `rotation_number`.
- `leg_role` ∈ `stock` | `covered_call` | `sold_put`.
- `wheel_premium_logs.premium_amount` is **signed** — sells positive, buybacks negative — so `SUM()` is net premium with no special-case logic. `event_type` + `event_date` + `notes` give a full audit trail per rotation.

**Slot state machine:**

```
awaiting_cc ──sell CC──► cc_active ──expire OTM──► awaiting_cc
                                   ──expire ITM──► awaiting_sold_put  (rotation++)
                                   ──bought back─► awaiting_cc
                                   ──rolled──────► cc_active (new leg linked)

awaiting_sold_put ──sell put──► sold_put_active ──expire OTM──► awaiting_sold_put
                                                ──assigned────► awaiting_cc (rotation++)
                                                ──bought back─► awaiting_sold_put
                                                ──rolled──────► sold_put_active (new leg linked)
```

8 resolve outcomes, all explicit user choices. The resolve endpoint updates slot status, `shares_held`, `rotation_number`, session `total_shares`, and writes the premium log entries. A **roll is modelled as buyback + new sale**, logged as two signed entries, matching broker reality.

**Why slots:** a slot owns exactly its own `100 × contracts` shares, so assignment and call-away accounting is unambiguous. `needs_action` is a *boolean flag*, not a status value, so the UI can say "CC Active — Action Required" rather than losing the state context.

### 3.3 Spreads (legacy, still live)

**`trade_sessions`** — the older generic grouping table (ticker, strategy, status, rotation_number, self-referential `parent_session_id`, JSONB metadata, legs → trades). Wheel migrated off it; **Iron Condors and Put Broken-Wing Flies still use it**, and it was deliberately left untouched for zero-risk migration.

### 3.4 Screener

**`screener`** — persisted watchlist row per symbol with a full technical snapshot (price, change%, IV percentile, RSI, weekly/daily MACD signal, 20/50/100/200-day MAs, Bollinger triple + bucketed position, next earnings, `volume_spikes` JSONB, `last_fetched_at`, `fetch_status`/`fetch_error`). **`screener_commentary`** — full CRUD notes per symbol (unlike trade commentary, these are editable).

### 3.5 Auth storage

**`schwab_tokens`** — single row (`id=1`) holding the Schwab OAuth access + refresh tokens and their expiries. Survives restarts. Refresh token has a **fixed 7-day life from original auth** — refreshing the access token does *not* extend it, so `refresh_expires_at` is preserved on refresh, never recomputed.

---

## 4. Feature Surface (what exists today)

Eight SPA pages: **Dashboard · Trades · WHEEL · Spreads · Margin · Scanner · Screener · Chain**.

### 4.1 WHEEL Dashboard (`/wheel`) — the primary workspace

Flat, status-grouped tables rather than nested cards, because ~19+ wheels need to be scannable at a glance. Four sections:

- **NEEDS ACTION** — any slot with `needs_action = true`, keeping its underlying status visible.
- **AWAITING CC** / **AWAITING SOLD PUT** — slots with no open option leg; show the *Timing* signals (the "is now a good moment?" read).
- **ACTIVE COVERED CALLS** / **ACTIVE SOLD PUTS** — slots with an open leg; show live option mid-price P&L%, DTE, and the Timing badges.

Per row: ticker with `1x100 R1` subscript (contracts × shares, rotation), expiry, strike, premium, live P&L%, signal badges (click to expand a full factor breakdown panel), a **Notes pill**, inline **contracts editing** (restricted to Awaiting slots — editing while a leg is open would corrupt assignment accounting on resolve), and slot delete.

- **Commentary**: the Notes pill opens an anchored popover (extension-style, not a modal). Reads a **merged slot history** (`GET /api/wheel/slots/{id}/history`) that interleaves slot-level notes with every past and current leg's trade notes, each tagged with its `origin` — one continuous "why I decided X" journal per slot across rotations. Writes go to the slot endpoint in Awaiting boxes and the trade endpoint in Active boxes, so each note stays attributed to the right entity.
- **Market Snapshot**: an opt-in checkbox per note captures the full signal objects (score, every factor, caution, strike hint, technicals) into `commentary.signal_snapshot` JSONB — explicitly so a future AI agent can read back the complete "why," not just a number.
- **Fetch controls**: per-row, per-section, and page-level. Signals are cached client-side for 1h in module-level records (survives SPA navigation, not page reload) and server-side for 4h. Bulk fetches are throttled to **4 concurrent requests** — an unthrottled `Promise.allSettled` of ~150–200 calls got the app WAF-blocked by Schwab with 403s.

### 4.2 Signals — the quantified trading logic

Four distinct signals, deliberately kept separate because they answer different questions.

**A. CC Signal / SP Signal** (`cc_signal.py`, `compute_combined_signal` — CC and SP computed in one pass to avoid double-fetching chains). Optimizes **overall wheel P&L** — so it *rewards* a bullish MACD for covered calls (you want the stock to appreciate too).

| Factor | Max |
|---|---|
| IV Percentile | 25 |
| RSI Momentum | 15 |
| Bollinger Position | 15 |
| Price vs MAs | 15 |
| MACD Trend | 10 |
| Momentum Exhaustion (CC) / Momentum Initiation (SP) | 10 |
| Strike Safety (OTM% of the ~0.30-delta, ~30 DTE contract) | 10 |
| Day Color | 5 |
| **Total** | **105** |

Grades: `strong ≥80`, `moderate ≥70`, `weak ≥60`, else `wait`. If IV is unavailable, the non-IV/non-Strike subtotal is renormalized to 100 rather than silently scoring low.

**B. CC Timing Signal / SP Timing Signal** (`cc_timing_signal.py`, `sp_timing_signal.py`). Answers the *narrower, opposite-leaning* question: **"will a contract sold right now likely expire OTM?"** For CC that means it *rewards* bearish weekly MACD — directly conflicting with the CC Signal's philosophy, which is exactly why the two are separate modules with separate UI slots.

| Factor | Max | Logic |
|---|---|---|
| MACD(W) | 30 | bearish 30 / neutral 14 / bullish 0 (inverted for SP); modulated by crossover exhaustion in **both** directions |
| RSI(D) Level | 25 | piecewise curve, no cliff: CC ideal ≥70 (gentle taper 50–70, steep 30–50); SP ideal ≤40 |
| Day Color | 20 | today's move vs prev close |
| Bollinger %B | 15 | continuous `(price−lower)/(upper−lower)`, not the coarse 5-bucket field |
| RSI(D) Trend | 10 | RSI vs its own 14-period signal line; freshness tiers 10/6/3 |
| **Total** | **100** (+10 confluence bonus, capped at 100) | |

Grades: `strong ≥80`, `moderate ≥60`, `weak ≥40`, else `wait`.

Two **non-scoring gates** sit on top:
- **IV Percentile gate**: if IV percentile < 20, cap the grade at `moderate` and append a thin-premium caution. It never adds points — on the wheel dashboard these are stocks you already own, so low premium is a caveat, not a reason to skip.
- **Weekly MACD exhaustion**: if MACD is in the ideal direction but `fading_near_flip`, append a reversal-risk caution.

**Design principles visible throughout the scoring code** (worth preserving in any new signal):
- *Piecewise continuous curves, never flat cutoffs* — RSI 69 vs 71 must not swing the score.
- *Partial credit below thresholds* — a candidate 20% under the ARR minimum scores 20/25, not 0.
- *Never return an empty result* — show how close things are, ranked.
- *Separate scoring from gating* — things that should caveat a grade don't dilute the score.
- *Freshness of a crossover matters as much as its direction* — the shared vocabulary `expanding` / `holding_strong` / `squeezing` / `fading_near_flip` drives both MACD and RSI trend factors so the trader learns one mental model.

Each signal also calls **Gemini 2.5 Flash** for a 1–2 sentence plain-trader-language commentary, a strike-selection hint, and an optional caution — returned as JSON, with silent null fallback if the key is absent or the call fails.

**C. MACD Trend** — three positional pills (Daily / 3-Day / Weekly) using the same formula on three closing-price series. The 3-day series is a positional resample of daily closes (every 3rd trading day, anchored to the most recent), because Schwab's price-history API has no 3-day candle frequency. The point is to let timeframes visibly disagree.

### 4.3 Chain Screener (`/chain`) — strike selection

Given a symbol and a strategy, pulls the next N **Friday** expiries from Schwab, scores every strike whose `|delta|` falls inside the target band, and returns the top N candidates per expiry, always ranked, never blank.

| Criterion | Max | Formula |
|---|---|---|
| Delta fit | 25 | `25 × max(0, 1 − dist/(tolerance×1.5))` |
| ARR (annualized return) | 25 | `min(25, 25 × arr/min_arr)` |
| Spread tightness | 20 | `20` if spread ≤5%, else linear decay to 0 at 30% |
| Volume | 15 | `min(15, 15 × vol/min_vol)` |
| Open Interest | 15 | `min(15, 15 × oi/min_oi)` |

All 7 thresholds are user-adjustable, because the design spike (NVDA vs BE) showed identical criteria behave completely differently across IV regimes. Page-level context: spot price, IV percentile, and the ticker's SP Timing signal (reused as-is). Expiries whose window contains an **earnings date** are flagged. Deep-linkable: `?symbol=&strategy=sell_put`, auto-runs on load; the Wheel dashboard's SP Timing panel links into it.

**Only `sell_put` is implemented.** Four more strategies (Sell Calls, Buy 6–12mo Calls, Buy 12–24mo Calls, Sell 3–6mo Puts) are visible-but-disabled in the dropdown.

### 4.4 Screener (`/screener`) — the watchlist

A persisted watchlist grid: price, change%, IV percentile, RSI, weekly MACD, 20/50/100/200-day MAs color-coded vs price, Bollinger position, last-fetched age, commentary. Expandable detail rows. Two add flows (direct form + lookup-preview-before-add). Client-side sort (nulls always last) and symbol substring filter. Per-symbol editable commentary thread.

Refresh is **always user-triggered** — single-row, or a "Fetch All" sequential background job (in-memory job dict, commits each row as it completes) that the frontend polls every 2s. Per-row "Fetching…" indicators are derived purely client-side by comparing each row's `last_fetched_at` against the job start timestamp — no backend change was needed.

### 4.5 Margin Dashboard (`/margin`) — risk sizing

CSV import of the brokerage portfolio export, analyzed entirely client-side. Core value: a **Black-Scholes probability of assignment** per short put via `N(−d1)` (Abramowitz & Stegun rational approximation, no dependencies), driving a **Confidence-Adjusted Obligation** total alongside the worst-case figure. Risk-free rate hardcoded at 4.5%; missing data falls back to `prob = 1` so exposure is never under-stated.

A two-pass parser is **spread-aware**: it caps obligation at the spread width for verticals, butterflies, and iron condors, matching on `ticker||expiry` (deliberately excluding quantity, so asymmetric structures like butterflies still match) and allocating higher-strike long puts first. Columns: Gain %, RSI pill, Assignment Prob, Weighted Obligation, plus an expiry-bucket breakdown.

### 4.6 Scanner (`/scanner`) — LEAPS IV surface

The oldest module (`options_scanner.py`, yfinance-based): fetches a LEAPS chain, fits an IV surface, and ranks contracts by **IV excess** vs the fitted surface. Different data source and different philosophy from the Chain screener — deliberately not merged.

### 4.7 Spreads (`/spreads`)

Iron Condor and Put Broken-Wing Fly sessions on the legacy `trade_sessions` model, with per-leg detail and live quotes.

### 4.8 Trades (`/trades`) + Commentary

Grouped trade table: collapsible sections by category, accent-bar headers with status breakdown, global sort (ticker / expiry), **drag-to-reorder groups persisted to localStorage**, status filter defaulting to `open`. Trade detail page with the full commentary thread, entry-time rationale rendered as the oldest entry, and an AI summary endpoint (Claude Haiku 4.5, 1h cache) returning `{summary, inferred_actions}`.

### 4.9 Chrome Extension — in-broker overlay

Injects into the E\*TRADE positions page in four stages, each independently toggleable from the popup:

1. **Category badges** + a filter toolbar above the grid.
2. **Hover commentary panel** — AI summary, inferred actions, recent notes, inline add-note with optional technicals attachment.
3. **Alert-based row coloring** — severity tint overrides category tint; a badge map per alert type.
4. **Technical signal dots** appended to the badge.

Plus **wheel pills** from `/api/wheel/active-slots` (60s TTL) with a GOOG/GOOGL ticker alias map, an add-trade modal, an edit modal, a session picker, and **Reconcile**.

The E\*TRADE grid is a **div-based virtual scroll list** (`#rdt_3`), not a table — only ~32 rows exist in the DOM at a time and row IDs are recycled. The extension handles this with a `MutationObserver` (150ms debounce) plus a two-level cache (`rowId → cacheKey`, `cacheKey → status`). Option symbols parse as `/^([A-Z]+)-{1,4}(\d{6})([CP])(\d{8})$/` where ticker+dashes is always 6 chars and the strike is the 8-digit field ÷ 1000.

**Reconcile** scrolls the entire page to accumulate *all* positions before snapshotting (the grid virtualizes against page scroll, so a naive `querySelectorAll` only ever saw ~50 rows), sends the complete snapshot, and the backend backdates anything absent as closed. All extension network calls go through a `bgFetch` relay to the service worker — direct `fetch()` from the content script is silently blocked by Chrome's Local Network Access policy.

---

## 5. Market Data Layer

**Schwab REST API is the backbone.** `SchwabClient` is a singleton: tokens in Postgres via asyncpg, direct `httpx` calls (no third-party wrapper), thread-safe refresh, 30s read timeout. Methods: `get_quotes` (batch), `get_price_history`, `get_option_chain`, `get_instrument_fundamentals`.

Migration off yfinance happened because **yfinance rate-limits at ~19+ tickers** — exactly the book size this app targets. yfinance survives for two things only: the **earnings calendar** (Schwab doesn't expose it) and the LEAPS **options scanner**.

**Hard-won operational details:**

- `contractType=ALL` on large ETFs (QQQ) returns a payload Schwab's gateway rejects with 502 TooBigBody → always two separate CALL + PUT calls with `strikeCount=30`.
- Trades entered from IST store expiry as Thursday where Schwab uses Friday → option price lookups match chain keys within **±3 days**.
- Non-optionable tickers raise `SchwabAPIError` → the signal column shows `—`.
- **Live intraday price is appended as the last daily bar** before computing RSI / daily MACD / day color, so the "live price" and "previous close" used by the timing signals stay consistent with what the indicators were computed from.
- **The refresh token expires 7 days after the original auth.** Current expiry: **2026-07-09** per project memory — re-run `python scripts/schwab_auth.py` (paste-URL OAuth flow) before then. The backend logs a warning within 24h of expiry. *This is the single most common way the whole app goes dark.*

**Cache TTLs:** signals 4h server-side / 1h client-side; option chains for P&L 5min; wheel active-slots 60s in the extension.

**Indicator library** (`technicals_fetcher.py`, ~500 lines): RSI(14) + RSI signal-line crossover state, MACD daily/3-day/weekly + crossover state (`cross_date`, `periods_since_cross`, `strength_score`, `trend`), Bollinger bands with a 5-zone bucket, MAs (20/50/100/200) with price-vs-MA flags, day color, volume-spike detection (2× a 20-day baseline over a 10-day lookback), IV percentile from the live chain, sentiment, next earnings date.

---

## 6. What Is Stubbed, Stale, or Known-Broken

**Be careful here — the README oversells.** Honest current state:

| Thing | Reality |
|---|---|
| **Morning Briefing** | `/api/briefing/*` returns **501 Not Implemented**. The `daily_briefings` table exists; nothing writes to it. The Dashboard page still says "coming in Phase 3." |
| **Dashboard page** | Three stat tiles (two populated) + an alert feed. Effectively a placeholder; the WHEEL page is the real home screen. |
| **Alert engine** | Implemented (~163 lines) and scheduled, but the 8 rules in the README are the design, not verified behavior; it only evaluates `trades`, so **wheel slots are not covered by alerts at all**. |
| **Signal engine** | Implemented; writes `technical_signals`, deactivates when conditions lapse. Drives extension dots only. |
| **README** | Partly stale: still describes yfinance as the price source and lists Phase 3/4 as pending. |
| **`test_prefetch_still_501`** | Broken on `master` — stale test for a removed route. Delete before the next merge. |
| **Pre-existing test failures** | A handful in `test_cc_signal.py`, `test_market_router_p2.py`, `test_schwab_client.py` — present before recent work, not regressions. |
| **Frontend tests** | None. No test suite configured. |
| **Dead code** | `WheelSlotCard.tsx` / `WheelSessionCardV2.tsx` have a "Past Rotations" section but are not imported by `WheelDashboardPage.tsx`. |
| **Decimal serialization gotcha** | This repo's Pydantic config serializes `Decimal` as JSON **strings** (`"195.50"`). Newer frontend types correctly use `string \| null` with explicit `parseFloat`; older `Rationale`/`TechnicalsData` types say `number \| null` (harmless only because nothing does arithmetic on them). **Any new numeric field must be typed as a string.** |
| **Call-side margin risk** | The margin dashboard tracks put obligation only; an iron condor's call wing appears in no obligation figure. |
| **Chain screener** | Holiday-shifted Friday expiries are silently skipped. `ChainPage` uses `?symbol=` while `ScannerPage` uses `?ticker=`. |
| **Scheduler** | Jobs are market-hours-gated (9:30–16:00 ET, weekdays). Nothing runs pre-market or after hours. |

---

## 7. Development Conventions

- **Branching:** feature branches off `develop`; **only `develop` merges to `master`**. Feature branches are deleted immediately after a fast-forward merge.
- **Per-feature workflow:** brainstorm → design spec in `docs/superpowers/specs/YYYY-MM-DD-<name>-design.md` → task plan in `docs/superpowers/plans/` → implement task-by-task with a fresh implementer + reviewer per task → whole-branch review → merge. Review findings are bundled into **one** fix dispatch, never one commit per finding.
- **Context files:** `context/_active.md` points at the live feature; each feature has a `context/feature-*.md` with Goal / Scope / Key Files / Technical Approach / **Decisions Made (with reasons)** / Open Questions / Progress Log / Current State. The Decisions tables are unusually valuable — they record *why* each trade-off was made, including rejected alternatives.
- **Commits:** granular and conventional (`feat(wheel):`, `fix(technicals):`, `refactor(wheel):`). Never commit unless asked.
- **Backend:** routers thin, services hold logic, Pydantic schemas are the contract. pytest. uv for deps.
- **Frontend:** TypeScript strict, functional components, Tailwind utilities only (no custom CSS), typed fetch wrappers in `src/api/`.
- **Extension:** vanilla JS, no build step, all network via `bgFetch`.

---

## 8. Where This Goes Next — Trading Leverage

Ordered roughly by *trading value per unit of work*, with the specific reason each one matters for this book.

### Tier 1 — Close the loop on what's already built

1. **Realized P&L and wheel-cycle performance analytics.** Everything needed is already in `wheel_premium_logs` (signed, per rotation, per slot) and `trades.closed_date` — but nothing reads it back. Per-ticker annualized return on capital, premium captured vs assignments taken, win rate by entry-signal grade. **This is the highest-value missing piece: without it, the signals can never be validated.**
2. **Signal backtesting / score calibration.** Every signal score is a hypothesis with no feedback loop. Persist each computed signal (score, grade, every factor) at the moment of entry — the `commentary.signal_snapshot` JSONB already captures exactly this when the trader opts in — then join against outcomes. Questions it answers: do `strong` CC Timing entries actually expire OTM more often? Which factor has predictive power and which is noise? The recent removal of the Swing Distance factor was a judgment call that this would have settled empirically.
3. **Revive the morning briefing, aimed at the wheel.** The stub exists and the Dashboard is empty. The genuinely useful version isn't a prose summary — it's an **action queue**: slots needing resolve, legs at ≤7 DTE, assignment-risk puts, earnings inside an open expiry window, awaiting-CC slots whose Timing just turned `strong`. Generate pre-market (the scheduler currently refuses to run before 9:30 — that gate needs lifting for this job).
4. **Extend alerting to wheel slots.** The alert engine only sees `trades`. Slots awaiting action, stale rotations, and assignment-risk-by-slot are invisible to it today. This is the gap between "the app knows" and "the app tells you."

### Tier 2 — Deepen the trading edge

5. **Finish the Chain screener's other four strategies.** Sell Calls is nearly free (mirror `sell_put`, use the CALL chain, pair with CC Timing). The two LEAPS-buying strategies need a genuinely different criteria set — ARR and delta-fit don't transfer to long options; think extrinsic-per-day, breakeven move required, IV percentile *low* being good instead of bad. This is explicitly flagged as an open design question.
6. **Roll decision support.** Rolling is the most frequent and least-supported wheel action. The resolve flow records a roll after the fact; nothing helps *choose* one. A "roll candidates" view — same chain-screener scoring applied to the next 2–4 expiries at or above the current strike, with net credit/debit, new ARR, and breakeven shift — slots naturally beside the ACTIVE boxes.
7. **Assignment-probability everywhere, not just on the margin page.** The Black-Scholes `N(−d1)` math already exists client-side. Delta is already in every chain response (and is itself a serviceable proxy). Surfacing per-leg assignment probability on the WHEEL ACTIVE boxes would make the "roll or let it ride" call quantitative. Natural follow-on: a **portfolio-level expected-assignment capital requirement**, which is the number that actually constrains how many wheels can run at once.
8. **Position sizing / capital allocator.** The app tracks positions but never asks "should this trade exist given everything else?" Concentration by ticker and by sector (sector is already fetched into the screener), correlated-assignment clustering on the same expiry, and free-capital-vs-obligation headroom.
9. **Earnings and event calendar as a first-class concern.** Currently a single yfinance call reused privately across modules, surfaced only as a Chain-screener flag. Earnings inside an expiry window is one of the highest-impact facts for a premium seller and deserves to sit on the wheel dashboard and in alerts, not just one page.

### Tier 3 — Structural

10. **Unify the two scanning philosophies.** Scanner (yfinance, LEAPS, IV-surface excess) and Chain (Schwab, short-dated, composite score) were deliberately kept apart. Now that Schwab is the backbone, porting the IV-surface work onto Schwab data would remove the last meaningful yfinance dependency besides earnings.
11. **An AI analyst over the journal.** The Market Snapshot design explicitly anticipates this: every note can carry the complete signal state as structured JSONB. The payoff is a "review my last 30 wheel decisions" agent that correlates stated reasoning against outcomes — essentially Tier 1 #2 with the trader's own words included. Gemini and Claude are both already wired in.
12. **Resilience on the Schwab token.** A 7-day refresh token with a manual CLI re-auth is the app's single point of total failure. At minimum: a visible banner in the UI with days remaining, not just a backend log line.
13. **Reduce the manual-resolve burden.** Automated `needs_action` detection was explicitly out of scope for v2, so slot resolution is fully manual. The reconcile snapshot already knows which positions vanished from E\*TRADE — that is enough to *propose* a resolve (never auto-apply it; the ITM/OTM/assigned distinction genuinely needs a human).

### Explicit non-goals (do not propose these)

Order placement or any broker write path · cloud hosting (runs on a home NAS by design) · a task queue, Redis, or any heavyweight infra for a single-user app · automatic state transitions that a human should own · server-side sort/filter for a watchlist of a few dozen rows.

---

## 9. Quick Reference

**API surface** (all under `/api`):
`trades` (CRUD, close, category, rationale, wheel-by-id) · `commentary` (+ AI summary) · `alerts` (read/dismiss/snooze) · `categories` · `positions/status`, `positions/reconcile`, `dashboard/today` · `market` (quote, rsi, options, technicals, macd-crossover, rsi-crossover, volume-spikes, cc-signal, sp-signal, combined-signal, cc-timing-signal, sp-timing-signal, option-price, refresh) · `sessions` (spreads) · `wheel` (sessions, slots, legs, resolve, active-slots, slot commentary, slot history) · `screener` (13 endpoints incl. fetch-all job + commentary CRUD) · `chain/{ticker}` · `briefing` (501) · `signals`.

**Run it:**
```bash
docker compose up db -d
cd backend && source venv/bin/activate && alembic upgrade head && uvicorn app.main:app --reload --port 5431
cd frontend && npm run dev          # http://localhost:5430, proxies /api → :5431
cd backend && pytest tests/ -v
python scripts/schwab_auth.py       # one-time OAuth, re-run before the refresh token expires
```

**Environment:** `DATABASE_URL`, `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`, `ANTHROPIC_API_KEY` (commentary summaries), `GEMINI_API_KEY` (signal commentary — read via `os.environ`, *not* via pydantic Settings), `ALERT_ENGINE_INTERVAL_MINUTES`, `PRICE_REFRESH_INTERVAL_MINUTES`, `BRIEFING_GENERATE_TIME`.
