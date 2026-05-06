# TradeMinder Phase 2B — Price Fetcher + Alert Engine Design

**Date:** 2026-05-05  
**Scope:** Price fetching, P&L calculation, alert engine (8 rules), APScheduler, market endpoints, frontend alert feed. Excludes indicator auto-fetch at trade creation (deferred to Phase 2A).

---

## Goal

Bring TradeMinder's alert system to life. Every 15 minutes during market hours, the backend fetches current prices for all open trades, updates P&L, evaluates 8 alert rules, and writes `Alert` rows to the database. The dashboard displays active alerts with read/dismiss controls. A manual refresh endpoint provides on-demand triggering.

---

## Architecture

```
FastAPI lifespan startup
    └── APScheduler AsyncIOScheduler
            ├── price_refresh_job  (every 15 min, market hours only)
            │       └── price_fetcher.refresh_open_trades(db)
            │               └── yfinance batch fetch → UPDATE trades
            │
            └── alert_engine_job  (every 15 min + 30s offset)
                    └── alert_engine.run(db)
                            └── 8 rules × all open trades → INSERT alerts

Manual trigger:
    POST /api/market/refresh
        └── price_refresh + alert_engine, on-demand

GET /api/market/quote/{ticker}
    └── yfinance single fetch → price + day stats
```

---

## File Map

**New files:**
- `backend/app/services/price_fetcher.py`
- `backend/app/services/alert_engine.py`
- `backend/app/scheduler.py`
- `frontend/src/components/Dashboard/AlertFeed.tsx`

**Modified files:**
- `backend/app/routers/market.py` — replace 501 stubs for `quote` and `refresh`
- `backend/app/main.py` — add `lifespan` for scheduler startup/shutdown
- `frontend/src/pages/DashboardPage.tsx` — add AlertFeed, wire alert count
- `frontend/src/api/alerts.ts` — already exists (no changes needed)

---

## Section 1: Price Fetcher

**File:** `backend/app/services/price_fetcher.py`

### Batch fetch (used by scheduler and manual refresh)

```python
async def refresh_open_trades(db: AsyncSession) -> dict:
    # 1. Load all open trades with strike_price, premium, quantity, strategy, type
    # 2. Collect unique tickers
    # 3. yf.download(tickers, period="1d", interval="1m", progress=False)
    # 4. Extract last close price per ticker
    # 5. For each trade: update current_price, last_price_at, unrealized_pnl
    # 6. Commit all updates
    # Returns: {"trades_updated": n, "tickers_fetched": n, "errors": [...]}
```

### Single ticker fetch (used by market quote endpoint)

```python
async def fetch_quote(ticker: str) -> dict | None:
    # yf.Ticker(ticker).fast_info
    # Returns: {ticker, price, change_pct, last_updated} or None on failure
```

### P&L calculation (proxy — no options chain lookup)

| Trade type | Formula |
|------------|---------|
| Sell Put / Sell PutCreditSpread | `(premium - max(strike - current_price, 0)) * quantity * 100` |
| Sell Call / Sell CoveredCall | `(premium - max(current_price - strike, 0)) * quantity * 100` |
| All others (stock, missing data) | `null` |

**Edge cases:**
- Ticker not found in yfinance → skip trade, log warning, leave existing `current_price`/`unrealized_pnl` unchanged
- `premium` or `strike_price` is null → skip P&L, leave `unrealized_pnl = null`
- All DB updates in a single commit per refresh run

---

## Section 2: Alert Engine

**File:** `backend/app/services/alert_engine.py`

### Entry point

```python
async def run(db: AsyncSession) -> dict:
    # Load all open trades with rationale + latest commentary created_at
    # For each trade: evaluate all 8 rules
    # Deduplicate: skip if unread+undismissed alert of same type already exists for trade
    # Bulk insert new alerts
    # Returns: {"alerts_created": n, "trades_evaluated": n}
```

### Deduplication query

Before inserting any alert, check:
```sql
SELECT 1 FROM alerts
WHERE trade_id = :trade_id
  AND alert_type = :alert_type
  AND is_dismissed = false
  AND is_read = false
LIMIT 1
```
If a row exists, skip insertion for that rule + trade combination.

### 8 Rules

All rules receive a `trade` ORM object (with `current_price`, `unrealized_pnl`, `rationale`, last commentary timestamp). Rules that cannot evaluate (missing data) return `None` silently.

| # | Rule | Condition | Severity | Applies to |
|---|------|-----------|----------|------------|
| 1 | `profit_target` | `unrealized_pnl / (premium × qty × 100) >= 0.50` | warning | Sell options with strike + premium |
| 2 | `stop_loss` | `unrealized_pnl <= -(premium × qty × 100 × 2)` | urgent | Sell options with strike + premium |
| 3 | `dte_threshold` | `days_to_expiry <= 21 and > 7` | warning | Any trade with `expiry_date` |
| 4 | `dte_critical` | `days_to_expiry <= 7` | urgent | Any trade with `expiry_date` |
| 5 | `earnings_approaching` | `rationale.next_earnings_date` within 5 calendar days | warning | All open trades with rationale |
| 6 | `assignment_risk` | `abs(strike - current_price) / strike <= 0.02` | warning | Put, PutCreditSpread |
| 7 | `overdue_review` | No commentary in last 5 days (uses `trade.created_at` if no commentary) | info | All open trades |
| 8 | `deep_itm` | `(current_price - strike) / strike >= 0.05` | urgent | CoveredCall |

**Note on `dte_threshold` vs `dte_critical`:** These are independent rules. A trade at 5 DTE fires both — one `dte_threshold` (warning) and one `dte_critical` (urgent). Each deduplicates independently.

### Alert title/message format

The alert engine embeds the ticker in the title so the frontend doesn't need to join to the trades table:

```
title:   "AAPL: Profit target reached"
message: "Unrealized P&L is $342 (51% of max profit). Consider closing."
```

---

## Section 3: Scheduler

**File:** `backend/app/scheduler.py`

### Setup

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler(timezone="America/New_York")
```

### Market hours check

```python
def is_market_hours() -> bool:
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:  # Saturday, Sunday
        return False
    start = time(9, 30)
    end = time(16, 0)
    return start <= now.time() <= end
```

Both jobs call `is_market_hours()` at the start and return immediately if outside hours.

### Jobs

```python
# Price refresh: every PRICE_REFRESH_INTERVAL_MINUTES (default 15)
scheduler.add_job(price_refresh_job, "interval", minutes=15, id="price_refresh")

# Alert engine: every 15 min, starts 30s after price refresh
scheduler.add_job(alert_engine_job, "interval", minutes=15, seconds=30, id="alert_engine")
```

Each job creates its own `AsyncSessionLocal()` session — isolated from the HTTP request cycle.

### FastAPI lifespan integration

```python
# backend/app/main.py
from contextlib import asynccontextmanager
from app.scheduler import scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)

app = FastAPI(title="TradeMinder API", version="0.2.0", lifespan=lifespan)
```

---

## Section 4: Market Endpoints

**File:** `backend/app/routers/market.py`

### Implemented in Phase 2B

**`GET /api/market/quote/{ticker}`**
```json
{
  "ticker": "AAPL",
  "price": 192.43,
  "change_pct": -0.82,
  "last_updated": "2026-05-05T14:32:00Z"
}
```
Returns 404 if ticker not found in yfinance.

**`POST /api/market/refresh`**
Triggers `refresh_open_trades` + `alert_engine.run` immediately regardless of market hours.
```json
{
  "trades_updated": 5,
  "alerts_created": 2,
  "tickers_fetched": 3
}
```

### Remain 501 (deferred to Phase 2A)

- `GET /api/market/options/{ticker}`
- `POST /api/market/prefetch/{ticker}`

---

## Section 5: Frontend Alert Feed

**File:** `frontend/src/components/Dashboard/AlertFeed.tsx`

### Behavior

- Fetches `GET /api/alerts` on mount
- Polls every 60 seconds
- Grouped by severity: urgent (red border) → warning (yellow border) → info (gray border)
- Count badge: "3 active alerts" / "No active alerts"

### Each alert card

- **Title** (contains ticker, e.g. "AAPL: Profit target reached")
- **Message** (detail text)
- **Time ago** (e.g. "12 minutes ago")
- **Mark read** button — fades the card opacity, re-fetches
- **Dismiss** button — removes card from list, re-fetches

### Dashboard layout changes (`DashboardPage.tsx`)

- "Open Alerts" stat card shows live count from `GET /api/alerts` response length
- `AlertFeed` component added below the 3 stat cards
- "Active Trades" stat card wired to `GET /api/trades?status=open` count (also new)

---

## Testing Strategy

**Backend (pytest-asyncio):**
- `test_price_fetcher.py` — mock yfinance, verify DB updates and P&L calculations for each trade type
- `test_alert_engine.py` — seed trades with known `current_price`/`unrealized_pnl`, verify correct alerts created and deduplication works
- `test_market_router.py` — mock price fetcher service, test `/quote` and `/refresh` endpoints
- Scheduler itself is not unit tested — too tightly coupled to time; covered by integration

**Frontend:**
- No automated tests in Phase 2 (no test framework set up); manual verification via dev server

---

## Dependencies

`pytz` or `zoneinfo` for timezone handling — `zoneinfo` is stdlib in Python 3.9+, no new dependency needed.

`apscheduler` is already listed as a project dependency (confirm in pyproject.toml — add if missing).

No other new dependencies.
