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
- Out of scope:
  - Server-side probability storage or history
  - Live options chain IV (uses IV from CSV snapshot)
  - Multi-leg positions or spreads
  - Probability decay over time (static DTE-based snapshot only)

## Key Files / Modules Involved
- `backend/app/services/price_fetcher.py` — `_fetch_one_rsi` returns `{rsi, price}` dict
- `backend/app/routers/market.py` — return type annotation updated
- `backend/tests/test_price_fetcher.py` — 4 new tests for dict return shape
- `extension/content.js` — `fetchRsiForAll` reads `val.rsi` not bare float
- `extension/background.js` — default API URL updated to 5431
- `extension/popup/popup.js` — default API URL updated to 5431
- `extension/popup/popup.html` — placeholder URL updated to 5431
- `frontend/src/pages/MarginDashboardPage.tsx` — all frontend changes
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

## Open Questions / Blockers
- [ ] Should `gainPct = 0` (no recorded entry premium) show as red or as `—`? Currently shows as red `0.0%` — could confuse a position with missing data for a losing trade.
- [ ] Banner uses emoji spinner (`⏳`) — consider replacing with a CSS spinner for better screen-reader experience (`aria-hidden` on decorative emoji).
- [ ] Liquid Coverage card lost the "Sufficient / Below 1:1" qualitative label — replaced by adjusted coverage %. Worth adding back as a second sub-line?

## Progress Log
- 2026-05-17 — Feature designed and specced (`docs/superpowers/specs/2026-05-17-margin-assignment-confidence-design.md`)
- 2026-05-17 — Implementation plan written (`docs/superpowers/plans/2026-05-17-margin-assignment-confidence.md`)
- 2026-05-17 — All 8 tasks implemented and reviewed via subagent-driven development. 19/19 backend tests pass, frontend build clean (97 modules, 312 kB).
- 2026-05-17 — Port reassignment across 10 files: frontend 5430, backend 5431, postgres 5432 (unchanged). Context files updated to match.
- 2026-05-17 — `context/margin.md` created (this file); `context/_active.md` updated to point here.

## Current State (Resume Here)
All implementation is complete and committed on branch `develop`. The `superpowers:finishing-a-development-branch` skill was invoked, tests verified (19/19 pass), and options were presented. **The merge/PR decision was not made — session ended before the user chose.**

Next step: Re-invoke `superpowers:finishing-a-development-branch` (or manually run the appropriate git commands). Choose one of:
1. `git checkout master && git pull && git merge develop` — merge locally
2. `git push -u origin develop && gh pr create` — open a PR
3. Keep `develop` as-is
