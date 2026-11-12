import uuid
from datetime import date
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sqla_func, or_
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.deps import get_current_user, market_data_flag
from app.models.user import User
from app.services.market_data import market_data_offline
from app.services.ownership import (
    get_trade, get_wheel_session, get_slot, resolve_account, resolve_account_filter, require_same_account,
)
from app.models.wheel_session import WheelSession
from app.models.wheel_slot import WheelSlot
from app.models.wheel_slot_leg import WheelSlotLeg
from app.models.wheel_premium_log import WheelPremiumLog
from app.models.trade import Trade
from app.models.commentary import Commentary
from app.schemas.commentary import CommentaryCreate, CommentaryResponse
from app.schemas.wheel import (
    WheelSessionCreate, WheelSessionUpdate, WheelSessionSummary, WheelSessionDetail,
    WheelSlotCreate, WheelSlotUpdate, WheelSlotSummary, WheelSlotDetail,
    WheelSlotLegCreate, WheelSlotLegItem,
    WheelResolveRequest,
    WheelPremiumLogItem, WheelActiveSlotItem,
    WheelSlotHistoryEntry, WheelSlotHistoryResponse,
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


async def _find_stock_position(
    db: AsyncSession, session: WheelSession,
) -> tuple[Optional[Decimal], Optional[Decimal]]:
    """Stock position backing a wheel — looked up in the wheel's own user + account only."""
    ticker = session.ticker

    async def _latest_open_stock_trade(t: str) -> Optional[Trade]:
        stmt = (
            select(Trade)
            .where(
                Trade.user_id == session.user_id,
                Trade.account_id == session.account_id,
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
        account_id=slot.account_id, account=slot.account,
        contracts=slot.contracts, shares_held=slot.shares_held,
        status=slot.status, needs_action=slot.needs_action,
        rotation_number=slot.rotation_number,
        legs=legs, premium_logs=logs, total_premium=total,
    )


async def _build_session_detail(
    db: AsyncSession, session: WheelSession, offline: Optional[bool] = None,
) -> WheelSessionDetail:
    if offline is None:
        offline = market_data_offline()  # write endpoints: cached state, no header
    slots = [_build_slot_detail(s) for s in sorted(session.slots, key=lambda s: s.slot_number)]
    if offline:
        for slot in slots:
            slot.legs = [leg.model_copy(update={"trade_current_price": None}) for leg in slot.legs]
    total = sum((s.total_premium for s in slots), Decimal("0"))
    stock_cost_basis, stock_current_price = await _find_stock_position(db, session)
    if offline:
        stock_current_price = None
    return WheelSessionDetail(
        market_data_offline=offline,
        id=session.id, account_id=session.account_id, account=session.account, ticker=session.ticker, total_shares=session.total_shares,
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
async def create_wheel_session(payload: WheelSessionCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    account = await resolve_account(db, user, payload.account_id)
    session = WheelSession(
        user_id=user.id,
        account_id=account.id,
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
    account_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(WheelSession).where(WheelSession.user_id == user.id)
    account_filter = await resolve_account_filter(db, user, account_id)
    if account_filter is not None:
        stmt = stmt.where(WheelSession.account_id == account_filter)
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
async def list_active_slots(
    account_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
    offline: bool = Depends(market_data_flag),  # no market fields; header only (extension notice)
):
    stmt = (
        select(WheelSlot)
        .join(WheelSession)
        .where(WheelSlot.user_id == user.id, WheelSession.user_id == user.id, WheelSession.status == "active")
        .options(
            selectinload(WheelSlot.session),
            selectinload(WheelSlot.legs).selectinload(WheelSlotLeg.trade),
        )
    )
    account_filter = await resolve_account_filter(db, user, account_id)
    if account_filter is not None:
        stmt = stmt.where(WheelSession.account_id == account_filter)
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
            account_id=slot.account_id, account=slot.account,
            contracts=slot.contracts, shares_held=slot.shares_held,
            status=slot.status, needs_action=slot.needs_action,
            rotation_number=slot.rotation_number,
            ticker=slot.session.ticker,
            etrade_symbols=[s.upper() for s in etrade_symbols],
        ))
    return items


@router.get("/{session_id}", response_model=WheelSessionDetail)
async def get_wheel_session_detail(
    session_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
    offline: bool = Depends(market_data_flag),
):
    session = await get_wheel_session(db, user, session_id, options=_load_session_options())
    return await _build_session_detail(db, session, offline)


@router.patch("/{session_id}", response_model=WheelSessionSummary)
async def update_wheel_session(session_id: uuid.UUID, payload: WheelSessionUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    session = await get_wheel_session(db, user, session_id, options=(selectinload(WheelSession.slots),))
    # The ticker is fixed once a slot exists: its legs are linked to trades in that ticker.
    if payload.ticker is not None and payload.ticker != session.ticker and session.slots:
        raise HTTPException(status_code=409, detail="Can't change the ticker of a wheel that has slots")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(session, field, value)
    await db.commit()
    await db.refresh(session)
    return session


@router.delete("/{session_id}", status_code=204)
async def delete_wheel_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    # Only a wheel with no slots: it has no legs, premium history or notes to lose. Slots are removed one by one first.
    session = await get_wheel_session(db, user, session_id, options=(selectinload(WheelSession.slots),))
    if session.slots:
        raise HTTPException(status_code=409, detail="Remove this wheel's slots before deleting it")
    await db.delete(session)
    await db.commit()


@router.post("/{session_id}/slots", response_model=WheelSlotSummary, status_code=201)
async def add_slot(session_id: uuid.UUID, payload: WheelSlotCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await get_wheel_session(db, user, session_id)
    count_stmt = select(sqla_func.count()).select_from(WheelSlot).where(WheelSlot.session_id == session_id)
    count_result = await db.execute(count_stmt)
    next_number = count_result.scalar() + 1

    slot = WheelSlot(
        user_id=user.id,
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
async def delete_slot(slot_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    slot = await get_slot(db, user, slot_id)
    await db.delete(slot)
    await db.commit()


@router.patch("/slots/{slot_id}", response_model=WheelSlotSummary)
async def update_slot(slot_id: uuid.UUID, payload: WheelSlotUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    slot = await get_slot(db, user, slot_id)
    if slot.status not in ("awaiting_cc", "awaiting_sold_put"):
        raise HTTPException(
            status_code=400,
            detail="Cannot change contracts while a leg is active — resolve or close the current leg first.",
        )
    if payload.contracts < 1:
        raise HTTPException(status_code=400, detail="Contracts must be at least 1")

    slot.contracts = payload.contracts
    await db.commit()
    await db.refresh(slot)
    return slot


@router.post("/slots/{slot_id}/legs", response_model=WheelSlotLegItem, status_code=201)
async def link_leg(slot_id: uuid.UUID, payload: WheelSlotLegCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    slot = await get_slot(db, user, slot_id)
    trade = await get_trade(db, user, payload.trade_id)
    require_same_account(slot.account_id, trade.account_id, "Trade")

    leg = WheelSlotLeg(
        user_id=user.id,
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
            user_id=user.id,
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
async def resolve_slot(slot_id: uuid.UUID, payload: WheelResolveRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    slot = await get_slot(db, user, slot_id)

    outcome = payload.outcome
    if outcome not in OUTCOME_MAP:
        raise HTTPException(status_code=400, detail=f"Unknown outcome: {outcome}")

    new_status, shares_action, increment_rotation, event_type = OUTCOME_MAP[outcome]
    session = slot.session

    if payload.buyback_cost is not None:
        db.add(WheelPremiumLog(
            user_id=user.id,
            slot_id=slot_id,
            rotation_number=slot.rotation_number,
            premium_amount=-abs(payload.buyback_cost),
            event_type=event_type,
            event_date=date.today(),
            notes=payload.notes,
        ))
    elif event_type in ("cc_expired_otm", "cc_expired_itm", "put_expired_otm", "put_assigned"):
        db.add(WheelPremiumLog(
            user_id=user.id,
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
        try:
            new_trade = await get_trade(db, user, payload.new_trade_id)
        except HTTPException:
            raise HTTPException(status_code=404, detail="New trade not found")
        require_same_account(slot.account_id, new_trade.account_id, "New trade")
        leg_role = "covered_call" if outcome == "cc_rolled" else "sold_put"
        new_leg = WheelSlotLeg(
            user_id=user.id,
            slot_id=slot_id,
            trade_id=payload.new_trade_id,
            leg_role=leg_role,
            rotation_number=slot.rotation_number,
        )
        db.add(new_leg)
        if new_trade.premium:
            roll_event = "cc_sold" if outcome == "cc_rolled" else "put_sold"
            db.add(WheelPremiumLog(
                user_id=user.id,
                slot_id=slot_id,
                rotation_number=slot.rotation_number,
                premium_amount=new_trade.premium * new_trade.quantity,
                event_type=roll_event,
                event_date=new_trade.open_date,
            ))

    if outcome == "put_assigned" and payload.new_trade_id:
        try:
            stock_trade = await get_trade(db, user, payload.new_trade_id)
        except HTTPException:
            raise HTTPException(status_code=404, detail="Stock trade not found")
        require_same_account(slot.account_id, stock_trade.account_id, "Stock trade")
        db.add(WheelSlotLeg(
            user_id=user.id,
            slot_id=slot_id,
            trade_id=payload.new_trade_id,
            leg_role="stock",
            rotation_number=slot.rotation_number,
        ))

    await db.commit()
    await db.refresh(slot)
    return slot


@router.post("/slots/{slot_id}/commentary", response_model=CommentaryResponse, status_code=201)
async def add_slot_commentary(slot_id: uuid.UUID, payload: CommentaryCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    slot = await get_slot(db, user, slot_id)

    comment = Commentary(
        user_id=user.id,
        slot_id=slot_id,
        note=payload.note,
        tags=payload.tags,
        signal_snapshot=payload.signal_snapshot,
    )
    db.add(comment)
    await db.commit()

    stmt = select(Commentary).where(Commentary.id == comment.id).options(selectinload(Commentary.rationale))
    result = await db.execute(stmt)
    return result.scalar_one()


@router.get("/slots/{slot_id}/history", response_model=WheelSlotHistoryResponse)
async def get_slot_history(
    slot_id: uuid.UUID,
    limit: int = Query(5, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    slot = await get_slot(db, user, slot_id)

    legs_result = await db.execute(
        select(WheelSlotLeg).where(WheelSlotLeg.slot_id == slot_id, WheelSlotLeg.user_id == user.id)
    )
    leg_by_trade_id = {leg.trade_id: leg for leg in legs_result.scalars().all()}
    trade_ids = list(leg_by_trade_id.keys())

    conditions = [Commentary.slot_id == slot_id]
    if trade_ids:
        conditions.append(Commentary.trade_id.in_(trade_ids))
    stmt = (
        select(Commentary)
        .where(Commentary.user_id == user.id, or_(*conditions))
        .options(selectinload(Commentary.rationale))
        .order_by(Commentary.created_at.desc())
    )
    result = await db.execute(stmt)
    all_entries = result.scalars().all()

    total = len(all_entries)
    page = all_entries[offset: offset + limit]

    items: list[WheelSlotHistoryEntry] = []
    for entry in page:
        entry_dict = CommentaryResponse.model_validate(entry).model_dump()
        if entry.slot_id is not None:
            items.append(WheelSlotHistoryEntry(**entry_dict, origin="slot", leg_role=None, rotation_number=None))
        else:
            leg = leg_by_trade_id.get(entry.trade_id)
            items.append(WheelSlotHistoryEntry(
                **entry_dict, origin="leg",
                leg_role=leg.leg_role if leg else None,
                rotation_number=leg.rotation_number if leg else None,
            ))

    return WheelSlotHistoryResponse(items=items, total=total, has_more=offset + limit < total)
