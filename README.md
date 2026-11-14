# TradeMinder

A personal trading assistant for active stock and options traders, focused on the Wheel strategy and related options plays. Solves the "fragile memory" problem: traders forget *why* they entered a trade, what their exit rules were, and what follow-up actions are overdue.

**Stack:** FastAPI · SQLAlchemy 2.0 async · PostgreSQL 15 · React 18 · Vite · TypeScript · Tailwind CSS · Chrome Extension (MV3)

---

## Core Value Proposition

- Store every trade with full technical rationale captured automatically at entry
- Maintain a timestamped running commentary per position (your trading journal)
- Alert you when action is overdue based on your own stated exit strategy
- Deliver a daily morning briefing summarizing active positions, pending alerts, and AI-synthesized rationale
- **Chrome extension** that overlays TradeMinder data directly onto your E\*TRADE portfolio page — category badges, alert coloring, commentary hover panels, and signal flags, without leaving the brokerage

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│         Chrome Extension (E*TRADE overlay)               │
│   Category badges · Alert colors · Commentary hover      │
│   Signal flags · Inline note entry                       │
└─────────────────────────┬───────────────────────────────┘
                          │ REST
┌─────────────────────────▼───────────────────────────────┐
│              React Dashboard (Vite + TypeScript)         │
│   Morning Briefing · Position Table · Alert Feed ·       │
│   Commentary Thread · Trade Entry Form                   │
└─────────────────────────┬───────────────────────────────┘
                          │ REST + WebSocket
┌─────────────────────────▼───────────────────────────────┐
│                   FastAPI Backend (Python)                │
│   Trade CRUD · Categories · Alert Engine ·               │
│   Price Fetcher · Signal Engine · AI Briefing            │
└──────┬──────────────────┬──────────────────┬────────────┘
       │                  │                  │
┌──────▼──────┐  ┌────────▼───────┐  ┌──────▼──────────┐
│ PostgreSQL   │  │ yfinance /     │  │  Anthropic API  │
│ (primary DB) │  │ Yahoo Finance  │  │  claude-sonnet  │
│              │  │ (live prices)  │  │  (briefings +   │
└─────────────┘  └────────────────┘  │   summaries)    │
                                      └─────────────────┘
```

### Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| Backend | FastAPI (Python 3.11+) | Async, auto-docs, Python-native for yfinance |
| Database | PostgreSQL 15+ | Relational lifecycle data, JSONB for flexible fields |
| ORM | SQLAlchemy 2.0 (async) | Type-safe, migration-friendly |
| Migrations | Alembic | Schema versioning |
| Price Data | yfinance | Free, reliable for EOD + delayed quotes |
| AI | Anthropic Claude API | Briefings, summaries, rationale synthesis |
| Frontend | React 18 + Vite + TypeScript | Fast iteration, component-based |
| UI Library | shadcn/ui + Tailwind CSS | Clean, professional, no design overhead |
| Scheduler | APScheduler (in-process) | Alert engine cron jobs, price refresh |
| Containerization | Docker + docker-compose | Postgres + backend + frontend in one command |
| Browser Extension | Chrome MV3 | In-broker overlay on E\*TRADE portfolio page |

---

## Quick Start — Full Docker

```bash
cp .env.example .env
docker compose up --build
docker compose exec backend alembic upgrade head
```

- Frontend: http://localhost:5430
- Backend API: http://localhost:5431
- API docs: http://localhost:5431/docs

```bash
docker compose down        # stop
docker compose down -v     # stop + delete database
```

---

## Local Dev — Backend (venv) + Docker Postgres

Recommended for backend development. Postgres runs in Docker; the backend runs locally for fast iteration.

```bash
# 1. Start Postgres
docker compose up db -d

# 2. Set up Python virtual environment
cd backend
python3.13 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# 3. Configure environment
cp .env.example .env      # from repo root

# 4. Run migrations
alembic upgrade head

# 5. Start backend
uvicorn app.main:app --reload --port 5431
```

API: http://localhost:5431 · Docs: http://localhost:5431/docs

---

## Local Dev — Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend: http://localhost:5430. Vite proxies `/api/*` to `http://localhost:5431`.

---

## Running Tests

```bash
cd backend
source venv/bin/activate
pytest tests/ -v
```

Postgres must be running. Tests use a separate `trademinder_test` database created automatically on first `docker compose up db`.

---

## Environment Variables

Copy `.env.example` to `.env`.

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://trademinder:password@localhost:5432/trademinder` | Use `db:5432` inside Docker Compose |
| `SECRET_KEY` | `changeme` | Set a strong random value in production |
| `ANTHROPIC_API_KEY` | _(empty)_ | Required for AI briefings and commentary summaries |
| `ALERT_ENGINE_INTERVAL_MINUTES` | `15` | How often the alert engine runs |
| `PRICE_REFRESH_INTERVAL_MINUTES` | `15` | How often prices are fetched |
| `BRIEFING_GENERATE_TIME` | `08:00` | Daily briefing generation time |
| `OWNER_EMAIL` | _(required)_ | Seeds the first (admin) user in migration 015 — the migration fails without it. Until login lands every request runs as this user |
| `OWNER_DISPLAY_NAME` | `Owner` | Display name for the seeded owner |

---

## Database Schema

### Design Philosophy
Each individual trade (buy, sell, assign) is its own `Trade` record. Trades on the same ticker within a wheel cycle are linked via `wheel_id`. This keeps inserts simple while enabling grouped views.

### Users and Brokerage Accounts (migrations 015–016)

Ownership is **user → brokerage account → trades / wheels / spreads**.

- **`users`** — tenant root. The tenant key is the internal UUID `id`; `email` is unique case-insensitively but never a key, and `external_subject` (nullable) will hold the Google identity once login lands. `role` is `admin` | `user`, `status` is `pending` | `active` | `disabled`. Migration 015 seeds the owner as the first active admin from `OWNER_EMAIL`.
- **`brokerage_accounts`** — one user owns many, including several at the same broker (e.g. "E\*TRADE Hold" and "E\*TRADE Wheel"). Fields: `broker` (free text; UI offers E\*TRADE, Schwab, Fidelity, Robinhood, Other), `nickname`, `last_four` (only the last four digits — full account numbers are never stored), `external_ref` (links a broker-side account in a later part), `default_category_id`, `is_default` (exactly one per user), `sort_order`, `is_archived`. An account with trades, wheels or spreads can only be archived.
- **`account_categories`** — categories are a per-user library; each account picks the ones it uses and may set a default for new trades.
- **`screener_account_memberships`** — one screener row per user per symbol (market data fetched once); each symbol belongs to one or more accounts. Screener notes carry an `account_id` because a note reflects one account's situation.
- Every user-owned table carries `user_id`. `trades`, `wheel_sessions`, `trade_sessions` (spreads) and `screener_commentary` also carry `account_id`; slots, legs, premium logs, rationale, commentary, alerts and signals inherit their account through their parent. Market data (`schwab_tokens`, quotes, technicals, signal caches) is app-level and shared.
- Migration 016 backfilled all existing data to the owner and a default account nicknamed "E\*TRADE".
- **Account facts (migration 019):** each account can record its tax treatment (taxable, traditional IRA, Roth IRA,
  other tax-advantaged), purpose (trading, long term), margin type (cash, limited margin, margin, portfolio margin),
  a broker-neutral options tier (none, covered, cash-secured and long, spreads, uncovered) with the broker's own
  label for it, and optional net liquidation value and cash with an as-of date.
  - All of them are optional and editable in Settings → Accounts, and accounts missing any of the four main facts
    show **Facts incomplete**.
  - Impossible combinations are rejected: an IRA with margin, or uncovered options without margin.
  - Nothing else in the app reads them yet.
- **Goal and preferences (migration 020):** each account can also record its objective (income, growth, mixed),
  assignment stance (willing, selective, unwilling), optional monthly premium and annual yield targets, and risk
  limits.
  - **Limits:** max position, max speculative position and max margin used fall back to house defaults (10%, 3%,
    30%) until you override them, and **Use default** resets one. Minimum cash reserve and defensive-at-loss have
    no default.
  - **Rules:** a cash account can't have a margin limit, and the speculative limit can't exceed the position
    limit.
  - **Display:** accounts without an objective and stance show **Goal not set**.
  - Nothing else in the app reads them yet.

### Migration 001 — Initial Schema

**`trades`** — primary record for every transaction
```sql
CREATE TABLE trades (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wheel_id        UUID,
    type            VARCHAR(10) NOT NULL,    -- 'Buy' | 'Sell' | 'Assigned'
    strategy        VARCHAR(30) NOT NULL,    -- 'Stock' | 'Put' | 'Call' | 'CoveredCall' | 'PutCreditSpread' | 'Skip' | 'Leap'
    ticker          VARCHAR(10) NOT NULL,
    open_date       DATE NOT NULL,
    expiry_date     DATE,
    closed_date     DATE,
    strike_price    NUMERIC(10, 2),
    quantity        INTEGER NOT NULL,
    premium         NUMERIC(10, 2),
    collateral      NUMERIC(12, 2),
    exit_strategy   TEXT,
    signal_action   TEXT,
    status          VARCHAR(10) NOT NULL DEFAULT 'open',
    current_price   NUMERIC(10, 2),
    last_price_at   TIMESTAMPTZ,
    unrealized_pnl  NUMERIC(10, 2),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**`rationale`** — technical indicator snapshot at trade entry (auto-fetched from yfinance; `notes` is the only user-provided field)

**`commentary`** — timestamped running log per trade; append-only, never edited

**`alerts`** — generated by the alert engine; includes `snoozed_until` for snooze support

**`daily_briefings`** — AI-generated morning briefings; stored for historical reference

### Migration 002 — Categories and Extension Support
```sql
CREATE TABLE categories (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(50) NOT NULL UNIQUE,
    color       VARCHAR(7)  NOT NULL DEFAULT '#6B7280',
    icon        VARCHAR(10),
    is_system   BOOLEAN NOT NULL DEFAULT false,
    sort_order  INTEGER NOT NULL DEFAULT 99,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Seeded: Wheel, Speculative, Momentum, Short Term, Long Term, Coach Suggested

ALTER TABLE trades ADD COLUMN category_id UUID REFERENCES categories(id);

CREATE TABLE technical_signals (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trade_id     UUID NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
    signal_type  VARCHAR(30) NOT NULL,
    signal_value NUMERIC(10, 4),
    triggered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_active    BOOLEAN NOT NULL DEFAULT true,
    notes        TEXT
);
```

---

## Alert Engine Rules

Runs every 15 minutes during market hours, once daily pre-market.

| Rule | Trigger | Severity |
|---|---|---|
| `profit_target` | Unrealized P&L ≥ 50% of max profit | warning |
| `stop_loss` | Unrealized loss ≥ 2x premium received | urgent |
| `dte_threshold` | Days to expiry ≤ 21 | warning |
| `dte_critical` | Days to expiry ≤ 7 | urgent |
| `earnings_approaching` | Earnings date within 5 calendar days | warning |
| `assignment_risk` | Put strike within 2% of current price | warning |
| `overdue_review` | No commentary in 5+ days on open trade | info |
| `deep_itm` | Call strike >5% below current price | urgent |

---

## Signal Engine

Runs after the alert engine. Writes to `technical_signals`. Deactivates signals when the condition no longer holds.

| Signal | Condition |
|---|---|
| `macd_bullish` / `macd_bearish` | Based on `rationale.macd_signal` |
| `rsi_oversold` / `rsi_overbought` | `rsi_14 < 30` / `rsi_14 > 70` |
| `bb_breakout_upper` / `bb_breakout_lower` | Bollinger position top/bottom |
| `above_ma200` / `below_ma200` | Price vs 200-day MA |
| `golden_cross` / `death_cross` | 50MA vs 200MA relationship |

---

## API Endpoints

### Trades
```
GET    /api/trades
POST   /api/trades
GET    /api/trades/{id}
PATCH  /api/trades/{id}
DELETE /api/trades/{id}
GET    /api/trades/wheel/{wheel_id}
POST   /api/trades/{id}/close
PATCH  /api/trades/{id}/category      body: { "category_id": "uuid" }
```

### Commentary
```
GET    /api/trades/{id}/commentary
POST   /api/trades/{id}/commentary
DELETE /api/commentary/{id}
GET    /api/trades/{id}/commentary/summary    ← AI summary via Anthropic
```

### Alerts
```
GET    /api/alerts
POST   /api/alerts/{id}/read
POST   /api/alerts/{id}/dismiss
POST   /api/alerts/{id}/snooze               body: { "hours": 24 }
GET    /api/alerts/trade/{trade_id}
```

### Categories
```
GET    /api/categories
POST   /api/categories
PATCH  /api/categories/{id}
DELETE /api/categories/{id}                   (405 for system categories)
```

### Positions — primary endpoint for Chrome extension
```
POST   /api/positions/status          body: { "positions": [...] }
GET    /api/dashboard/today
```

Response per position includes: category, alert severity, last commentary note, active signals, rationale snapshot, and trade details — everything the extension needs in one round trip.

### Market Data

All market data goes through one provider boundary: `app/services/market_data.py`. `get_market_data()`
returns the configured provider, set by `MARKET_DATA_PROVIDER`; only `schwab` exists, and unknown values fail
at startup. Only that module and the Schwab implementation (`schwab_client.py`) know about Schwab. yfinance
(earnings calendar, LEAPS scanner) is separate.

**When the Schwab refresh token lapses, the app degrades instead of going dark.** This covers an expired token,
a rejected refresh (`invalid_grant`) and no tokens at all. The provider then stops calling Schwab, so there are
no retries and no log spam.

| Endpoint kind | While offline |
|---|---|
| Pure market endpoints (quote, technicals, signals, chain, option price, RSI, screener preview, single fetch) | Return `503 {"code": "market_data_offline"}`. Signals with a server-side cached result return that result instead, with `stale: true` and its `as_of` time. |
| Mixed endpoints (trades, trade detail, wheel detail, active slots, positions/status, dashboard summary, screener list) | Return their database data with the `X-Market-Data-Offline: true` header. Market fields are `null` (screener rows are served as stored, with `stale: true`). Object responses also carry `market_data_offline: true`. |
| Everything else | Keeps working: journal, commentary, wheels, slot resolves, accounts, Reconcile, categories, margin CSV analysis. |

- **Reconnect only in production; dev follows.**
  - **One grant:** each Schwab login invalidates the previous grant's refresh token, so only production
    reconnects and refreshes.
  - **Dev as a token follower:** dev sets `SCHWAB_TOKEN_SYNC_URL` (production's https origin) and the shared
    `SCHWAB_TOKEN_SYNC_SECRET`, which production also sets.
    - Dev then pulls production's current tokens instead of refreshing: when its access token runs low, after a
      401, or while offline. It pulls at most once a minute, and the original call is retried once.
    - Dev's Reconnect is disabled (409, hidden), and Settings → Market data shows "Token source: Production",
      the last pull and **Pull now**.
  - **Setup:** `docs/deployment/schwab-reconnect.md` ("One-time setup").
- **Recovery (re-auth):** **Reconnect in the production app**: the admin clicks **Reconnect Schwab** (on the banner
  or in Settings → Market data), logs in at Schwab, and pastes the address of the page that fails to load
  afterwards. The new tokens take effect immediately, with no restart; runbook:
  `docs/deployment/schwab-reconnect.md`.
  - **CLI fallback:** `python scripts/schwab_auth.py` writes the row of whichever database `DATABASE_URL` points
    to; the provider re-reads the row at most once a minute and resumes on its own.
  - Going offline and coming back are each logged once.
- **Expiry banner:** admins see it in the app. Amber from 72h to 24h left (dismissible for the session), red
  under 24h, and red "Market data offline" once expired. It is backed by `GET /api/market-data/status`
  (admin only), and `GET /api/me` tells the SPA whether the user is an admin.
- **Reconnect endpoints** (admin only): `start` returns Schwab's authorize URL with a signed, single-use,
  10-minute state. `complete` validates the pasted URL, exchanges the code, and stores the tokens. Errors are
  `{detail, code}` (400/409/502). The CLI and the app share `app/services/schwab_oauth.py`. On a token follower
  both return 409 `token_follower`.
- **Token sync:** `POST /api/market-data/sync/tokens` is server to server, outside the session check, and
  authenticated only by the `X-Token-Sync-Secret` header. It's production → dev, and returns 404 unless production
  sets the secret. `POST /api/market-data/sync/pull` (admin, follower only) pulls now.

```
GET    /api/market-data/status      (admin) provider, state ok|expiring|critical|offline, expiry, last success/error
POST   /api/market-data/reconnect/start     (admin) → { authorize_url, state_expires_at }
POST   /api/market-data/reconnect/complete  (admin) { redirect_url } → same shape as /status
POST   /api/market-data/sync/pull   (admin, follower only) pull tokens from production now → same shape as /status
POST   /api/market-data/sync/tokens (server to server, X-Token-Sync-Secret only) production → follower token pair
GET    /api/me                      current user (id, email, display_name, role)
GET    /api/market/quote/{ticker}
GET    /api/market/options/{ticker}
POST   /api/market/refresh
POST   /api/market/prefetch/{ticker}
GET    /api/trades/{id}/signals
POST   /api/market/signals/refresh
```

### AI / Briefing
```
GET    /api/briefing/today
POST   /api/briefing/generate
GET    /api/briefing/{date}
POST   /api/trades/{id}/summarize
```

Full interactive docs: http://localhost:5431/docs

---

## Chrome Extension

The extension overlays TradeMinder data on the E\*TRADE portfolio page in four stages. Enabled/disabled individually via the popup settings UI.

### Server address and accounts
- **Server address**: set once in the popup (default `http://127.0.0.1:5431`). Saving asks Chrome for access to that host (optional host permission). Every API call goes through the service worker, which uses the stored address. If TradeMinder can't be reached, the account bar says so.
- **Which account is on screen**: read from E\*TRADE's account dropdown. The first time an E\*TRADE account is selected, a **Link this E\*TRADE account** card asks which TradeMinder account it is (existing, or create new — prefilled with E\*TRADE, the nickname and last four). The link is stored server-side, so it survives reinstalls and works on any computer; Settings → Accounts in the app shows it and can unlink it.
- **Privacy**: the link key is a SHA-256 fingerprint of the broker + full account number, computed in the service worker. The full account number is never sent to TradeMinder, stored, or logged.
- **Scoping**: in a single linked account, badges, pills, Add trade, Edit and the session picker use only that account. In **All brokerage accounts**, statuses match across all of your accounts and a position held in several accounts shows a chip per account; Add trade asks for the account. Unlinked accounts show nothing until linked.
- **Reconcile** runs only for a single, linked account and only ever backdate-closes that account's trades. It's disabled (with the reason shown) in the All view and for unlinked accounts.

### Stage 1 — Category Indicators
Reads ticker from DOM → calls `/api/positions/status` → injects a TM badge column and adds a filter toolbar above the grid.

```
[TradeMinder: All] [Wheel] [Speculative] [Momentum] [+ New]

| Ticker | ... | TM Status         |
| NVDA   | ... | 🔄 Wheel          |  ← blue tint
| MSTR   | ... | 🎲 Speculative    |  ← red tint
| GOOGL  | ... | ⊘ Not tracked    |  ← gray border
```

### Stage 2 — Commentary + AI Summary on Hover
```
┌──────────────────────────────────────────────────┐
│ NVDA · Sell Put · $850 · 7 DTE                   │
├──────────────────────────────────────────────────┤
│ 🤖 AI SUMMARY                                    │
│ Position near profit target (62%). Notes suggest  │
│ elevated IV kept you holding. 7 DTE — consider   │
│ closing to lock in gains.                         │
│                                                  │
│ INFERRED ACTIONS                                 │
│ • Close — profit target rule met                 │
│ • Monitor: earnings Jun 4 approaching            │
│                                                  │
│ May 3  "IV elevated, holding for now"            │
│ Apr 28 "Entered on oversold RSI signal"          │
│                                                  │
│ [Add Note ________________________] [Save]       │
│ [View All Notes]  [Snooze Alert]                 │
└──────────────────────────────────────────────────┘
```

### Stage 3 — Alert-Based Row Coloring
Alert severity overrides category color tint:

| Severity | Background | Border |
|---|---|---|
| 🔴 Urgent | `rgba(239,68,68,0.18)` | red |
| 🟡 Warning | `rgba(245,158,11,0.15)` | amber |
| 🟣 Info/Overdue | `rgba(139,92,246,0.12)` | purple |
| 🟢 OK | `rgba(34,197,94,0.08)` | green |

Alert badge map:
| Alert type | Badge |
|---|---|
| `profit_target` | ✅ Close Now · 62% |
| `stop_loss` | 🛑 Stop Loss Hit |
| `dte_critical` | ⏰ 7 DTE — Expiring |
| `dte_threshold` | 📅 21 DTE — Review |
| `earnings_approaching` | 📢 Earnings 4d |
| `assignment_risk` | ⚠️ Assignment Risk |
| `deep_itm` | 🔻 Deep ITM |
| `overdue_review` | 📝 Review Due |

### Stage 4 — Technical Signal Flags
Signal dots appended to TM badge. Green = bullish signal, red = bearish.
```
| NVDA | ... | 🔴 Close Now · 62% ●● |
```

---

## E\*TRADE DOM Reference

The E\*TRADE portfolio page uses a **div-based virtual scroll grid** (not a `<table>`). Only ~32 rows are rendered at a time; rows are recycled as you scroll.

Key facts:
| Property | Value |
|---|---|
| Grid | `[role="grid"][aria-label="Portfolios"]` — the `rdt_N` id is **not stable** (`rdt_2` in captures) |
| Account selector | `select#accountDropdown`; option value = full account number + `-` + label; All view = `all-…`; selection only in the live `.value` |
| Account info on rows | none — no account column or group rows in any view |
| All-accounts view | rows have no Trade button (full symbol comes from the quote link `?symbol=`); no Customize button in the filter bar |
| Class names | `Block---element---<hash>`; the hash changes between releases, so match the prefix |
| Row height | 37px fixed, positioned via `transform: translateY(Npx)` |
| Row IDs | recycled on scroll and on re-render |

### Selectors (prefix-based)
```javascript
// cls(p) → '[class^="p"],[class*=" p"]'
const ETRADE = {
  grid:            '[role="grid"][aria-label="Portfolios"]',
  contentArea:     cls('Content---root---'),
  positionRows:    '[role="row"][level="0"]' /* minus Row---placeholderRow---* */,
  symbolContent:   cls('SymbolCellRenderer---content---'),
  symbolRoot:      cls('SymbolCellRenderer---root---'),
  optionClassPrefix: 'SymbolCellRenderer---option---',
  itmClassPrefix:  'SymbolCellRenderer---in-the-money---',
  headerTitle:     cls('HeaderCell---title---'),
  customizeView:   cls('PortfoliosFilters---customize-view---'),
  accountDropdown: 'select#accountDropdown',
};
```

Ticker comes from `aria-label` on `.SymbolCellRenderer---content---mcwCT`.
For ITM options the aria-label is `"NVDA, This option is in the money"` — take everything before the first comma.

### Option Symbol Format
Pattern: `TICKER + 2–4 dashes + YYMMDD + [C/P] + 8-digit-strike`

Total length of `TICKER + DASHES` is always 6 characters:
- 4-char ticker → 2 dashes: `AAPL--260508C00290000`
- 3-char ticker → 3 dashes: `AMD---260508P00400000`
- 2-char ticker → 4 dashes: `BE----260522P00225000`

Regex: `/^([A-Z]+)-{1,4}(\d{6})([CP])(\d{8})$/`

Strike parsing: divide 8-digit field by 1000 (e.g. `00400000` → `400.00`).

Use `MutationObserver` on `.Content---root---D2Ylg` with a 150ms debounce to handle virtual scroll row recycling.

---

## Project Structure

```
TradeMinder/
├── README.md
├── docker-compose.yml
├── docker-compose.prod.yml
├── .env.example
├── .gitignore
│
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/
│   │   └── versions/
│   │       ├── 001_initial_schema.py
│   │       └── 002_categories_and_extensions.py
│   ├── app/
│   │   ├── main.py           # FastAPI app + router registration
│   │   ├── config.py         # pydantic-settings from env
│   │   ├── database.py       # async engine + get_db
│   │   ├── models/           # SQLAlchemy ORM models
│   │   ├── schemas/          # Pydantic request/response models
│   │   ├── routers/          # trades, commentary, alerts, categories, positions, market, briefing
│   │   ├── services/         # alert_engine, signal_engine, price_fetcher, indicator_fetcher, ai_briefing
│   │   └── scheduler.py
│   └── tests/
│
├── frontend/
│   ├── Dockerfile
│   ├── nginx.conf            # Production nginx + /api proxy
│   ├── vite.config.ts        # Dev server + /api proxy
│   └── src/
│       ├── api/              # Typed fetch wrappers
│       ├── types/            # TypeScript interfaces
│       ├── components/       # Dashboard, Trades, Commentary, shared
│       └── pages/            # DashboardPage, TradesPage, TradeDetailPage, HistoryPage
│
└── extension/
    ├── manifest.json
    ├── background.js         # Service worker, API URL config
    ├── content.js            # All 4 stages, feature-flagged by popup settings
    ├── content.css
    ├── sidebar/              # Full commentary thread + action queue
    ├── popup/                # Settings: API URL, enable/disable each stage
    └── icons/
```

---

## Sign-in and multi-user

TradeMinder is multi-user. Sign-in is with **Google**, which serves only as the identity check.

- **Sessions:** after the Google callback the backend issues its own session.
  - It's a random token in an httpOnly, Secure, SameSite=Lax `tm_session` cookie. Only its SHA-256 is stored, in
    `user_sessions`.
  - It slides for `SESSION_DAYS` (30): any use within that window extends it.
  - Logout deletes the row. No JWTs, no Redis.
- **Sign-in rules, in order:**
  1. match by Google subject;
  2. else match the seeded owner or an invited user by email and link the subject once (never replaced; the
     internal user id stays the tenant key);
  3. else create a **pending** user, who sees only "Waiting for approval".

  Disabled users are refused. Disabling someone ends their sessions and extension tokens immediately.
- **Admin:** an extra permission on a normal account (the owner from `OWNER_EMAIL` is the bootstrap admin).
  - The Admin page has a pending queue, invite by email, approve/reject, disable/re-enable and role changes. You
    can never disable or demote yourself, or the last admin.
  - It shows account-management fields only, never anyone's trading data.
- **Every API route** needs a session or an extension token, except `/health` and `/api/auth/*`; a test enforces
  it. `/api/me` is the one route a pending user may call.
- **Extension:** the popup's **Sign in** opens the portal's "Connect this browser extension?" page
  (`chrome.identity.launchWebAuthFlow`). Approving issues a personal token, hashed, revocable and with a
  last-used time, which the service worker sends as a bearer header on every call. Only extension IDs in
  `EXTENSION_IDS` can receive tokens.
- **Settings → Connected extensions** lists and revokes them.
- **Schwab re-auth:** the in-app **Reconnect Schwab** (admin only) in production is the default, and
  `scripts/schwab_auth.py` is the fallback. Never reconnect on dev: dev follows production's tokens. See
  `docs/deployment/schwab-reconnect.md`.

Local dev with real sign-in: set `PUBLIC_BASE_URL=http://localhost:5430` and the Google client id/secret in
`.env`, and add `http://localhost:5430/api/auth/google/callback` to the OAuth client's redirect URIs.

## QNAP Deployment (Production)

Production is a QNAP NAS (amd64) running a **Portainer stack** (`docker-compose.prod.yml`) with four services:

| Service | Detail |
|---|---|
| `traefik` (`v3.1.6`) | Only port **443**. A Let's Encrypt certificate for `tm.<domain>` through the **Cloudflare DNS-01** challenge (the NAS is never exposed; no port 80), stored on the `traefik-letsencrypt` volume and auto-renewed. Routes `/api` → backend, everything else → frontend, on one origin |
| `backend` | FastAPI on 5431; runs `alembic upgrade head` on start; trusts Traefik's forwarded headers |
| `frontend` | nginx serving the SPA build with an `index.html` fallback for deep links |
| `db` | Postgres 15 |

`tm.<domain>` is a DNS-only Cloudflare record pointing at the NAS's LAN IP, so the app is reachable on the home
Wi-Fi only. All secrets (Google client, `AUTH_STATE_SECRET`, Cloudflare token, Schwab keys) are Portainer stack
environment variables, never in git.

The full step-by-step upgrade (backup, migrations, env vars, certificate, first sign-in, pilot user, extension,
DNS rebinding) is in **[docs/deployment/qnap-login-and-https.md](docs/deployment/qnap-login-and-https.md)**.

---

## Build Plan

### Phase 1 — Foundation ✅
Docker + Postgres, FastAPI skeleton, SQLAlchemy models, Alembic migration 001, CRUD endpoints (trades / commentary / alerts), React frontend with trade list and trade detail.

### Phase 2 — Categories + Chrome Extension ✅
Migration 002 (categories, signals), category CRUD, `/api/positions/status`, commentary AI summary, signal engine, alert snooze, Chrome extension all 4 stages with confirmed E\*TRADE DOM selectors.

### Phase 3 — Price Data + Alert Engine
- [ ] yfinance price fetcher (live prices for P&L and alerts)
- [ ] Alert engine with all 8 rules
- [ ] APScheduler jobs (price refresh + alert evaluation)

### Phase 4 — AI Briefing
- [ ] Anthropic API integration (`ai_briefing.py`)
- [ ] Daily briefing endpoint + scheduler job (8am)
- [ ] MorningBriefing component (rendered markdown)
- [ ] Per-trade AI summary endpoint

### Phase 5 — Dashboard Polish
- [ ] Wheel grouping view (group trades by `wheel_id`)
- [ ] P&L display with color coding
- [ ] DTE countdown badges
- [ ] Historical briefings page
- [ ] Filter/search on trades page

### Phase 6 — Future
- [ ] Options chain viewer
- [ ] Trade import from CSV / brokerage export
- [ ] Performance analytics (realized P&L over time by strategy)
- [ ] User-configurable alert rules

---

## Key Design Decisions

**Individual trade records, not position aggregates** — each Buy/Sell/Assign is its own row; `wheel_id` links related legs. Keeps inserts trivial while allowing grouped views.

**Commentary is append-only** — never edit old entries, always add new ones. Preserves your actual thought process at each point in time.

**Alerts are generated, not user-configured (initially)** — hardcoded rules first; add user-configurable rules in a later phase.

**yfinance for prices** — free, zero auth, ~15min delayed intraday. Acceptable for MVP; upgrade to Tradier or Polygon if needed.

**AI briefing is pull, not push** — generated at 8am and stored; page load fetches the stored briefing. Avoids latency and preserves history.

**Multi-user is in progress, behind one current-user seam** — every router touching user data depends on `app/deps.py::get_current_user`, and every per-id lookup goes through `app/services/ownership.py`, which filters by the owning user and returns 404 for other users' ids. Today the seam returns the seeded owner; Google login (a later part) replaces only its body.

**Extension talks directly to local backend** — calls `http://localhost:5431` (configurable). No relay server, no cloud dependency.

**Virtual scroll handled with MutationObserver + row cache** — E\*TRADE recycles DOM rows on scroll. The extension tracks `rowId → cacheKey` (avoids re-processing unchanged rows) and `cacheKey → status` (avoids re-fetching the same ticker data).

---

## Resetting the Database

```bash
cd backend
source venv/bin/activate
alembic downgrade base
alembic upgrade head
```

Or nuke the Docker volume:
```bash
docker compose down -v
docker compose up db -d
cd backend && source venv/bin/activate && alembic upgrade head
```
