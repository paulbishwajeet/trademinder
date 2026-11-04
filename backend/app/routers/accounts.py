import uuid
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.schemas.account import AccountCreate, AccountUpdate, AccountCategoriesUpdate, AccountResponse
from app.services import accounts as accounts_service

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("", response_model=list[AccountResponse])
async def list_accounts(
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await accounts_service.list_accounts(db, user, include_archived)


@router.post("", response_model=AccountResponse, status_code=201)
async def create_account(payload: AccountCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await accounts_service.create_account(db, user, payload)


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


@router.delete("/{account_id}", status_code=204)
async def delete_account(account_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await accounts_service.delete_account(db, user, account_id)
