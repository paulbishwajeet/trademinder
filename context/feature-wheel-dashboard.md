# Feature: WHEEL Strategy Dashboard v2
**Status:** Active development — CC Timing Signal + SP Timing Signal merged to develop 2026-09-10
**Branch:** develop (worktree-cc-timing-signal and worktree-sp-timing-signal both fast-forward merged)
**Created:** 2026-05-31 (v1), **Redesigned:** 2026-06-22 (v2)

## Goal
A slot-based WHEEL strategy system that supports multi-contract parallel wheels per ticker, per-slot state machines with a resolve flow for ITM/OTM/buyback/roll outcomes, a premium audit trail, and a compact dashboard grouped by slot status.

## Scope
- In scope (v2):
  - New data model: `wheel_sessions` → `wheel_slots` → `wheel_slot_legs` (join to `trades`) + `wheel_premium_logs`
  - Each slot is an independent state machine: `awaiting_cc` → `cc_active` → resolve → `awaiting_sold_put` → `sold_put_active` → resolve
  - `needs_action` boolean flag preserves slot status context (doesn't replace status)
  - Multi-contract slots (variable `contracts` per slot, e.g. 2 contracts = 200 shares)
  - Resolve flow: 8 outcomes (CC expired OTM/ITM, bought back, rolled; Put expired OTM, assigned, bought back, rolled)
  - Premium audit trail with signed amounts (sells positive, buybacks negative)
  - Compact dashboard: four status-grouped table sections (Needs Action, Awaiting CC, Awaiting Sold Put, Active)
  - Extension pills from `/api/wheel/active-slots` with GOOG/GOOGL ticker aliasing
  - Old `trade_sessions` table preserved for spread strategies (IC, PBWB) — zero changes to spread code
- Out of scope:
  - Automated `needs_action` detection (e.g. watching for trade closures) — user resolves manually
  - Migration of old `trade_sessions` WHEEL data into new tables (old data was cleared)
  - Removing old `trade_sessions` table (still used by spreads)

## Key Files / Modules Involved

### Backend — Models
- `backend/app/models/wheel_session.py` — WheelSession (per ticker)
- `backend/app/models/wheel_slot.py` — WheelSlot (per contract unit, independent state machine)
- `backend/app/models/wheel_slot_leg.py` — WheelSlotLeg (join table: slot ↔ trade with leg_role + rotation_number)
- `backend/app/models/wheel_premium_log.py` — WheelPremiumLog (append-only audit trail)
- `backend/app/models/trade.py` — added `wheel_slot_legs` relationship
- `backend/app/models/__init__.py` — registers all 4 new models

### Backend — Schema + Router
- `backend/app/schemas/wheel.py` — all Pydantic schemas (create/update/detail/resolve/active-slot)
- `backend/app/routers/wheel.py` — all endpoints under `/api/wheel/`
- `backend/app/main.py` — registers wheel router

### Backend — Migration + Tests
- `backend/alembic/versions/008_wheel_v2.py` — creates 4 new tables
- `backend/tests/test_wheel_models.py` — model import test
- `backend/tests/test_wheel_schemas.py` — schema validation tests
- `backend/tests/test_wheel_crud.py` — 12 CRUD endpoint tests
- `backend/tests/test_wheel_resolve.py` — 9 resolve outcome tests

### Frontend
- `frontend/src/api/wheel.ts` — wheelApi client
- `frontend/src/types/index.ts` — WheelSessionDetail, WheelSlotDetail, WheelActiveSlot, etc.
- `frontend/src/pages/WheelDashboardPage.tsx` — compact status-grouped table dashboard
- `frontend/src/components/Wheel/WheelSessionCardV2.tsx` — session card with nested slots
- `frontend/src/components/Wheel/WheelSlotCard.tsx` — individual slot card
- `frontend/src/components/Wheel/NewWheelModalV2.tsx` — create wheel session
- `frontend/src/components/Wheel/AddSlotModal.tsx` — add slot to session
- `frontend/src/components/Wheel/ResolveModal.tsx` — resolve outcomes (OTM/ITM/buyback/roll)
- `frontend/src/components/Wheel/LinkLegModalV2.tsx` — link trade as leg to slot

### Extension
- `extension/content.js` — wheel pills via `/api/wheel/active-slots`, ticker alias map, stock-only pill fallback

### Schwab Integration (added 2026-07-01)
- `backend/app/models/schwab_token.py` — SchwabToken ORM model (single row id=1)
- `backend/alembic/versions/009_schwab_tokens.py` — migration creating `schwab_tokens` table
- `backend/app/services/schwab_client.py` — SchwabClient: asyncpg token storage, httpx calls to Schwab REST API, singleton with thread-safe refresh; `get_option_chain` now accepts `strike_count` param; read timeout bumped to 30s
- `scripts/schwab_auth.py` — one-time OAuth CLI (paste-URL flow, port 8765 callback, asyncpg upsert)
- `backend/app/services/technicals_fetcher.py` — rewritten to use Schwab price history
- `backend/app/services/cc_signal.py` — combined CC+SP signal in one function (`compute_combined_signal`); `fetch_option_mid` for P&L lookup; `_option_chain_cache` with 5-min TTL
- `backend/app/services/price_fetcher.py` — rewritten to use Schwab batch quotes + price history
- `backend/app/routers/market.py` — `/cc-signal`, `/sp-signal`, `/combined-signal`, `/option-price` endpoints
- `backend/app/config.py` — added `schwab_app_key` / `schwab_app_secret` fields
- `frontend/src/api/wheel.ts` — `ccSignalApi`, `spSignalApi`, `combinedSignalApi`, `optionPriceApi`
- `frontend/src/pages/WheelDashboardPage.tsx` — CC+SP signal badges, P&L% column, active leg info under ticker, overflow-x-auto table
- `frontend/src/types/index.ts` — added `OptionPriceResult` interface

### Docs
- `docs/superpowers/specs/2026-07-01-schwab-api-design.md` — Schwab integration design spec
- `docs/superpowers/plans/2026-07-01-schwab-api.md` — Schwab integration implementation plan (6 tasks)
- `docs/superpowers/plans/2026-06-22-wheel-v2.md` — full wheel v2 implementation plan (10 tasks)
- `docs/superpowers/plans/2026-09-09-cc-timing-signal.md` — CC Timing Signal implementation plan (6 tasks)
- `docs/superpowers/plans/2026-09-10-sp-timing-signal.md` — SP Timing Signal implementation plan (6 tasks, mirrors CC Timing)

### Dashboard UI polish + CC/SP Timing Signals (added 2026-09-08 to 2026-09-10)
- `frontend/src/pages/WheelDashboardPage.tsx` — page container widened (`max-w-5xl` → `max-w-screen-2xl`); AWAITING CC and AWAITING SOLD PUT split off from the shared `renderSection`/`renderSlotRow` into independent `renderAwaitingCCSection`/`renderAwaitingCCSlotRow` and `renderAwaitingSPSection`/`renderAwaitingSPSlotRow` with their own (smaller) column sets; added Price/Change%/RSI(D)/MACD(W) columns (live via Schwab, not the persisted Screener table) to both Awaiting boxes; added module-level 1-hour client cache (`CacheEntry<T>`, `seedFromCache`, `isCacheFresh`) for signals/spSignals/quotes/technicals/ccTimingSignals/spTimingSignals/optionPrices so page navigation doesn't re-fetch; added per-section "Fetch" button + "Fetched X ago" age label (`renderSectionFetchControls`) to AWAITING CC, AWAITING SOLD PUT, and ACTIVE (not Needs Action); added "CC Timing" badge+breakdown column to AWAITING CC only and "SP Timing" badge+breakdown column to AWAITING SOLD PUT only, reusing `renderSignalBadge`/`renderSignalDetailRow` generalized to a 4-way type union (`'CC' | 'SP' | 'CCTiming' | 'SPTiming'`).
- `backend/app/services/cc_timing_signal.py` (new) — standalone CC Timing Signal: `_score_cc_timing_factors` (pure, 6 factors: RSI(D) Level, RSI(D) Trend, MACD(W), Bollinger %B, Swing High Distance, Day Color, +confluence bonus) and `compute_cc_timing_signal`/`_compute_cc_timing_fresh` (live compute, IV-percentile grade-cap gate via CALL chain, reuses `_get_llm_commentary` from `cc_signal.py`, 4h cache). Does not modify `cc_signal.py` at all.
- `backend/tests/test_cc_timing_signal.py` (new) — unit tests for the scoring curve/factors + mocked live-compute test.
- `backend/app/services/sp_timing_signal.py` (new) — mirror of `cc_timing_signal.py` with every directional factor inverted (bullish MACD favored, RSI(D) Level ideal ≤40, lower-mid Bollinger zone, "Swing Low Distance" via trailing 3-month close min as support, red day favored); IV-percentile gate uses the PUT chain, not CALL.
- `backend/tests/test_sp_timing_signal.py` (new) — mirrors the CC Timing test suite with SP-direction assertions.
- `backend/app/routers/market.py` — added `GET /cc-timing-signal/{ticker}` and `GET /sp-timing-signal/{ticker}` routes (both `?refresh=true` to bypass server cache), following the existing `/cc-signal`/`/sp-signal` route pattern.
- `frontend/src/api/wheel.ts` — added `ccTimingSignalApi`, `spTimingSignalApi` (both reuse the existing `CCSignalResult` type).
- `frontend/src/api/technicals.ts` — added `technicalsApi.quote()` (wraps `GET /market/quote/{ticker}`) alongside the existing `technicalsApi.fetch()`.

## Technical Approach (v2)
- `wheel_sessions`: id, ticker, total_shares, status (active/closed), opened_at, closed_at
- `wheel_slots`: id, session_id FK, slot_number, contracts, shares_held, status (awaiting_cc/cc_active/awaiting_sold_put/sold_put_active), needs_action (bool), rotation_number
- `wheel_slot_legs`: id, slot_id FK, trade_id FK, leg_role (stock/covered_call/sold_put), rotation_number — thin join table, Trade stays generic
- `wheel_premium_logs`: id, slot_id FK, leg_id FK, rotation_number, premium_amount (signed), event_type, event_date, notes
- Linking a trade auto-transitions slot status and logs premium
- Resolve endpoint handles all 8 outcomes: updates slot status, shares_held, rotation_number, session total_shares, and logs premium events
- Extension fetches `/api/wheel/active-slots` (60s TTL), renders pills per ticker with combined slot statuses

## WHEEL State Machine (v2)
```
awaiting_cc ──sell CC──→ cc_active ──expire OTM──→ awaiting_cc
                                   ──expire ITM──→ awaiting_sold_put (rotation++)
                                   ──bought back──→ awaiting_cc
                                   ──rolled──→ cc_active (new leg linked)

awaiting_sold_put ──sell put──→ sold_put_active ──expire OTM──→ awaiting_sold_put
                                                ──assigned──→ awaiting_cc (rotation++)
                                                ──bought back──→ awaiting_sold_put
                                                ──rolled──→ sold_put_active (new leg linked)
```

## Decisions Made
| Decision | Chosen | Reason |
|----------|--------|--------|
| Schwab API data source | Replace yfinance with Schwab REST API for technicals/CC signal/price fetcher | yfinance rate-limits at 19+ tickers; Schwab provides stable real-time quotes, price history, options chains |
| Token storage | Single `schwab_tokens` row (id=1) in Postgres | Tokens survive restarts; single-user app doesn't need per-user token rows |
| Schwab HTTP client | Direct httpx calls (no schwabdev library) | Avoid third-party dependency on an unofficial library |
| SchwabClient DB driver | asyncpg (not psycopg2) | Project uses asyncpg throughout; psycopg2 not installed |
| Pydantic Settings for secrets | `schwab_app_key`/`schwab_app_secret` in `app/config.py` Settings | `os.environ.get()` doesn't pick up `.env` — pydantic BaseSettings does |
| OAuth callback flow | Paste-URL (user copies redirect URL from browser) | Local HTTPS server with self-signed cert is blocked by browsers; paste flow is simpler and reliable |
| yfinance for earnings | Kept `_get_next_earnings()` on yfinance | Schwab doesn't provide earnings calendar; yfinance still works for this single use case |
| CC Signal fetch strategy | Auto-fetch on page load (from cache), "Fetch Signals" button force-refreshes | Page load is instant from cache; button gives user control over when to hit Schwab for fresh data |
| `refresh_expires_at` on access-token refresh | Preserve existing DB value, do not recompute | Schwab refresh token has fixed 7-day life from original auth — each access-token refresh does NOT extend it |
| CC+SP combined into one endpoint | `compute_combined_signal` → `GET /combined-signal/{ticker}` | Prevents double Schwab API calls when loading both badges per ticker |
| `contractType=ALL` avoided for large ETFs | Two separate CALL+PUT calls with `strikeCount=30` instead | QQQ with ALL returns a response too large for Schwab's gateway (502 TooBigBody) |
| Option P&L expiry tolerance | Match chain expiry keys within ±3 days of stored date | Trades entered from India (IST) have expiry stored as Thursday; Schwab uses Friday — 1-day offset is common |
| P&L% cache | 5-min TTL on option chain per ticker+contract_type | P&L needs fresher data than signals (4h); same chain reused for multiple legs on same ticker |


| Decision | Chosen | Reason |
|----------|--------|--------|
| Slot-per-contract model | Each slot independently tracks its own 100×contracts shares | Solves multi-contract problem — never need to figure out "which 100 of 900 shares were called away" |
| `needs_action` as boolean | Boolean field, not a status value | Preserves slot status context (user sees "CC Active — Action Required" not just "Needs Action") |
| `wheel_slot_legs` join table | Thin join with leg_role + rotation_number | Keeps Trade table generic; wheel-specific metadata lives in the join |
| Premium log with signed amounts | Sells positive, buybacks negative, SUM gives net | Natural accounting — no special logic for net premium queries |
| Resolve as explicit user action | User picks outcome from dropdown | System can't guess ITM vs OTM or whether shares were actually called away |
| Roll = buyback + new sale | Single resolve action logs both entries | Matches broker reality; premium log shows the debit and credit separately |
| Ticker aliases (GOOG/GOOGL) | Client-side alias map in extension | GOOG shares + GOOGL options are the same underlying; extension needs to match across share classes |
| Stock-only pill fallback | Extension pills on stock rows match by ticker; option rows require explicit etrade_symbol match | Prevents unrelated options from showing wheel pills |
| Dashboard layout | Flat status-grouped tables instead of nested session→slot cards | 19+ wheels need to be scannable at a glance; one row per slot is much more compact |
| Old trade_sessions preserved | Not dropped or modified | IC and PBWB spread strategies still use it; zero-risk migration |

| Decision | Chosen | Reason |
|----------|--------|--------|
| CC Timing Signal as a new, separate signal | Built as `cc_timing_signal.py`, independent of the existing CC/SP Signal in `cc_signal.py` (unmodified) | Existing CC Signal optimizes for overall wheel P&L (rewards bullish MACD); the new signal answers a narrower, opposite-leaning question — "will this call likely expire OTM right now" (rewards bearish MACD). The two philosophies conflict on bearish setups; keeping them separate avoids one silently overriding the other's UX slot |
| RSI(D) Level as a piecewise curve, not a flat cutoff | `rsi>=70`→20, gentle taper 50-70, steep taper 30-50, `rsi<30`→0 (mirrored for SP Timing around a ≤40 ideal cutoff) | A flat "RSI>70 is good, else not" cutoff creates an arbitrary score cliff at the boundary (69 vs 71 shouldn't swing wildly); the two-slope curve encodes "50-70 is meaningfully less bad than <50" without a hard edge |
| Bollinger position as continuous `%B`, not the 5-bucket `bollinger_position` field | `%B = (price-lower)/(upper-lower)` computed fresh in each Timing module | The existing bucketed field (`above_upper`/`near_upper`/`mid`/`near_lower`/`below_lower`) is too coarse to express "mid-to-upper but not touching either extreme" as a single zone |
| Confluence bonus (+10, capped 100) | Awarded only when RSI, MACD, and Day Color ALL hit their literal ideal condition simultaneously | Additive scoring under-rewards the exact "textbook setup" the user described; the bonus makes that specific alignment visibly stand out from a score that reached the same total via unrelated factors |
| IV Percentile as a grade-capping gate, not a scored factor | If `iv_percentile < 20`, cap grade at "moderate" + append caution note; never adds points | On the WHEEL dashboard these are stocks already owned — low premium doesn't mean "skip this ticker" (you can't skip stock you hold), so it's a caveat on the grade rather than a competing scored factor diluting the technical-timing read |
| SP Timing's RSI ideal cutoff = ≤40 (not the exact mirror-symmetric ≤30) | User explicitly chose 40 over the perfectly symmetric mirror of CC Timing's ≥70 | User's literal stated threshold ("RSI<40 is oversold") took priority over architectural symmetry; the curve shape (gentle/steep taper) was still kept symmetric, just re-centered so the ideal edge lands at 40 |
| SP Timing IV gate uses the PUT chain | `client.get_option_chain(ticker, contract_type="PUT", ...)`, not CALL | Matches how the existing `cc_signal.py` already computes CC vs SP IV percentile from different option types; put premium richness is what's relevant when selling puts |
| Badge type strings `'CC'/'SP'/'CCTiming'/'SPTiming'` (not a shared `'Timing'`) | Renamed the original `'Timing'` string to `'CCTiming'` when SP Timing was added | A ticker can have a slot in both AWAITING CC and AWAITING SOLD PUT simultaneously; both would have collided on the same `${ticker}-Timing` detail-row key across two different table sections, showing wrong/stale data in one of them |
| Client-side 1h signal/quote/technicals cache lives in module-level `Record`s outside the component | Not React state, not localStorage | Survives route navigation within the SPA (module stays loaded) without persisting across full page reloads; simplest mechanism that satisfies "don't re-fetch every page transition, only on Fetch button or after 1h" |
| Both Timing signals built via full plan+subagent-driven-development workflow | worktree isolation → 6-task plan → implementer+reviewer subagent per task → final whole-branch review → local fast-forward merge to develop | Matches the project's branching convention (feature branches off develop, only develop merges to master); subagent review caught and fixed a real defect (an implementer that accidentally committed to `develop` instead of the worktree branch — see Open Questions) |

## Open Questions / Blockers
- [ ] **Schwab refresh token expires ~2026-07-16** — re-run `python scripts/schwab_auth.py` before then (token was re-issued 2026-07-09). Backend logs a warning within 24h of expiry.
- [ ] **`test_prefetch_still_501` is broken on master** — stale test for a removed `/api/market/prefetch` stub route. Should be deleted before next merge to keep test suite green.
- [ ] **CC Signal under token refresh** — not yet tested whether `_ensure_valid_token()` correctly refreshes the access token mid-session. Will surface naturally after ~30 min of use.
- [ ] **Schwab options chain for non-optionable tickers** — `get_option_chain` raises `SchwabAPIError` for tickers with no options; signal column shows `—`. Acceptable but could show a clearer label.
- [ ] **P&L% for deep OTM/ITM strikes** — `strikeCount=60` in `fetch_option_mid` is centered on ATM. A strike far OTM (e.g. from a big move since entry) might fall outside the 60 returned; P&L would show `—`. Could increase to 100 or use Schwab `range=ALL` with date filter if this becomes an issue.
- [ ] **Trade expiry timezone bug** — trades entered from India (IST) are stored with expiry one day early due to UTC conversion in the frontend. The ±3 day tolerance in `fetch_option_mid` works around this but the root cause (date-only fields being converted through UTC) should be fixed in the trade entry form.


- [ ] **Automated `needs_action` detection** — currently manual. Could watch for trade closures (via extension sync or a background job) and auto-set `needs_action=true` when a linked leg's trade gets closed. Deferred.
- [ ] **Premium log edge case:** when a trade has `premium=0` (e.g. stock leg), the link-leg endpoint skips logging. If a stock purchase has a meaningful cost basis that should be tracked, the log schema supports it but the endpoint doesn't capture it.
- [ ] **Closing a wheel session** — UI has no "Close Wheel" button yet on the dashboard. The PATCH endpoint supports it (`status: "closed"`), but no frontend trigger exists. Low priority — user can do it via API.
- [ ] **Add Slot from dashboard** — the `WheelSessionCardV2` has the "+ Slot" button but the new flat dashboard doesn't surface it. Need to decide if adding slots belongs on a session detail page or a global action.
- [ ] **Production migration** — `alembic upgrade head` needs to run on prod DB to create the 4 new tables (migration 008).
- [ ] **Worktree cleanup pending** — `.claude/worktrees/sp-timing-signal` (branch `worktree-sp-timing-signal`) is still on disk, unremoved (user interrupted the cleanup step before the session ended). Both `develop` and `worktree-sp-timing-signal` point at the identical commit `987d5e3` (verified via fast-forward merge, nothing would be lost) — safe to remove via `ExitWorktree` (`action: "remove"`, `discard_changes: true`) whenever resumed, or leave it and just note it's redundant.
- [ ] **Neither CC Timing nor SP Timing Signal has been visually verified in a live browser this session** — all verification was `tsc`/`eslint`/`pytest` + code review; Task 6 of both plans explicitly allowed skipping the manual dev-server click-through as "optional/best-effort," and both implementers skipped it. Worth a manual pass on `/wheel` before considering this fully done: check both badges render, both breakdown panels expand with correct factor lists, and (if a ticker happens to have slots in both AWAITING CC and AWAITING SOLD PUT simultaneously) that opening one signal's detail panel then the other doesn't show stale/wrong data — this was the specific bug the CCTiming/SPTiming rename fixed, reasoned through by reviewers but never clicked through live.
- [ ] **Frontend dev server may need another restart** — it was restarted once mid-session (after the CC Timing merge, since the previous instance had been running since 2026-08-11). The SP Timing Signal merge happened after that restart; Vite's HMR should pick up the new `WheelDashboardPage.tsx` changes without a restart, but if the SP Timing column doesn't appear on reload, restart `npm run dev` from the main checkout. The backend (`uvicorn --reload`, port 5431) auto-reloads and needs no action.
- [ ] **Volume-on-green-day and Relative-Strength-vs-SPY/sector columns deferred** — discussed during CC Timing Signal brainstorming as informational-only columns (not scored) for the AWAITING CC box, explicitly deferred ("decide later"). Not started.

## Progress Log
- 2026-05-30 — v1 design discussion and spec
- 2026-05-31 — v1 implemented (8 tasks, `strategy-sessions` branch)
- 2026-06-09 — v1 extension pill fix (etrade_symbol matching), NewWheelModal multi-select
- 2026-06-10 — v1 called_away signal badge, auto-close option legs
- 2026-06-18 — v1 LinkLegModal, extension 60s TTL refresh
- 2026-06-22 — **v2 complete redesign**: new slot-based data model (WheelSession/WheelSlot/WheelSlotLeg/WheelPremiumLog), alembic migration 008, full CRUD + resolve router with 25 tests, frontend rewrite with 7 new components, extension pills from `/api/wheel/active-slots`, old WHEEL sessions cleared from DB, compact status-grouped dashboard layout. Bugs fixed: stock-only pill fallback, GOOG/GOOGL alias.
- 2026-07-01 to 2026-07-02 — **Schwab API integration**: replaced yfinance with Schwab REST API for technicals, CC signal, and price fetching. Added `SchwabToken` model + migration 009, `SchwabClient` service (asyncpg token storage, httpx calls), one-time OAuth CLI script (`scripts/schwab_auth.py`). Rewrote `technicals_fetcher.py`, `cc_signal.py`, `price_fetcher.py` to use Schwab. Added `?refresh=true` param to CC signal endpoint for cache-busting. CC Signal column now auto-fetches on page load; "Fetch Signals" button force-refreshes from Schwab. OAuth flow verified working end-to-end with real Schwab brokerage credentials.
- 2026-07-09 — **SP signal + combined endpoint + P&L% column**: Added SP (Sold Put) signal scoring as mirror of CC scoring. Merged CC+SP fetch into `compute_combined_signal` (one Schwab call set per ticker instead of two). Added `fetch_option_mid` with 5-min cached option chain lookup and ±3-day expiry tolerance to handle Thu/Fri date offset. New P&L% column in Active section shows `(premium - current_mid) / premium` colored green/red; fetched alongside signals on "Fetch Signals" button. Active leg info (expiry, strike, CC/SP) shown under ticker symbol. Table uses `overflow-x-auto` + `whitespace-nowrap` for 10-column layout. Fixed QQQ 502 overflow by switching from `contractType=ALL` to separate CALL+PUT calls with `strikeCount=30`. Merged to `develop`.
- 2026-09-08 to 2026-09-10 — **Dashboard UI polish + CC Timing Signal + SP Timing Signal**: Widened page container, split AWAITING CC/AWAITING SOLD PUT into independent column sets (dropped irrelevant columns each side, e.g. Status/Active Leg/opposite signal/P&L%), added live Price/Change%/RSI(D)/MACD(W) columns to both, added a 1-hour client-side cache (module-level, outside React state) so page navigation stops re-fetching signals/quotes/technicals every time, added per-section "Fetch" buttons + age indicators to AWAITING CC/AWAITING SOLD PUT/ACTIVE. Then designed and shipped two new scoring signals via full brainstorm → plan → subagent-driven-development workflow, each in its own worktree with per-task implementer+reviewer subagents and a final whole-branch review: **CC Timing Signal** (0-100 confidence score answering "will this covered call likely expire OTM right now," 6 factors — RSI(D) Level/Trend, MACD(W), Bollinger %B, Swing High Distance, Day Color — plus a confluence bonus and an IV-percentile grade-capping gate; deliberately separate from the existing CC Signal, which optimizes for a different thing) and **SP Timing Signal** (exact directional mirror for cash-secured puts, IV gate via PUT chain instead of CALL). Both merged to `develop` via local fast-forward. One process bug surfaced and was corrected during CC Timing's Task 1: an implementer subagent's Bash calls ran in the main checkout instead of the worktree and committed to `develop` by mistake — fixed via reset + cherry-pick, and all later dispatches were given explicit worktree-path guardrails, which prevented a repeat during SP Timing's build.

## Current State (Resume Here)
`develop` branch, HEAD at `987d5e3` ("feat(wheel): show SP Timing Signal badge and breakdown in AWAITING SOLD PUT"). Both the CC Timing Signal and SP Timing Signal features are fully implemented, task-reviewed, and final-whole-branch-reviewed with no Critical/Important findings, then fast-forward merged to `develop` locally. Backend: 289 passed, 6 pre-existing unrelated failures (test_cc_signal.py x4 assertion/RuntimeError issues, test_market_router_p2.py::test_prefetch_still_501 stale-route test, test_schwab_client.py::test_schwab_alias_maps_spx — none touched or caused by this session's work). Frontend: `tsc --noEmit` clean, `eslint src/pages/WheelDashboardPage.tsx` at its pre-existing 3-problem baseline (no unused-var regressions).

**The single next action:** decide what to do with the leftover worktree at `.claude/worktrees/sp-timing-signal` (branch `worktree-sp-timing-signal`) — it's fully merged and redundant (identical commit to `develop`), just needs `ExitWorktree` cleanup or can be ignored. After that, the natural follow-up is a manual browser pass on `/wheel` to visually confirm both new badges/breakdowns render correctly (see Open Questions — this was never clicked through live, only verified via tsc/eslint/pytest/code review).

**Wheel dashboard is live with:**
- Four status-grouped sections: Needs Action, Awaiting CC (own column set + CC Timing badge), Awaiting Sold Put (own column set + SP Timing badge), Active (shared column set with Needs Action)
- CC Signal + SP Signal badges (grade + score) still present everywhere they were before, fetched via `GET /combined-signal/{ticker}` (4h server cache + new 1h client cache, "Fetch Signals" button or per-section Fetch buttons force-refresh)
- NEW: CC Timing badge (AWAITING CC only) and SP Timing badge (AWAITING SOLD PUT only), both click-to-expand into a factor breakdown panel exactly like the existing CC/SP Signal panels
- NEW: Price/Change%/RSI(D)/MACD(W) columns on both Awaiting boxes, live from Schwab (not the persisted Screener table)
- Active section only: P&L% column (green = profit, red = loss) fetched live via `GET /option-price/{ticker}?strike=&expiry=&contract_type=` (5-min cache) alongside signals
- Table is horizontally scrollable (`overflow-x-auto`) with `whitespace-nowrap`

**Known data quirk:** trades entered from India have expiry stored one day early (timezone UTC conversion). `fetch_option_mid` handles this with ±3 day tolerance when matching Schwab chain expiry keys. The underlying date entry bug in the frontend is not yet fixed.
