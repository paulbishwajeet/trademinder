# TradeMinder

Personal trading assistant for options and Wheel strategy traders. Tracks trades, journals commentary, and surfaces alerts.

**Stack:** FastAPI · SQLAlchemy 2.0 async · PostgreSQL 15 · React 18 · Vite · TypeScript · Tailwind CSS v3

---

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Docker Desktop | 4.x+ | Runs PostgreSQL (required for all modes) |
| Python | 3.13 | Backend local dev |
| Node.js | 20+ | Frontend local dev |

---

## Quick Start — Full Docker

Runs everything (Postgres + backend + frontend) in containers.

```bash
# 1. Copy env file
cp .env.example .env

# 2. Start all services
docker compose up --build

# 3. Run database migrations (first time only)
docker compose exec backend alembic upgrade head
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API docs: http://localhost:8000/docs

To stop:
```bash
docker compose down
```

To stop and delete database data:
```bash
docker compose down -v
```

---

## Local Dev — Backend (venv) + Docker Postgres

This is the recommended workflow for backend development. Postgres runs in Docker; the backend runs locally for fast iteration.

### 1. Start Postgres

```bash
docker compose up db -d
```

### 2. Set up Python virtual environment

```bash
cd backend
python3.13 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

### 3. Configure environment

```bash
# From the repo root
cp .env.example .env
```

The default `.env` connects to `localhost:5432` which is where Docker exposes Postgres.

### 4. Run database migrations

```bash
cd backend
source venv/bin/activate
alembic upgrade head
```

### 5. Start the backend

```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

API available at http://localhost:8000  
Interactive docs at http://localhost:8000/docs

---

## Local Dev — Frontend

Requires the backend to be running (either locally or via Docker).

```bash
cd frontend
npm install
npm run dev
```

Frontend available at http://localhost:3000

The Vite dev server proxies `/api/*` requests to `http://localhost:8000`, so no CORS configuration is needed.

---

## Running Tests

Postgres must be running (Docker). The test suite uses a separate `trademinder_test` database that is created automatically on first `docker compose up db`.

```bash
cd backend
source venv/bin/activate
pytest tests/ -v
```

Expected: 24 tests, all passing.

---

## Environment Variables

Copy `.env.example` to `.env` and adjust as needed.

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://trademinder:password@localhost:5432/trademinder` | Change `localhost` to `db` when running inside Docker |
| `SECRET_KEY` | `changeme` | Set a strong random value in production |
| `ANTHROPIC_API_KEY` | _(empty)_ | Required for Phase 3 AI briefings |
| `ALERT_ENGINE_INTERVAL_MINUTES` | `15` | How often the alert engine runs |
| `PRICE_REFRESH_INTERVAL_MINUTES` | `15` | How often prices are fetched |
| `BRIEFING_GENERATE_TIME` | `08:00` | Daily briefing generation time |

**DATABASE_URL note:** Use `localhost:5432` when running the backend with a local venv. Use `db:5432` when running the backend inside Docker Compose.

---

## Project Structure

```
TradeMinder/
├── docker-compose.yml
├── .env.example
│
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic/                  # Database migrations
│   │   └── versions/
│   │       └── 001_initial_schema.py
│   ├── app/
│   │   ├── main.py               # FastAPI app entry point
│   │   ├── config.py             # Settings (reads from .env)
│   │   ├── database.py           # Async engine + session
│   │   ├── models/               # SQLAlchemy ORM models
│   │   ├── schemas/              # Pydantic request/response schemas
│   │   └── routers/              # API route handlers
│   └── tests/
│
└── frontend/
    ├── Dockerfile
    ├── nginx.conf                 # Production nginx config
    ├── src/
    │   ├── App.tsx               # Routes
    │   ├── api/                  # Typed API client
    │   ├── types/                # TypeScript interfaces
    │   ├── components/           # Reusable UI components
    │   └── pages/                # Page components
    └── vite.config.ts            # Dev server + /api proxy
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/api/trades` | List trades (filter by status, ticker, strategy) |
| POST | `/api/trades` | Create trade |
| GET | `/api/trades/{id}` | Get trade detail (includes rationale) |
| PATCH | `/api/trades/{id}` | Update trade |
| POST | `/api/trades/{id}/close` | Close a trade |
| DELETE | `/api/trades/{id}` | Delete trade |
| GET | `/api/trades/{id}/commentary` | List commentary for a trade |
| POST | `/api/trades/{id}/commentary` | Add commentary note |
| DELETE | `/api/commentary/{id}` | Delete a commentary entry |
| GET | `/api/alerts` | List active (non-dismissed) alerts |
| POST | `/api/alerts/{id}/read` | Mark alert as read |
| POST | `/api/alerts/{id}/dismiss` | Dismiss alert |
| GET | `/api/alerts/trade/{trade_id}` | Alerts for a specific trade |
| GET | `/api/market/*` | Market data (Phase 2 — returns 501) |
| GET | `/api/briefing/*` | Daily briefing (Phase 3 — returns 501) |

Full interactive documentation: http://localhost:8000/docs

---

## Resetting the Database

```bash
# Drop and recreate schema
cd backend
source venv/bin/activate
alembic downgrade base
alembic upgrade head
```

Or nuke the Docker volume entirely:
```bash
docker compose down -v
docker compose up db -d
cd backend && source venv/bin/activate && alembic upgrade head
```
