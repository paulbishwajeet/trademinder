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

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API docs: http://localhost:8000/docs

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
uvicorn app.main:app --reload --port 8000
```

API: http://localhost:8000 · Docs: http://localhost:8000/docs

---

## Local Dev — Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend: http://localhost:3000. Vite proxies `/api/*` to `http://localhost:8000`.

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

---

## Database Schema

### Design Philosophy
Each individual trade (buy, sell, assign) is its own `Trade` record. Trades on the same ticker within a wheel cycle are linked via `wheel_id`. This keeps inserts simple while enabling grouped views.

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
```
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

Full interactive docs: http://localhost:8000/docs

---

## Chrome Extension

The extension overlays TradeMinder data on the E\*TRADE portfolio page in four stages. Enabled/disabled individually via the popup settings UI. API URL is configurable (default: `http://localhost:8000`).

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
| Grid ID | `rdt_3` |
| Total positions (as observed) | 82 |
| Row height | 37px fixed, positioned via `transform: translateY(Npx)` |
| Grid width | 1200px fixed |
| Row IDs | `r0_0` through `r0_N` (recycled on scroll) |

### Confirmed Selectors
```javascript
const ETRADE = {
  gridRoot:          '#rdt_3',
  contentArea:       '.Content---root---D2Ylg',
  positionRows:      '[role="row"][level="0"]:not(.Row---placeholderRow---2t5Gs)',
  placeholderRow:    '.Row---placeholderRow---2t5Gs',
  footerRow:         '.Footer---row---g5JDN',
  symbolContent:     '.SymbolCellRenderer---content---mcwCT',
  symbolLink:        'a.SymbolCellRenderer---symbol---_S70m',
  optionClass:       'SymbolCellRenderer---option---qIlje',
  itmClass:          'SymbolCellRenderer---in-the-money---AQRUo',
  optionDescription: 'span.SymbolCellRenderer---description---KHPND',
  headerRow:         '[data-header="true"] [role="row"]',
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

## QNAP Deployment (Production)

Production target is a **QNAP TS-251+** running Container Station.

| Constraint | Detail |
|---|---|
| Architecture | Intel Celeron J1800 — `linux/amd64` only |
| Port conflicts | QNAP uses 80/443/8080; use 8000 (backend) and 3000 (frontend) |
| Volumes | Map to `/share/trademinder/` for persistence across Container Station updates |
| Memory | Keep `shared_buffers=128MB`; full stack fits in ~1GB |

```bash
# Build amd64 images on Mac
docker buildx build --platform linux/amd64 \
  -t yourdockerhub/trademinder-backend:latest --push ./backend

docker buildx build --platform linux/amd64 \
  --build-arg VITE_API_URL=http://<qnap-local-ip>:8000 \
  -t yourdockerhub/trademinder-frontend:latest --push ./frontend

# Deploy on QNAP
ssh admin@<qnap-local-ip>
cd /share/trademinder
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d

# First deploy only
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
```

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

**Extension talks directly to local backend** — calls `http://localhost:8000` (configurable). No relay server, no cloud dependency.

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
