# Feature: Schwab Hardening (Part 4 of 5)

## Goal
Turn a lapsed Schwab refresh token into a labelled "market data offline" mode instead of a blackout:
- an admin expiry banner;
- every non-market feature keeps working;
- a CLI re-auth recovers without a restart;
- all market data goes through one provider boundary.

## Scope
**In:**
- the provider interface and factory;
- offline detection and recovery;
- the admin status endpoint (+ `/api/me`);
- router degradation (503s, null fields + flag, stale caches);
- scheduler and engine behaviour;
- the SPA banner and dashes;
- the extension notice;
- tests, docs.

**Out:**
- in-app Reconnect, OAuth callback, HTTPS, login (Part 5);
- a second provider, normalised shapes, yfinance behind the interface;
- notifications, cloud, queues;
- signal scoring, the slot state machine, chain scoring.

## Key Files
- **Spec:** `docs/superpowers/specs/2026-11-04-schwab-hardening-design.md` (inventory, endpoint table, checklist
  results)
- **Plan:** `docs/superpowers/plans/2026-11-04-schwab-hardening.md`
- **Backend, provider and boundary:**
  - new: `app/services/market_data.py` (Protocol, `get_market_data`, `market_data_offline[_now]`,
    `compute_state`, `prime_market_data`) and `app/services/market_data_errors.py` (`MarketDataUnavailable`);
  - `app/services/schwab_client.py`: offline state, ≤1/min token-row recheck, `status()`, `is_offline()`,
    `refresh_offline_state()`; `get_schwab_client` removed;
  - `app/config.py`: `market_data_provider` and its validator.
- **Backend, endpoints:**
  - `app/deps.py`: `require_admin`, `market_data_flag`;
  - new routers `app/routers/market_data.py` (status) and `app/routers/me.py`, with schemas `market_data.py`
    and `user.py`;
  - `app/main.py`: 503 handler, CORS `expose_headers`, lifespan priming.
- **Backend, services and routers:**
  - services: `price_fetcher`, `technicals_fetcher`, `cc_signal`, `cc_timing_signal`, `sp_timing_signal`,
    `chain_screener`, `screener_fetcher`, `alert_engine`, `signal_engine`;
  - `app/scheduler.py`;
  - routers: `trades`, `wheel`, `dashboard`, `positions`, `screener`, `chain`, `signals`;
  - schemas: `trade`, `wheel`, `dashboard`, `screener` (flags).
- **Tests:**
  - new `tests/test_market_data_provider.py` and `tests/test_market_data_offline.py`;
  - patch targets renamed in `test_{technicals_fetcher,price_fetcher,chain_screener,screener_fetcher,sp_timing_signal,cc_timing_signal,cc_signal}.py`.
- **Frontend:**
  - `src/api/client.ts` (code, header, offline store), `src/api/marketData.ts`;
  - `src/context/MarketDataContext.tsx`, `src/hooks/useMarketDataOffline.ts`;
  - `src/components/MarketData/MarketDataBanner.tsx`, `src/components/shared/MarketDash.tsx`, `PnLDisplay.tsx`;
  - `App.tsx`, `WheelDashboardPage.tsx`, `TradeDetailPage.tsx`, `ChainPage.tsx`, `MarginDashboardPage.tsx`;
  - `Spreads/SpreadSessionCard.tsx`, `Screener/ScreenerTable.tsx`, `types/index.ts`.
- **Extension:** `background.js` (`marketDataOffline`), `content.js` (`setMarketDataOffline`,
  `renderMarketDataNotice`), `content.css`.
- **Docs:** `README.md` (Market Data), `docs/TradeMinder-Context.md` §5.

## Decisions Made
| Decision | Reason |
|---|---|
| Banner: > 72h none · 72–24h amber "expires in N days" · < 24h red with hours · expired or refresh failing red "Market data offline. Run scripts/schwab_auth.py." · admins only | Given in the brief |
| While offline, non-market features keep working; market fields show "—" with a "Market data offline" tooltip | Given in the brief |
| One provider interface with today's return shapes; normalising is deferred | Given in the brief: a future provider is a swap |
| Stacked on Part 3 (`b26ec00`), built in a worktree | Parts 1–3 aren't in develop; the live dev backend reloads from the main checkout |
| `schwab_client.py` stays where it is as the Schwab implementation; `market_data.py` is the boundary; errors in their own module | No import-path change for `test_schwab_client.py`; avoids an import cycle |
| `MarketDataUnavailable` and `SchwabAPIError` don't inherit from each other; broad `except` blocks re-raise the offline error | Per-ticker handlers must never swallow "offline" |
| Offline on expiry, `invalid_grant` (400/401), no tokens or no key/secret; a transient refresh failure is not offline | Only an expired or rejected grant needs a human |
| No-tokens keeps raising `SchwabAPIError("No Schwab tokens…")` on the first call, but marks the provider offline | `test_schwab_client.py` pins that type, and the brief only allows import-path edits there |
| The token row's `(updated_at, refresh_expires_at)` is re-read at most once a minute, online and offline; a change → reload + online | The CLI's upsert sets `updated_at = NOW()`; no migration needed; an edited expiry also shows in the banner |
| Mixed endpoints flag offline with an `X-Market-Data-Offline` header (+ a `market_data_offline` body field on object responses) | Most mixed responses are bare lists or maps; changing their shape would break the SPA and the extension |
| Mixed endpoints blank the stored prices (not served stale) | The brief says market fields null for mixed endpoints; stale serving is for cached signals and technicals |
| Screener list is served stale (`stale: true`, as of `last_fetched_at`) rather than nulled | It is a server-side cache of market data, which the brief says to serve stale |
| Adding a screener symbol works offline (no data); single fetch returns 503; fetch-all stops without touching rows | Tracking needs no market data; an offline refresh used to wipe stored metrics |
| Signal rules return True/False/None; None never flips a signal; price rules skipped offline | "Deactivation only on real evaluated data" |
| `GET /api/me` added | The SPA had no way to know the role, and Part 5 needs it anyway |
| WHEEL page doesn't cache stale results client-side; the throttle is untouched | Avoids showing stale data for an hour after recovery |

## Open Questions
1. **Live token** expires 2026-11-06 16:17 UTC. The live banner will be amber as soon as this ships; re-run
   `scripts/schwab_auth.py` soon.
2. **Offline request queue on WHEEL.** The page still sends its whole throttled queue while offline. Each request
   is an instant 503 with no Schwab traffic. It could stop the queue on the first offline response if that
   matters.
3. **Write endpoints still return stored prices** offline: trade create, close and patch. The SPA reloads lists
   afterwards, so this hasn't shown up.
4. Parts 1–4 are all unmerged and stacked.

## Progress Log
- 2026-11-04:
  - Branch and worktree created (stacked on Part 3).
  - Inventory by a read-only agent.
  - Provider boundary, offline detection, status and me endpoints, router degradation, scheduler and engines,
    frontend banner and dashes, extension notice.
  - 50 new tests. Suite 450 passed / 6 known failures; `tsc` has only the 2 pre-existing errors.
  - Manual checklist 5/5 on a DB copy (2d / 10h / expired / re-auth recovered in 45s), results in the spec.
  - Sandbox torn down; the live DB and token row are untouched.
- 2026-11-04: Switched the main checkout to the branch for user testing. The user checked the live app (amber
  banner, ~40h left) and approved it; they'll watch the real expiry on Nov 6 to see offline mode.
- 2026-11-04: Committed Part 4 and merged Parts 1–4 into `develop` (local, `--no-ff`, one merge commit per part,
  in order). Not pushed.

## Current State
**Parts 1–4 are merged into local `develop` (not pushed). The main checkout is on `develop`.**

- **Branches:**
  - `develop` = the previous `4872ac1` plus four `--no-ff` merges: `feature/multi-account-foundation`,
    `feature/account-container-ui`, `feature/extension-account-awareness`, `feature/schwab-hardening`.
  - `origin/develop` is behind: it doesn't even have `4872ac1`. Nothing has been pushed; the feature branches
    exist only locally.
- **Live environment:**
  - The dev servers (5430/5431) serve `develop` (same code as Part 4) against the live DB at revision 017.
  - Backups: `backups/trademinder-pre-016-*.dump` and `backups/trademinder-pre-017-20261104-1233.dump`.
- **Verification:** pytest 450 passed / 6 known failures; `tsc -b` only the 2 pre-existing errors; Part 4 manual
  checklist 5/5 on a DB copy; user-tested live.
- **Still open:**
  - The live Schwab refresh token expires 2026-11-06 16:17 UTC. The user plans to let it lapse to watch offline
    mode on real data, then run `scripts/schwab_auth.py` (recovery within a minute, no restart).
  - Part 3: the remaining real-page checks (Reconcile scoping, All-view chips, extension reinstall).
  - Fingerprint strength (Part 3 Open Question 3).

**Single next action:** push `develop` to origin (and, per the branching rule, merge `develop` → `master` when
the user decides to release). Then start Part 5 (login/OAuth + HTTPS + in-app Schwab Reconnect) off `develop`.
