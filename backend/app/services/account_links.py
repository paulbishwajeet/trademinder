"""E*TRADE account links: one dropdown entry (by fingerprint) ↔ one brokerage account, per user.

The fingerprint is the extension's hex SHA-256 of broker + full account number; the number itself
never reaches the backend. An account has at most one link and a fingerprint links to at most one of
the user's accounts (also enforced by a partial unique index).
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brokerage_account import BrokerageAccount
from app.models.user import User
from app.schemas.account import AccountCreate
from app.services import accounts as accounts_service
from app.services.ownership import get_account


async def _find_by_fingerprint(db: AsyncSession, user: User, fingerprint: str) -> Optional[BrokerageAccount]:
    stmt = select(BrokerageAccount).where(
        BrokerageAccount.user_id == user.id, BrokerageAccount.external_ref == fingerprint,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def resolve(db: AsyncSession, user: User, fingerprint: str, label: Optional[str]) -> Optional[BrokerageAccount]:
    """The linked account, or None. A hit refreshes the last label and last-seen time."""
    account = await _find_by_fingerprint(db, user, fingerprint)
    if account is None:
        return None
    if label:
        account.external_label = label
    account.external_seen_at = datetime.now(timezone.utc)
    await db.commit()
    return account


def _attach(account: BrokerageAccount, fingerprint: str, label: str) -> None:
    account.external_ref = fingerprint
    account.external_label = label
    account.external_seen_at = datetime.now(timezone.utc)


async def link_existing(
    db: AsyncSession, user: User, account_id: uuid.UUID, fingerprint: str, label: str,
) -> BrokerageAccount:
    account = await get_account(db, user, account_id)
    if account.external_ref is not None and account.external_ref != fingerprint:
        raise HTTPException(status_code=409, detail="This account is already linked to another E*TRADE account")
    holder = await _find_by_fingerprint(db, user, fingerprint)
    if holder is not None and holder.id != account.id:
        raise HTTPException(
            status_code=409, detail=f"This E*TRADE account is already linked to \"{holder.nickname}\"",
        )
    _attach(account, fingerprint, label)
    await db.commit()
    return await accounts_service.reload_account(db, account.id)


async def create_and_link(
    db: AsyncSession, user: User, payload: AccountCreate, fingerprint: str, label: str,
) -> BrokerageAccount:
    holder = await _find_by_fingerprint(db, user, fingerprint)
    if holder is not None:
        raise HTTPException(
            status_code=409, detail=f"This E*TRADE account is already linked to \"{holder.nickname}\"",
        )
    created = await accounts_service.create_account(db, user, payload, commit=False)
    _attach(created, fingerprint, label)
    await db.commit()
    return await accounts_service.reload_account(db, created.id)


async def unlink(db: AsyncSession, user: User, account_id: uuid.UUID) -> BrokerageAccount:
    account = await get_account(db, user, account_id)
    account.external_ref = None
    account.external_label = None
    account.external_seen_at = None
    await db.commit()
    return await accounts_service.reload_account(db, account.id)
