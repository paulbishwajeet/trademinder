# Feature: Margin Assignment Confidence

**Status:** Complete — Pending Merge
**Branch:** develop
**Created:** 2026-05-17

## Goal
Adds a Black-Scholes probability-of-assignment layer to the margin dashboard. Each short put gets an assignment probability derived from N(-d1), combining current stock price and implied volatility from the position's CSV data. The dashboard shows a confidence-adjusted weighted obligation total (obligation × prob, falling back to full obligation when data is unavailable) alongside the existing worst-case figures, giving a realistic view of how much capital is actually at risk.

## Scope
- In scope:
  - Extend `/api/market/rsi` to return `{rsi, price}` per ticker (price is free from the same yfinance download)
  - Client-side BS math (`normalCDF`, `bsPutAssignmentProb`) in the frontend — no external dependencies
  - `gainPct` computed from CSV at parse time (no backend needed)
  - `enrichedPuts` useMemo: enriches each position with `stockPrice`, `rsi`, `assignmentProb`, `weightedObligation`
  - 5th summary card: Confidence-Adjusted Obligation (`border-t-violet-500`)
  - Liquid Coverage card updated sub-text: shows adjusted coverage %
  - Loading/error banner beneath header
  - Position table: 4 new columns — Gain %, RSI (colored pill), Assign. Prob, Wtd. Obligation
  - Expiry breakdown table: Wtd. Obligation column + footer total
  - Extension `fetchRsiForAll` updated to read `val.rsi` from new response shape
  - Spread-aware obligation: two-pass CSV parser caps obligation at spread width for vertical spreads, butterflies, and iron condors
- Out of scope:
  - Server-side probability storage or history
  - Live options chain IV (uses IV from CSV snapshot)
  - Probability decay over time (static DTE-based snapshot only)
  - Call spread obligation tracking (only put side is tracked)

## Key Files / Modules Involved
- `backend/app/services/price_fetcher.py` — `_fetch_one_rsi` returns `{rsi, price}` dict
- `backend/app/routers/market.py` — return type annotation updated
- `backend/tests/test_price_fetcher.py` — 4 new tests for dict return shape
- `extension/content.js` — `fetchRsiForAll` reads `val.rsi` not bare float
- `extension/background.js` — default API URL updated to 5431
- `extension/popup/popup.js` — default API URL updated to 5431
- `extension/popup/popup.html` — placeholder URL updated to 5431
- `frontend/src/pages/MarginDashboardPage.tsx` — all frontend changes; spread-aware parser; `API_URL` fix
- `frontend/vite.config.ts` — dev port 5430, proxy target 5431
- `frontend/Dockerfile` — EXPOSE updated to 5430
- `frontend/nginx.conf` — proxy_pass updated to backend:5431
- `docker-compose.yml` — ports updated (frontend 5430, backend 5431)
- `docker-compose.prod.yml` — uvicorn port 5431, frontend default port 5430
- `context/margin.md` — this file (created this session)

## Technical Approach
Pure client-side computation triggered by a single batch request to the existing `/api/market/rsi` endpoint (now extended to return price). The Abramowitz & Stegun rational approximation implements `normalCDF` with no external dependencies. `enrichedPuts` is a `useMemo` keyed on `[parsed, marketData]` — reruns only when market data loads. `fetchMarketData` uses an `AbortController` (stored in a ref) to cancel in-flight requests on rapid re-upload. The conservative fallback `prob ?? 1` ensures positions with missing market data count as 100% assignment risk, so the weighted total never under-represents exposure. Risk-free rate hardcoded at `r = 0.045`.

## Decisions Made
| Decision | Chosen | Reason |
|----------|--------|--------|
| Probability model | Black-Scholes N(-d1) | Standard risk-neutral proxy; computationally cheap; all inputs available from CSV + backend |
| Data source for price | Extend existing `/api/market/rsi` | Price is free from the same 45-day yfinance download; no new endpoint needed |
| Risk-free rate | 0.045 | Approximate current T-bill rate as of 2026-05 |
| Missing-data fallback | `prob ?? 1` (full obligation) | Conservative — never under-weights exposure when backend is unavailable |
| Error-state value on 5th card | Show `—` (not weighted total) | On error all probs fall back to 1, so the card would equal raw obligation — misleading |
| `gainPct = 0` when `entryPremium = 0` | Clamped to 0, shows red | Degenerate case; documented as known limitation |
| Row key in position table | `p.symbol` | Unique per option contract; more stable than array index under `marketData` re-renders |
| AbortController on `fetchMarketData` | Yes, via `abortCtrlRef` | Prevents stale response from earlier upload overwriting newer one on rapid re-upload |
| Application ports | frontend 5430, backend 5431, postgres 5432 | Consolidate onto a consistent port range; avoid conflicts with common dev defaults (3000/3001) |
| Spread obligation matching key | `ticker\|\|expiryLabel` (no qty) | Butterflies have short qty = 2× long qty; excluding qty from the key lets the algorithm match across asymmetric structures |
| Spread obligation allocation order | Higher-strike long puts first (zero obligation), then lower-strike | Higher-strike long put assignment = profitable (sell at L > buy-at-K); allocating those first minimises obligation correctly |
| `API_URL` constant | `''` (empty string) | All other pages use relative `/api` paths through the Vite proxy / nginx; hardcoded `http://localhost:5431` broke access from any non-localhost client |
| RSI batch fetch strategy | Single `yf.download()` call for all tickers | Per-ticker parallel downloads (5 workers) triggered Yahoo Finance rate limiting (`YFRateLimitError`), returning null for every ticker and silently breaking weighted obligation |

## Open Questions / Blockers
- [ ] Should `gainPct = 0` (no recorded entry premium) show as red or as `—`? Currently shows as red `0.0%` — could confuse a position with missing data for a losing trade.
- [ ] Banner uses emoji spinner (`⏳`) — consider replacing with a CSS spinner for better screen-reader experience (`aria-hidden` on decorative emoji).
- [ ] Liquid Coverage card lost the "Sufficient / Below 1:1" qualitative label — replaced by adjusted coverage %. Worth adding back as a second sub-line?
- [ ] Call spread obligation is not tracked — Iron Condor call wing (e.g. short 764C / long 770C) does not appear in any obligation figure. If call-side risk tracking is desired, `parsePortfolioCSV` needs a parallel pass for short calls.
- [ ] Even with batched `yf.download`, Yahoo Finance may still rate-limit if the endpoint is hit repeatedly in quick succession (e.g. rapid CSV re-uploads). Consider adding a short TTL cache (e.g. 60s) on `fetch_rsi_batch` results to avoid redundant calls.

## Progress Log
- 2026-05-17 — Feature designed and specced (`docs/superpowers/specs/2026-05-17-margin-assignment-confidence-design.md`)
- 2026-05-17 — Implementation plan written (`docs/superpowers/plans/2026-05-17-margin-assignment-confidence.md`)
- 2026-05-17 — All 8 tasks implemented and reviewed via subagent-driven development. 19/19 backend tests pass, frontend build clean (97 modules, 312 kB).
- 2026-05-17 — Port reassignment across 10 files: frontend 5430, backend 5431, postgres 5432 (unchanged). Context files updated to match.
- 2026-05-17 — `context/margin.md` created (this file); `context/_active.md` updated to point here.
- 2026-06-02 — Fixed spread-aware obligation in `parsePortfolioCSV`: two-pass parser now matches long puts by `ticker||expiryLabel` (no qty), allocates higher-strike long puts first (zero obligation) then lower-strike ones. Handles Iron Condor (equal qty) and Put Butterfly (short qty = 2× long qty). Verified against real portfolio CSV: SPXW butterfly $4,566,000 → $3,000; total obligation $5,726,650 → $1,163,650. Also fixed `API_URL` constant from `http://localhost:5431` to `''` so market data fetch works from non-localhost clients.
- 2026-06-22 — Fixed delta-based margin bug: confidence-adjusted weighted obligation was showing identical values to raw obligation. Root cause was `_fetch_rsi_from_yfinance` in `price_fetcher.py` using per-ticker parallel `yf.download()` calls (5 ThreadPoolExecutor workers), which triggered Yahoo Finance rate limiting (`YFRateLimitError`) on every ticker. All prices returned null → `assignmentProb` null → fallback `prob ?? 1` → weighted = raw. Fix: replaced parallel per-ticker downloads with a single batched `yf.download(all_tickers)` call. Verified working after backend restart.

## Current State (Resume Here)
Branch `bug/deltabasedmargin` has an uncommitted fix to `backend/app/services/price_fetcher.py`. The `_fetch_rsi_from_yfinance` function was rewritten from parallel per-ticker `yf.download()` calls (via `ThreadPoolExecutor`) to a single batched `yf.download(all_tickers, group_by="ticker")` call. This avoids Yahoo Finance rate limiting that was causing all prices to return null, which broke the delta-based weighted obligation calculation (every position fell back to `prob = 1`, making weighted obligation identical to raw obligation).

**How weighted obligation actually works (for reference):**
- IV comes from the CSV (column 14), stock price comes from `/api/market/rsi` endpoint
- `bsPutAssignmentProb(price, strike, DTE/365, IV)` computes `N(-d1)` (Black-Scholes put delta = assignment probability)
- `weightedObligation = obligation × prob`
- RSI is display-only (colored pill in position table) — not used in the calculation

**What changed this session:**
- `backend/app/services/price_fetcher.py` — `_fetch_rsi_from_yfinance()` rewritten: single batched `yf.download()` with MultiIndex DataFrame handling for multi-ticker responses. `_fetch_one_rsi()` still exists (unused by batch path, kept for potential single-ticker use).

**Next action:** Commit the `price_fetcher.py` fix on this branch, then decide whether to merge into `master` or open a PR.
