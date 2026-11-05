import uuid
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select, exists, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brokerage_account import BrokerageAccount, AccountCategory, ScreenerAccountMembership
from app.models.category import Category
from app.models.screener import Screener
from app.models.screener_commentary import ScreenerCommentary
from app.models.trade import Trade
from app.models.trade_session import TradeSession
from app.models.user import User
from app.models.wheel_session import WheelSession
from app.schemas.account import AccountCreate, AccountUpdate
from app.services.ownership import get_account, get_category


async def list_accounts(db: AsyncSession, user: User, include_archived: bool = False) -> list[BrokerageAccount]:
    stmt = select(BrokerageAccount).where(BrokerageAccount.user_id == user.id)
    if not include_archived:
        stmt = stmt.where(BrokerageAccount.is_archived.is_(False))
    stmt = stmt.order_by(BrokerageAccount.sort_order, BrokerageAccount.created_at)
    return list((await db.execute(stmt)).scalars().all())


async def _active_accounts(db: AsyncSession, user: User) -> list[BrokerageAccount]:
    return await list_accounts(db, user, include_archived=False)


async def _make_default(db: AsyncSession, user: User, account: BrokerageAccount) -> None:
    # The one-default partial unique index is not deferrable: clear the old default first.
    for other in await list_accounts(db, user, include_archived=True):
        if other.id != account.id and other.is_default:
            other.is_default = False
    await db.flush()
    account.is_default = True


async def _validate_category_ids(db: AsyncSession, user: User, category_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    unique_ids = list(dict.fromkeys(category_ids))
    for cid in unique_ids:
        await get_category(db, user, cid)  # 404 if not the user's
    return unique_ids


def _check_default_category(default_category_id: Optional[uuid.UUID], category_ids: list[uuid.UUID]) -> None:
    if default_category_id is not None and default_category_id not in category_ids:
        raise HTTPException(status_code=400, detail="Default category must be one of the account's categories")


async def _reload(db: AsyncSession, account_id: uuid.UUID) -> BrokerageAccount:
    db.expire_all()
    stmt = select(BrokerageAccount).where(BrokerageAccount.id == account_id)
    return (await db.execute(stmt)).scalar_one()


async def create_account(db: AsyncSession, user: User, payload: AccountCreate) -> BrokerageAccount:
    if payload.category_ids is None:
        result = await db.execute(select(Category.id).where(Category.user_id == user.id))
        category_ids = [row[0] for row in result.all()]
    else:
        category_ids = await _validate_category_ids(db, user, payload.category_ids)
    _check_default_category(payload.default_category_id, category_ids)

    first_account = not await _active_accounts(db, user)
    account = BrokerageAccount(
        user_id=user.id,
        broker=payload.broker,
        nickname=payload.nickname,
        last_four=payload.last_four,
        sort_order=payload.sort_order,
        default_category_id=payload.default_category_id,
        is_default=False,
    )
    db.add(account)
    await db.flush()
    for cid in category_ids:
        db.add(AccountCategory(account_id=account.id, category_id=cid))
    if payload.is_default or first_account:
        await _make_default(db, user, account)
    await db.commit()
    return await _reload(db, account.id)


async def update_account(db: AsyncSession, user: User, account_id: uuid.UUID, payload: AccountUpdate) -> BrokerageAccount:
    account = await get_account(db, user, account_id)
    data = payload.model_dump(exclude_unset=True)

    if "default_category_id" in data and data["default_category_id"] is not None:
        await get_category(db, user, data["default_category_id"])
        _check_default_category(data["default_category_id"], account.category_ids)

    is_default = data.pop("is_default", None)
    if is_default is True:
        if account.is_archived:
            raise HTTPException(status_code=400, detail="An archived account cannot be the default")
        await _make_default(db, user, account)
    elif is_default is False and account.is_default:
        raise HTTPException(status_code=400, detail="Make another account the default instead of unsetting this one")

    for field, value in data.items():
        if field in ("broker", "nickname", "sort_order") and value is None:
            continue
        setattr(account, field, value)
    await db.commit()
    return await _reload(db, account.id)


async def set_account_categories(
    db: AsyncSession, user: User, account_id: uuid.UUID, category_ids: list[uuid.UUID],
) -> BrokerageAccount:
    account = await get_account(db, user, account_id)
    wanted = await _validate_category_ids(db, user, category_ids)
    await db.execute(delete(AccountCategory).where(AccountCategory.account_id == account.id))
    for cid in wanted:
        db.add(AccountCategory(account_id=account.id, category_id=cid))
    if account.default_category_id is not None and account.default_category_id not in wanted:
        account.default_category_id = None
    await db.commit()
    return await _reload(db, account.id)


async def link_category_to_active_accounts(db: AsyncSession, user: User, category_id: uuid.UUID) -> None:
    """New categories appear in every active account, matching the pre-accounts behaviour."""
    for account in await _active_accounts(db, user):
        db.add(AccountCategory(account_id=account.id, category_id=category_id))


async def account_has_data(db: AsyncSession, account_id: uuid.UUID) -> bool:
    for model in (Trade, WheelSession, TradeSession, ScreenerCommentary):
        if await db.scalar(select(exists().where(model.account_id == account_id))):
            return True
    return False


async def _ensure_not_last_active(db: AsyncSession, user: User, account: BrokerageAccount) -> None:
    active = await _active_accounts(db, user)
    if not account.is_archived and len(active) <= 1:
        raise HTTPException(status_code=400, detail="The last active account cannot be archived or deleted")


async def _move_default_off(db: AsyncSession, user: User, account: BrokerageAccount) -> None:
    if not account.is_default:
        return
    successor = next((a for a in await _active_accounts(db, user) if a.id != account.id), None)
    account.is_default = False
    await db.flush()
    if successor is not None:
        successor.is_default = True


async def archive_account(db: AsyncSession, user: User, account_id: uuid.UUID) -> BrokerageAccount:
    account = await get_account(db, user, account_id)
    if account.is_archived:
        return account
    await _ensure_not_last_active(db, user, account)
    await _move_default_off(db, user, account)
    account.is_archived = True
    await db.commit()
    return await _reload(db, account.id)


async def delete_account(db: AsyncSession, user: User, account_id: uuid.UUID) -> None:
    """Hard delete — only for accounts that never held trades, wheels, spreads or screener notes."""
    account = await get_account(db, user, account_id)
    if await account_has_data(db, account.id):
        raise HTTPException(status_code=409, detail="Account has trades, wheels, spreads or notes — archive it instead")
    await _ensure_not_last_active(db, user, account)
    await _move_default_off(db, user, account)
    await db.delete(account)
    await db.flush()
    # Symbols that only belonged to this account would otherwise sit in no account at all.
    orphan_ids = select(Screener.id).where(
        Screener.user_id == user.id,
        ~exists().where(ScreenerAccountMembership.screener_id == Screener.id),
    )
    await db.execute(delete(Screener).where(Screener.id.in_(orphan_ids)))
    await db.commit()
