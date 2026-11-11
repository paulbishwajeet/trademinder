# backend/app/routers/trades.py
import uuid
from datetime import date, datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.deps import get_current_user, market_data_flag
from app.models.user import User
from app.models.trade import Trade
from app.models.rationale import Rationale
from app.services.ownership import (
    get_trade, get_category, get_category_by_name, get_trade_session, resolve_account,
    resolve_account_filter, require_same_account,
)
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
    stale: bool = Query(False),
    account_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    offline: bool = Depends(market_data_flag),
):
    stmt = select(Trade).where(Trade.user_id == user.id)
    account_filter = await resolve_account_filter(db, user, account_id)
    if account_filter is not None:
        stmt = stmt.where(Trade.account_id == account_filter)
    if stale:
        threshold = datetime.now(timezone.utc) - timedelta(days=1)
        stmt = stmt.where(
            Trade.status == "open",
            Trade.last_etrade_seen.isnot(None),
            Trade.last_etrade_seen < threshold,
        )
    else:
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
    return _without_market_fields(result.scalars().all(), offline)


@router.post("", response_model=TradeListItem, status_code=201)
async def create_trade(
    payload: TradeCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    account = await resolve_account(db, user, payload.account_id)

    if payload.category is not None:
        category_name = payload.category
        cat = await get_category_by_name(db, user, category_name)
    elif account.default_category_id is not None:
        cat = await get_category(db, user, account.default_category_id)
        category_name = cat.name
    else:
        raise HTTPException(status_code=422, detail="category is required (the account has no default category)")

    if payload.session_id is not None:
        trade_session = await get_trade_session(db, user, payload.session_id)
        require_same_account(account.id, trade_session.account_id, "Session")

    trade = Trade(
        user_id=user.id,
        account_id=account.id,
        wheel_id=payload.wheel_id,
        session_id=payload.session_id,
        type=payload.type,
        category=category_name,
        category_id=cat.id if cat else None,
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
        user_id=user.id,
        trade_id=trade.id,
        notes=payload.rationale_notes,
        fetch_status="pending",
    )
    db.add(rationale)
    await db.commit()
    await db.refresh(trade)
    return trade


@router.get("/wheel/{wheel_id}", response_model=list[TradeListItem])
async def list_wheel_legs(
    wheel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    offline: bool = Depends(market_data_flag),
):
    stmt = select(Trade).where(Trade.user_id == user.id, Trade.wheel_id == wheel_id).order_by(Trade.open_date)
    result = await db.execute(stmt)
    return _without_market_fields(result.scalars().all(), offline)


@router.get("/{trade_id}", response_model=TradeResponse)
async def get_trade_detail(
    trade_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    offline: bool = Depends(market_data_flag),
):
    trade = await get_trade(db, user, trade_id, options=(selectinload(Trade.rationale),))
    item = TradeResponse.model_validate(trade)
    if offline:
        item = item.model_copy(update={"current_price": None, "unrealized_pnl": None, "market_data_offline": True})
    return item


def _without_market_fields(trades, offline: bool):
    """While market data is offline, stored prices / P&L are not shown (null). Built on response
    models, never on the ORM rows, so nothing is written back."""
    if not offline:
        return trades
    return [
        TradeListItem.model_validate(t).model_copy(update={"current_price": None, "unrealized_pnl": None})
        for t in trades
    ]


@router.put("/{trade_id}/rationale", response_model=RationaleResponse)
async def upsert_trade_rationale(
    trade_id: uuid.UUID,
    payload: RationaleCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await get_trade(db, user, trade_id)

    # Find existing entry-time rationale (commentary_id IS NULL)
    stmt = select(Rationale).where(
        Rationale.trade_id == trade_id,
        Rationale.commentary_id.is_(None),
    )
    result = await db.execute(stmt)
    rationale = result.scalar_one_or_none()

    if rationale is None:
        rationale = Rationale(user_id=user.id, trade_id=trade_id, commentary_id=None)
        db.add(rationale)

    data = payload.model_dump(exclude_none=True)
    data["fetch_status"] = "ok"
    for field, value in data.items():
        setattr(rationale, field, value)

    await db.commit()
    await db.refresh(rationale)
    return rationale


@router.patch("/{trade_id}", response_model=TradeResponse)
async def update_trade(
    trade_id: uuid.UUID,
    payload: TradeUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    trade = await get_trade(db, user, trade_id, options=(selectinload(Trade.rationale),))

    data = payload.model_dump(exclude_none=True)

    # Handle rationale_notes separately — stored in the related Rationale row
    rationale_notes = data.pop('rationale_notes', None)

    # When category string changes, sync category_id FK
    if 'category' in data:
        cat = await get_category_by_name(db, user, data['category'])
        trade.category_id = cat.id if cat else None

    if data.get('session_id') is not None:
        trade_session = await get_trade_session(db, user, data['session_id'])
        require_same_account(trade.account_id, trade_session.account_id, "Session")

    for field, value in data.items():
        setattr(trade, field, value)

    if rationale_notes is not None and trade.rationale:
        trade.rationale.notes = rationale_notes

    await db.commit()
    stmt2 = select(Trade).where(Trade.id == trade_id, Trade.user_id == user.id).options(selectinload(Trade.rationale))
    result2 = await db.execute(stmt2)
    trade = result2.scalar_one()
    return trade


@router.post("/{trade_id}/close", response_model=TradeListItem)
async def close_trade(
    trade_id: uuid.UUID,
    body: CloseTradeRequest = CloseTradeRequest(),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    trade = await get_trade(db, user, trade_id)
    trade.status = "closed"
    trade.closed_date = body.closed_date or date.today()
    await db.commit()
    await db.refresh(trade)
    return trade


@router.delete("/{trade_id}", status_code=204)
async def delete_trade(
    trade_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    trade = await get_trade(db, user, trade_id)
    await db.delete(trade)
    await db.commit()


class CategoryAssignRequest(BaseModel):
    category_id: Optional[uuid.UUID] = None


@router.patch("/{trade_id}/category", response_model=TradeListItem)
async def assign_category(
    trade_id: uuid.UUID,
    payload: CategoryAssignRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    trade = await get_trade(db, user, trade_id)
    if payload.category_id is not None:
        await get_category(db, user, payload.category_id)
    trade.category_id = payload.category_id
    await db.commit()
    await db.refresh(trade)
    return trade
