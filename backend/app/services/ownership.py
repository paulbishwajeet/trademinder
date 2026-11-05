"""Every per-id lookup of a user-owned row goes through here.

Each getter filters by the owning user and raises 404 for a missing *or foreign* id, so another
user's rows are indistinguishable from rows that don't exist (never 403).
"""
import uuid
from typing import Optional, TypeVar

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert
from app.models.brokerage_account import BrokerageAccount
from app.models.category import Category
from app.models.commentary import Commentary
from app.models.screener import Screener
from app.models.screener_commentary import ScreenerCommentary
from app.models.trade import Trade
from app.models.trade_session import TradeSession
from app.models.user import User
from app.models.wheel_session import WheelSession
from app.models.wheel_slot import WheelSlot

M = TypeVar("M")


async def get_owned(db: AsyncSession, model: type[M], obj_id: uuid.UUID, user: User, label: str, options=()) -> M:
    stmt = select(model).where(model.id == obj_id, model.user_id == user.id)
    if options:
        stmt = stmt.options(*options)
    obj = (await db.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return obj


async def get_trade(db: AsyncSession, user: User, trade_id: uuid.UUID, options=()) -> Trade:
    return await get_owned(db, Trade, trade_id, user, "Trade", options)


async def get_wheel_session(db: AsyncSession, user: User, session_id: uuid.UUID, options=()) -> WheelSession:
    return await get_owned(db, WheelSession, session_id, user, "Wheel session", options)


async def get_slot(db: AsyncSession, user: User, slot_id: uuid.UUID, options=()) -> WheelSlot:
    return await get_owned(db, WheelSlot, slot_id, user, "Slot", options)


async def get_trade_session(db: AsyncSession, user: User, session_id: uuid.UUID, options=()) -> TradeSession:
    return await get_owned(db, TradeSession, session_id, user, "Session", options)


async def get_category(db: AsyncSession, user: User, category_id: uuid.UUID) -> Category:
    return await get_owned(db, Category, category_id, user, "Category")


async def get_category_by_name(db: AsyncSession, user: User, name: str) -> Optional[Category]:
    stmt = select(Category).where(Category.user_id == user.id, Category.name == name)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_alert(db: AsyncSession, user: User, alert_id: uuid.UUID) -> Alert:
    return await get_owned(db, Alert, alert_id, user, "Alert")


async def get_commentary(db: AsyncSession, user: User, comment_id: uuid.UUID) -> Commentary:
    return await get_owned(db, Commentary, comment_id, user, "Commentary entry")


async def get_screener_commentary(db: AsyncSession, user: User, comment_id: uuid.UUID) -> ScreenerCommentary:
    return await get_owned(db, ScreenerCommentary, comment_id, user, "Commentary entry")


async def get_screener_row(db: AsyncSession, user: User, symbol: str) -> Screener:
    stmt = select(Screener).where(Screener.user_id == user.id, Screener.symbol == symbol.upper())
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{symbol.upper()} is not tracked")
    return row


async def get_account(
    db: AsyncSession, user: User, account_id: uuid.UUID, include_archived: bool = True,
) -> BrokerageAccount:
    account = await get_owned(db, BrokerageAccount, account_id, user, "Account")
    if account.is_archived and not include_archived:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


async def get_default_account(db: AsyncSession, user: User) -> BrokerageAccount:
    stmt = select(BrokerageAccount).where(
        BrokerageAccount.user_id == user.id, BrokerageAccount.is_default.is_(True),
    )
    account = (await db.execute(stmt)).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=500, detail="User has no default brokerage account")
    return account


async def resolve_account(db: AsyncSession, user: User, account_id: Optional[uuid.UUID]) -> BrokerageAccount:
    """Account a *write* lands in: the named (active) account, or the user's default when None."""
    if account_id is None:
        return await get_default_account(db, user)
    return await get_account(db, user, account_id, include_archived=False)


async def resolve_account_filter(db: AsyncSession, user: User, account_id: Optional[uuid.UUID]) -> Optional[uuid.UUID]:
    """Account a *list* is narrowed to: validated id, or None meaning all of the user's accounts.
    Archived accounts are still listable."""
    if account_id is None:
        return None
    return (await get_account(db, user, account_id)).id


def require_same_account(expected: uuid.UUID, actual: uuid.UUID, what: str) -> None:
    if expected != actual:
        raise HTTPException(status_code=400, detail=f"{what} belongs to a different account")
