# Spreads Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Iron Condor (IC) and Put Broken Wing Butterfly (PBWB) multi-leg strategy sessions, extending the existing WHEEL session infrastructure with a Spreads Dashboard page and live price-signal pills in the Chrome extension.

**Architecture:** Reuse the existing `trade_sessions` table (strategy/status are unconstrained VARCHAR columns — no migration needed). The backend lookup endpoint is generalized to cover all strategies per ticker and extended to return leg strike data. The extension session cache is broadened to all strategies; a new price cache drives a colored IC/PBWB status pill. A new `/spreads` React page mirrors WheelDashboardPage with a price indicator bar on each session card.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Pydantic v2, pytest/httpx, React 19, TypeScript 6, Tailwind CSS, Chrome MV3 vanilla JS.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `backend/app/schemas/session.py` | Modify | Add `SessionLookupItem`; change lookup response to include legs |
| `backend/app/routers/sessions.py` | Modify | Optional strategy filter; fix closed-status exclusion; eagerly load legs in lookup |
| `backend/tests/test_sessions.py` | Modify | Tests for new lookup behaviour (no-strategy, closed exclusion, legs in response) |
| `frontend/src/api/sessions.ts` | Modify | Broaden status union type; add `listSpreads` and `quotePrice` helpers |
| `frontend/src/App.tsx` | Modify | Add `/spreads` route and nav link |
| `frontend/src/components/Spreads/SpreadSessionCard.tsx` | Create | Session card with legs table, price signal indicator, close-session button |
| `frontend/src/pages/SpreadsDashboardPage.tsx` | Create | Page: fetches IC+PBWB sessions + prices; renders SpreadSessionCards |
| `extension/content.js` | Modify (×2 tasks) | Generalise session fetch + price cache + strategy pill; session picker in Add Trade modal |

---

## Task 1: Backend — Generalise session lookup (schema + router)

**Files:**
- Modify: `backend/app/schemas/session.py`
- Modify: `backend/app/routers/sessions.py`

- [ ] **Step 1: Add `SessionLookupItem` to schema and update `SessionLookupResponse`**

Open `backend/app/schemas/session.py`. Add `SessionLookupItem` after `SessionWithLegs` and update `SessionLookupResponse.sessions` type:

```python
# backend/app/schemas/session.py
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict


class SessionCreate(BaseModel):
    ticker: str
    strategy: str = "WHEEL"
    status: str
    opened_at: date
    rotation_number: int = 1
    parent_session_id: Optional[uuid.UUID] = None


class SessionUpdate(BaseModel):
    status: Optional[str] = None
    closed_at: Optional[date] = None


class SessionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticker: str
    strategy: str
    status: str
    rotation_number: int
    opened_at: date
    closed_at: Optional[date] = None
    parent_session_id: Optional[uuid.UUID] = None


class SessionLegItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    strategy: str
    ticker: str
    open_date: date
    expiry_date: Optional[date] = None
    strike_price: Optional[Decimal] = None
    quantity: int
    premium: Optional[Decimal] = None
    status: str


class SessionWithLegs(SessionSummary):
    legs: list[SessionLegItem] = []
    rotation_chain: list[SessionSummary] = []


# Lightweight session shape used in lookup responses — includes legs but not rotation_chain
class SessionLookupItem(SessionSummary):
    legs: list[SessionLegItem] = []


class SessionLookupResponse(BaseModel):
    ticker: str
    strategy: str          # "any" when no strategy filter was applied
    has_existing: bool
    sessions: list[SessionLookupItem]
```

- [ ] **Step 2: Update the lookup endpoint in the router**

Open `backend/app/routers/sessions.py`. Replace the existing `lookup_sessions` function and update the import of `SessionLookupResponse` to also import `SessionLookupItem`:

```python
from app.schemas.session import (
    SessionCreate, SessionUpdate, SessionSummary,
    SessionWithLegs, SessionLegItem, SessionLookupResponse, SessionLookupItem,
)
```

Then replace the `lookup_sessions` function (the entire `@router.get("/lookup")` block):

```python
@router.get("/lookup", response_model=SessionLookupResponse)
async def lookup_sessions(
    ticker: str = Query(...),
    strategy: Optional[str] = Query(None),   # was: str = Query("WHEEL")
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(TradeSession)
        .where(
            TradeSession.ticker == ticker.upper(),
            TradeSession.status.not_in(["completed", "closed"]),  # was: != "completed"
        )
        .options(selectinload(TradeSession.legs))
    )
    if strategy:
        stmt = stmt.where(TradeSession.strategy == strategy)
    stmt = stmt.order_by(TradeSession.rotation_number.desc())
    result = await db.execute(stmt)
    sessions = result.scalars().all()
    return SessionLookupResponse(
        ticker=ticker.upper(),
        strategy=strategy or "any",
        has_existing=len(sessions) > 0,
        sessions=[SessionLookupItem.model_validate(s) for s in sessions],
    )
```

- [ ] **Step 3: Run existing session tests to confirm nothing is broken**

```bash
cd /path/to/project && uv run pytest backend/tests/test_sessions.py -v
```

Expected: all existing tests pass. The `test_session_lookup_with_existing` test passes `strategy=WHEEL` explicitly — this still works because `strategy` being optional doesn't break callers that pass it.

- [ ] **Step 4: Commit**

```bash
git add backend/app/schemas/session.py backend/app/routers/sessions.py
git commit -m "feat: generalise session lookup — optional strategy, include legs, exclude closed"
```

---

## Task 2: Backend — Tests for new lookup behaviour

**Files:**
- Modify: `backend/tests/test_sessions.py`

- [ ] **Step 1: Write failing tests**

Add these three tests at the end of `backend/tests/test_sessions.py`:

```python
async def test_session_lookup_no_strategy_returns_all_strategies(client: AsyncClient):
    """Omitting strategy= returns sessions across all strategies for the ticker."""
    await client.post("/api/sessions", json=SESSION_PAYLOAD)  # WHEEL put_open
    await client.post("/api/sessions", json={
        **SESSION_PAYLOAD,
        "strategy": "IRON_CONDOR",
        "status": "open",
    })
    response = await client.get("/api/sessions/lookup?ticker=NVDA")
    assert response.status_code == 200
    data = response.json()
    assert data["has_existing"] is True
    assert data["strategy"] == "any"
    assert len(data["sessions"]) == 2


async def test_session_lookup_excludes_closed(client: AsyncClient):
    """Lookup does not return sessions with status='closed'."""
    await client.post("/api/sessions", json={
        **SESSION_PAYLOAD,
        "strategy": "IRON_CONDOR",
        "status": "closed",
    })
    response = await client.get("/api/sessions/lookup?ticker=NVDA")
    assert response.status_code == 200
    assert response.json()["has_existing"] is False


async def test_session_lookup_includes_legs(client: AsyncClient):
    """Lookup response embeds linked trade legs in each session."""
    session_resp = await client.post("/api/sessions", json={
        **SESSION_PAYLOAD,
        "strategy": "IRON_CONDOR",
        "status": "open",
    })
    session_id = session_resp.json()["id"]
    await client.post("/api/trades", json={**TRADE_PAYLOAD, "session_id": session_id})

    response = await client.get("/api/sessions/lookup?ticker=NVDA&strategy=IRON_CONDOR")
    assert response.status_code == 200
    data = response.json()
    assert len(data["sessions"]) == 1
    assert len(data["sessions"][0]["legs"]) == 1
    assert data["sessions"][0]["legs"][0]["strike_price"] == "120.00"
```

- [ ] **Step 2: Run to confirm they fail first**

```bash
uv run pytest backend/tests/test_sessions.py::test_session_lookup_no_strategy_returns_all_strategies backend/tests/test_sessions.py::test_session_lookup_excludes_closed backend/tests/test_sessions.py::test_session_lookup_includes_legs -v
```

Expected: FAIL — the router was already updated in Task 1, so these should actually pass. If they pass here, that's fine — the implementation was correct.

- [ ] **Step 3: Run full session test suite**

```bash
uv run pytest backend/tests/test_sessions.py -v
```

Expected: all tests pass (17+ tests).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_sessions.py
git commit -m "test: add lookup tests for no-strategy filter, closed exclusion, legs in response"
```

---

## Task 3: Frontend — API helpers, types, routing

**Files:**
- Modify: `frontend/src/api/sessions.ts`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Update `sessions.ts` — broaden status type and add spread helpers**

Replace the full content of `frontend/src/api/sessions.ts`:

```typescript
// frontend/src/api/sessions.ts
import { apiFetch } from './client'
import type { SessionSummary, SessionWithLegs, SessionLookupResponse } from '../types'

export interface SessionCreate {
  ticker: string
  strategy: string
  status: string   // broadened: was a narrow union; IC/PBWB use 'open', WHEEL uses put_open etc.
  opened_at: string
  rotation_number?: number
  parent_session_id?: string | null
}

export interface SessionUpdate {
  status?: string
  closed_at?: string | null
}

export const sessionsApi = {
  list: (params?: { strategy?: string; status?: string; ticker?: string }) => {
    const entries = Object.entries(params ?? {}).filter((e): e is [string, string] => e[1] !== undefined)
    const qs = entries.length ? '?' + new URLSearchParams(entries).toString() : ''
    return apiFetch<SessionSummary[]>(`/sessions${qs}`)
  },

  get: (id: string) => apiFetch<SessionWithLegs>(`/sessions/${id}`),

  create: (payload: SessionCreate) =>
    apiFetch<SessionSummary>('/sessions', { method: 'POST', body: JSON.stringify(payload) }),

  update: (id: string, payload: SessionUpdate) =>
    apiFetch<SessionSummary>(`/sessions/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  lookup: (ticker: string, strategy?: string) => {
    const qs = strategy ? `&strategy=${encodeURIComponent(strategy)}` : ''
    return apiFetch<SessionLookupResponse>(`/sessions/lookup?ticker=${encodeURIComponent(ticker)}${qs}`)
  },

  // Fetch open sessions for a spread strategy (IC or PBWB)
  listSpreads: (strategy: 'IRON_CONDOR' | 'PUT_B_W_FLY', status = 'open') =>
    apiFetch<SessionSummary[]>(`/sessions?strategy=${strategy}&status=${status}`),
}

export async function quotePrice(ticker: string): Promise<number | null> {
  try {
    const data = await apiFetch<{ price: number }>(`/market/quote/${encodeURIComponent(ticker)}`)
    return data.price ?? null
  } catch {
    return null
  }
}
```

- [ ] **Step 2: Add `/spreads` route and nav link to `App.tsx`**

Open `frontend/src/App.tsx`. Add the import and route:

```typescript
// frontend/src/App.tsx
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import { DashboardPage } from './pages/DashboardPage'
import { TradesPage } from './pages/TradesPage'
import { TradeDetailPage } from './pages/TradeDetailPage'
import { MarginDashboardPage } from './pages/MarginDashboardPage'
import { ScannerPage } from './pages/ScannerPage'
import { WheelDashboardPage } from './pages/WheelDashboardPage'
import { SpreadsDashboardPage } from './pages/SpreadsDashboardPage'

function NavItem({ to, label }: { to: string; label: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `px-4 py-2 text-sm font-medium rounded ${isActive ? 'bg-blue-600 text-white' : 'text-gray-600 hover:bg-gray-100'}`
      }
    >
      {label}
    </NavLink>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-50">
        <nav className="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-2">
          <span className="font-bold text-gray-900 mr-4">TradeMinder</span>
          <NavItem to="/" label="Dashboard" />
          <NavItem to="/trades" label="Trades" />
          <NavItem to="/wheel" label="WHEEL" />
          <NavItem to="/spreads" label="Spreads" />
          <NavItem to="/margin" label="Margin" />
          <NavItem to="/scanner" label="Scanner" />
        </nav>
        <main>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/trades" element={<TradesPage />} />
            <Route path="/trades/:id" element={<TradeDetailPage />} />
            <Route path="/wheel" element={<WheelDashboardPage />} />
            <Route path="/spreads" element={<SpreadsDashboardPage />} />
            <Route path="/margin" element={<MarginDashboardPage />} />
            <Route path="/scanner" element={<ScannerPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: 0 errors. (The `SpreadsDashboardPage` import will produce an error until Task 5 creates the file — that's fine, fix it after Task 5.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/sessions.ts frontend/src/App.tsx
git commit -m "feat: add spread session API helpers and /spreads route"
```

---

## Task 4: Frontend — SpreadSessionCard component

**Files:**
- Create: `frontend/src/components/Spreads/SpreadSessionCard.tsx`

- [ ] **Step 1: Create the component directory and file**

```bash
mkdir -p frontend/src/components/Spreads
```

Create `frontend/src/components/Spreads/SpreadSessionCard.tsx`:

```typescript
// frontend/src/components/Spreads/SpreadSessionCard.tsx
import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { SessionWithLegs, SessionLeg } from '../../types'
import { sessionsApi } from '../../api/sessions'

interface Props {
  session: SessionWithLegs
  price: number | null
  onClosed: (id: string) => void
}

const STRATEGY_LABELS: Record<string, string> = {
  IRON_CONDOR: 'IC',
  PUT_B_W_FLY: 'PBWB',
}

const STRATEGY_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  IRON_CONDOR: { bg: '#EDE9FE', text: '#5B21B6', border: '#C4B5FD' },
  PUT_B_W_FLY: { bg: '#CCFBF1', text: '#0F766E', border: '#5EEAD4' },
}

type Signal = 'safe' | 'warning' | 'danger' | 'unknown'

function computeSignal(legs: SessionLeg[], price: number, strategy: string): Signal {
  if (strategy === 'IRON_CONDOR') {
    const shortPutStrikes = legs
      .filter(l => l.strategy === 'Sell Put' && l.strike_price != null)
      .map(l => l.strike_price as number)
    const shortCallStrikes = legs
      .filter(l => l.strategy === 'Sell Call' && l.strike_price != null)
      .map(l => l.strike_price as number)
    if (!shortPutStrikes.length || !shortCallStrikes.length) return 'unknown'
    const sp = Math.max(...shortPutStrikes)
    const sc = Math.min(...shortCallStrikes)
    if (price <= sp || price >= sc) return 'danger'
    if (price < sp * 1.05 || price > sc * 0.95) return 'warning'
    return 'safe'
  }
  if (strategy === 'PUT_B_W_FLY') {
    const shortStrikes = legs
      .filter(l => l.strategy === 'Sell Put' && l.strike_price != null)
      .map(l => l.strike_price as number)
    if (shortStrikes.length < 2) return 'unknown'
    const low = Math.min(...shortStrikes)
    const high = Math.max(...shortStrikes)
    if (price <= low || price >= high) return 'danger'
    if (price < low * 1.05 || price > high * 0.95) return 'warning'
    return 'safe'
  }
  return 'unknown'
}

const SIGNAL_STYLES: Record<Signal, { bg: string; border: string; text: string; icon: string; label: string }> = {
  safe:    { bg: 'bg-green-50', border: 'border-green-200', text: 'text-green-700', icon: '✓', label: 'Safe' },
  warning: { bg: 'bg-amber-50', border: 'border-amber-200', text: 'text-amber-700', icon: '⚠', label: 'Approaching' },
  danger:  { bg: 'bg-red-50',   border: 'border-red-200',   text: 'text-red-700',   icon: '✗', label: 'Breached' },
  unknown: { bg: 'bg-gray-50',  border: 'border-gray-200',  text: 'text-gray-400',  icon: '?', label: 'No signal' },
}

function PriceSignal({ session, price }: { session: SessionWithLegs; price: number | null }) {
  if (price == null) {
    return <span className="text-xs text-gray-400">Price unavailable</span>
  }
  const signal = computeSignal(session.legs, price, session.strategy)
  const s = SIGNAL_STYLES[signal]
  return (
    <span className={`text-xs px-2 py-0.5 rounded border ${s.bg} ${s.border} ${s.text}`}>
      {s.icon} {s.label} · ${price.toFixed(2)}
    </span>
  )
}

export function SpreadSessionCard({ session, price, onClosed }: Props) {
  const [expanded, setExpanded] = useState(false)
  const [closing, setClosing] = useState(false)
  const [closeError, setCloseError] = useState<string | null>(null)

  const strategyLabel = STRATEGY_LABELS[session.strategy] ?? session.strategy
  const strategyColor = STRATEGY_COLORS[session.strategy] ?? { bg: '#F3F4F6', text: '#374151', border: '#D1D5DB' }

  const expiry = session.legs.find(l => l.expiry_date)?.expiry_date ?? null

  async function handleClose() {
    setClosing(true)
    setCloseError(null)
    try {
      await sessionsApi.update(session.id, { status: 'closed', closed_at: new Date().toISOString().slice(0, 10) })
      onClosed(session.id)
    } catch {
      setCloseError('Failed to close session')
    } finally {
      setClosing(false)
    }
  }

  return (
    <div
      className="bg-white border border-gray-200 rounded-lg overflow-hidden"
      style={{ borderLeft: `4px solid ${strategyColor.border}` }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-gray-50 select-none"
        onClick={() => setExpanded(e => !e)}
      >
        <div className="flex items-center gap-3">
          <span
            className="text-gray-400 text-xs inline-block transition-transform duration-150"
            style={{ transform: expanded ? 'rotate(0deg)' : 'rotate(-90deg)' }}
          >▼</span>
          <span className="font-bold text-gray-900">{session.ticker}</span>
          <span
            className="text-xs font-medium px-2 py-0.5 rounded-full"
            style={{ background: strategyColor.bg, color: strategyColor.text, border: `1px solid ${strategyColor.border}` }}
          >
            {strategyLabel}
          </span>
          {expiry && <span className="text-xs text-gray-400">exp {expiry}</span>}
        </div>
        <div className="flex items-center gap-3" onClick={e => e.stopPropagation()}>
          <PriceSignal session={session} price={price} />
          <button
            onClick={handleClose}
            disabled={closing}
            className="px-2 py-1 text-xs border border-gray-300 rounded hover:bg-gray-100 disabled:opacity-50"
          >
            {closing ? 'Closing…' : 'Close Session'}
          </button>
        </div>
      </div>

      {closeError && (
        <p className="px-4 pb-2 text-xs text-red-600">{closeError}</p>
      )}

      {/* Expanded legs */}
      {expanded && (
        <div className="border-t border-gray-100 px-4 py-3">
          <div className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">
            Legs · opened {session.opened_at}
          </div>
          {session.legs.length === 0 ? (
            <p className="text-xs text-gray-400 italic">No legs linked yet.</p>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-gray-400 border-b border-gray-100">
                  <th className="pb-1 pr-3 font-normal">Date</th>
                  <th className="pb-1 pr-3 font-normal">Strategy</th>
                  <th className="pb-1 pr-3 font-normal">Type</th>
                  <th className="pb-1 pr-3 font-normal">Strike</th>
                  <th className="pb-1 pr-3 font-normal">Expiry</th>
                  <th className="pb-1 pr-3 font-normal">Qty</th>
                  <th className="pb-1 pr-3 font-normal">Premium</th>
                  <th className="pb-1 font-normal"></th>
                </tr>
              </thead>
              <tbody>
                {session.legs.map(leg => (
                  <tr key={leg.id} className="border-t border-gray-50">
                    <td className="py-1.5 pr-3 text-gray-500">{leg.open_date}</td>
                    <td className="py-1.5 pr-3">{leg.strategy}</td>
                    <td className="py-1.5 pr-3">{leg.type}</td>
                    <td className="py-1.5 pr-3">{leg.strike_price != null ? `$${leg.strike_price}` : '—'}</td>
                    <td className="py-1.5 pr-3">{leg.expiry_date ?? '—'}</td>
                    <td className="py-1.5 pr-3">{leg.quantity}</td>
                    <td className="py-1.5 pr-3">{leg.premium != null ? `$${leg.premium}` : '—'}</td>
                    <td className="py-1.5">
                      <Link to={`/trades/${leg.id}`} className="text-blue-500 hover:underline">view</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: 0 errors (or only the missing `SpreadsDashboardPage` import in `App.tsx` which is resolved next task).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Spreads/SpreadSessionCard.tsx
git commit -m "feat: add SpreadSessionCard with price signal indicator"
```

---

## Task 5: Frontend — SpreadsDashboardPage

**Files:**
- Create: `frontend/src/pages/SpreadsDashboardPage.tsx`

- [ ] **Step 1: Create the page**

Create `frontend/src/pages/SpreadsDashboardPage.tsx`:

```typescript
// frontend/src/pages/SpreadsDashboardPage.tsx
import { useState, useEffect } from 'react'
import type { SessionSummary, SessionWithLegs } from '../types'
import { sessionsApi, quotePrice } from '../api/sessions'
import { SpreadSessionCard } from '../components/Spreads/SpreadSessionCard'

export function SpreadsDashboardPage() {
  const [sessions, setSessions] = useState<SessionWithLegs[]>([])
  const [closedSessions, setClosedSessions] = useState<SessionSummary[]>([])
  const [prices, setPrices] = useState<Record<string, number | null>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      // Fetch open IC and PBWB sessions in parallel
      const [icSummaries, pbwbSummaries, icClosed, pbwbClosed] = await Promise.all([
        sessionsApi.listSpreads('IRON_CONDOR', 'open'),
        sessionsApi.listSpreads('PUT_B_W_FLY', 'open'),
        sessionsApi.listSpreads('IRON_CONDOR', 'closed'),
        sessionsApi.listSpreads('PUT_B_W_FLY', 'closed'),
      ])

      // Fetch full leg detail for each open session
      const openSummaries = [...icSummaries, ...pbwbSummaries]
      const detailed = await Promise.all(openSummaries.map(s => sessionsApi.get(s.id)))
      setSessions(detailed)
      setClosedSessions([...icClosed, ...pbwbClosed])

      // Fetch current price for each unique ticker
      const tickers = [...new Set(openSummaries.map(s => s.ticker))]
      const priceResults = await Promise.all(tickers.map(t => quotePrice(t)))
      const priceMap: Record<string, number | null> = {}
      tickers.forEach((t, i) => { priceMap[t] = priceResults[i] })
      setPrices(priceMap)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load sessions')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  function handleClosed(id: string) {
    const session = sessions.find(s => s.id === id)
    if (session) setClosedSessions(prev => [{ ...session, status: 'closed' }, ...prev])
    setSessions(prev => prev.filter(s => s.id !== id))
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Spreads Dashboard</h1>
      </div>

      {loading && <p className="text-gray-500 text-center py-12">Loading…</p>}

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded p-4 mb-4 text-sm">{error}</div>
      )}

      {!loading && !error && sessions.length === 0 && (
        <div className="text-center py-16">
          <p className="text-gray-400 mb-2">No open spread sessions.</p>
          <p className="text-sm text-gray-400">
            Add a trade in the E*TRADE extension and link it to a new IC or PBWB session.
          </p>
        </div>
      )}

      {!loading && !error && sessions.length > 0 && (
        <section className="mb-8">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-sm font-bold text-gray-700">OPEN POSITIONS</span>
            <span className="bg-gray-100 text-gray-600 text-xs px-2 py-0.5 rounded-full font-medium">
              {sessions.length}
            </span>
          </div>
          <div className="space-y-2">
            {sessions.map(s => (
              <SpreadSessionCard
                key={s.id}
                session={s}
                price={prices[s.ticker] ?? null}
                onClosed={handleClosed}
              />
            ))}
          </div>
        </section>
      )}

      {!loading && !error && closedSessions.length > 0 && (
        <section>
          <div className="flex items-center gap-2 mb-3">
            <span className="text-sm font-bold text-gray-400">CLOSED</span>
            <span className="bg-gray-100 text-gray-400 text-xs px-2 py-0.5 rounded-full font-medium">
              {closedSessions.length}
            </span>
          </div>
          <div className="space-y-1">
            {closedSessions.map(s => (
              <div key={s.id} className="flex items-center gap-3 px-4 py-2 bg-white border border-gray-100 rounded text-sm text-gray-500">
                <span className="font-medium text-gray-700">{s.ticker}</span>
                <span className="text-xs">{s.strategy === 'IRON_CONDOR' ? 'IC' : 'PBWB'}</span>
                <span className="text-xs">{s.opened_at} → {s.closed_at ?? '—'}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Run TypeScript check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 3: Start dev server and verify the page loads**

```bash
cd frontend && npm run dev
```

Navigate to `http://localhost:5173/spreads`. Expected: "No open spread sessions" empty state renders without errors (backend calls will 200 with empty arrays if no IC/PBWB sessions exist yet).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/SpreadsDashboardPage.tsx
git commit -m "feat: add SpreadsDashboardPage at /spreads with price indicator"
```

---

## Task 6: Extension — Generalise session fetch + price cache + strategy pill

**Files:**
- Modify: `extension/content.js` (state section ~line 38, processVisibleRows ~line 382, renderWheelPill ~line 596, applyWheelPillToRow ~line 626, fetchWheelSessionsForTickers ~line 1140)

- [ ] **Step 1: Add `priceCache` to the state section**

After line 38 (`const sessionCache = new Map();`), add:

```javascript
// ticker (uppercase) → current price (number) | null (spread session price signal)
const priceCache = new Map();
```

- [ ] **Step 2: Rename `fetchWheelSessionsForTickers` and remove the strategy filter**

Replace the entire `fetchWheelSessionsForTickers` function (lines ~1140–1155) with:

```javascript
async function fetchSessionsForTickers(tickers) {
  const unique = [...new Set(tickers.map(t => t.toUpperCase()))];
  await Promise.all(unique.map(async ticker => {
    if (sessionCache.has(ticker)) return; // already fetched this page load
    try {
      const res = await fetch(
        `${tmApiUrl}/api/sessions/lookup?ticker=${encodeURIComponent(ticker)}`,
        { signal: AbortSignal.timeout(5000) },
      );
      if (!res.ok) { sessionCache.set(ticker, null); return; }
      const data = await res.json();
      sessionCache.set(ticker, data.has_existing && data.sessions?.length ? data.sessions[0] : null);
    } catch {
      sessionCache.set(ticker, null);
    }
  }));
}
```

- [ ] **Step 3: Add `fetchPricesForSpreadSessions`**

Add this function immediately after `fetchSessionsForTickers`:

```javascript
async function fetchPricesForSpreadSessions(tickers) {
  const spreadTickers = tickers
    .map(t => t.toUpperCase())
    .filter(t => {
      const s = sessionCache.get(t);
      return s && (s.strategy === 'IRON_CONDOR' || s.strategy === 'PUT_B_W_FLY');
    });
  await Promise.all(spreadTickers.map(async ticker => {
    if (priceCache.has(ticker)) return;
    try {
      const res = await fetch(
        `${tmApiUrl}/api/market/quote/${encodeURIComponent(ticker)}`,
        { signal: AbortSignal.timeout(5000) },
      );
      if (!res.ok) { priceCache.set(ticker, null); return; }
      const data = await res.json();
      priceCache.set(ticker, typeof data.price === 'number' ? data.price : null);
    } catch {
      priceCache.set(ticker, null);
    }
  }));
}
```

- [ ] **Step 4: Add `computePriceSignal` and `renderStrategyPill`**

Add these two functions immediately after `renderWheelPill` (after line ~624):

```javascript
function computePriceSignal(session) {
  const price = priceCache.get(session.ticker?.toUpperCase());
  if (price == null) return 'unknown';
  const legs = session.legs || [];

  if (session.strategy === 'IRON_CONDOR') {
    const shortPutStrikes = legs
      .filter(l => l.strategy === 'Sell Put' && l.strike_price != null)
      .map(l => Number(l.strike_price));
    const shortCallStrikes = legs
      .filter(l => l.strategy === 'Sell Call' && l.strike_price != null)
      .map(l => Number(l.strike_price));
    if (!shortPutStrikes.length || !shortCallStrikes.length) return 'unknown';
    const sp = Math.max(...shortPutStrikes);
    const sc = Math.min(...shortCallStrikes);
    if (price <= sp || price >= sc) return 'danger';
    if (price < sp * 1.05 || price > sc * 0.95) return 'warning';
    return 'safe';
  }

  if (session.strategy === 'PUT_B_W_FLY') {
    const shortStrikes = legs
      .filter(l => l.strategy === 'Sell Put' && l.strike_price != null)
      .map(l => Number(l.strike_price));
    if (shortStrikes.length < 2) return 'unknown';
    const low = Math.min(...shortStrikes);
    const high = Math.max(...shortStrikes);
    if (price <= low || price >= high) return 'danger';
    if (price < low * 1.05 || price > high * 0.95) return 'warning';
    return 'safe';
  }
  return 'unknown';
}

function renderStrategyPill(session) {
  if (!session) return null;
  const signal = computePriceSignal(session);
  const shortLabel = session.strategy === 'IRON_CONDOR' ? 'IC' : 'PBWB';
  const icons = { safe: '✓', warning: '⚠', danger: '✗', unknown: '' };
  const icon = icons[signal] || '';
  const label = icon ? `${shortLabel} ${icon}` : shortLabel;

  const colorMap = {
    safe: session.strategy === 'IRON_CONDOR'
      ? { bg: '#EDE9FE', color: '#5B21B6', border: '#C4B5FD' }
      : { bg: '#CCFBF1', color: '#0F766E', border: '#5EEAD4' },
    warning: { bg: '#FEF3C7', color: '#92400E', border: '#FCD34D' },
    danger:  { bg: '#FEE2E2', color: '#991B1B', border: '#FCA5A5' },
    unknown: session.strategy === 'IRON_CONDOR'
      ? { bg: '#EDE9FE', color: '#5B21B6', border: '#C4B5FD' }
      : { bg: '#CCFBF1', color: '#0F766E', border: '#5EEAD4' },
  };
  const c = colorMap[signal];

  const pill = document.createElement('span');
  pill.className = 'tm-strategy-pill';
  pill.textContent = label;
  pill.style.cssText = [
    'display:inline-flex', 'align-items:center', 'font-size:10px',
    'padding:1px 5px', 'border-radius:3px', 'margin-left:4px', 'white-space:nowrap',
    `background:${c.bg}`, `color:${c.color}`, `border:1px solid ${c.border}`,
  ].join(';');
  return pill;
}
```

- [ ] **Step 5: Update `applyWheelPillToRow` to handle all strategies**

Replace the existing `applyWheelPillToRow` function (~lines 626–638) with:

```javascript
function applyWheelPillToRow(row, ticker) {
  const flyoutBtn = row.querySelector('button[aria-label="Open Quote Flyout"]');
  if (!flyoutBtn) return;
  const symbolDiv = flyoutBtn.parentElement;
  symbolDiv.querySelector('.tm-wheel-pill')?.remove();
  symbolDiv.querySelector('.tm-strategy-pill')?.remove();

  if (!sessionCache.has(ticker)) return;
  const session = sessionCache.get(ticker);
  if (!session) return;

  if (session.strategy === 'WHEEL') {
    const pill = renderWheelPill(session);
    if (pill) symbolDiv.appendChild(pill);
  } else {
    const pill = renderStrategyPill(session);
    if (pill) symbolDiv.appendChild(pill);
  }
}
```

- [ ] **Step 6: Update `processVisibleRows` to chain price fetch after session fetch**

At line ~383, replace:

```javascript
    // Fire-and-forget: prefetch wheel sessions for all visible tickers (fills sessionCache async)
    if (seenTickers.size > 0) {
      fetchWheelSessionsForTickers([...seenTickers]);
    }
```

with:

```javascript
    // Fire-and-forget: fetch sessions for all strategies, then prices for spread sessions
    if (seenTickers.size > 0) {
      fetchSessionsForTickers([...seenTickers]).then(async () => {
        await fetchPricesForSpreadSessions([...seenTickers]);
        // Re-apply pills now that price data is available
        document.querySelectorAll(ETRADE.positionRows).forEach(row => {
          const info = getRowInfo(row);
          if (info?.ticker) applyWheelPillToRow(row, info.ticker);
        });
      });
    }
```

- [ ] **Step 7: Test in E*TRADE**

Load the extension on E*TRADE. Expected:
- WHEEL rows still show their blue/amber pills as before
- Tickers with IC/PBWB sessions (once added via Task 7) show purple/teal pills
- No console errors

- [ ] **Step 8: Commit**

```bash
git add extension/content.js
git commit -m "feat: generalise extension session fetch, add price-signal strategy pill for IC/PBWB"
```

---

## Task 7: Extension — Session picker in Add Trade modal

**Files:**
- Modify: `extension/content.js` (showAddTradeModal ~line 1300, submit handler ~line 1419)

- [ ] **Step 1: Add session picker HTML row to the modal template**

Inside `showAddTradeModal`, in the `overlay.innerHTML = \`...\`` template string, add the session picker row after the category field row (after the `</div>` that closes the category `tm-field-row`):

Locate the block ending with:
```javascript
        <div class="tm-field-row tm-field-full">
          <label>Category <span class="tm-required">*</span></label>
          <select name="category">
            ${buildCategoryOptions(categories, 'WHEEL')}
          </select>
        </div>
```

Add immediately after it:

```javascript
        ${info.isOption ? `
        <div class="tm-field-row tm-field-full" id="tm-session-row">
          <label>Spread Session <span style="font-weight:normal;color:#6B7280">(optional)</span></label>
          <select name="session_id" id="tm-session-select">
            <option value="">Loading…</option>
          </select>
        </div>` : ''}
```

- [ ] **Step 2: Populate session picker after modal is inserted**

After the `document.body.appendChild(overlay);` line, add:

```javascript
  // Populate spread session picker for option rows
  if (info.isOption) {
    const sessionSelect = overlay.querySelector('#tm-session-select');
    const ticker = (info.ticker || '').toUpperCase();
    try {
      const res = await fetch(
        `${tmApiUrl}/api/sessions?ticker=${encodeURIComponent(ticker)}&status=open`,
        { signal: AbortSignal.timeout(5000) },
      );
      const sessions = res.ok ? await res.json() : [];
      const spreadSessions = sessions.filter(s =>
        s.strategy === 'IRON_CONDOR' || s.strategy === 'PUT_B_W_FLY'
      );
      sessionSelect.innerHTML =
        '<option value="">— None —</option>' +
        spreadSessions.map(s => {
          const label = s.strategy === 'IRON_CONDOR' ? 'IC' : 'PBWB';
          return `<option value="${s.id}">${label} · ${s.ticker} · opened ${s.opened_at}</option>`;
        }).join('') +
        '<option value="__new_IC__">→ New Iron Condor Session</option>' +
        '<option value="__new_PBWB__">→ New Put BWB Session</option>';
    } catch {
      sessionSelect.innerHTML =
        '<option value="">— None —</option>' +
        '<option value="__new_IC__">→ New Iron Condor Session</option>' +
        '<option value="__new_PBWB__">→ New Put BWB Session</option>';
    }
  }
```

- [ ] **Step 3: Update the submit handler to handle session_id**

Inside the `overlay.querySelector('#tm-modal-form').addEventListener('submit', async (e) => {` handler, after the `payload` object is built and before the `try { const resp = await fetch(...)` block, add:

```javascript
    // Resolve session_id: create a new session if requested, or use existing
    let resolvedSessionId = null;
    const rawSession = info.isOption ? (fd.get('session_id') || '') : '';
    if (rawSession && !rawSession.startsWith('__new_')) {
      resolvedSessionId = rawSession;
    } else if (rawSession === '__new_IC__' || rawSession === '__new_PBWB__') {
      const strategy = rawSession === '__new_IC__' ? 'IRON_CONDOR' : 'PUT_B_W_FLY';
      const sessionResp = await fetch(`${tmApiUrl}/api/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ticker: payload.ticker,
          strategy,
          status: 'open',
          opened_at: payload.open_date,
        }),
        signal: AbortSignal.timeout(8000),
      });
      if (!sessionResp.ok) {
        const err = await sessionResp.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to create session');
      }
      const newSession = await sessionResp.json();
      resolvedSessionId = newSession.id;
      // Invalidate session cache so the pill reflects the new session
      sessionCache.delete(payload.ticker.toUpperCase());
    }
    if (resolvedSessionId) payload.session_id = resolvedSessionId;
```

- [ ] **Step 4: Test the session picker end-to-end**

On E*TRADE, click the "+" reconcile pill on any option row to open the Add Trade modal. Verify:
1. "Spread Session" dropdown appears (only for option rows)
2. Existing IC/PBWB sessions for the ticker are listed
3. "→ New Iron Condor Session" and "→ New Put BWB Session" are available
4. Submitting with "→ New IC Session" creates the session then links the trade
5. Submitting with an existing session links the trade to it
6. Submitting with "— None —" creates a standalone trade (no session)
7. After adding a second leg and linking to the same session, the extension shows the "IC" pill on that row

- [ ] **Step 5: Commit**

```bash
git add extension/content.js
git commit -m "feat: add spread session picker to extension Add Trade modal"
```

---

## Self-Review Notes

**Spec coverage check:**
- ✅ Backend: `strategy` optional in lookup, `closed` excluded, `legs` in response — Task 1
- ✅ Backend tests — Task 2
- ✅ Frontend: `/spreads` route, nav link — Task 3
- ✅ Frontend: `SpreadSessionCard` with price signal — Task 4
- ✅ Frontend: `SpreadsDashboardPage` with open/closed sections + price fetch — Task 5
- ✅ Extension: generalised session fetch (no strategy filter) — Task 6
- ✅ Extension: `priceCache` + `fetchPricesForSpreadSessions` — Task 6
- ✅ Extension: `computePriceSignal`, `renderStrategyPill` (IC purple, PBWB teal) — Task 6
- ✅ Extension: session picker in Add Trade modal (existing + new IC/PBWB) — Task 7

**Placeholder check:** No TBD or TODO in any code block. All types, function names, and API paths are consistent across tasks.

**Type consistency:**
- `SessionLookupItem` defined in Task 1 schema, imported in Task 1 router — consistent
- `computeSignal` in Task 4 uses `SessionLeg.strategy` ('Sell Put', 'Sell Call') — consistent with `SessionLegItem.strategy` in backend schema
- `computePriceSignal` in Task 6 uses the same 'Sell Put'/'Sell Call' strategy strings — consistent
- `renderStrategyPill` uses `.tm-strategy-pill` CSS class; `applyWheelPillToRow` removes `.tm-strategy-pill` — consistent
- `quotePrice` in Task 3 returns `Promise<number | null>` — `SpreadsDashboardPage` stores as `Record<string, number | null>` — consistent
