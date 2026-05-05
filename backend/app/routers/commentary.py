# backend/app/routers/commentary.py
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.commentary import Commentary
from app.schemas.commentary import CommentaryCreate, CommentaryResponse

router = APIRouter(tags=["commentary"])


@router.get("/api/trades/{trade_id}/commentary", response_model=list[CommentaryResponse])
async def list_commentary(trade_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Commentary)
        .where(Commentary.trade_id == trade_id)
        .order_by(Commentary.created_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/api/trades/{trade_id}/commentary", response_model=CommentaryResponse, status_code=201)
async def add_commentary(trade_id: uuid.UUID, payload: CommentaryCreate, db: AsyncSession = Depends(get_db)):
    comment = Commentary(
        trade_id=trade_id,
        note=payload.note,
        tags=payload.tags,
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    return comment


@router.delete("/api/commentary/{comment_id}", status_code=204)
async def delete_commentary(comment_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = select(Commentary).where(Commentary.id == comment_id)
    result = await db.execute(stmt)
    comment = result.scalar_one_or_none()
    if comment is None:
        raise HTTPException(status_code=404, detail="Commentary entry not found")
    await db.delete(comment)
    await db.commit()
