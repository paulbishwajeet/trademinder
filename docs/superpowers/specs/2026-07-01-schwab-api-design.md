# Schwab API Integration Design

**Date:** 2026-07-01
**Branch:** feature/technicals
**Status:** Approved, ready for implementation

## Goal

Replace yfinance as the data source for technicals, CC signal, and trade price refresh with the Schwab Developer REST API. yfinance rate-limiting causes unreliable results at 19+ wheel tickers. Schwab provides real-time quotes, price history, and options chains via a stable authenticated API.

## Scope

**In scope:**
- `technicals_fetcher.py` — price history (daily + weekly closes) via Schwab
- `cc_signal.py` — live price + options chain (IV percentile) via Schwab
- `price_fetcher.py` — batch quotes and RSI history via Schwab
- OAuth token persistence in Postgres (single `schwab_tokens` row)
- One-time CLI auth script (`scripts/schwab_auth.py`)
- CC signal column on Wheel Dashboard UI (grade chip + IV percentile per session)

**Out of scope:**
- `options_scanner.py` — stays on yfinance
- Earnings dates — `_get_next_earnings()` in `technicals_fetcher.py` stays on `yf.Ticker().calendar`
- Any automated token refresh reminders (just a log warning)

## Architecture

```
CLI auth script (one-time)
        │
        ▼
schwab_tokens (Postgres, id=1)
        │
        ▼
SchwabClient (backend/app/services/schwab_client.py)
  ├── get_quotes(tickers)
  ├── get_price_history(ticker, ...)
  └── get_option_chain(ticker, ...)
        │
        ├──▶ technicals_fetcher.py  (unchanged signatures)
        ├──▶ cc_signal.py           (unchanged signatures)
        └──▶ price_fetcher.py       (unchanged signatures)
                                            │
                                            ▼
                                   market.py router  (untouched)
                                            │
                                            ▼
                                   WheelDashboardPage.tsx
                                   (new CC signal column)
```

## Section 1: Data Layer

### New model: `backend/app/models/schwab_token.py`

Single-row table — `id=1` always. Upserted by the CLI auth script, read/written by `SchwabClient`.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | always 1 |
| `access_token` | text | ~30 min TTL |
| `refresh_token` | text | 7-day rolling TTL |
| `access_expires_at` | timestamptz | refresh when within 5 min of expiry |
| `refresh_expires_at` | timestamptz | log warning when within 24h |
| `updated_at` | timestamptz | for debugging |

### New migration: `backend/alembic/versions/009_schwab_tokens.py`

Creates `schwab_tokens` table. No data dependencies; standalone migration.

## Section 2: SchwabClient

**File:** `backend/app/services/schwab_client.py`

### Initialization

- Module-level singleton (`_schwab_client: SchwabClient | None = None`, lazy init via `get_schwab_client()`)
- Reads `SCHWAB_APP_KEY` + `SCHWAB_APP_SECRET` from env
- Uses `httpx.Client` (sync — all callers already run in thread executor via `loop.run_in_executor`)

### Token Refresh

Called before every API request:

```
if access_expires_at - now < 5 min:
    POST /v1/oauth/token  grant_type=refresh_token
    write new tokens to DB (id=1 upsert)
if refresh_expires_at - now < 24h:
    log.warning("Schwab refresh token expires soon — re-run scripts/schwab_auth.py")
```

### Public Methods

```python
def get_quotes(tickers: list[str]) -> dict[str, dict]:
    # GET /marketdata/v1/quotes?symbols=AAPL,MSFT&fields=quote
    # Returns {ticker: {lastPrice, closePrice, ...}}

def get_price_history(
    ticker: str,
    period_type: str,   # "year", "month", "day", "ytd"
    period: int,
    frequency_type: str, # "daily", "weekly"
    frequency: int,
) -> pd.DataFrame:
    # GET /marketdata/v1/pricehistory?symbol=...
    # Returns DataFrame with DatetimeIndex and "Close" column

def get_option_chain(
    ticker: str,
    contract_type: str = "CALL",
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    # GET /marketdata/v1/chains?symbol=...&contractType=CALL
    # Returns raw Schwab chain response dict
```

### Error Handling

- Custom `SchwabAPIError(Exception)` raised on any HTTP error or auth failure
- Service files catch `SchwabAPIError` and return their existing `{"fetch_status": "error", "fetch_error": str(exc)}` shape
- No change visible to callers

### Index Symbols

Schwab uses different notation for indices. The `_YF_ALIASES` map in `price_fetcher.py` is replaced with a `_SCHWAB_ALIASES` map inside `SchwabClient.get_quotes()`:

```python
_SCHWAB_ALIASES = {
    "SPX":  "$SPX.X",
    "SPXW": "$SPX.X",
    "XSP":  "$XSP.X",
    "NDX":  "$NDX.X",
    "RUT":  "$RUT.X",
    "VIX":  "$VIX.X",
}
```

## Section 3: CLI Auth Script

**File:** `scripts/schwab_auth.py`

**Run once manually** (outside Docker) any time before the 7-day refresh token expires.

**Flow:**

1. Load `.env` via `python-dotenv` — reads `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`, `DATABASE_URL`
2. Build Schwab authorize URL:
   `https://api.schwabapi.com/v1/oauth/authorize?response_type=code&client_id=<key>&redirect_uri=https://127.0.0.1:8765/callback&scope=readonly`
3. Print URL + open in browser (`webbrowser.open`)
4. Start minimal `http.server` on port **8765**, capture `?code=...` from the redirect
5. POST to `https://api.schwabapi.com/v1/oauth/token`:
   - `grant_type=authorization_code`, `code=<captured>`, `redirect_uri=https://127.0.0.1:8765/callback`
   - Basic auth: `SCHWAB_APP_KEY:SCHWAB_APP_SECRET`
6. Parse response: `access_token`, `refresh_token`, `expires_in` (seconds)
7. Upsert `schwab_tokens` row (`id=1`) directly via `psycopg2`
8. Print: `"Tokens stored. Access token expires at <time>. Refresh token expires at <time>."`

**Prerequisites:**
- Update Schwab developer portal callback URL from `https://127.0.0.1:8080/callback` to `https://127.0.0.1:8765/callback`
- Run from project root with venv active: `python scripts/schwab_auth.py`

## Section 4: Service File Rewrites

All existing function signatures are preserved. `market.py` is untouched.

### `technicals_fetcher.py`

| Was (yfinance) | Becomes (Schwab) |
|---|---|
| `yf.download(ticker, period="200d", interval="1d")` | `schwab_client.get_price_history(ticker, "year", 1, "daily", 1)` |
| `yf.download(ticker, period="2y", interval="1wk")` | `schwab_client.get_price_history(ticker, "year", 2, "weekly", 1)` |
| `yf.Ticker(ticker).calendar` | unchanged — stays on yfinance |

All downstream computation (RSI, Bollinger, MACD, MAs, sentiment) is untouched.

### `cc_signal.py`

`_compute_fresh()` and `_compute_iv_percentile_from_ticker()` are rewritten:

| Was (yfinance) | Becomes (Schwab) |
|---|---|
| `yf.Ticker(ticker)` object `t` | eliminated |
| `t.fast_info.last_price` | `schwab_client.get_quotes([ticker])[ticker]["lastPrice"]` |
| `t.options` (expiration list) | parsed from `get_option_chain()` response keys |
| `t.option_chain(best_exp).calls` | filtered from `get_option_chain()` response |
| `atm_row["impliedVolatility"]` | `atm_row["volatility"] / 100` (Schwab returns IV as percentage) |

IV percentile math (log returns vs HV30) is unchanged.

### `price_fetcher.py`

| Function | Was (yfinance) | Becomes (Schwab) |
|---|---|---|
| `_fetch_prices_from_yfinance()` | `yf.Tickers().history()` | `schwab_client.get_quotes(tickers)` → extract `lastPrice` |
| `fetch_quote()` | `yf.Ticker().fast_info` | `schwab_client.get_quotes([ticker])` → `lastPrice`, `closePrice` |
| `_fetch_rsi_from_yfinance()` | `yf.download(45d daily)` | `schwab_client.get_price_history(ticker, "month", 2, "daily", 1)` |

`_YF_ALIASES` dict removed; alias handling moves into `SchwabClient.get_quotes()`.

## Section 5: Wheel Dashboard CC Signal Column

**Files changed:** `frontend/src/pages/WheelDashboardPage.tsx`

### Data Fetching

After the main session list loads, fire parallel CC signal requests for all unique tickers:

```typescript
const tickers = [...new Set(sessions.map(s => s.ticker))];
const results = await Promise.allSettled(tickers.map(t => marketApi.getCCSignal(t)));
// store in Map<ticker, CCSignalResult> in component state
```

Results are cached in component state for page lifetime (backend already applies 4-hour TTL).

### New Column

Added to each status-grouped table (`Needs Action`, `Awaiting CC`, `Awaiting Sold Put`, `Active`):

**Column header:** `CC Signal`

**Cell content:** grade chip + IV percentile (or `—` while loading / on error)

| Grade | Chip style |
|---|---|
| `strong` | green badge |
| `moderate` | yellow badge |
| `weak` | orange badge |
| `wait` | gray badge |

**Format:** `[strong] 74th` — chip label + IV percentile as ordinal

**Loading:** table renders immediately; CC signal column shows `—` until responses arrive. All 19 parallel requests resolve quickly since backend caches.

## New Files Summary

| File | Purpose |
|---|---|
| `backend/app/models/schwab_token.py` | SchwabToken ORM model |
| `backend/alembic/versions/009_schwab_tokens.py` | DB migration |
| `backend/app/services/schwab_client.py` | Schwab HTTP client + token refresh |
| `scripts/schwab_auth.py` | One-time CLI OAuth flow |

## Modified Files Summary

| File | Change |
|---|---|
| `backend/app/models/__init__.py` | Register SchwabToken |
| `backend/app/services/technicals_fetcher.py` | Replace yf.download with Schwab price history |
| `backend/app/services/cc_signal.py` | Replace yf.Ticker options + fast_info with Schwab |
| `backend/app/services/price_fetcher.py` | Replace yf batch calls with Schwab quotes |
| `frontend/src/pages/WheelDashboardPage.tsx` | Add CC signal column |

## Schwab API Reference

- Base URL: `https://api.schwabapi.com`
- Auth: `https://api.schwabapi.com/v1/oauth/authorize` / `/v1/oauth/token`
- Quotes: `GET /marketdata/v1/quotes?symbols=...&fields=quote`
- Price history: `GET /marketdata/v1/pricehistory?symbol=...&periodType=...&period=...&frequencyType=...&frequency=...`
- Options chain: `GET /marketdata/v1/chains?symbol=...&contractType=CALL`

## Open Questions

- None — all decisions made above.
