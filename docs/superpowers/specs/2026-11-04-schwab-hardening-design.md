# Schwab Hardening — Part 4 of 5 (Design)

**Date:** 2026-11-04 · **Branch:** `feature/schwab-hardening` · **Depends on:** Parts 1–3

## Goal

A lapsed Schwab refresh token becomes a clearly labelled "market data offline" mode instead of a blackout:
- the admin sees an expiry banner ahead of time;
- every non-market feature keeps working;
- re-running `scripts/schwab_auth.py` restores market data without a restart;
- all market data goes through one provider interface.

Not in scope: the in-app Reconnect button, OAuth callback, HTTPS (Part 5), login (Part 5), a second provider,
normalised return shapes, yfinance.

## Repo reality vs. the brief

1. **Parts 1–3 are not merged.** `develop` is still `4872ac1`, so this branch is stacked on
   `feature/extension-account-awareness` (`b26ec00`). It was built in the worktree `.claude/worktrees/schwab-hardening`,
   because the user's dev backend reloads from the main checkout against the live DB, and a half-done provider
   refactor there would break the running app.
2. **shadcn is not installed.** The banner uses Tailwind and lucide-react, like the Part 2 UI.
3. **The SPA had no way to know the user's role.** `GET /api/me` was added through the current-user seam, so the
   status endpoint is only polled for admins.
4. **The extension has no sidebar and no signal dots.** As of Part 3, nothing in `content.js` renders
   `active_signals`. The "Market data offline" notice goes in the TradeMinder toolbar next to the account
   indicator, and "render badges without signal dots" needs no change.
5. **No migration.** Offline detection compares `schwab_tokens.updated_at` and `refresh_expires_at`. The CLI's
   upsert already sets `updated_at = NOW()`.
6. **The 4-concurrent throttle lives in the frontend.** It is `SIGNAL_FETCH_CONCURRENCY = 4` with
   `runWithConcurrency` in `WheelDashboardPage.tsx`, and it is unchanged. The backend has no throttle besides the
   RSI batch's `ThreadPoolExecutor(max_workers ≤ 10)`, also unchanged.
7. **Bugs on the offline path, fixed here:**
   - **Price refresh silently did nothing.** `refresh_open_trades` called Schwab synchronously on the event
     loop, where the token load's `asyncio.run` fails and the error was swallowed. It now runs in an executor.
   - **Screener data was wiped.** An offline screener refresh overwrote every stored metric with NULL. The
     fetcher now raises the offline error and callers leave rows alone.
   - **Signal errors were cached.** Signal endpoints returned 200 error payloads that the WHEEL page cached for
     an hour. Offline is now a 503, and stale results are not cached client-side.
   - **Three technicals endpoints answered 500.** They now return 503 offline, because only `SchwabAPIError`
     was caught before.
8. **Missing tokens keep their old error type.** `test_schwab_client.py` pins "no tokens" to
   `SchwabAPIError("No Schwab tokens…")`, and the brief only allows import-path edits to that file. So the first
   call still raises that, but the provider is marked offline, and later calls raise `MarketDataUnavailable`.

## Inventory: every module that imported or called SchwabClient (before the refactor)

| Module | What it called | Reached from |
|---|---|---|
| `services/schwab_client.py` | defines `SchwabClient`, `get_schwab_client()`, `SchwabAPIError` | — |
| `services/price_fetcher.py` | `get_quotes` (`_fetch_prices_from_schwab`, `fetch_quote`), `get_price_history` (`_fetch_rsi_from_schwab`) | scheduler `price_refresh_job`; `POST /api/market/refresh`; `GET /api/market/quote/{t}`; `POST /api/market/rsi` |
| `services/technicals_fetcher.py` | `get_price_history`, `get_quotes` (`_append_live_bar`) | `GET /api/market/technicals`, `/macd-crossover`, `/rsi-crossover`, `/volume-spikes`; cc_signal, cc/sp timing, screener fetcher |
| `services/cc_signal.py` | `get_quotes`, `get_option_chain` ×2 (CALL+PUT, strikeCount 30), `fetch_option_mid` (±3-day expiry match) | `/api/market/cc-signal`, `/sp-signal`, `/combined-signal`, `/option-price` |
| `services/cc_timing_signal.py` | `get_option_chain` CALL | `/api/market/cc-timing-signal` |
| `services/sp_timing_signal.py` | `get_option_chain` PUT | `/api/market/sp-timing-signal`; chain screener |
| `services/chain_screener.py` | `get_option_chain` | `GET /api/chain/{ticker}` |
| `services/screener_fetcher.py` | `get_quotes`, `get_option_chain`, `get_instrument_fundamentals` | screener preview / add / fetch / fetch-all |
| Tests | `test_schwab_client.py`, `test_schwab_client_fundamentals.py` (the client itself); `test_{technicals_fetcher,price_fetcher,chain_screener,screener_fetcher,sp_timing_signal,cc_timing_signal,cc_signal}.py` patched `<module>.get_schwab_client` | — |

**After the refactor:**
- The seven service modules import `get_market_data`, `MarketDataUnavailable` and `SchwabAPIError` from
  `app.services.market_data`.
- Their test patch targets are now `<module>.get_market_data`. `test_schwab_client.py` is unchanged; its import
  path didn't move.
- `test_only_the_provider_module_imports_schwab_client` fails if anything outside `market_data.py` /
  `schwab_client.py` imports the Schwab module or names `SchwabClient`.

## Design

**Provider boundary** (`app/services/market_data.py`):
- `MarketDataProvider` is a Protocol: `get_quotes`, `get_price_history`, `get_option_chain`,
  `get_instrument_fundamentals`, `is_offline()` (no I/O), `refresh_offline_state()`, and `status()` returning a
  `ProviderStatus`.
- `get_market_data()` is the factory singleton. `settings.market_data_provider` defaults to `schwab`, and a
  pydantic validator rejects unknown names at startup.
- `market_data_offline_now()` is the async helper for endpoints and the scheduler. While offline, it re-reads
  the token row in an executor, at most once a minute.
- `compute_state()` derives the banner state.
- `prime_market_data()` runs in the lifespan, so token expiry is known before the first market call.
- Errors live in `market_data_errors.py` to avoid an import cycle.
- Every Schwab workaround stays inside `schwab_client.py` or the services where it lived: CALL/PUT split, ±3 days,
  `SchwabAPIError` for non-optionable symbols, the live bar, and the caches. The throttle stays in the frontend.

**Offline detection** (`SchwabClient`):

| Trigger | Result |
|---|---|
| Refresh token past `refresh_expires_at` | offline |
| Refresh answered 400/401 `invalid_grant` | offline |
| No tokens, or no app key/secret | offline |
| Transient refresh failure (5xx, network) | not offline: `SchwabAPIError` |

- While offline every call raises `MarketDataUnavailable` without touching Schwab.
- The token row's `(updated_at, refresh_expires_at)` marker is re-read at most once a minute (also while online,
  so a re-auth or an edited expiry is picked up). A changed row reloads the tokens and clears offline.
- Each transition is logged once with `log.warning`. The "< 24h left" warning is logged once per token, not per
  request.
- `last_error` is a short message with no tokens and no response bodies. `last_success_at` is set on each 200.

**Banner state:**

| Hours left (h) | State |
|---|---|
| h > 72 | `ok` |
| 24 ≤ h ≤ 72 | `expiring` |
| 0 < h < 24 | `critical` |
| h ≤ 0, or offline | `offline` |

The boundaries (72 and 24 both amber) follow the brief's "72 down to 24" and "under 24".

**Status endpoint.** `GET /api/market-data/status` (admin via `require_admin`) returns provider, state,
refresh_expires_at, hours_remaining (negative once expired), last_success_at and last_error.

## Endpoint behaviour while offline

| Endpoint | Kind | Offline behaviour |
|---|---|---|
| `GET /api/market/quote/{t}` | pure | 503 `market_data_offline` (was 404) |
| `POST /api/market/rsi` | pure | 503 (was all-null) |
| `GET /api/market/technicals/{t}`, `/macd-crossover`, `/rsi-crossover`, `/volume-spikes` | pure | 503 (the last three used to answer 500) |
| `GET /api/market/combined-signal`, `/cc-signal`, `/sp-signal` | pure, cached 4h | the last good cached result (any age) with `stale: true`, `as_of`; no cache → 503 |
| `GET /api/market/cc-timing-signal`, `/sp-timing-signal` | pure, cached 4h | same: stale cache or 503 (also with `?refresh=true`) |
| `GET /api/market/option-price/{t}` | pure | 503 |
| `GET /api/chain/{t}` | pure | 503 (was 502) |
| `GET /api/screener/preview/{t}`, `POST /api/screener/{s}/fetch` | pure | 503; stored row untouched |
| `POST /api/market/refresh` | pure trigger | 503; stored prices untouched |
| `POST /api/screener/fetch-all` | background job | stops at the first offline symbol with error "Market data offline"; no row touched |
| `POST /api/screener` (add) | DB + market | still adds the symbol: no data, `fetch_status: error`, `last_fetched_at` null |
| `GET /api/trades`, `GET /api/trades/wheel/{id}` | mixed | DB rows; `current_price`, `unrealized_pnl` null; header `X-Market-Data-Offline: true` |
| `GET /api/trades/{id}` | mixed | the same plus `market_data_offline: true` in the body; `last_price_at` kept |
| `GET /api/wheel/{session_id}` | mixed | slots/legs/premium logs; `stock_current_price` and each leg's `trade_current_price` null; header + body flag. Wheel write endpoints that return a session detail blank these too (cached state, no header) |
| `GET /api/wheel/active-slots` | mixed (no market fields) | unchanged data + header (drives the extension notice) |
| `POST /api/positions/status` | mixed (rationale snapshot, alerts and signal rows are DB data) | unchanged data + header |
| `GET /api/dashboard/summary` | mixed (no market fields) | unchanged data + header + `market_data_offline: true` |
| `GET /api/screener` | cached market data | stored metrics served as-is, each row `stale: true` (as of `last_fetched_at`) + header |
| `POST /api/market/signals/refresh` | DB-only | runs with price rules skipped |
| `GET /api/market/options/{t}` (yfinance scanner) | not market-data-provider | unaffected |
| Journal, commentary, wheels/slots/resolves, sessions, accounts, categories, Reconcile, alerts | DB | unaffected |

- Mixed responses never write back. Fields are blanked on response models, not on ORM rows.
- Write endpoints that return a trade (create, close, patch) still return the stored price. The SPA reloads lists
  afterwards.
- The header is exposed via CORS (`expose_headers`), so the extension's service worker can read it.

## Scheduler and engines

- `scheduler.market_offline()` logs once on entering and once on leaving an offline period.
- `price_refresh_job` is skipped while offline. If it goes offline mid-run, stored prices stay untouched.
- **Alert engine:** `run(…, market_offline=True)` skips the price/P&L rules (profit target, stop loss,
  assignment risk, deep ITM). DTE, earnings and overdue review keep running.
- **Signal engine:** `run(…, market_offline=True)` skips the price rules (`above_ma200`, `below_ma200`).
- **Signal rules return True, False or None.** None means missing inputs or an exception, and leaves the signal
  as it is. Deactivation happens only on a real evaluation (False). Previously missing data deactivated
  signals.

## Frontend

- **`apiFetch`:** parses `code` into `ApiError.code` and adds `isMarketDataOffline(err)`. It reads
  `X-Market-Data-Offline` into a small global store (`setMarketDataOffline`), read via the
  `useMarketDataOffline()` hook.
- **Status polling:** `MarketDataProvider` fetches `/api/me`, then (admins only) `/api/market-data/status` at
  start and every 15 minutes.
- **`MarketDataBanner`:** in the app shell above page content. Amber is dismissible for the session (keyed by
  expiry, in sessionStorage); red is not.
- **Dashes:** `MarketDash` and `staleTooltip`. The WHEEL page's price, change, RSI, MACD, P&L and gain/loss
  cells, signal badges, trade tables, trade detail and spreads price signal show "—" or "Market data offline"
  with the tooltip.
- **Stale values:** stale signal badges are dimmed with "Market data offline · as of …". Stale screener rows are
  dimmed with the same tooltip.
- **Chain page:** "Market data offline — the option chain is unavailable…".
- **Margin page:** the CSV analysis still works, with an "offline" message for the probability columns.
- **WHEEL client cache:** stale results are not stored in the 1h client cache. The 4-concurrent throttle is
  untouched.

## Extension

- **Service worker:** `apiFetch` returns `marketDataOffline` from the header, or from a 503 with the code.
- **Content script:** `bgFetch` → `setMarketDataOffline` → `renderMarketDataNotice()` shows a red "Market data
  offline" pill after the account indicator. It goes away when a later response says online.
- Every other overlay feature is unchanged.

## Manual verification checklist

On a copy of the live DB (`trademinder_p4test`, the real Schwab keys, backend :5462, SPA :5464, the extension
fixture from Part 3 replaying the fresh Nov captures), by editing `schwab_tokens`:

1. **Refresh expiry 2 days out:**
   - the admin banner is amber, "expires in 2 days", and dismissible;
   - the dismissal persists for the session;
   - market data still works.
2. **10 hours out:** the banner is red, "expires in 10 hours", and not dismissible.
3. **Expiry in the past:**
   - the red "Market data offline. Run scripts/schwab_auth.py." banner shows;
   - the WHEEL, Trades and Dashboard pages render with dashes and the offline tooltip, with no error screens;
   - adding commentary, a slot resolve and Reconcile work;
   - the extension shows the offline notice;
   - the backend logs offline once and makes no Schwab calls.
4. **The CLI re-auth** (same row write as `schwab_auth.py`: new expiry + `updated_at = NOW()`): market data is
   back within a minute without a restart, and the extension notice clears.
5. pytest passes apart from the known failures; `tsc -b` adds no errors.

### Results (2026-11-04)

| # | Result |
|---|---|
| 1 | Pass. Banner: "Schwab connection expires in 2 days. Run scripts/schwab_auth.py to renew.", amber, `role=status`, Dismiss button present. Dismissed, it stayed hidden after a reload. A live AAPL quote returned 200. |
| 2 | Pass. "Schwab connection expires in 10 hours…", red, `role=alert`, no Dismiss button. |
| 3 | Pass. Banner: "Market data offline. Run scripts/schwab_auth.py." WHEEL rendered 68 rows, with all 472 market cells showing "—" and the "Market data offline" tooltip. Trades rendered 149 rows with 131 offline P&L dashes. The Dashboard rendered without an error screen. Commentary add returned 201, slot resolve 200 (`put_expired_otm` → `awaiting_sold_put`), Reconcile 200. Trade detail had `current_price`/`unrealized_pnl` null and `market_data_offline: true`. The extension fixture (All view) showed "Market data offline" next to the account indicator, with all badges still rendering. The backend log has exactly one "Market data offline (Schwab)" line across 548 answered 503s, and no "Refreshing Schwab access token" lines (no Schwab calls). |
| 4 | Pass. 45 seconds after the row write, `GET /api/market/quote/AAPL` returned 200 again, with no restart. The log shows one "Market data back online (Schwab): token row changed". The status returned to `expiring`, with `last_success_at` set. The extension notice cleared on the next status call. |
| 5 | Pass. pytest: 450 passed / 6 known failures (`test_cc_signal.py` ×4, `test_market_router_p2.py::test_prefetch_still_501`, `test_schwab_client.py::test_schwab_alias_maps_spx`). `tsc -b`: only the 2 pre-existing unused-symbol errors. |

**Notes:**
- The real `scripts/schwab_auth.py` needs the user's interactive Schwab login, so step 4 replayed its exact row
  write.
- The sandbox's own refresh never touched the live DB, and the live token row is unchanged (`updated_at`
  21:07:40).
- While offline, the WHEEL page still issues its whole throttled request queue. Each request gets an instant 503
  with no Schwab call, so this was left as is.
- No stale signal badges appeared in the run, because the fresh sandbox process had no cached signals. Stale
  serving is covered by pytest.
- **Live token:** at the time of the run it expires 2026-11-06 16:17 UTC (~42h). The banner on the user's app will
  be amber once this ships.
