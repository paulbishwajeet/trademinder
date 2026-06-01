# WHEEL Strategy Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated WHEEL Strategy page that groups active WHEEL positions by ticker, shows their current phase (Put Open / Shares Sitting / CC Open / Called Away), and surfaces "needs attention" items at the top.

**Architecture:** A new `trade_sessions` table stores WHEEL instances (and future strategy sessions) with a `status` field tracking the current phase. Trades gain a nullable `session_id` FK — NULL means standalone/opportunistic, set means the trade is a leg of a session. The frontend fetches all WHEEL sessions on page load and renders them as expandable cards split into "Needs Action" and "Monitoring" sections. Status transitions are manual (user patches the session).

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic (backend); React 19 + TypeScript + Tailwind CSS 3 (frontend); vanilla JS content script (Chrome extension).

---

## File Structure

**New files:**
- `backend/alembic/versions/006_trade_sessions.py` — migration: create `trade_sessions`, add `session_id` to `trades`
- `backend/app/models/trade_session.py` — SQLAlchemy `TradeSession` model
- `backend/app/schemas/session.py` — Pydantic schemas: `SessionCreate`, `SessionUpdate`, `SessionSummary`, `SessionWithLegs`, `SessionLegItem`, `SessionLookupResponse`
- `backend/app/routers/sessions.py` — CRUD + lookup endpoints
- `backend/tests/test_sessions.py` — all session tests

**Modified files:**
- `backend/app/models/__init__.py` — add `TradeSession` import
- `backend/app/models/trade.py` — add `session_id` FK + `session` relationship
- `backend/app/schemas/trade.py` — add `session_id` to `TradeCreate`, `TradeUpdate`, `TradeListItem`
- `backend/app/routers/trades.py` — pass `session_id` on create; `setattr` loop already handles PATCH
- `backend/app/main.py` — register sessions router

**New frontend files:**
- `frontend/src/api/sessions.ts` — `sessionsApi` wrapper
- `frontend/src/components/Wheel/WheelSessionCard.tsx` — session card component
- `frontend/src/components/Wheel/NewWheelModal.tsx` — two-step session creation modal
- `frontend/src/pages/WheelDashboardPage.tsx` — main dashboard page

**Modified frontend files:**
- `frontend/src/types/index.ts` — add `Session*` types; add `session_id` to `Trade` and `TradeUpdate`
- `frontend/src/App.tsx` — add `/wheel` route and nav item

**Modified extension files:**
- `extension/content.js` — add `sessionCache`, `fetchWheelSessionsForTickers()`, WHEEL status pill in badge

---

## Task 1: DB Migration + TradeSession Model

**Files:**
- Create: `backend/alembic/versions/006_trade_sessions.py`
- Create: `backend/app/models/trade_session.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Write the failing test (model import check)**

```python
# backend/tests/test_sessions.py
import pytest
from httpx import AsyncClient
from datetime import date

SESSION_PAYLOAD = {
    "ticker": "NVDA",
    "strategy": "WHEEL",
    "status": "put_open",
    "opened_at": str(date.today()),
}

async def test_placeholder(client: AsyncClient):
    # Will be replaced in Task 2 — just confirms import works
    assert True
```

Run: `cd /path/to/TradeMinder && pytest backend/tests/test_sessions.py -v`
Expected: PASS (trivial test)

- [ ] **Step 2: Create the Alembic migration**

```python
# backend/alembic/versions/006_trade_sessions.py
"""create trade_sessions table and add session_id to trades

Revision ID: 006
Revises: 005
Create Date: 2026-05-31
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trade_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("strategy", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("rotation_number", sa.Integer, nullable=False, server_default="1"),
        sa.Column("parent_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("opened_at", sa.Date, nullable=False),
        sa.Column("closed_at", sa.Date, nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_session_id"], ["trade_sessions.id"],
            name="fk_trade_sessions_parent",
            ondelete="SET NULL",
        ),
    )
    op.create_index("idx_trade_sessions_ticker_strategy", "trade_sessions", ["ticker", "strategy"])
    op.create_index("idx_trade_sessions_status", "trade_sessions", ["status"])
    op.execute(
        "CREATE INDEX idx_trade_sessions_parent ON trade_sessions (parent_session_id) "
        "WHERE parent_session_id IS NOT NULL"
    )

    op.add_column(
        "trades",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_trades_session_id",
        "trades", "trade_sessions",
        ["session_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_trades_session_id", "trades", ["session_id"],
        postgresql_where=sa.text("session_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_trades_session_id", "trades")
    op.drop_constraint("fk_trades_session_id", "trades", type_="foreignkey")
    op.drop_column("trades", "session_id")
    op.execute("DROP INDEX IF EXISTS idx_trade_sessions_parent")
    op.drop_index("idx_trade_sessions_status", "trade_sessions")
    op.drop_index("idx_trade_sessions_ticker_strategy", "trade_sessions")
    op.drop_table("trade_sessions")
```

- [ ] **Step 3: Create the SQLAlchemy model**

```python
# backend/app/models/trade_session.py
import uuid
from datetime import date, datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Integer, Date, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func, text
from app.database import Base

if TYPE_CHECKING:
    from app.models.trade import Trade


class TradeSession(Base):
    __tablename__ = "trade_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    strategy: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    rotation_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("trade_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    opened_at: Mapped[date] = mapped_column(Date, nullable=False)
    closed_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    legs: Mapped[list["Trade"]] = relationship(
        "Trade",
        back_populates="session",
        foreign_keys="Trade.session_id",
    )

    __table_args__ = (
        Index("idx_trade_sessions_ticker_strategy", "ticker", "strategy"),
        Index("idx_trade_sessions_status", "status"),
        Index(
            "idx_trade_sessions_parent",
            "parent_session_id",
            postgresql_where=text("parent_session_id IS NOT NULL"),
        ),
    )
```

- [ ] **Step 4: Register model in `__init__.py`**

Current content of `backend/app/models/__init__.py`:
```python
from app.models.trade import Trade
from app.models.rationale import Rationale
from app.models.commentary import Commentary
from app.models.alert import Alert
from app.models.briefing import DailyBriefing
from app.models.category import Category
from app.models.signal import TechnicalSignal

__all__ = ["Trade", "Rationale", "Commentary", "Alert", "DailyBriefing", "Category", "TechnicalSignal"]
```

Add `TradeSession` — replace with:
```python
from app.models.trade import Trade
from app.models.rationale import Rationale
from app.models.commentary import Commentary
from app.models.alert import Alert
from app.models.briefing import DailyBriefing
from app.models.category import Category
from app.models.signal import TechnicalSignal
from app.models.trade_session import TradeSession

__all__ = ["Trade", "Rationale", "Commentary", "Alert", "DailyBriefing", "Category", "TechnicalSignal", "TradeSession"]
```

- [ ] **Step 5: Add `session_id` FK + relationship to `Trade` model**

In `backend/app/models/trade.py`, add to the TYPE_CHECKING block:
```python
if TYPE_CHECKING:
    from app.models.rationale import Rationale
    from app.models.commentary import Commentary
    from app.models.alert import Alert
    from app.models.category import Category
    from app.models.signal import TechnicalSignal
    from app.models.trade_session import TradeSession  # add this line
```

Add the `session_id` column after `wheel_id`:
```python
session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
    UUID(as_uuid=True),
    ForeignKey("trade_sessions.id", ondelete="SET NULL"),
    nullable=True,
)
```

Add the `session` relationship after the existing relationships:
```python
session: Mapped[Optional["TradeSession"]] = relationship(
    "TradeSession",
    back_populates="legs",
    foreign_keys=[session_id],
)
```

Add to `__table_args__`:
```python
__table_args__ = (
    Index("idx_trades_ticker", "ticker"),
    Index("idx_trades_wheel_id", "wheel_id"),
    Index("idx_trades_status", "status"),
    Index("idx_trades_expiry", "expiry_date", postgresql_where=text("expiry_date IS NOT NULL")),
    Index("idx_trades_session_id", "session_id", postgresql_where=text("session_id IS NOT NULL")),
)
```

- [ ] **Step 6: Run TypeScript check and confirm tests still pass**

```bash
cd backend && pytest backend/tests/ -v --tb=short 2>&1 | tail -20
```
Expected: All existing tests pass. The `test_sessions.py::test_placeholder` passes.

- [ ] **Step 7: Commit**

```bash
git add backend/alembic/versions/006_trade_sessions.py \
        backend/app/models/trade_session.py \
        backend/app/models/__init__.py \
        backend/app/models/trade.py \
        backend/tests/test_sessions.py
git commit -m "feat: add trade_sessions table and session_id FK to trades"
```

---

## Task 2: Sessions Schemas + CRUD Router + Tests

**Files:**
- Create: `backend/app/schemas/session.py`
- Create: `backend/app/routers/sessions.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_sessions.py`

- [ ] **Step 1: Create schemas**

```python
# backend/app/schemas/session.py
import uuid
from datetime import date, datetime
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


class SessionLookupResponse(BaseModel):
    ticker: str
    strategy: str
    has_existing: bool
    sessions: list[SessionSummary]
```

- [ ] **Step 2: Write the failing tests**

Replace `backend/tests/test_sessions.py` with:

```python
# backend/tests/test_sessions.py
import pytest
from httpx import AsyncClient
from datetime import date

SESSION_PAYLOAD = {
    "ticker": "NVDA",
    "strategy": "WHEEL",
    "status": "put_open",
    "opened_at": str(date.today()),
}

TRADE_PAYLOAD = {
    "type": "Sell",
    "category": "WHEEL",
    "strategy": "Sell Put",
    "ticker": "NVDA",
    "open_date": str(date.today()),
    "expiry_date": "2026-06-20",
    "strike_price": "120.00",
    "quantity": 1,
    "premium": "2.50",
}


async def test_create_session(client: AsyncClient):
    response = await client.post("/api/sessions", json=SESSION_PAYLOAD)
    assert response.status_code == 201
    data = response.json()
    assert data["ticker"] == "NVDA"
    assert data["status"] == "put_open"
    assert data["rotation_number"] == 1
    assert data["parent_session_id"] is None


async def test_list_sessions_empty(client: AsyncClient):
    response = await client.get("/api/sessions")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_sessions_filters_by_strategy(client: AsyncClient):
    await client.post("/api/sessions", json=SESSION_PAYLOAD)
    response = await client.get("/api/sessions?strategy=WHEEL")
    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_list_sessions_filters_by_ticker(client: AsyncClient):
    await client.post("/api/sessions", json=SESSION_PAYLOAD)
    await client.post("/api/sessions", json={**SESSION_PAYLOAD, "ticker": "AAPL"})
    response = await client.get("/api/sessions?ticker=NVDA")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["ticker"] == "NVDA"


async def test_get_session_not_found(client: AsyncClient):
    response = await client.get("/api/sessions/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


async def test_get_session_with_no_legs(client: AsyncClient):
    session_resp = await client.post("/api/sessions", json=SESSION_PAYLOAD)
    session_id = session_resp.json()["id"]
    response = await client.get(f"/api/sessions/{session_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == session_id
    assert data["legs"] == []
    assert data["rotation_chain"] == []


async def test_patch_session_status(client: AsyncClient):
    session_resp = await client.post("/api/sessions", json=SESSION_PAYLOAD)
    session_id = session_resp.json()["id"]
    response = await client.patch(f"/api/sessions/{session_id}", json={"status": "shares_sitting"})
    assert response.status_code == 200
    assert response.json()["status"] == "shares_sitting"


async def test_patch_session_not_found(client: AsyncClient):
    response = await client.patch(
        "/api/sessions/00000000-0000-0000-0000-000000000000",
        json={"status": "shares_sitting"},
    )
    assert response.status_code == 404


async def test_session_lookup_no_existing(client: AsyncClient):
    response = await client.get("/api/sessions/lookup?ticker=NVDA&strategy=WHEEL")
    assert response.status_code == 200
    data = response.json()
    assert data["has_existing"] is False
    assert data["sessions"] == []


async def test_session_lookup_with_existing(client: AsyncClient):
    await client.post("/api/sessions", json=SESSION_PAYLOAD)
    response = await client.get("/api/sessions/lookup?ticker=NVDA&strategy=WHEEL")
    assert response.status_code == 200
    data = response.json()
    assert data["has_existing"] is True
    assert len(data["sessions"]) == 1


async def test_session_lookup_excludes_completed(client: AsyncClient):
    await client.post("/api/sessions", json={**SESSION_PAYLOAD, "status": "completed"})
    response = await client.get("/api/sessions/lookup?ticker=NVDA&strategy=WHEEL")
    assert response.status_code == 200
    assert response.json()["has_existing"] is False


async def test_rotation_chain(client: AsyncClient):
    parent_resp = await client.post("/api/sessions", json={**SESSION_PAYLOAD, "status": "completed"})
    parent_id = parent_resp.json()["id"]

    child_resp = await client.post("/api/sessions", json={
        **SESSION_PAYLOAD,
        "status": "put_open",
        "rotation_number": 2,
        "parent_session_id": parent_id,
    })
    child_id = child_resp.json()["id"]

    response = await client.get(f"/api/sessions/{child_id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data["rotation_chain"]) == 1
    assert data["rotation_chain"][0]["id"] == parent_id
    assert data["rotation_chain"][0]["rotation_number"] == 1
```

- [ ] **Step 3: Run tests to confirm they fail**

```bash
cd backend && pytest backend/tests/test_sessions.py -v 2>&1 | tail -20
```
Expected: FAIL — "404 Not Found" or "connection refused" (router not registered yet)

- [ ] **Step 4: Create the sessions router**

```python
# backend/app/routers/sessions.py
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.trade_session import TradeSession
from app.schemas.session import (
    SessionCreate, SessionUpdate, SessionSummary,
    SessionWithLegs, SessionLegItem, SessionLookupResponse,
)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionSummary])
async def list_sessions(
    strategy: Optional[str] = Query("WHEEL"),
    status: Optional[str] = Query(None),
    ticker: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(TradeSession)
    if strategy:
        stmt = stmt.where(TradeSession.strategy == strategy)
    if status:
        stmt = stmt.where(TradeSession.status == status)
    if ticker:
        stmt = stmt.where(TradeSession.ticker == ticker.upper())
    stmt = stmt.order_by(TradeSession.ticker)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("", response_model=SessionSummary, status_code=201)
async def create_session(payload: SessionCreate, db: AsyncSession = Depends(get_db)):
    if payload.parent_session_id:
        parent = await db.get(TradeSession, payload.parent_session_id)
        if parent is None:
            raise HTTPException(status_code=404, detail="Parent session not found")

    session = TradeSession(
        ticker=payload.ticker.upper(),
        strategy=payload.strategy,
        status=payload.status,
        rotation_number=payload.rotation_number,
        parent_session_id=payload.parent_session_id,
        opened_at=payload.opened_at,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


# NOTE: /lookup must be defined BEFORE /{session_id} so FastAPI
# does not try to parse "lookup" as a UUID path parameter.
@router.get("/lookup", response_model=SessionLookupResponse)
async def lookup_sessions(
    ticker: str = Query(...),
    strategy: str = Query("WHEEL"),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(TradeSession)
        .where(
            TradeSession.ticker == ticker.upper(),
            TradeSession.strategy == strategy,
            TradeSession.status != "completed",
        )
        .order_by(TradeSession.rotation_number.desc())
    )
    result = await db.execute(stmt)
    sessions = result.scalars().all()
    return SessionLookupResponse(
        ticker=ticker.upper(),
        strategy=strategy,
        has_existing=len(sessions) > 0,
        sessions=sessions,
    )


@router.get("/{session_id}", response_model=SessionWithLegs)
async def get_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(TradeSession)
        .where(TradeSession.id == session_id)
        .options(selectinload(TradeSession.legs))
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Walk parent chain to build rotation_chain (oldest first)
    chain: list[TradeSession] = []
    current_parent_id = session.parent_session_id
    seen: set[uuid.UUID] = {session_id}
    for _ in range(20):  # guard against accidental cycles
        if current_parent_id is None or current_parent_id in seen:
            break
        seen.add(current_parent_id)
        parent = await db.get(TradeSession, current_parent_id)
        if parent is None:
            break
        chain.append(parent)
        current_parent_id = parent.parent_session_id
    chain.reverse()

    legs_sorted = sorted(session.legs, key=lambda t: t.open_date)

    return SessionWithLegs(
        id=session.id,
        ticker=session.ticker,
        strategy=session.strategy,
        status=session.status,
        rotation_number=session.rotation_number,
        opened_at=session.opened_at,
        closed_at=session.closed_at,
        parent_session_id=session.parent_session_id,
        legs=[SessionLegItem.model_validate(t) for t in legs_sorted],
        rotation_chain=[SessionSummary.model_validate(s) for s in chain],
    )


@router.patch("/{session_id}", response_model=SessionSummary)
async def update_session(
    session_id: uuid.UUID,
    payload: SessionUpdate,
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(TradeSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(session, field, value)

    await db.commit()
    await db.refresh(session)
    return session
```

- [ ] **Step 5: Register router in `main.py`**

In `backend/app/main.py`, add the import and `include_router` call:

```python
from app.routers import trades, commentary, alerts, market, briefing, categories, positions, signals, sessions

# ... existing code ...

app.include_router(sessions.router)   # add this line alongside the others
```

- [ ] **Step 6: Run the tests**

```bash
cd backend && pytest backend/tests/test_sessions.py -v
```
Expected: All 13 tests PASS.

- [ ] **Step 7: Run full test suite to check for regressions**

```bash
cd backend && pytest backend/tests/ -v --tb=short 2>&1 | tail -30
```
Expected: All existing tests still pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas/session.py \
        backend/app/routers/sessions.py \
        backend/app/main.py \
        backend/tests/test_sessions.py
git commit -m "feat: add trade_sessions CRUD API with lookup endpoint"
```

---

## Task 3: Add `session_id` to Trades API

**Files:**
- Modify: `backend/app/schemas/trade.py`
- Modify: `backend/app/routers/trades.py`
- Modify: `backend/tests/test_sessions.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_sessions.py`:

```python
async def test_create_trade_with_session_id(client: AsyncClient):
    session_resp = await client.post("/api/sessions", json=SESSION_PAYLOAD)
    session_id = session_resp.json()["id"]

    response = await client.post("/api/trades", json={**TRADE_PAYLOAD, "session_id": session_id})
    assert response.status_code == 201
    assert response.json()["session_id"] == session_id


async def test_create_trade_without_session_id_is_null(client: AsyncClient):
    response = await client.post("/api/trades", json=TRADE_PAYLOAD)
    assert response.status_code == 201
    assert response.json()["session_id"] is None


async def test_patch_trade_links_session(client: AsyncClient):
    session_resp = await client.post("/api/sessions", json=SESSION_PAYLOAD)
    session_id = session_resp.json()["id"]

    trade_resp = await client.post("/api/trades", json=TRADE_PAYLOAD)
    trade_id = trade_resp.json()["id"]

    patch_resp = await client.patch(f"/api/trades/{trade_id}", json={"session_id": session_id})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["session_id"] == session_id


async def test_get_session_includes_linked_trade(client: AsyncClient):
    session_resp = await client.post("/api/sessions", json=SESSION_PAYLOAD)
    session_id = session_resp.json()["id"]

    await client.post("/api/trades", json={**TRADE_PAYLOAD, "session_id": session_id})

    response = await client.get(f"/api/sessions/{session_id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data["legs"]) == 1
    assert data["legs"][0]["ticker"] == "NVDA"
    assert data["legs"][0]["strategy"] == "Sell Put"
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd backend && pytest backend/tests/test_sessions.py::test_create_trade_with_session_id -v
```
Expected: FAIL — `session_id` field not accepted by `TradeCreate`

- [ ] **Step 3: Add `session_id` to trade schemas**

In `backend/app/schemas/trade.py`, add `session_id` to `TradeCreate`:

```python
class TradeCreate(BaseModel):
    wheel_id: Optional[uuid.UUID] = None
    session_id: Optional[uuid.UUID] = None   # add this line
    type: Annotated[str, Field(min_length=1, max_length=10)]
    category: Annotated[str, Field(min_length=1, max_length=20)]
    # ... rest unchanged
```

Add `session_id` to `TradeUpdate`:

```python
class TradeUpdate(BaseModel):
    # ... existing fields ...
    session_id: Optional[uuid.UUID] = None   # add at end
```

Add `session_id` to `TradeListItem` response:

```python
class TradeListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    wheel_id: Optional[uuid.UUID] = None
    session_id: Optional[uuid.UUID] = None   # add this line
    # ... rest unchanged
```

- [ ] **Step 4: Pass `session_id` in `create_trade`**

In `backend/app/routers/trades.py`, in the `create_trade` function, add `session_id=payload.session_id` to the `Trade(...)` constructor:

```python
trade = Trade(
    wheel_id=payload.wheel_id,
    session_id=payload.session_id,   # add this line
    type=payload.type,
    # ... rest unchanged
)
```

The `update_trade` function already handles `session_id` via the generic `setattr` loop — no changes needed there.

- [ ] **Step 5: Run the new tests**

```bash
cd backend && pytest backend/tests/test_sessions.py -v
```
Expected: All 17 tests PASS.

- [ ] **Step 6: Run full test suite**

```bash
cd backend && pytest backend/tests/ -v --tb=short 2>&1 | tail -20
```
Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/trade.py \
        backend/app/routers/trades.py \
        backend/tests/test_sessions.py
git commit -m "feat: add session_id to trades create/update/response"
```

---

## Task 4: Frontend Types + Sessions API Wrapper

**Files:**
- Modify: `frontend/src/types/index.ts`
- Create: `frontend/src/api/sessions.ts`

- [ ] **Step 1: Add session types and update Trade types in `frontend/src/types/index.ts`**

Add `session_id` to the existing `Trade` interface (after `wheel_id`):

```typescript
export interface Trade {
  id: string
  wheel_id: string | null
  session_id: string | null   // add this line
  type: string
  // ... rest unchanged
}
```

Add `session_id` to `TradeUpdate`:

```typescript
export interface TradeUpdate {
  // ... existing fields ...
  session_id?: string | null
}
```

Append the new session types at the end of the file:

```typescript
export interface SessionSummary {
  id: string
  ticker: string
  strategy: string
  status: string
  rotation_number: number
  opened_at: string
  closed_at: string | null
  parent_session_id: string | null
}

export interface SessionLeg {
  id: string
  type: string
  strategy: string
  ticker: string
  open_date: string
  expiry_date: string | null
  strike_price: number | null
  quantity: number
  premium: number | null
  status: string
}

export interface SessionWithLegs extends SessionSummary {
  legs: SessionLeg[]
  rotation_chain: SessionSummary[]
}

export interface SessionLookupResponse {
  ticker: string
  strategy: string
  has_existing: boolean
  sessions: SessionSummary[]
}
```

- [ ] **Step 2: Create `frontend/src/api/sessions.ts`**

```typescript
// frontend/src/api/sessions.ts
import { apiFetch } from './client'
import type { SessionSummary, SessionWithLegs, SessionLookupResponse } from '../types'

export interface SessionCreate {
  ticker: string
  strategy: string
  status: string
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
    const entries = Object.entries(params ?? {}).filter(([, v]) => v !== undefined) as [string, string][]
    const qs = entries.length ? '?' + new URLSearchParams(entries).toString() : ''
    return apiFetch<SessionSummary[]>(`/sessions${qs}`)
  },

  get: (id: string) => apiFetch<SessionWithLegs>(`/sessions/${id}`),

  create: (payload: SessionCreate) =>
    apiFetch<SessionSummary>('/sessions', { method: 'POST', body: JSON.stringify(payload) }),

  update: (id: string, payload: SessionUpdate) =>
    apiFetch<SessionSummary>(`/sessions/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  lookup: (ticker: string, strategy = 'WHEEL') =>
    apiFetch<SessionLookupResponse>(`/sessions/lookup?ticker=${encodeURIComponent(ticker)}&strategy=${encodeURIComponent(strategy)}`),
}
```

- [ ] **Step 3: TypeScript check**

```bash
cd frontend && npx tsc --noEmit
```
Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/sessions.ts
git commit -m "feat: add session types and sessionsApi frontend wrapper"
```

---

## Task 5: WheelSessionCard Component

**Files:**
- Create: `frontend/src/components/Wheel/WheelSessionCard.tsx`

- [ ] **Step 1: Create the component**

```tsx
// frontend/src/components/Wheel/WheelSessionCard.tsx
import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { SessionWithLegs, SessionSummary, SessionLeg } from '../../types'
import { sessionsApi } from '../../api/sessions'

interface Props {
  session: SessionWithLegs
  onStatusUpdate: (id: string, newStatus: string) => void
}

const STATUS_LABELS: Record<string, string> = {
  put_open: 'Put Open',
  shares_sitting: 'Shares Sitting',
  cc_open: 'CC Open',
  called_away: 'Called Away / Waiting Cash',
  completed: 'Completed',
}

const STATUS_COLORS: Record<string, string> = {
  put_open: '#3B82F6',
  shares_sitting: '#F59E0B',
  cc_open: '#3B82F6',
  called_away: '#F59E0B',
  completed: '#10B981',
}

const VALID_NEXT_STATUSES: Record<string, string[]> = {
  put_open: ['shares_sitting', 'completed'],
  shares_sitting: ['cc_open'],
  cc_open: ['shares_sitting', 'called_away', 'completed'],
  called_away: ['completed'],
  completed: [],
}

function activeLegSummary(legs: SessionLeg[]): string {
  const openLegs = legs.filter(l => l.status === 'open')
  const leg = openLegs.length > 0 ? openLegs[openLegs.length - 1] : legs[legs.length - 1]
  if (!leg) return '—'
  const parts: string[] = [leg.strategy]
  if (leg.strike_price != null) parts.push(`$${leg.strike_price}`)
  if (leg.expiry_date) parts.push(`exp ${leg.expiry_date}`)
  if (leg.premium != null) parts.push(`$${leg.premium} prem`)
  return parts.join(' · ')
}

export function WheelSessionCard({ session, onStatusUpdate }: Props) {
  const [expanded, setExpanded] = useState(false)
  const [showStatusEdit, setShowStatusEdit] = useState(false)
  const [saving, setSaving] = useState(false)

  const color = STATUS_COLORS[session.status] ?? '#6B7280'
  const label = STATUS_LABELS[session.status] ?? session.status
  const nextStatuses = VALID_NEXT_STATUSES[session.status] ?? []

  const totalPremium = session.legs
    .filter(l => l.premium != null)
    .reduce((sum, l) => sum + (l.premium ?? 0) * l.quantity, 0)

  async function handleStatusChange(newStatus: string) {
    setSaving(true)
    try {
      await sessionsApi.update(session.id, { status: newStatus })
      onStatusUpdate(session.id, newStatus)
      setShowStatusEdit(false)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="bg-white border border-gray-200 rounded-lg overflow-hidden" style={{ borderLeft: `4px solid ${color}` }}>
      {/* Collapsed header */}
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
            className="text-xs font-medium px-2 py-0.5 rounded-full text-white"
            style={{ background: color }}
          >
            {label}
          </span>
          <span className="text-xs text-gray-400">Rotation {session.rotation_number}</span>
        </div>

        <div className="flex items-center gap-3 text-sm text-gray-500">
          <span className="hidden sm:block">{activeLegSummary(session.legs)}</span>
          <div className="flex gap-2" onClick={e => e.stopPropagation()}>
            {session.status === 'called_away' && (
              <Link
                to="/trades"
                className="px-2 py-1 text-xs bg-amber-100 text-amber-800 rounded hover:bg-amber-200"
              >
                + New Put
              </Link>
            )}
            {session.status === 'shares_sitting' && (
              <Link
                to="/trades"
                className="px-2 py-1 text-xs bg-amber-100 text-amber-800 rounded hover:bg-amber-200"
              >
                + Sell CC
              </Link>
            )}
            {nextStatuses.length > 0 && !showStatusEdit && (
              <button
                onClick={() => setShowStatusEdit(true)}
                className="px-2 py-1 text-xs border border-gray-300 rounded hover:bg-gray-100"
              >
                Update Status
              </button>
            )}
            {showStatusEdit && (
              <div className="flex items-center gap-1">
                <select
                  className="text-xs border border-gray-300 rounded px-1 py-0.5"
                  defaultValue=""
                  onChange={e => e.target.value && handleStatusChange(e.target.value)}
                  disabled={saving}
                >
                  <option value="" disabled>Move to…</option>
                  {nextStatuses.map(s => (
                    <option key={s} value={s}>{STATUS_LABELS[s] ?? s}</option>
                  ))}
                </select>
                <button
                  onClick={() => setShowStatusEdit(false)}
                  className="text-xs text-gray-400 hover:text-gray-600"
                >✕</button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Expanded body */}
      {expanded && (
        <div className="border-t border-gray-100 px-4 py-3 space-y-3">
          {/* Current rotation legs */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wider">
                Rotation {session.rotation_number} · started {session.opened_at}
              </span>
              {totalPremium > 0 && (
                <span className="text-xs font-medium text-green-600">${totalPremium.toFixed(2)} collected</span>
              )}
            </div>

            {session.legs.length === 0 ? (
              <p className="text-xs text-gray-400 italic">No legs linked yet.</p>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-gray-400 border-b border-gray-100">
                    <th className="pb-1 pr-3 font-normal">Date</th>
                    <th className="pb-1 pr-3 font-normal">Strategy</th>
                    <th className="pb-1 pr-3 font-normal">Strike</th>
                    <th className="pb-1 pr-3 font-normal">Expiry</th>
                    <th className="pb-1 pr-3 font-normal">Qty</th>
                    <th className="pb-1 pr-3 font-normal">Premium</th>
                    <th className="pb-1 pr-3 font-normal">Status</th>
                    <th className="pb-1 font-normal"></th>
                  </tr>
                </thead>
                <tbody>
                  {[...session.legs].reverse().map(leg => (
                    <tr key={leg.id} className="border-t border-gray-50">
                      <td className="py-1.5 pr-3 text-gray-500">{leg.open_date}</td>
                      <td className="py-1.5 pr-3">{leg.strategy}</td>
                      <td className="py-1.5 pr-3">{leg.strike_price != null ? `$${leg.strike_price}` : '—'}</td>
                      <td className="py-1.5 pr-3">{leg.expiry_date ?? '—'}</td>
                      <td className="py-1.5 pr-3">{leg.quantity}</td>
                      <td className="py-1.5 pr-3">{leg.premium != null ? `$${leg.premium}` : '—'}</td>
                      <td className="py-1.5 pr-3 capitalize">{leg.status}</td>
                      <td className="py-1.5">
                        <Link to={`/trades/${leg.id}`} className="text-blue-500 hover:underline">view</Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Rotation chain */}
          {session.rotation_chain.length > 0 && (
            <div className="border-t border-gray-100 pt-3">
              <div className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-1">Past Rotations</div>
              {session.rotation_chain.map(r => (
                <div key={r.id} className="text-xs text-gray-500 py-0.5">
                  Rotation {r.rotation_number} &middot; {r.opened_at} → {r.closed_at ?? 'ongoing'} &middot; {STATUS_LABELS[r.status] ?? r.status}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: TypeScript check**

```bash
cd frontend && npx tsc --noEmit
```
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Wheel/WheelSessionCard.tsx
git commit -m "feat: add WheelSessionCard component"
```

---

## Task 6: NewWheelModal Component

**Files:**
- Create: `frontend/src/components/Wheel/NewWheelModal.tsx`

- [ ] **Step 1: Create the component**

```tsx
// frontend/src/components/Wheel/NewWheelModal.tsx
import { useState } from 'react'
import type { SessionSummary, Trade } from '../../types'
import { sessionsApi } from '../../api/sessions'
import { tradesApi } from '../../api/trades'

interface Props {
  onClose: () => void
  onCreated: (session: SessionSummary) => void
}

const WHEEL_STATUSES = [
  { value: 'put_open', label: 'Put Open — I have an active Sold Put' },
  { value: 'shares_sitting', label: 'Shares Sitting — I own the stock, no CC yet' },
  { value: 'cc_open', label: 'CC Open — I have an active Covered Call' },
  { value: 'called_away', label: 'Called Away / Waiting Cash' },
]

export function NewWheelModal({ onClose, onCreated }: Props) {
  const [step, setStep] = useState<1 | 2>(1)
  const [ticker, setTicker] = useState('')
  const [status, setStatus] = useState('put_open')
  const [openedAt, setOpenedAt] = useState(() => new Date().toISOString().slice(0, 10))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [createdSession, setCreatedSession] = useState<SessionSummary | null>(null)

  // Step 2 state
  const [availableTrades, setAvailableTrades] = useState<Trade[]>([])
  const [selectedTradeId, setSelectedTradeId] = useState('')
  const [linking, setLinking] = useState(false)

  async function handleCreateSession() {
    if (!ticker.trim()) { setError('Ticker is required'); return }
    setSaving(true)
    setError(null)
    try {
      const session = await sessionsApi.create({
        ticker: ticker.trim().toUpperCase(),
        strategy: 'WHEEL',
        status,
        opened_at: openedAt,
      })
      setCreatedSession(session)
      const all = await tradesApi.list({ ticker: ticker.trim().toUpperCase() })
      setAvailableTrades(all.filter(t => !t.session_id))
      setStep(2)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to create session')
    } finally {
      setSaving(false)
    }
  }

  async function handleLinkAndFinish() {
    if (!selectedTradeId || !createdSession) return
    setLinking(true)
    setError(null)
    try {
      await tradesApi.update(selectedTradeId, { session_id: createdSession.id })
      onCreated(createdSession)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to link trade')
    } finally {
      setLinking(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg w-full max-w-md p-6 shadow-xl">
        {step === 1 && (
          <>
            <h2 className="text-lg font-bold text-gray-900 mb-4">New WHEEL Session</h2>
            {error && <p className="text-sm text-red-600 mb-3">{error}</p>}
            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Ticker</label>
                <input
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm uppercase"
                  value={ticker}
                  onChange={e => setTicker(e.target.value.toUpperCase())}
                  placeholder="e.g. NVDA"
                  autoFocus
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Current Phase</label>
                <select
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
                  value={status}
                  onChange={e => setStatus(e.target.value)}
                >
                  {WHEEL_STATUSES.map(s => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Started On</label>
                <input
                  type="date"
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
                  value={openedAt}
                  onChange={e => setOpenedAt(e.target.value)}
                />
              </div>
            </div>
            <div className="flex gap-2 justify-end mt-5">
              <button onClick={onClose} className="px-4 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50">
                Cancel
              </button>
              <button
                onClick={handleCreateSession}
                disabled={saving}
                className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
              >
                {saving ? 'Creating…' : 'Create Session →'}
              </button>
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <h2 className="text-lg font-bold text-gray-900 mb-1">Link an Existing Trade</h2>
            <p className="text-sm text-gray-500 mb-4">
              Optionally attach an existing {ticker} trade to this session as a leg.
            </p>
            {error && <p className="text-sm text-red-600 mb-3">{error}</p>}
            {availableTrades.length === 0 ? (
              <p className="text-sm text-gray-400 italic mb-4">No unlinked {ticker} trades found.</p>
            ) : (
              <div className="mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-1">Select trade to link</label>
                <select
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
                  value={selectedTradeId}
                  onChange={e => setSelectedTradeId(e.target.value)}
                >
                  <option value="">— Skip —</option>
                  {availableTrades.map(t => (
                    <option key={t.id} value={t.id}>
                      {t.strategy} · {t.open_date}{t.strike_price != null ? ` · $${t.strike_price}` : ''} · {t.status}
                    </option>
                  ))}
                </select>
              </div>
            )}
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => createdSession && onCreated(createdSession)}
                className="px-4 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50"
              >
                Skip
              </button>
              {selectedTradeId && (
                <button
                  onClick={handleLinkAndFinish}
                  disabled={linking}
                  className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
                >
                  {linking ? 'Linking…' : 'Link & Done'}
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: TypeScript check**

```bash
cd frontend && npx tsc --noEmit
```
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Wheel/NewWheelModal.tsx
git commit -m "feat: add NewWheelModal for session creation and trade linking"
```

---

## Task 7: WheelDashboardPage + App Routing

**Files:**
- Create: `frontend/src/pages/WheelDashboardPage.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Create the page**

```tsx
// frontend/src/pages/WheelDashboardPage.tsx
import { useState, useEffect } from 'react'
import type { SessionSummary, SessionWithLegs } from '../types'
import { sessionsApi } from '../api/sessions'
import { WheelSessionCard } from '../components/Wheel/WheelSessionCard'
import { NewWheelModal } from '../components/Wheel/NewWheelModal'

const NEEDS_ACTION = new Set(['called_away', 'shares_sitting'])

export function WheelDashboardPage() {
  const [sessions, setSessions] = useState<SessionWithLegs[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showNewModal, setShowNewModal] = useState(false)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const summaries = await sessionsApi.list({ strategy: 'WHEEL' })
      const detailed = await Promise.all(summaries.map(s => sessionsApi.get(s.id)))
      setSessions(detailed)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load sessions')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  function handleStatusUpdate(id: string, newStatus: string) {
    setSessions(prev => prev.map(s => s.id === id ? { ...s, status: newStatus } : s))
  }

  function handleNewSession(_session: SessionSummary) {
    setShowNewModal(false)
    load()
  }

  const needsAction = sessions.filter(s => NEEDS_ACTION.has(s.status))
  const monitoring = sessions.filter(s => !NEEDS_ACTION.has(s.status) && s.status !== 'completed')

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold text-gray-900">WHEEL Strategy</h1>
        <button
          onClick={() => setShowNewModal(true)}
          className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700"
        >
          + New Wheel
        </button>
      </div>

      {loading && (
        <p className="text-gray-500 text-center py-12">Loading…</p>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded p-4 mb-4 text-sm">
          {error}
        </div>
      )}

      {!loading && !error && sessions.length === 0 && (
        <div className="text-center py-16">
          <p className="text-gray-400 mb-4">No WHEEL sessions yet.</p>
          <button
            onClick={() => setShowNewModal(true)}
            className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700"
          >
            + New Wheel
          </button>
        </div>
      )}

      {!loading && !error && sessions.length > 0 && (
        <>
          {needsAction.length > 0 && (
            <section className="mb-6">
              <div className="flex items-center gap-2 mb-3">
                <span className="text-sm font-bold text-amber-600">⚠ NEEDS ACTION</span>
                <span className="bg-amber-100 text-amber-700 text-xs px-2 py-0.5 rounded-full font-medium">
                  {needsAction.length}
                </span>
              </div>
              <div className="space-y-2">
                {needsAction.map(s => (
                  <WheelSessionCard key={s.id} session={s} onStatusUpdate={handleStatusUpdate} />
                ))}
              </div>
            </section>
          )}

          {monitoring.length > 0 && (
            <section>
              <div className="flex items-center gap-2 mb-3">
                <span className="text-sm font-bold text-blue-600">✓ MONITORING</span>
                <span className="bg-blue-100 text-blue-700 text-xs px-2 py-0.5 rounded-full font-medium">
                  {monitoring.length}
                </span>
              </div>
              <div className="space-y-2">
                {monitoring.map(s => (
                  <WheelSessionCard key={s.id} session={s} onStatusUpdate={handleStatusUpdate} />
                ))}
              </div>
            </section>
          )}
        </>
      )}

      {showNewModal && (
        <NewWheelModal onClose={() => setShowNewModal(false)} onCreated={handleNewSession} />
      )}
    </div>
  )
}
```

- [ ] **Step 2: Add route and nav item to `frontend/src/App.tsx`**

Add import:
```tsx
import { WheelDashboardPage } from './pages/WheelDashboardPage'
```

Add nav item (between "Trades" and "Margin"):
```tsx
<NavItem to="/wheel" label="WHEEL" />
```

Add route (after the `/trades/:id` route):
```tsx
<Route path="/wheel" element={<WheelDashboardPage />} />
```

The full updated `App.tsx`:
```tsx
// frontend/src/App.tsx
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import { DashboardPage } from './pages/DashboardPage'
import { TradesPage } from './pages/TradesPage'
import { TradeDetailPage } from './pages/TradeDetailPage'
import { MarginDashboardPage } from './pages/MarginDashboardPage'
import { ScannerPage } from './pages/ScannerPage'
import { WheelDashboardPage } from './pages/WheelDashboardPage'

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
          <NavItem to="/margin" label="Margin" />
          <NavItem to="/scanner" label="Scanner" />
        </nav>
        <main>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/trades" element={<TradesPage />} />
            <Route path="/trades/:id" element={<TradeDetailPage />} />
            <Route path="/wheel" element={<WheelDashboardPage />} />
            <Route path="/margin" element={<MarginDashboardPage />} />
            <Route path="/scanner" element={<ScannerPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
```

- [ ] **Step 3: TypeScript check**

```bash
cd frontend && npx tsc --noEmit
```
Expected: No errors.

- [ ] **Step 4: Start the dev server and verify the page renders**

```bash
cd frontend && npm run dev
```

Navigate to `http://localhost:5173/wheel`. Verify:
1. "WHEEL" nav item is visible and active when on the page
2. Page shows "No WHEEL sessions yet." with a "+ New Wheel" button
3. Clicking "+ New Wheel" opens the modal with Ticker / Current Phase / Started On fields
4. Create a session (e.g. NVDA, Put Open) → modal advances to Step 2
5. Step 2 shows "Skip" option; clicking Skip closes the modal and the session card appears
6. Session card shows NVDA in the Monitoring section (put_open = monitoring)
7. Clicking "Update Status" → select "shares_sitting" → card moves to Needs Action section
8. Expanding the card shows "No legs linked yet."

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/WheelDashboardPage.tsx frontend/src/App.tsx
git commit -m "feat: add WheelDashboardPage with needs-action/monitoring sections"
```

---

## Task 8: Chrome Extension — WHEEL Status Pill

**Files:**
- Modify: `extension/content.js`

- [ ] **Step 1: Add `sessionCache` variable alongside other caches**

In `extension/content.js`, find the section where `rsiCache`, `commentaryCountCache`, and `statusCache` are declared. Add:

```javascript
const sessionCache = new Map(); // ticker (uppercase) → { status: string } | null
```

- [ ] **Step 2: Add `fetchWheelSessionsForTickers` function**

Add this function alongside `fetchRsiForAll` and other batch-fetch functions:

```javascript
async function fetchWheelSessionsForTickers(tickers) {
  const unique = [...new Set(tickers.map(t => t.toUpperCase()))];
  await Promise.all(unique.map(async ticker => {
    if (sessionCache.has(ticker)) return; // already fetched this page load
    try {
      const res = await fetch(`${TM_API_URL}/api/sessions/lookup?ticker=${encodeURIComponent(ticker)}&strategy=WHEEL`);
      if (!res.ok) { sessionCache.set(ticker, null); return; }
      const data = await res.json();
      sessionCache.set(ticker, data.has_existing ? data.sessions[0] : null);
    } catch {
      sessionCache.set(ticker, null);
    }
  }));
}
```

- [ ] **Step 3: Add `renderWheelPill` helper**

Add this function alongside other badge rendering helpers:

```javascript
function renderWheelPill(session) {
  if (!session) return null;
  const labels = {
    put_open: 'WHEEL: Put Open',
    shares_sitting: 'WHEEL: Shares Sitting',
    cc_open: 'WHEEL: CC Open',
    called_away: 'WHEEL: ⚠ Action Needed',
  };
  const label = labels[session.status];
  if (!label) return null; // don't show pill for 'completed'

  const needsAction = session.status === 'called_away' || session.status === 'shares_sitting';
  const pill = document.createElement('span');
  pill.className = 'tm-wheel-pill';
  pill.textContent = label;
  pill.style.cssText = [
    'display:inline-flex',
    'align-items:center',
    'font-size:10px',
    'padding:1px 5px',
    'border-radius:3px',
    'margin-left:4px',
    'white-space:nowrap',
    `background:${needsAction ? '#FEF3C7' : '#DBEAFE'}`,
    `color:${needsAction ? '#92400E' : '#1E40AF'}`,
    `border:1px solid ${needsAction ? '#FCD34D' : '#93C5FD'}`,
  ].join(';');
  return pill;
}
```

- [ ] **Step 4: Call `fetchWheelSessionsForTickers` in the main row-processing loop**

Find `processVisibleRows` (the function that runs on each MutationObserver tick). At the start of the function, after collecting visible tickers, add a call to batch-fetch session data:

```javascript
// Collect visible tickers and prefetch wheel sessions
const visibleTickers = [...new Set(
  visibleRows.map(row => extractTicker(row)).filter(Boolean)
)];
if (visibleTickers.length > 0) {
  fetchWheelSessionsForTickers(visibleTickers); // fire-and-forget; cache fills async
}
```

Note: The session lookup is async but the badge is injected synchronously. On first load the pill won't appear until the next MutationObserver tick (when the cache is populated). This is the same pattern as the RSI pill — acceptable for a read-only display feature.

- [ ] **Step 5: Append the WHEEL pill to each badge after it is built**

In the badge-building code (where `badge.innerHTML` is set and RSI/commentary elements are appended), add:

```javascript
const wheelSession = sessionCache.get(ticker ? ticker.toUpperCase() : '');
if (wheelSession !== undefined) { // undefined means not yet fetched; null means no session
  const pill = renderWheelPill(wheelSession);
  if (pill) badge.appendChild(pill);
}
```

- [ ] **Step 6: Clear `sessionCache` on full reprocess**

Find where `statusCache` and `processedRows` are cleared on full reprocess (typically when the page reloads or trade is added). Add:

```javascript
sessionCache.clear();
```

at the same location.

- [ ] **Step 7: Manual verification in browser**

1. Load the extension on the E*TRADE positions page
2. In the TradeMinder app, create a WHEEL session for a ticker that appears in your E*TRADE positions (e.g. NVDA)
3. Reload the E*TRADE page
4. The NVDA position row should show a blue `WHEEL: Put Open` pill after the existing DTE/RSI badges
5. In TradeMinder, update the session status to `called_away`
6. Reload E*TRADE page — pill should now show amber `WHEEL: ⚠ Action Needed`

- [ ] **Step 8: Commit**

```bash
git add extension/content.js
git commit -m "feat: add WHEEL session status pill to E*TRADE position badges"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| `trade_sessions` table with all 9 columns | Task 1 |
| `trades.session_id` nullable FK | Task 1 |
| Alembic migration 006 | Task 1 |
| `TradeSession` SQLAlchemy model | Task 1 |
| `GET /api/sessions` list with filters | Task 2 |
| `POST /api/sessions` create | Task 2 |
| `GET /api/sessions/lookup` | Task 2 |
| `GET /api/sessions/{id}` with legs + rotation chain | Task 2 |
| `PATCH /api/sessions/{id}` status update | Task 2 |
| `session_id` on TradeCreate/TradeUpdate/TradeListItem | Task 3 |
| Frontend Session types | Task 4 |
| `sessionsApi` wrapper | Task 4 |
| `WheelSessionCard` — collapsed/expanded, status edit, rotation chain | Task 5 |
| `NewWheelModal` — 2-step: create session + link trade | Task 6 |
| `WheelDashboardPage` — needs action / monitoring split | Task 7 |
| `/wheel` route + nav item | Task 7 |
| Extension session cache + batch lookup | Task 8 |
| Extension WHEEL status pill on badges | Task 8 |

All spec requirements are covered. No gaps found.
