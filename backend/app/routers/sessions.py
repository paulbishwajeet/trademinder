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
    SessionWithLegs, SessionLegItem, SessionLookupResponse, SessionLookupItem,
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
    if strategy is not None:
        stmt = stmt.where(TradeSession.strategy == strategy)
    stmt = stmt.order_by(TradeSession.rotation_number.desc())
    result = await db.execute(stmt)
    sessions = result.scalars().all()
    return SessionLookupResponse(
        ticker=ticker.upper(),
        strategy=strategy,
        has_existing=len(sessions) > 0,
        sessions=[SessionLookupItem.model_validate(s) for s in sessions],
    )


# NOTE: /active must be defined BEFORE /{session_id} so FastAPI
# does not try to parse "active" as a UUID path parameter.
@router.get("/active", response_model=list[SessionLookupItem])
async def list_active_sessions(db: AsyncSession = Depends(get_db)):
    stmt = (
        select(TradeSession)
        .where(TradeSession.status.not_in(["completed", "closed"]))
        .options(selectinload(TradeSession.legs))
    )
    result = await db.execute(stmt)
    sessions = result.scalars().all()
    return [SessionLookupItem.model_validate(s) for s in sessions]


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
