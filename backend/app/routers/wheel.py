import uuid
from datetime import date
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sqla_func
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.wheel_session import WheelSession
from app.models.wheel_slot import WheelSlot
from app.models.wheel_slot_leg import WheelSlotLeg
from app.models.wheel_premium_log import WheelPremiumLog
from app.models.trade import Trade
from app.schemas.wheel import (
    WheelSessionCreate, WheelSessionUpdate, WheelSessionSummary, WheelSessionDetail,
    WheelSlotCreate, WheelSlotSummary, WheelSlotDetail,
    WheelSlotLegCreate, WheelSlotLegItem,
    WheelResolveRequest,
    WheelPremiumLogItem, WheelActiveSlotItem,
)

router = APIRouter(prefix="/api/wheel", tags=["wheel"])

LEG_ROLE_TO_STATUS = {
    "covered_call": "cc_active",
    "sold_put": "sold_put_active",
}

LEG_ROLE_TO_EVENT = {
    "covered_call": "cc_sold",
    "sold_put": "put_sold",
}

OUTCOME_MAP = {
    "cc_expired_otm":  ("awaiting_cc",        "keep",   False, "cc_expired_otm"),
    "cc_expired_itm":  ("awaiting_sold_put",   "zero",   True,  "cc_expired_itm"),
    "cc_bought_back":  ("awaiting_cc",         "keep",   False, "cc_bought_back"),
    "cc_rolled":       ("cc_active",           "keep",   False, "cc_bought_back"),
    "put_expired_otm": ("awaiting_sold_put",   "keep",   False, "put_expired_otm"),
    "put_assigned":    ("awaiting_cc",         "assign", True,  "put_assigned"),
    "put_bought_back": ("awaiting_sold_put",   "keep",   False, "put_bought_back"),
    "put_rolled":      ("sold_put_active",     "keep",   False, "put_bought_back"),
}

TICKER_ALIASES = {"GOOG": "GOOGL", "GOOGL": "GOOG"}


async def _find_stock_position(db: AsyncSession, ticker: str) -> tuple[Optional[Decimal], Optional[Decimal]]:
    async def _latest_open_stock_trade(t: str) -> Optional[Trade]:
        stmt = (
            select(Trade)
            .where(
                Trade.category == "WHEEL",
                Trade.strategy == "Stock",
                Trade.status == "open",
                Trade.ticker == t,
            )
            .order_by(Trade.open_date.desc())
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    trade = await _latest_open_stock_trade(ticker)
    if trade is None and ticker in TICKER_ALIASES:
        trade = await _latest_open_stock_trade(TICKER_ALIASES[ticker])
    if trade is None:
        return None, None
    return trade.premium, trade.current_price


def _build_leg_item(leg: WheelSlotLeg) -> WheelSlotLegItem:
    t = leg.trade
    return WheelSlotLegItem(
        id=leg.id, slot_id=leg.slot_id, trade_id=leg.trade_id,
        leg_role=leg.leg_role, rotation_number=leg.rotation_number,
        trade_type=t.type if t else None,
        trade_strategy=t.strategy if t else None,
        trade_ticker=t.ticker if t else None,
        trade_open_date=t.open_date if t else None,
        trade_expiry_date=t.expiry_date if t else None,
        trade_strike_price=t.strike_price if t else None,
        trade_quantity=t.quantity if t else None,
        trade_premium=t.premium if t else None,
        trade_current_price=t.current_price if t else None,
        trade_status=t.status if t else None,
        trade_etrade_symbol=t.etrade_symbol if t else None,
    )


def _build_slot_detail(slot: WheelSlot) -> WheelSlotDetail:
    legs = [_build_leg_item(l) for l in sorted(slot.legs, key=lambda l: l.created_at)]
    logs = [WheelPremiumLogItem.model_validate(p) for p in sorted(slot.premium_logs, key=lambda p: p.event_date)]
    total = sum((p.premium_amount for p in slot.premium_logs), Decimal("0"))
    return WheelSlotDetail(
        id=slot.id, session_id=slot.session_id, slot_number=slot.slot_number,
        contracts=slot.contracts, shares_held=slot.shares_held,
        status=slot.status, needs_action=slot.needs_action,
        rotation_number=slot.rotation_number,
        legs=legs, premium_logs=logs, total_premium=total,
    )


async def _build_session_detail(db: AsyncSession, session: WheelSession) -> WheelSessionDetail:
    slots = [_build_slot_detail(s) for s in sorted(session.slots, key=lambda s: s.slot_number)]
    total = sum((s.total_premium for s in slots), Decimal("0"))
    stock_cost_basis, stock_current_price = await _find_stock_position(db, session.ticker)
    return WheelSessionDetail(
        id=session.id, ticker=session.ticker, total_shares=session.total_shares,
        status=session.status, opened_at=session.opened_at, closed_at=session.closed_at,
        slots=slots, total_premium=total,
        stock_cost_basis=stock_cost_basis, stock_current_price=stock_current_price,
    )


def _load_session_options():
    return (
        selectinload(WheelSession.slots)
        .selectinload(WheelSlot.legs)
        .selectinload(WheelSlotLeg.trade),
        selectinload(WheelSession.slots)
        .selectinload(WheelSlot.premium_logs),
    )


@router.post("", response_model=WheelSessionSummary, status_code=201)
async def create_wheel_session(payload: WheelSessionCreate, db: AsyncSession = Depends(get_db)):
    session = WheelSession(
        ticker=payload.ticker.upper(),
        total_shares=payload.total_shares,
        opened_at=payload.opened_at,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("", response_model=list[WheelSessionSummary])
async def list_wheel_sessions(
    status: Optional[str] = Query(None),
    ticker: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(WheelSession)
    if status:
        stmt = stmt.where(WheelSession.status == status)
    else:
        stmt = stmt.where(WheelSession.status != "closed")
    if ticker:
        stmt = stmt.where(WheelSession.ticker == ticker.upper())
    stmt = stmt.order_by(WheelSession.ticker)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/active-slots", response_model=list[WheelActiveSlotItem])
async def list_active_slots(db: AsyncSession = Depends(get_db)):
    stmt = (
        select(WheelSlot)
        .join(WheelSession)
        .where(WheelSession.status == "active")
        .options(
            selectinload(WheelSlot.session),
            selectinload(WheelSlot.legs).selectinload(WheelSlotLeg.trade),
        )
    )
    result = await db.execute(stmt)
    slots = result.scalars().all()
    items = []
    for slot in slots:
        etrade_symbols = [
            l.trade.etrade_symbol
            for l in slot.legs
            if l.trade and l.trade.etrade_symbol and l.trade.status == "open"
        ]
        items.append(WheelActiveSlotItem(
            id=slot.id, session_id=slot.session_id, slot_number=slot.slot_number,
            contracts=slot.contracts, shares_held=slot.shares_held,
            status=slot.status, needs_action=slot.needs_action,
            rotation_number=slot.rotation_number,
            ticker=slot.session.ticker,
            etrade_symbols=[s.upper() for s in etrade_symbols],
        ))
    return items


@router.get("/{session_id}", response_model=WheelSessionDetail)
async def get_wheel_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    opts = _load_session_options()
    stmt = select(WheelSession).where(WheelSession.id == session_id).options(*opts)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Wheel session not found")
    return await _build_session_detail(db, session)


@router.patch("/{session_id}", response_model=WheelSessionSummary)
async def update_wheel_session(session_id: uuid.UUID, payload: WheelSessionUpdate, db: AsyncSession = Depends(get_db)):
    session = await db.get(WheelSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Wheel session not found")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(session, field, value)
    await db.commit()
    await db.refresh(session)
    return session


@router.post("/{session_id}/slots", response_model=WheelSlotSummary, status_code=201)
async def add_slot(session_id: uuid.UUID, payload: WheelSlotCreate, db: AsyncSession = Depends(get_db)):
    session = await db.get(WheelSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Wheel session not found")
    count_stmt = select(sqla_func.count()).select_from(WheelSlot).where(WheelSlot.session_id == session_id)
    count_result = await db.execute(count_stmt)
    next_number = count_result.scalar() + 1

    slot = WheelSlot(
        session_id=session_id,
        slot_number=next_number,
        contracts=payload.contracts,
        shares_held=payload.shares_held,
        status=payload.status,
    )
    db.add(slot)
    await db.commit()
    await db.refresh(slot)
    return slot


@router.delete("/slots/{slot_id}", status_code=204)
async def delete_slot(slot_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    slot = await db.get(WheelSlot, slot_id)
    if slot is None:
        raise HTTPException(status_code=404, detail="Slot not found")
    await db.delete(slot)
    await db.commit()


@router.post("/slots/{slot_id}/legs", response_model=WheelSlotLegItem, status_code=201)
async def link_leg(slot_id: uuid.UUID, payload: WheelSlotLegCreate, db: AsyncSession = Depends(get_db)):
    slot = await db.get(WheelSlot, slot_id)
    if slot is None:
        raise HTTPException(status_code=404, detail="Slot not found")
    trade = await db.get(Trade, payload.trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found")

    leg = WheelSlotLeg(
        slot_id=slot_id,
        trade_id=payload.trade_id,
        leg_role=payload.leg_role,
        rotation_number=slot.rotation_number,
    )
    db.add(leg)
    await db.flush()

    new_status = LEG_ROLE_TO_STATUS.get(payload.leg_role)
    if new_status:
        slot.status = new_status

    event_type = LEG_ROLE_TO_EVENT.get(payload.leg_role)
    if event_type and trade.premium:
        premium_log = WheelPremiumLog(
            slot_id=slot_id,
            leg_id=leg.id,
            rotation_number=slot.rotation_number,
            premium_amount=trade.premium * trade.quantity,
            event_type=event_type,
            event_date=trade.open_date,
        )
        db.add(premium_log)

    await db.commit()
    await db.refresh(leg, attribute_names=["trade"])
    return _build_leg_item(leg)


@router.post("/slots/{slot_id}/resolve", response_model=WheelSlotSummary)
async def resolve_slot(slot_id: uuid.UUID, payload: WheelResolveRequest, db: AsyncSession = Depends(get_db)):
    slot = await db.get(WheelSlot, slot_id)
    if slot is None:
        raise HTTPException(status_code=404, detail="Slot not found")

    outcome = payload.outcome
    if outcome not in OUTCOME_MAP:
        raise HTTPException(status_code=400, detail=f"Unknown outcome: {outcome}")

    new_status, shares_action, increment_rotation, event_type = OUTCOME_MAP[outcome]
    session = await db.get(WheelSession, slot.session_id)

    if payload.buyback_cost is not None:
        db.add(WheelPremiumLog(
            slot_id=slot_id,
            rotation_number=slot.rotation_number,
            premium_amount=-abs(payload.buyback_cost),
            event_type=event_type,
            event_date=date.today(),
            notes=payload.notes,
        ))
    elif event_type in ("cc_expired_otm", "cc_expired_itm", "put_expired_otm", "put_assigned"):
        db.add(WheelPremiumLog(
            slot_id=slot_id,
            rotation_number=slot.rotation_number,
            premium_amount=Decimal("0"),
            event_type=event_type,
            event_date=date.today(),
            notes=payload.notes,
        ))

    if shares_action == "zero":
        if session:
            session.total_shares -= slot.shares_held
        slot.shares_held = 0
    elif shares_action == "assign":
        assigned = slot.contracts * 100
        slot.shares_held = assigned
        if session:
            session.total_shares += assigned

    if increment_rotation:
        slot.rotation_number += 1

    slot.status = new_status
    slot.needs_action = False

    if outcome in ("cc_rolled", "put_rolled") and payload.new_trade_id:
        new_trade = await db.get(Trade, payload.new_trade_id)
        if new_trade is None:
            raise HTTPException(status_code=404, detail="New trade not found")
        leg_role = "covered_call" if outcome == "cc_rolled" else "sold_put"
        new_leg = WheelSlotLeg(
            slot_id=slot_id,
            trade_id=payload.new_trade_id,
            leg_role=leg_role,
            rotation_number=slot.rotation_number,
        )
        db.add(new_leg)
        if new_trade.premium:
            roll_event = "cc_sold" if outcome == "cc_rolled" else "put_sold"
            db.add(WheelPremiumLog(
                slot_id=slot_id,
                rotation_number=slot.rotation_number,
                premium_amount=new_trade.premium * new_trade.quantity,
                event_type=roll_event,
                event_date=new_trade.open_date,
            ))

    if outcome == "put_assigned" and payload.new_trade_id:
        stock_trade = await db.get(Trade, payload.new_trade_id)
        if stock_trade is None:
            raise HTTPException(status_code=404, detail="Stock trade not found")
        db.add(WheelSlotLeg(
            slot_id=slot_id,
            trade_id=payload.new_trade_id,
            leg_role="stock",
            rotation_number=slot.rotation_number,
        ))

    await db.commit()
    await db.refresh(slot)
    return slot
