# Project Overview

> A short map for starting a session. The detailed, authoritative reference is
> **`docs/TRADEMINDER_MASTER_CONTEXT.md`** (its dated Current State section wins over anything here); decision
> history is in `docs/decisions.md`. Keep this file short so the two don't drift into duplicates.

**Name:** TradeMinder — trading assistant for an options income trader running the Wheel strategy. Multi-user
(small LAN pilot) since 2026-11-11; production on a QNAP NAS at `https://tm.<domain>` (LAN only).

**Stack:**
- **Backend:** FastAPI, SQLAlchemy 2.0 async (asyncpg), Alembic, PostgreSQL 15, APScheduler. Python 3.13 in Docker
  (`pyproject` allows >=3.11).
- **Market data:** Schwab REST behind a provider boundary; yfinance only for earnings and the LEAPS scanner.
- **LLMs:** Gemini 2.5 Flash for signal commentary, Claude Haiku 4.5 for commentary summaries; both optional.
- **Auth:** Google OIDC with backend sessions, plus extension bearer tokens.
- **Frontend:** React 19, Vite 8, TypeScript 6 (strict), Tailwind 3, React Router 7, Radix (Dialog, Collapsible,
  Popover), cmdk, lucide. shadcn-style primitives are written by hand in `src/components/ui/`; the shadcn CLI isn't
  set up.
- **Extension:** Chrome MV3, vanilla JS, no build step.
- **Deploy:** Docker Compose as a Portainer Git stack; Traefik on 443 (Let's Encrypt via Cloudflare DNS-01).

**Package managers:**
- Frontend: npm (`frontend/package.json`).
- Backend: uv (`backend/pyproject.toml`, `backend/uv.lock`; venv at `backend/.venv`). An older `backend/venv`
  also exists [?].

**Key directories:**
```
backend/            FastAPI app: app/{routers,services,models,schemas}, alembic/versions (head 018), tests/
frontend/           React SPA: src/{pages,components,api,context,lib,hooks,types}
extension/          Chrome MV3: content.js, background.js, popup/, manifest.json
docs/               TRADEMINDER_MASTER_CONTEXT.md, decisions.md, deployment/, superpowers/{specs,plans}
context/            Working notes (this directory); see README.md for the template
stockpile-main/     Older Python workspace (options scanner etc.), partly superseded
```

**Conventions (observed):**
- Branches: `feature/<name>` off `develop`; `--no-ff` merges into `develop`, then `develop` into `master` (done in
  the `../trademinder-release` worktree, which is on `master`). Feature branches are pushed and kept.
- Commits: conventional prefixes (`feat(wheel):`, `fix(...)`, `docs(...)`); never commit unless asked.
- Backend: thin routers, logic in services, Pydantic schemas as the contract. Every router except auth and me is
  mounted behind the `get_current_user` seam; all data is scoped by user and account.
- Frontend: TypeScript strict, functional components, Tailwind only, typed fetch wrappers in `src/api/`. Filter
  state lives in URL search params, and open overlays carry `data-escape-layer`.
- Decimals arrive from the API as JSON strings.
- Extension: every network call goes through `bgFetch` to the service worker.
- Development happens in `.claude/worktrees/<name>` while the user's dev servers run from the main checkout;
  verification runs on a copy of the dev DB.

**Testing:**
- Backend: pytest (`backend/tests`, run from `backend/`); 6 known pre-existing failures.
- Frontend: no test suite. The production build (`npm run build` = `tsc -b && vite build`) is the type gate, and
  the NAS runs it.

**Env/config notes:**
- Local `.env` at the repo root (git-ignored); `.env.example` lists the names.
- Production values live only in the Portainer stack's environment.
- Dev servers: Vite `:5430` (proxies `/api` to `:5431`), uvicorn `--reload` `:5431`, Postgres `:5432` in Docker.
  Locally the extension's server address is `http://localhost:5430`.

**Modules/Features list** (✅ = done and on `master`):
- ✅ Trades CRUD, categories, commentary threads, rationale snapshots
- ✅ Alert engine and signal engine (alerts cover trades only, not wheel slots)
- ✅ WHEEL v2: slots, legs, signed premium logs, resolve flow, CC/SP Signal and Timing, slot commentary
- ✅ WHEEL filter bar (symbol) and NEW — NEEDS SLOT collapse/edit/delete
- ✅ Spreads (legacy `trade_sessions`)
- ✅ Screener, Chain screener (sell_put only), Scanner (LEAPS IV surface)
- ✅ Margin dashboard (CSV, client-side Black-Scholes)
- ✅ Chrome extension: badges, hover commentary, alert tinting, wheel pills, Reconcile, account awareness, sign-in
- ✅ Multi-user: accounts and ownership, account container UI, Schwab hardening, Google sign-in and HTTPS
- ⏳ In-app Schwab reconnect, phase 1 (`feature/schwab-reconnect`, unmerged)
- ⏳ Morning briefing: endpoint returns 501 (stub)
