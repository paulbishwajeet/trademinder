"""Admin: manage user accounts (never their data)."""
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import require_admin
from app.models.user import User
from app.schemas.auth import AdminUserResponse, InviteRequest, RoleUpdate
from app.services import user_admin

router = APIRouter(prefix="/api/admin/users", tags=["admin"])


def _view(user: User) -> AdminUserResponse:
    view = AdminUserResponse.model_validate(user)
    return view.model_copy(update={"has_signed_in": user.external_subject is not None})


@router.get("", response_model=list[AdminUserResponse])
async def list_users(
    status: Optional[Literal["pending", "active", "disabled"]] = Query(None),
    db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin),
):
    return [_view(u) for u in await user_admin.list_users(db, status)]


@router.post("/invite", response_model=AdminUserResponse, status_code=201)
async def invite(payload: InviteRequest, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    return _view(await user_admin.invite(db, admin, payload.email, payload.role))


@router.post("/{user_id}/approve", response_model=AdminUserResponse)
async def approve(user_id: uuid.UUID, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    return _view(await user_admin.approve(db, admin, user_id))


@router.post("/{user_id}/reject", response_model=AdminUserResponse)
async def reject(user_id: uuid.UUID, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    return _view(await user_admin.disable(db, admin, user_id, action="reject"))


@router.post("/{user_id}/disable", response_model=AdminUserResponse)
async def disable(user_id: uuid.UUID, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    return _view(await user_admin.disable(db, admin, user_id))


@router.post("/{user_id}/enable", response_model=AdminUserResponse)
async def enable(user_id: uuid.UUID, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    return _view(await user_admin.enable(db, admin, user_id))


@router.patch("/{user_id}/role", response_model=AdminUserResponse)
async def set_role(user_id: uuid.UUID, payload: RoleUpdate, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    return _view(await user_admin.set_role(db, admin, user_id, payload.role))
