# backend/app/routers/categories.py
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services.ownership import get_category, get_category_by_name
from app.services.accounts import link_category_to_active_accounts
from app.models.category import Category
from app.schemas.category import CategoryCreate, CategoryUpdate, CategoryResponse

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("", response_model=list[CategoryResponse])
async def list_categories(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(Category).where(Category.user_id == user.id).order_by(Category.sort_order))
    return result.scalars().all()


@router.post("", response_model=CategoryResponse, status_code=201)
async def create_category(payload: CategoryCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    if await get_category_by_name(db, user, payload.name) is not None:
        raise HTTPException(status_code=409, detail=f"Category {payload.name} already exists")
    cat = Category(user_id=user.id, **payload.model_dump())
    db.add(cat)
    await db.flush()
    await link_category_to_active_accounts(db, user, cat.id)
    await db.commit()
    await db.refresh(cat)
    return cat


@router.patch("/{category_id}", response_model=CategoryResponse)
async def update_category(category_id: uuid.UUID, payload: CategoryUpdate,
                           db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    cat = await get_category(db, user, category_id)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(cat, field, value)
    await db.commit()
    await db.refresh(cat)
    return cat


@router.delete("/{category_id}", status_code=204)
async def delete_category(category_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    cat = await get_category(db, user, category_id)
    if cat.is_system:
        raise HTTPException(status_code=405, detail="Cannot delete system categories")
    await db.delete(cat)
    await db.commit()
