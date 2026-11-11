# Feature: Chain Screener
**Status:** Shipped — merged to `develop`, plus a first deep-link source wired in from the Wheel dashboard
**Branch:** feature/chain-screener (merged and deleted; work now lives on `develop`)
**Created:** 2026-09-23

## Goal
A new "Chain" page that screens an options chain for tradeable strike/expiry candidates against a chosen strategy, starting with **Selling Short Puts**. Replaces manual spot-checking (as done live for NVDA and BE while designing this feature) with a repeatable, tunable, visually scannable tool — deep-linkable so other pages can eventually jump straight into a pre-filled screen.

## Scope
- In scope:
  - New `/chain` page: symbol input, strategy dropdown (5 options — only "Selling Short Puts" implemented, other 4 visible but disabled), adjustable thresholds, results grouped by expiry.
  - New backend endpoint that pulls N Friday expiries via Schwab, scores every strike near the target delta on 5 weighted criteria (delta fit, ARR, volume, OI, bid-ask spread tightness), returns the top N candidates per expiry — never empty, always ranks what's available.
  - Page-level context: spot price, existing SP Timing Signal (grade + score, reused as-is), IV Percentile (reused as-is).
  - Earnings-date awareness: flag any expiry whose window contains an earnings date (reusing the existing yfinance-based fetcher in `options_scanner.py`).
  - Deep-link receiving side: `?symbol=&strategy=` (and optionally the threshold params) populate and auto-run on load, mirroring the existing Scanner page's `useSearchParams` pattern.
- Out of scope:
  - The other 4 strategies (Sell Calls, Buy 6-12mo Calls, Buy 12-24mo Calls, Sell 3-6mo Puts) — dropdown entries exist and are disabled, no logic.
  - Any deep-link *source* wiring (e.g., a clickable ticker on the Wheels dashboard that lands here) — only the receiving side is built now.
  - Non-earnings market events (dividends, macro calendar, etc.) — no such data source exists in the codebase today.
  - Automated/scheduled screening, alerts, or persistence of past screens — this is a live, on-demand tool, nothing is saved.

## Key Files / Modules Involved
- `frontend/src/pages/ChainPage.tsx` (new) — symbol input, strategy dropdown, advanced thresholds, per-expiry result boxes
- `frontend/src/api/chain.ts` (new) — typed `apiFetch` wrapper for the chain endpoint
- `frontend/src/App.tsx` — new nav item "Chain" → `/chain`, placed after "Screener"
- `backend/app/routers/chain.py` (new) — `GET /api/chain/{ticker}`, strategy dispatch (only `sell_put` implemented, else 400); 502 handler logs via `log.exception` and chains with `raise ... from exc`
- `backend/app/services/chain_screener.py` (new) — Friday-expiry selection (`_select_friday_expiries`), per-strike scoring (5 criteria via `_score_delta_fit`/`_score_arr`/`_score_volume`/`_score_oi`/`_score_spread`/`_score_candidate`), full pipeline in `compute_chain_screen(...)`
- `backend/app/schemas/chain.py` (new) — Pydantic response models (`ChainFactor`, `ChainCandidate`, `ChainExpiry`, `SpTimingSignalSummary`, `ChainScreenResponse`)
- `backend/app/main.py` — mount the new chain router
- Reused, unmodified: `backend/app/services/schwab_client.py` (`get_option_chain`, `get_price_history`), `backend/app/services/technicals_fetcher.py` (`compute_iv_percentile_from_chain`), `backend/app/services/sp_timing_signal.py` (`compute_sp_timing_signal`), `backend/app/services/options_scanner.py` (`_fetch_earnings_dates`)
- `backend/tests/test_chain_screener.py` (new) — 19 tests: scoring formula unit tests, Friday-expiry selection test, mocked live-compute test
- `frontend/src/pages/WheelDashboardPage.tsx` (modified, 2026-09-24) — `renderSignalDetailRow`'s SP Timing panel header now includes a `Link` to `/chain?symbol=<ticker>&strategy=sell_put` ("Screen strikes on Chain →"), gated on `isSPTiming` only. This is the deep-link *source* wiring the Open Questions below had flagged as deferred.

## Technical Approach
Per candidate strike, 5 weighted criteria total 100 pts, same `{name, points, max, detail}` shape as the existing `CCSignalFactor` type. Curves are piecewise/continuous (not flat cutoffs), matching how `cc_timing_signal.py`/`sp_timing_signal.py` already score RSI/MACD:

| Criterion | Max | Formula |
|---|---|---|
| Delta fit | 25 | `25 × max(0, 1 − dist / (tolerance × 1.5))` where `dist = abs(abs(delta) − target_delta)` |
| ARR | 25 | `min(25, 25 × arr_pct / min_arr_pct)` (partial credit below the minimum — no cliff) |
| Volume | 15 | `min(15, 15 × volume / min_volume)` |
| Open Interest | 15 | `min(15, 15 × oi / min_oi)` |
| Spread tightness | 20 | `20` if `spread_pct ≤ 0.05`, else `max(0, 20 × (1 − (spread_pct − 0.05) / 0.25))` |

Candidate gathering: every strike with `abs(delta)` inside `[target_delta − tolerance×1.5, target_delta + tolerance×1.5]` is scored; top `candidates_per_expiry` kept per expiry, sorted descending. Zero strikes in band → explicit "no strikes in target delta band" message, never a blank box.

IV Percentile is a **page-level** value (one per ticker, from `compute_iv_percentile_from_chain`'s internal ~30-45 DTE ATM lookup), not a per-candidate scored factor — confirmed by reading its implementation before writing the spec.

Full API shape, response JSON example, frontend layout details, and error-handling behavior are in the approved design doc: `docs/superpowers/specs/2026-09-23-chain-screener-design.md`.

## Decisions Made
| Decision | Chosen | Reason |
|----------|--------|--------|
| New service/router, not extending `options_scanner.py` | `chain_screener.py` + `routers/chain.py`, entirely new files | Different data source (Schwab, not yfinance) and different purpose (short-dated CSP screening vs. LEAPS IV-excess ranking) — conflating them would tangle two different scanning philosophies |
| Data source: Schwab, not yfinance | Reuses `schwab_client.get_option_chain` (same client already used for Wheel signals) | Matches the rest of the app's live-data backbone; yfinance is already known to rate-limit at scale (the original reason Wheel migrated off it) |
| Composite scoring with always-show-top-N, not a hard AND-filter | 5 weighted criteria, never a blank result | A strict filter went to zero candidates on NVDA during the live spike that motivated this feature — scoring shows "how close," matching the existing CC/SP Timing signal philosophy the user already relies on |
| IV Percentile is page-level context, not a per-candidate scored factor | Displayed once near spot price / SP Timing Signal | `compute_iv_percentile_from_chain` always samples its own internal ~30-45 DTE ATM option regardless of which strike/expiry is being evaluated — it's a ticker-level number, not strike-differentiating; scoring it per-candidate would have been factually wrong |
| Other 4 strategies visible-but-disabled in the dropdown, not hidden | User's explicit choice | Sets expectations for where the feature is headed without building unfinished logic now |
| All 7 filter thresholds user-adjustable in v1 (not just the 2 explicitly requested) | Delta target/tolerance, min ARR%, min volume, min OI all exposed as inputs alongside num-expiries and candidates-per-expiry | The NVDA-vs-BE spike showed identical criteria behave very differently by ticker (IV richness) — the user will need to tune these per-ticker, not just per-session |
| Earnings-only event scope for v1 | Reuses existing `_fetch_earnings_dates` from `options_scanner.py` as-is | No other market-event data source exists anywhere in the backend today; broader events would need new integration work, deferred |
| Deep-link receiving side only, no source wiring this round | `ChainPage.tsx` accepts and auto-runs `?symbol=&strategy=`, mirroring `ScannerPage.tsx`'s existing pattern; no other page links into it yet | User's explicit choice — prove out the Chain page itself before wiring a real click-through from e.g. the Wheels dashboard |
| Spec self-review caught two errors before commit | Fixed a garbled markdown formula (stray `{{}}` template artifact) and an example JSON value that didn't match its own stated formula | Caught during the mandatory self-review pass, not by the user — worth noting since it's the kind of slip that's easy to miss on a read-through |
| Worktree base ref (`EnterWorktree` default) corrected to local `develop` | Reset the fresh worktree branch to local `develop` instead of `origin/master` | The native tool's default base (`origin/<default-branch>`) was stale and missing this plan's own unpushed spec/context/plan commits |
| Task 3's earnings-date test fixed at the test level only | Changed `earnings_date = today + timedelta(days=3)` (date-fragile, fails on Wed/Thu/Fri) to `friday - timedelta(days=1)` (always inside window regardless of weekday) | A genuine plan defect caught by the implementer's own TDD red phase, independently re-verified by both me and the task reviewer; no implementation code touched |
| Final whole-branch review's 2 Important + 1 Minor findings bundled into one fix dispatch | SP Timing click-to-expand, "fewer than N expiries" note/empty-state, 502 logging+chaining — all fixed together in commit `1d2f083` | Both Important findings were judged plan defects (spec required them, no task carried them forward), not implementer deviations; the skill requires exactly one bundled fix dispatch for final-review findings, never one per finding |
| Wheel dashboard → Chain deep link placed at the top of the SP Timing breakdown panel, next to the heading | `Link to={"/chain?symbol=<ticker>&strategy=sell_put"}` in `renderSignalDetailRow`, visible immediately without scrolling past factor details | User's explicit choice over placing it at the bottom with strike_hint/caution |
| Chain link shown only for SP Timing, not CC Signal/SP Signal/CC Timing | Gated on `isSPTiming` in the shared `renderSignalDetailRow` function | Chain only implements the `sell_put` strategy today; linking from the other signal types would point to an unsupported/misleading screen |

## Open Questions / Blockers
- [ ] Exact pill color thresholds (green ≥70% of max points, amber 40-70%, red <40%) are a first guess in the design doc — untested against real data across multiple tickers/strategies; may need tuning once the page is live and used for a while.
- [ ] `options_scanner._fetch_earnings_dates` is currently a private (`_`-prefixed) function being imported directly from another service module rather than through a shared/public util — pragmatic reuse, not a formal refactor. Fine for now; worth revisiting if a third consumer ever needs it.
- [ ] No decision yet on where/how the other 4 strategies' logic will eventually differ structurally (e.g. do "Buy Calls" strategies need a totally different scoring criteria set, given ARR/delta-fit/spread don't obviously transfer to a long-option strategy?) — deferred until one of them is actually built.
- [x] ~~Deep-link source wiring (e.g. Wheels dashboard → Chain)~~ — done 2026-09-24: SP Timing panel on the Wheel dashboard now links to `/chain?symbol=&strategy=sell_put`. Other potential sources (e.g. a ticker click elsewhere) are still unwired.
- [ ] Minor findings parked (not fixed) during the final whole-branch review, still open: holiday-shifted Friday expiries are silently skipped (spec-mandated Friday-only behavior, arguably fine); `ChainPage`'s `?symbol=` vs `ScannerPage`'s `?ticker=` param-name inconsistency (now that a second deep-link source exists, this is worth resolving before a third one is built); empty numeric input in the advanced filters sends `0` and fails backend validation with a cosmetic 422; one unreachable `else`-branch in `STRATEGY_CONTRACT_TYPE` dispatch (forward-compat, harmless); two unguarded parse assumptions on stable Schwab payload shape (would 502, not crash, if violated).
- [ ] New minor found during the fix-wave re-review, parked not fixed: the "Found N of M requested expiries" note on `ChainPage` compares the result against the *live* `form.numExpiries` value rather than what was actually submitted with the request — if a user edits the "# Fridays" field after a successful screen without re-running, the note can misreport the count. Cosmetic only, no crash.

## Progress Log
- 2026-09-23 — Feature created. Live-verified the underlying idea by hand first: ran NVDA and BE puts through the proposed 1-3 week/delta-0.2/ARR>30% criteria via a throwaway script against the real Schwab chain, which is what surfaced the core design tension (delta-fit and ARR>30% don't overlap for NVDA at current IV, but do for BE) that shaped the scoring approach below. Brainstormed architectural-path design (approaches → clarifying questions → sectioned design → written spec → self-review), spec committed to `docs/superpowers/specs/2026-09-23-chain-screener-design.md`. Not yet planned or implemented.
- 2026-09-23 — Wrote the 7-task implementation plan via `writing-plans`, self-reviewed. Executed all 7 tasks via `subagent-driven-development` in worktree `feature/chain-screener` (backend service/scoring/endpoint, frontend API client/page shell/results rendering), each individually reviewed and approved. Final whole-branch review (opus) returned "Ready to merge: With fixes" — 2 Important + 1 Minor findings bundled into one fix wave (commit `1d2f083`: SP Timing click-to-expand breakdown, "fewer than N expiries" note + empty state, 502 handler logging/exception-chaining), all verified live in-browser except the zero-expiries empty state (code-inspection only). Scoped re-review of the fix wave: all 3 findings ADDRESSED, one new Minor parked (see Open Questions). Merged to `develop` via fast-forward (`220710a..1d2f083`), worktree and branch cleaned up.
- 2026-09-24 — Added deep-link source wiring: a "Screen strikes on Chain →" link in the Wheel dashboard's SP Timing breakdown panel (`WheelDashboardPage.tsx`), pointing to `/chain?symbol=&strategy=sell_put`. Bounded-path brainstorm (one clarifying question on placement), implemented, `tsc --noEmit` clean. Not yet committed.

## Current State (Resume Here)
Chain Screener itself is fully shipped and live on `develop` (backend endpoint + scoring, frontend page, all merged). The one thing NOT yet done: **the Wheel-dashboard-to-Chain link just added in `frontend/src/pages/WheelDashboardPage.tsx` (the `isSPTiming` block in `renderSignalDetailRow`, ~line 586-591) is uncommitted** — `git status` on `develop` will show it as a modified file. tsc has been verified clean; it has NOT been manually clicked through in a live browser yet.

Single next action: verify the new link live (start dev servers, open the Wheel dashboard, click an SP Timing pill, confirm the link renders and navigates to `/chain?symbol=<ticker>&strategy=sell_put` and the Chain page auto-runs), then commit it — there's no branch/worktree for this small change, it was made directly on `develop`, so a plain `git add frontend/src/pages/WheelDashboardPage.tsx && git commit` is enough (confirm with the user whether they want it as its own commit or squashed into something else first).
