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
from app.schemas.trade import TradeCreate, TradeUpdate, TradeListItem, TradeResponse

router = APIRouter(prefix="/api/trades", tags=["trades"])


class CloseTradeRequest(BaseModel):
    closed_date: Optional[date] = None


@router.get("", response_model=list[TradeListItem])
async def list_trades(
    status: Optional[str] = Query(None),
    ticker: Optional[str] = Query(None),
    strategy: Optional[str] = Query(None),
    wheel_id: Optional[uuid.UUID] = Query(None),
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


@router.patch("/{trade_id}", response_model=TradeResponse)
async def update_trade(trade_id: uuid.UUID, payload: TradeUpdate, db: AsyncSession = Depends(get_db)):
    stmt = select(Trade).where(Trade.id == trade_id).options(selectinload(Trade.rationale))
    result = await db.execute(stmt)
    trade = result.scalar_one_or_none()
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(trade, field, value)
    await db.commit()
    # Re-fetch with rationale after commit
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
