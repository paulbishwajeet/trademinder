# Project Overview

**Name:** TradeMinder — personal trading assistant for active stock/options traders (Wheel strategy focus)

**Stack:**
- Backend: FastAPI (Python 3.14+), SQLAlchemy 2.0 async, Alembic migrations, PostgreSQL 15, yfinance, Anthropic Claude API, APScheduler
- Frontend: React 19, Vite 8, TypeScript 6, Tailwind CSS 3, shadcn/ui (Radix UI), React Router 7
- Extension: Chrome MV3 content script (vanilla JS + CSS), overlays onto E*TRADE positions page

**Package Manager:**
- Frontend: npm (package.json in `frontend/`)
- Backend: uv (workspace in `stockpile-main/`, app in `backend/`)

**Key Directories:**
```
/backend/         FastAPI app (app/, alembic/, tests/, docker/)
/frontend/        React app (src/pages/, src/components/, src/api/, src/types/)
/extension/       Chrome extension (content.js, content.css, manifest.json, background.js, popup/)
/stockpile-main/  Python workspace with shared libs (positions, options-scanner, cost-basis-charts, shared)
/docs/            Design specs, DOM samples, planning docs
/context/         Session context files (this directory)
```

**Frontend Pages (`frontend/src/pages/`):**
- `DashboardPage.tsx` — morning briefing, AI summary, active positions overview
- `TradesPage.tsx` — trade list table with alert coloring and filters
- `TradeDetailPage.tsx` — single trade view with commentary thread
- `ScannerPage.tsx` — IV surface options scanner (routes to /scanner)
- `MarginDashboardPage.tsx` — CSV-based portfolio margin analysis (no backend dependency)

**Frontend Components (`frontend/src/components/`):**
- `Commentary/` — commentary thread UI
- `Dashboard/` — briefing/dashboard widgets
- `Trades/` — trade table, detail, forms
- `shared/` — shared UI primitives

**Coding Conventions:**
- TypeScript strict mode; functional React components with hooks
- Tailwind utility classes only (no custom CSS in frontend)
- shadcn/ui + Radix UI for interactive components
- API calls via `src/api/` — fetch wrappers typed against backend models
- Extension: vanilla JS only (no build step); CSS in `content.css`; badge injection via MutationObserver on E*TRADE DOM
- Backend routes in `backend/app/routers/`; models in `backend/app/models/`; schemas in `backend/app/schemas/`

**Testing Framework:**
- Backend: pytest (testpaths = `backend/tests/` and `stockpile-main/*/src`)
- Frontend: no test suite configured yet

**Env/Config Notes:**
- `docker-compose.yml` — local dev (postgres + backend)
- `docker-compose.prod.yml` — production
- Backend env: DATABASE_URL, ANTHROPIC_API_KEY (set in docker env or .env)
- Extension connects to backend at `http://localhost:8000` (hardcoded in content.js for local dev)

**Modules/Features List:**
- Trade CRUD + alert engine (core)
- Commentary threads per trade
- Morning briefing (AI-generated via Claude)
- Chrome extension overlay (E*TRADE positions page)
  - Status badges (DTE, RSI, commentary count)
  - Hover-reveal commentary panel
  - Inline add-trade modal
  - Filter toolbar
- Options scanner (IV surface, yfinance)
- Margin dashboard (CSV import, client-side analysis)
- RSI column / scanner integration
