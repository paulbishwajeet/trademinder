import uuid
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.schemas.account import (
    AccountCreate, AccountUpdate, AccountCategoriesUpdate, AccountOrderUpdate, AccountResponse,
    AccountCreateAndLink, AccountLinkRequest, AccountLinkResolveRequest, AccountLinkResolveResponse,
)
from app.services import accounts as accounts_service
from app.services import account_links

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("", response_model=list[AccountResponse])
async def list_accounts(
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await accounts_service.list_accounts_annotated(db, user, include_archived)


@router.post("", response_model=AccountResponse, status_code=201)
async def create_account(payload: AccountCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await accounts_service.create_account(db, user, payload)


# Declared before /{account_id} routes so "order" is never parsed as an id.
@router.put("/order", response_model=list[AccountResponse])
async def reorder_accounts(
    payload: AccountOrderUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    return await accounts_service.reorder_accounts(db, user, payload.account_ids)


# E*TRADE links. Fingerprints only ever travel in request bodies, never in URLs (access logs).
@router.post("/links/resolve", response_model=AccountLinkResolveResponse)
async def resolve_link(
    payload: AccountLinkResolveRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    account = await account_links.resolve(db, user, payload.fingerprint, payload.label)
    if account is None:
        return AccountLinkResolveResponse(linked=False)
    return AccountLinkResolveResponse(linked=True, account=account, is_archived=account.is_archived)


@router.post("/links", response_model=AccountResponse, status_code=201)
async def create_and_link(
    payload: AccountCreateAndLink, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    return await account_links.create_and_link(db, user, payload.account, payload.fingerprint, payload.label)


@router.post("/{account_id}/link", response_model=AccountResponse)
async def link_account(
    account_id: uuid.UUID, payload: AccountLinkRequest,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    return await account_links.link_existing(db, user, account_id, payload.fingerprint, payload.label)


@router.delete("/{account_id}/link", response_model=AccountResponse)
async def unlink_account(account_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await account_links.unlink(db, user, account_id)


@router.patch("/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: uuid.UUID, payload: AccountUpdate,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    return await accounts_service.update_account(db, user, account_id, payload)


@router.put("/{account_id}/categories", response_model=AccountResponse)
async def set_account_categories(
    account_id: uuid.UUID, payload: AccountCategoriesUpdate,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    return await accounts_service.set_account_categories(db, user, account_id, payload.category_ids)


@router.post("/{account_id}/archive", response_model=AccountResponse)
async def archive_account(account_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await accounts_service.archive_account(db, user, account_id)


@router.post("/{account_id}/restore", response_model=AccountResponse)
async def restore_account(account_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await accounts_service.restore_account(db, user, account_id)


@router.delete("/{account_id}", status_code=204)
async def delete_account(account_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await accounts_service.delete_account(db, user, account_id)
