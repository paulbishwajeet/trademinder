# backend/app/routers/trades.py
import uuid
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.trade import Trade
from app.models.rationale import Rationale
from app.models.category import Category
from app.schemas.trade import TradeCreate, TradeUpdate, TradeListItem, TradeResponse, RationaleCreate, RationaleResponse

router = APIRouter(prefix="/api/trades", tags=["trades"])


class CloseTradeRequest(BaseModel):
    closed_date: Optional[date] = None


@router.get("", response_model=list[TradeListItem])
async def list_trades(
    status: Optional[str] = Query(None),
    ticker: Optional[str] = Query(None),
    strategy: Optional[str] = Query(None),
    wheel_id: Optional[uuid.UUID] = Query(None),
    etrade_symbol: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Trade)
    if status:
        stmt = stmt.where(Trade.status == status)
    if ticker:
        stmt = stmt.where(Trade.ticker == ticker.upper())
    if strategy:
        stmt = stmt.where(Trade.strategy == strategy)
    if wheel_id:
        stmt = stmt.where(Trade.wheel_id == wheel_id)
    if etrade_symbol:
        stmt = stmt.where(Trade.etrade_symbol == etrade_symbol)
    stmt = stmt.order_by(Trade.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("", response_model=TradeListItem, status_code=201)
async def create_trade(payload: TradeCreate, db: AsyncSession = Depends(get_db)):
    trade = Trade(
        wheel_id=payload.wheel_id,
        type=payload.type,
        category=payload.category,
        strategy=payload.strategy,
        ticker=payload.ticker.upper(),
        open_date=payload.open_date,
        expiry_date=payload.expiry_date,
        strike_price=payload.strike_price,
        quantity=payload.quantity,
        premium=payload.premium,
        collateral=payload.collateral,
        exit_strategy=payload.exit_strategy,
        signal_action=payload.signal_action,
        etrade_symbol=payload.etrade_symbol,
    )
    db.add(trade)
    await db.flush()  # get trade.id before creating rationale

    rationale = Rationale(
        trade_id=trade.id,
        notes=payload.rationale_notes,
        fetch_status="pending",
    )
    db.add(rationale)
    await db.commit()
    await db.refresh(trade)
    return trade


@router.get("/wheel/{wheel_id}", response_model=list[TradeListItem])
async def list_wheel_legs(wheel_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = select(Trade).where(Trade.wheel_id == wheel_id).order_by(Trade.open_date)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{trade_id}", response_model=TradeResponse)
async def get_trade(trade_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Trade)
        .where(Trade.id == trade_id)
        .options(selectinload(Trade.rationale))
    )
    result = await db.execute(stmt)
    trade = result.scalar_one_or_none()
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found")
    return trade


@router.put("/{trade_id}/rationale", response_model=RationaleResponse)
async def upsert_trade_rationale(
    trade_id: uuid.UUID,
    payload: RationaleCreate,
    db: AsyncSession = Depends(get_db),
):
    # Verify trade exists
    trade_stmt = select(Trade).where(Trade.id == trade_id)
    trade_result = await db.execute(trade_stmt)
    if trade_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Trade not found")

    # Find existing entry-time rationale (commentary_id IS NULL)
    stmt = select(Rationale).where(
        Rationale.trade_id == trade_id,
        Rationale.commentary_id.is_(None),
    )
    result = await db.execute(stmt)
    rationale = result.scalar_one_or_none()

    if rationale is None:
        rationale = Rationale(trade_id=trade_id, commentary_id=None)
        db.add(rationale)

    data = payload.model_dump(exclude_none=True)
    data["fetch_status"] = "ok"
    for field, value in data.items():
        setattr(rationale, field, value)

    await db.commit()
    await db.refresh(rationale)
    return rationale


@router.patch("/{trade_id}", response_model=TradeResponse)
async def update_trade(trade_id: uuid.UUID, payload: TradeUpdate, db: AsyncSession = Depends(get_db)):
    stmt = select(Trade).where(Trade.id == trade_id).options(selectinload(Trade.rationale))
    result = await db.execute(stmt)
    trade = result.scalar_one_or_none()
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found")

    data = payload.model_dump(exclude_none=True)

    # Handle rationale_notes separately — stored in the related Rationale row
    rationale_notes = data.pop('rationale_notes', None)

    # When category string changes, sync category_id FK
    if 'category' in data:
        cat_result = await db.execute(select(Category).where(Category.name == data['category']))
        cat = cat_result.scalar_one_or_none()
        trade.category_id = cat.id if cat else None

    for field, value in data.items():
        setattr(trade, field, value)

    if rationale_notes is not None and trade.rationale:
        trade.rationale.notes = rationale_notes

    await db.commit()
    stmt2 = select(Trade).where(Trade.id == trade_id).options(selectinload(Trade.rationale))
    result2 = await db.execute(stmt2)
    trade = result2.scalar_one()
    return trade


@router.post("/{trade_id}/close", response_model=TradeListItem)
async def close_trade(
    trade_id: uuid.UUID,
    body: CloseTradeRequest = CloseTradeRequest(),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Trade).where(Trade.id == trade_id)
    result = await db.execute(stmt)
    trade = result.scalar_one_or_none()
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found")
    trade.status = "closed"
    trade.closed_date = body.closed_date or date.today()
    await db.commit()
    await db.refresh(trade)
    return trade


@router.delete("/{trade_id}", status_code=204)
async def delete_trade(trade_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = select(Trade).where(Trade.id == trade_id)
    result = await db.execute(stmt)
    trade = result.scalar_one_or_none()
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found")
    await db.delete(trade)
    await db.commit()


class CategoryAssignRequest(BaseModel):
    category_id: Optional[uuid.UUID] = None


@router.patch("/{trade_id}/category", response_model=TradeListItem)
async def assign_category(
    trade_id: uuid.UUID,
    payload: CategoryAssignRequest,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Trade).where(Trade.id == trade_id)
    result = await db.execute(stmt)
    trade = result.scalar_one_or_none()
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found")
    trade.category_id = payload.category_id
    await db.commit()
    await db.refresh(trade)
    return trade
