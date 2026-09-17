# Feature: WHEEL Strategy Dashboard v2
**Status:** Active development — CC/SP Timing Signals, ACTIVE box redesign, MACD Trend column, and RSI(D) Trend crossover redesign all committed and pushed as of 2026-09-17 but still not manually verified in a live browser; a same-day follow-up (commentary pill on Active boxes + signal-fetch throttle fix) is manually verified live but uncommitted — see Current State
**Branch:** develop (all worktrees fast-forward merged)
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

### RSI(D) Trend redesign — signal-line crossover (added 2026-09-17)
- `backend/app/services/cc_timing_signal.py` / `backend/app/services/sp_timing_signal.py` — RSI(D) Trend factor rewritten from scratch: dropped the old ad-hoc "6-day trailing RSI window, was RSI ever >60 (CC) / <40 (SP), then check direction" logic (and its now-unused `_compute_rsi_14` import) in favor of the already-computed `rsi_cross_direction` (RSI vs its own 14-period moving-average "signal line", bullish/bearish) and `rsi_trend` (`expanding`/`holding_strong`/`squeezing`/`fading_near_flip` — same vocabulary as `macd_weekly_trend`) fields from `_rsi_crossover_state()` in `technicals_fetcher.py`. New scoring: ideal-direction cross (bearish for CC, bullish for SP) scores 10/6/3 by freshness tier, wrong-direction cross scores 0, no-crossover-data falls back to 3. No new backend capability needed — this data already existed, just wasn't consumed by either Timing signal before.
- `backend/tests/test_cc_timing_signal.py` / `backend/tests/test_sp_timing_signal.py` — 3 new tests each (6 total) covering the freshness tiers, wrong-direction zeroing, and the no-data fallback.

### Per-leg commentary on Active boxes + signal-fetch throttling (added 2026-09-17)
- `frontend/src/components/Commentary/CommentaryPopover.tsx` (new) — pill button (note-count icon) that opens an anchored floating panel (positioned via the trigger button's `getBoundingClientRect()`, flips above/below/clamps to viewport, closes on outside-click/Escape) instead of the centered-modal pattern `CommentaryCell` uses on the Trades page. Internally just wires `tradeId`/`ticker` into the existing `CommentaryThread`/`CommentaryForm`/`TechnicalsPanel`/`commentaryApi` — no duplicated note/tag/rationale logic.
- `frontend/src/pages/WheelDashboardPage.tsx` — added a `Notes` column to the shared `renderActiveSection` table (both ACTIVE COVERED CALLS and ACTIVE SOLD PUTS), rendering `<CommentaryPopover>` keyed to the slot's currently-open leg (`rotation_number === slot.rotation_number && trade_status === 'open' && leg_role !== 'stock'`); bumped `renderLegRows`/`renderSignalDetailRow` colspans 12→13 to match. Separately, replaced the flat `Promise.allSettled([...huge array...])` in `loadSignals()` with a new `runWithConcurrency(tasks, limit)` helper (cap `SIGNAL_FETCH_CONCURRENCY = 4`) — see Decisions Made for why.
- Backend: **no changes** — reused `GET/POST /api/trades/{trade_id}/commentary` as-is.

### ACTIVE box redesign + MACD Trend + weekly-MACD exhaustion (added 2026-09-11 to 2026-09-14)
- `frontend/src/pages/WheelDashboardPage.tsx` — ACTIVE split off from the shared `renderSection`/`renderSlotRow` (which NEEDS ACTION still uses, unchanged) into its own `renderActiveSlotRow`/`renderActiveSection`, then split AGAIN into two independent boxes: **ACTIVE COVERED CALLS** (`cc_active` slots) and **ACTIVE SOLD PUTS** (`sold_put_active` slots), both filtered from the same already-expiry-sorted `active` array (via `activeCC`/`activeSP`) so sort order is preserved; `renderActiveSection` generalized to take `(title, color, bgColor, borderColor, fetchKey, slots)` so both boxes reuse one function with independent fetch-cache keys. Within the row: removed "Active Leg" and "Status" columns; merged "Size"/"Rot" into the Ticker cell as a small subscript (`1x100 R1`); added a colored pill (amber = CC, blue = SP) to the existing expiry/strike leg-summary line via new `renderActiveLegSummary`; replaced "CC Signal"/"SP Signal" columns with "CC Timing"/"SP Timing" badges; added Price/Change%/RSI(D)/MACD(W) columns (reusing existing cell renderers).
- New "MACD Trend" column: three small color-coded pills (D / 3D / W) via new `renderMacdTrendCell`, added to ACTIVE, AWAITING CC, and AWAITING SOLD PUT. In the two Awaiting boxes it replaced the removed "CC Signal"/"SP Signal" columns (net column count unchanged); in ACTIVE it's additive.
- `backend/app/services/technicals_fetcher.py` — added `_resample_n_day_closes(close, n)` (positional bucketing anchored to the most recent close, not calendar-based, since business-day series have holiday gaps) and wired it into `fetch_technicals()` to compute `macd_daily_signal`/`macd_daily_notes` (same bullish/bearish/neutral formula as weekly, run on daily closes) and `macd_3day_signal`/`macd_3day_notes` (same formula run on a 3-trading-day resample). Purely additive — existing `macd_signal`/`macd_weekly_*`/`macd_daily_cross_*` fields untouched.
- `backend/tests/test_technicals_fetcher.py` — added 3 tests for `_resample_n_day_closes` (anchoring, every-Nth selection, empty-series guard).
- `frontend/src/types/index.ts` — `TechnicalsData` extended with `macd_daily_signal`/`macd_daily_notes`/`macd_3day_signal`/`macd_3day_notes`.
- `backend/app/services/cc_timing_signal.py` / `backend/app/services/sp_timing_signal.py` — MACD(W) factor now reads `macd_weekly_trend` (already computed by `_macd_crossover_state`, just not previously consumed by either Timing signal) to detect exhaustion of the confirming trend: when the ideal-direction MACD read (bearish for CC, bullish for SP) is `"squeezing"` → 18/25 (was 25), `"fading_near_flip"` → 12/25 (same as neutral) plus a caution note naming weeks-since-cross. Wrong-direction MACD is unaffected (stays 0 regardless of trend). Confirmed live against AAPL via curl: MACD(W) dropped from 25→12 and the caution note appeared exactly as designed.
- `backend/tests/test_cc_timing_signal.py` / `backend/tests/test_sp_timing_signal.py` — 2 new tests each (4 total) covering the exhaustion point deltas and confirming the trend is ignored when MACD is already in the "bad" direction.

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

| Decision | Chosen | Reason |
|----------|--------|--------|
| ACTIVE box split off from the shared NEEDS ACTION renderer | New `renderActiveSlotRow`/`renderActiveSection`, not a shared-code change to `renderSlotRow`/`renderSection` | User only wanted CC Signal/SP Signal → CC Timing/SP Timing swapped in ACTIVE, not in NEEDS ACTION; sharing the row renderer would have forced the change onto both |
| ACTIVE split again into two boxes by option type | "ACTIVE COVERED CALLS" / "ACTIVE SOLD PUTS", filtered from the same sorted `active` array rather than re-deriving/re-sorting | `.filter()` on an already-sorted array preserves order for free — no need to duplicate the expiry-sort logic per box |
| Size/Rot merged into the Ticker cell as a subscript; Status and Active Leg columns dropped (ACTIVE box only) | `1x100 R1` inline next to the ticker symbol | User wanted a denser ACTIVE box; these three columns carried info already inferable from context (all ACTIVE slots share the same two statuses) or now redundant with the new subscript |
| CC/SP pills colored amber/blue (not green/red) | Amber = CC, Blue = SP, shown inline in the leg-summary line | User's explicit color choice after an initial green/blue iteration; avoids clashing with the green/red used elsewhere for P&L direction |
| "MACD Trend" as 3 positional pills (D/3D/W), not a single blended value | Reuses the same bullish/bearish/neutral formula 3x on different closing-price series, not a new indicator | Keeps each timeframe's read independently visible — the whole point was to let 3 timeframes disagree visibly (confirmed the AAPL case: D=bullish, 3D=bearish, W=bearish) |
| 3-Day MACD computed via positional resample of daily closes, not a separate Schwab API call | `_resample_n_day_closes` takes every 3rd trading day, anchored to the most recent close | Schwab's price-history API doesn't support a 3-day candle frequency type; resampling the already-fetched daily series avoids a new API call entirely |
| Weekly MACD exhaustion (`macd_weekly_trend`) folded into the MACD(W) scoring factor of both Timing signals | `squeezing` → 18/25, `fading_near_flip` → 12/25, only when MACD is already in the signal's ideal direction | User's specific real-world observation (AAPL: bearish MACD but 4 weeks since cross, strength fading) — a stale confirmation is worth less than a fresh one; docking points was judged better than a separate factor since it's a modifier on the existing MACD read, not new independent information |
| Exhaustion caution note fires only on `fading_near_flip`, not `squeezing` | `squeezing` treated as a mild, non-alarming softening | User's explicit choice — only the most extreme exhaustion state (imminent flip) is worth interrupting the trader with a caution |

| Decision | Chosen | Reason |
|----------|--------|--------|
| RSI(D) Trend replaced entirely with RSI-vs-signal-line crossover, not patched | Full rewrite using `rsi_cross_direction`/`rsi_trend`, old `>60`/`<40` "was elevated/depressed" window logic removed outright | User's real NBIS example exposed a genuine blind spot: RSI fell from 58.49→47.23 (a clear downward move) but scored only 3/10 "Neutral/weak" because it never touched the 60 threshold first. A direction-based signal-line cross has no such blind spot and reuses data (`rsi_ma_14`, `rsi_cross_direction`, `rsi_trend`) that was already computed but unused |
| RSI(D) Trend freshness tiers (10/6/3) mirror the MACD(W) exhaustion tiers (25/18/12→same-as-neutral pattern) exactly | Same `expanding`/`holding_strong`/`squeezing`/`fading_near_flip` vocabulary drives both factors | Consistency — a trader reading "squeezing" already knows what it means from the MACD(W) factor; reusing the same freshness concept for RSI avoids introducing a second mental model |
| No-crossover-data fallback scores 3 (neutral), not 0 | Matches the old logic's insufficient-data behavior | Absence of data shouldn't be scored as a bearish/bullish signal in either direction — 3 is the same "no clear signal" value used elsewhere in this factor |

| Decision | Chosen | Reason |
|----------|--------|--------|
| Commentary reuses `Commentary`/`trades.id`, not a new wheel-specific table | `WheelSlotLeg.trade_id → Trade.id` already exists; `GET/POST /api/trades/{trade_id}/commentary` needed zero changes | Both the Chrome extension and the Trades page already write/read commentary keyed by `trade_id`; a leg's trade_id is the same row either surface touches, so notes added from either location show the same trail with no new join logic |
| New `CommentaryPopover` component instead of reusing `CommentaryCell`'s modal | Anchored floating panel, positioned off the trigger button, closes on outside-click/Escape | User explicitly asked for extension-style popover placement, not `CommentaryCell`'s centered `Dialog` modal; still reuses `CommentaryThread`/`CommentaryForm`/`TechnicalsPanel` underneath so there's no duplicated note/rationale logic, only the chrome differs |
| Commentary pill scoped to the active leg only, not past rotations | Targets `slot.legs.find(rotation_number === slot.rotation_number && trade_status === 'open' && leg_role !== 'stock')` | Past-rotation legs aren't rendered anywhere on the current Wheels page at all (the `WheelSlotCard.tsx`/`WheelSessionCardV2.tsx` components that show a "Past Rotations" section are dead code, not imported by `WheelDashboardPage.tsx`) — adding past-leg commentary would first require adding past-leg rows to the page, which is out of scope; explicitly deferred |
| Slot-level commentary (for AWAITING CC/AWAITING SOLD PUT, before a leg/trade exists) deferred as a fast-follow, not built this session | Discussed and designed (make `Commentary.trade_id` nullable, add nullable `slot_id` FK + XOR check constraint, mirror `GET/POST /api/wheel/slots/{slot_id}/commentary`) but not implemented | User wanted the active-leg pill shipped first; the slot-level case needs a schema migration (`trade_id` nullable + new `slot_id` column) which is a bigger change than the active-leg case, which needed zero backend changes |
| Bulk signal fetch throttled to 4 concurrent requests (`runWithConcurrency`) | Small local worker-pool helper, not a library (no new dependency) | Root-caused via reproduction: `loadSignals()` fired ~150-200 simultaneous Schwab API calls (5 endpoints × ~40 tickers) via one flat `Promise.allSettled`; Schwab's WAF returns 403 "Access Denied" on that burst pattern and stays blocked for a stretch afterward, so unrelated requests (including a user's "Fetch Technicals" click) failed too. Verified fix live: reloaded the page fresh, zero 403s in the backend log, all signal columns populated, and the commentary popover's Fetch Technicals succeeded immediately after |

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
- [ ] **Worktree `.claude/worktrees/sp-timing-signal` cleanup still pending** — still on disk, unremoved, from the SP Timing Signal build. Its commits are fully contained in `develop`'s history (now several commits further along, past `987d5e3`, `08a769c`, and `f8cc437`) — still safe to remove via `ExitWorktree` (`action: "remove"`, `discard_changes: true"`) whenever convenient, nothing would be lost.
- [ ] **Nothing in this feature has been visually verified in a live browser across the last three sessions of changes** — CC/SP Timing badges, the ACTIVE box redesign, the MACD Trend column, and today's RSI(D) Trend crossover redesign have all been verified via `tsc`/`eslint`/`pytest` (and, for a few specific factors, live `curl` checks against the running backend) but never clicked through in an actual browser session on `/wheel`. Worth a full manual pass at some point: check every badge renders, every breakdown panel expands with the right factor list, and that a ticker with slots in both an Awaiting/Active-CC box and an Awaiting/Active-SP box simultaneously doesn't show stale/crossed data between the two.
- [ ] **Volume-on-green-day and Relative-Strength-vs-SPY/sector columns deferred** — discussed during CC Timing Signal brainstorming as informational-only columns (not scored) for the AWAITING CC box, explicitly deferred ("decide later"). Not started.
- [ ] **Slot-level commentary fast-follow** — commentary on a slot itself (for AWAITING CC/AWAITING SOLD PUT, before any leg/trade exists — "why I'm sitting on this slot") was designed but not built. Needs: `Commentary.trade_id` made nullable, new nullable `slot_id` FK (→ `wheel_slots.id`, `ON DELETE CASCADE`) + a DB check constraint that exactly one of `trade_id`/`slot_id` is set, a mirror `GET/POST /api/wheel/slots/{slot_id}/commentary` route pair, and generalizing `CommentaryPopover`/`CommentaryForm`/`commentaryApi` to accept `slotId` as an alternative to `tradeId`. Also undecided: whether slot-level notes stay visible permanently once the slot has an active leg, or get treated as historical once legs exist (see this session's discussion) — needs a decision before implementing.
- [ ] **Past-rotation legs aren't shown anywhere on the live Wheels page** — discovered while scoping commentary: `WheelDashboardPage.tsx`'s `renderLegRows` only ever shows the *current* rotation (`rotation_number === slot.rotation_number`) when a row is expanded. The "Past Rotations" section exists in `WheelSlotCard.tsx`/`WheelSessionCardV2.tsx` but those components are dead code, not imported by the actual page. If past-leg detail (or past-leg commentary) is ever wanted on the dashboard, the rows need to be added to `renderLegRows` first — separate, unscoped task.
- [ ] **This session's commentary-pill + signal-fetch-throttle changes are uncommitted** — `frontend/src/pages/WheelDashboardPage.tsx` (modified) and `frontend/src/components/Commentary/CommentaryPopover.tsx` (new, untracked) are sitting in the working tree on `develop`, not yet committed or pushed. `tsc --noEmit` is clean; verified live in a real browser (note added with technicals attached, persisted via API, pill count updated; signal-fetch burst/403 fix confirmed via backend log + fresh page reload) but not covered by any automated test.

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
- 2026-09-11 to 2026-09-14 — **ACTIVE box redesign, MACD Trend column, weekly-MACD exhaustion scoring**: Iteratively redesigned the ACTIVE box via direct edits (no plan/worktree, small scope each step) — swapped CC Signal/SP Signal for CC Timing/SP Timing badges (required splitting ACTIVE off from the NEEDS-ACTION-shared row renderer), removed Active Leg and Status columns, merged Size/Rot into the ticker as a subscript, added colored CC/SP pills (amber/blue) to the leg-summary line, added Price/Change%/RSI(D)/MACD(W) columns, then split ACTIVE itself into "ACTIVE COVERED CALLS" and "ACTIVE SOLD PUTS" by slot status. Along the way, live-checked CC Timing details for BE and SOFI via curl for the user (analysis only, no code changes). Built a new "MACD Trend" column (3 pills: Daily/3-Day/Weekly bullish-bearish-neutral) — added `_resample_n_day_closes()` to `technicals_fetcher.py` for the 3-day read (no new Schwab call, just a positional resample of already-fetched daily closes) and wired daily/3-day MACD into `fetch_technicals()`; rolled the column out to ACTIVE, then to AWAITING CC and AWAITING SOLD PUT (replacing the removed CC Signal/SP Signal columns there too, at the user's follow-up request). Finally, incorporated weekly MACD **exhaustion** into both Timing signals' scoring: when the ideal-direction MACD read is `squeezing` or `fading_near_flip` (per the already-computed `macd_weekly_trend` crossover state), the MACD(W) factor now scores lower (18/25 or 12/25 instead of 25/25) plus a caution note on `fading_near_flip` — prompted by the user's own read of a real AAPL case ("bearish exhaustion," 4 weeks since cross, fading strength). Verified live via curl against AAPL that the score and caution note both update as designed. All of this is backend-tested (pytest) and frontend-typechecked/linted at every step. (Committed by the user directly as `f8cc437`, "updated wheel context files", along with the previous session's context update.)
- 2026-09-15 to 2026-09-17 — **CC Timing lookups + RSI(D) Trend redesign**: Ran a few live CC Timing Signal checks on request (SOFI, NBIS) via curl, with judgment/analysis on each. The NBIS check surfaced a real flaw in RSI(D) Trend: RSI had fallen from 58.49 to 47.23 over 5 sessions (a clear downward move) but scored only 3/10 "Neutral/weak" because it never crossed the factor's `>60` "was elevated" threshold. Rewrote RSI(D) Trend for both `cc_timing_signal.py` and `sp_timing_signal.py` to use `rsi_cross_direction`/`rsi_trend` (RSI vs. its own 14-period moving-average signal line, already computed by `_rsi_crossover_state()` but previously unused by either Timing signal) instead of the old ad-hoc 6-day-window/threshold logic — verified live that NBIS now correctly scores 10/10 "Bearish cross, expanding." Added 6 new tests (3 per file). Backend: 302 passed, same 6 pre-existing unrelated failures. Committed and pushed to `origin/develop`.
- 2026-09-17 — **Per-leg commentary pill on Active boxes + signal-fetch throttling**: Brainstormed (bounded path) and shipped a commentary pill (note-count icon → anchored floating panel, extension-style) on each row of ACTIVE COVERED CALLS / ACTIVE SOLD PUTS, targeting the slot's currently-open leg's `trade_id`; reused the existing `Commentary`/`trades.id` data model and `CommentaryThread`/`CommentaryForm`/`TechnicalsPanel` components end-to-end, so zero backend changes were needed. Verified live in a browser: added a note, fetched technicals on demand mid-note, submitted with the rationale snapshot attached, confirmed via direct API query that it persisted correctly, and confirmed the pill's count updated in the table. Also discussed (not yet built) the natural fast-follow — slot-level commentary for AWAITING CC/AWAITING SOLD PUT slots before any leg exists — and designed the schema change it needs (nullable `trade_id` + new nullable `slot_id` on `Commentary`); logged as an Open Question. Separately, debugged a user report that "Fetch Technicals" failed in the new popover: root-caused (via live reproduction, not guessing) to a pre-existing, unrelated bug — `loadSignals()`'s bulk fetch fires ~150-200 concurrent Schwab API calls with no throttling, which trips Schwab's WAF (403 Access Denied) and blocks any request landing in that window, including the new popover's fetch. Fixed by adding a small concurrency-limited task runner (`runWithConcurrency`, cap 4) and routing the bulk fetch through it; verified live that a fresh page load now produces zero 403s and the popover's Fetch Technicals succeeds immediately. A second reported failure that same session turned out to be a red herring — the user's local frontend dev server simply wasn't running. Changes are **uncommitted** at end of session (see Current State).

## Current State (Resume Here)
`develop` branch. Working tree has **uncommitted changes** from today's session, not yet committed or pushed:
- Modified: `frontend/src/pages/WheelDashboardPage.tsx` — adds the `Notes` column + `<CommentaryPopover>` wiring to the ACTIVE COVERED CALLS/ACTIVE SOLD PUTS table (targets the slot's active leg's `trade_id`), plus the unrelated `runWithConcurrency`/`SIGNAL_FETCH_CONCURRENCY` throttle fix inside `loadSignals()`.
- New/untracked: `frontend/src/components/Commentary/CommentaryPopover.tsx`.
- Everything else in the repo (RSI(D) Trend redesign and earlier) is already committed and pushed to `origin/develop` — only today's two items above are outstanding.

Both changes were manually verified live in a real browser this session (see Progress Log above for specifics) — `tsc --noEmit` is clean — but neither has an automated test, and neither has been through code review.

**The single next action:** review and commit these two changes (`git add frontend/src/pages/WheelDashboardPage.tsx frontend/src/components/Commentary/CommentaryPopover.tsx`, then commit — they're logically two unrelated changes bundled in one session: consider whether the user wants them as one commit or split into "commentary pill" + "signal-fetch throttle fix"), then push to `origin/develop`. After that, the still-pending manual-browser-verification pass for the CC/SP Timing badges/ACTIVE box redesign (carried forward from prior sessions, see Open Questions) and the leftover `.claude/worktrees/sp-timing-signal` cleanup are still open, in that order.

**Wheel dashboard is live with:**
- Four boxes plus NEEDS ACTION: Awaiting CC (own columns + CC Timing badge + MACD Trend), Awaiting Sold Put (own columns + SP Timing badge + MACD Trend), **Active Covered Calls** and **Active Sold Puts** (split from a single ACTIVE box; own columns + CC Timing/SP Timing badges + MACD Trend; ticker cell shows `1x100 R1` subscript + expiry/strike + colored CC/SP pill)
- CC Signal + SP Signal badges (grade + score) remain ONLY in NEEDS ACTION now (removed from both Awaiting boxes and both Active boxes this session), fetched via `GET /combined-signal/{ticker}` (4h server cache + 1h client cache)
- CC Timing / SP Timing badges now appear in Awaiting CC/SP AND both Active boxes, all click-to-expand into a factor breakdown panel
- MACD Trend column (3 pills: D/3D/W) now in all four non-NeedsAction boxes
- Active boxes only: P&L% column (green = profit, red = loss) fetched live via `GET /option-price/{ticker}?...` (5-min cache) alongside signals
- Tables are horizontally scrollable (`overflow-x-auto`) with `whitespace-nowrap`

**Known data quirk:** trades entered from India have expiry stored one day early (timezone UTC conversion). `fetch_option_mid` handles this with ±3 day tolerance when matching Schwab chain expiry keys. The underlying date entry bug in the frontend is not yet fixed.
