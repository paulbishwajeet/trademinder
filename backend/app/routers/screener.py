import asyncio
import uuid
from datetime import datetime, timezone
from functools import partial
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, exists, func

from app.database import get_db, AsyncSessionLocal
from app.deps import get_current_user
from app.models.brokerage_account import ScreenerAccountMembership
from app.models.screener import Screener
from app.models.screener_commentary import ScreenerCommentary
from app.models.user import User
from app.schemas.screener import (
    ScreenerFetchedFields,
    ScreenerRowCreate,
    ScreenerRowResponse,
    ScreenerRowPatch,
    ScreenerPreviewResponse,
    ScreenerJobStatus,
    ScreenerCommentaryCreate,
    ScreenerCommentaryUpdate,
    ScreenerCommentaryResponse,
)
from app.services.ownership import (
    get_screener_row, get_screener_commentary, resolve_account, resolve_account_filter,
)
from app.services.screener_fetcher import fetch_screener_row

router = APIRouter(prefix="/api/screener", tags=["screener"])

_SCREENER_FIELDS = list(ScreenerFetchedFields.model_fields.keys())


async def _reload_row(db: AsyncSession, row_id: uuid.UUID) -> Screener:
    db.expire_all()
    return (await db.execute(select(Screener).where(Screener.id == row_id))).scalar_one()


@router.get("", response_model=list[ScreenerRowResponse])
async def list_screener(
    account_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(Screener).where(Screener.user_id == user.id)
    account_filter = await resolve_account_filter(db, user, account_id)
    if account_filter is not None:
        stmt = stmt.where(exists().where(
            ScreenerAccountMembership.screener_id == Screener.id,
            ScreenerAccountMembership.account_id == account_filter,
        ))
    result = await db.execute(stmt.order_by(Screener.symbol))
    return result.scalars().all()


@router.get("/preview/{ticker}", response_model=ScreenerPreviewResponse)
async def preview_screener(ticker: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    symbol = ticker.upper()
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, fetch_screener_row, symbol)
    existing = await db.execute(select(Screener.id).where(Screener.user_id == user.id, Screener.symbol == symbol))
    already_tracked = existing.scalar_one_or_none() is not None
    return {**data, "symbol": symbol, "already_tracked": already_tracked}


@router.post("", response_model=ScreenerRowResponse, status_code=201)
async def add_screener_symbol(
    payload: ScreenerRowCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Track a symbol in an account (default account when none given). The symbol row is created
    for the user if needed; a symbol already tracked elsewhere just gains the membership."""
    account = await resolve_account(db, user, payload.account_id)
    symbol = payload.symbol.upper()
    existing = await db.execute(select(Screener).where(Screener.user_id == user.id, Screener.symbol == symbol))
    row = existing.scalar_one_or_none()

    if row is not None:
        if account.id in row.account_ids:
            raise HTTPException(status_code=409, detail=f"{symbol} is already tracked")
        db.add(ScreenerAccountMembership(screener_id=row.id, account_id=account.id))
        await db.commit()
        return await _reload_row(db, row.id)

    if payload.precomputed is not None:
        data = payload.precomputed.model_dump()
    else:
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(None, fetch_screener_row, symbol)
        data = ScreenerFetchedFields(**raw).model_dump()

    row = Screener(
        user_id=user.id,
        symbol=symbol,
        category=payload.category,
        last_fetched_at=datetime.now(timezone.utc),
        **{k: data.get(k) for k in _SCREENER_FIELDS},
    )
    db.add(row)
    await db.flush()
    db.add(ScreenerAccountMembership(screener_id=row.id, account_id=account.id))
    await db.commit()
    return await _reload_row(db, row.id)


@router.post("/{symbol}/fetch", response_model=ScreenerRowResponse)
async def fetch_screener_symbol(symbol: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    row = await get_screener_row(db, user, symbol)
    loop = asyncio.get_running_loop()
    raw = await loop.run_in_executor(None, partial(fetch_screener_row, row.symbol, row.sector))
    data = ScreenerFetchedFields(**raw).model_dump()
    for k in _SCREENER_FIELDS:
        setattr(row, k, data.get(k))
    row.last_fetched_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{symbol}", status_code=204)
async def delete_screener_symbol(
    symbol: str,
    account_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """With account_id: remove the symbol from that account only, deleting the row once it belongs to
    no account. Without: delete the symbol everywhere (pre-accounts behaviour)."""
    row = await get_screener_row(db, user, symbol)
    if account_id is None:
        await db.delete(row)
        await db.commit()
        return

    account_filter = await resolve_account_filter(db, user, account_id)
    membership = next((m for m in row.memberships if m.account_id == account_filter), None)
    if membership is None:
        raise HTTPException(status_code=404, detail=f"{symbol.upper()} is not tracked in this account")
    row.memberships.remove(membership)
    await db.flush()
    remaining = await db.scalar(
        select(func.count()).select_from(ScreenerAccountMembership).where(ScreenerAccountMembership.screener_id == row.id)
    )
    if remaining == 0:
        await db.delete(row)
    await db.commit()


@router.patch("/{symbol}", response_model=ScreenerRowResponse)
async def patch_screener_symbol(
    symbol: str, payload: ScreenerRowPatch,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    row = await get_screener_row(db, user, symbol)
    if payload.sector is not None:
        row.sector = payload.sector
    if payload.category is not None:
        row.category = payload.category
    await db.commit()
    await db.refresh(row)
    return row


# job_id -> status. Each job records its owner; other users get 404.
_jobs: dict[str, dict] = {}


def _job_view(job_id: str, job: dict) -> dict:
    return {"job_id": job_id, **{k: v for k, v in job.items() if k != "user_id"}}


async def _run_fetch_all_job(
    job_id: str, user_id: uuid.UUID, symbols: list[str], session_factory=AsyncSessionLocal,
) -> None:
    loop = asyncio.get_running_loop()
    for symbol in symbols:
        async with session_factory() as session:
            stmt = select(Screener).where(Screener.user_id == user_id, Screener.symbol == symbol)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is not None:
                raw = await loop.run_in_executor(None, partial(fetch_screener_row, symbol, row.sector))
                data = ScreenerFetchedFields(**raw).model_dump()
                if data.get("fetch_status") == "error":
                    _jobs[job_id]["errors"].append({"symbol": symbol, "error": data.get("fetch_error")})
                for k in _SCREENER_FIELDS:
                    setattr(row, k, data.get(k))
                row.last_fetched_at = datetime.now(timezone.utc)
                await session.commit()
        _jobs[job_id]["completed"] += 1
    _jobs[job_id]["status"] = "done"


@router.post("/fetch-all", response_model=ScreenerJobStatus, status_code=202)
async def fetch_all_screener(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    # One fetch per symbol per user — memberships don't multiply fetches.
    result = await db.execute(select(Screener.symbol).where(Screener.user_id == user.id))
    symbols = [row[0] for row in result.all()]
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"user_id": user.id, "status": "running", "total": len(symbols), "completed": 0, "errors": []}
    asyncio.create_task(_run_fetch_all_job(job_id, user.id, symbols, session_factory=AsyncSessionLocal))
    return _job_view(job_id, _jobs[job_id])


@router.get("/jobs/{job_id}", response_model=ScreenerJobStatus)
async def get_screener_job(job_id: str, user: User = Depends(get_current_user)):
    job = _jobs.get(job_id)
    if job is None or job.get("user_id") != user.id:
        raise HTTPException(status_code=404, detail="Unknown job")
    return _job_view(job_id, job)


@router.get("/{symbol}/commentary", response_model=list[ScreenerCommentaryResponse])
async def list_screener_commentary(
    symbol: str,
    account_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Without account_id: notes from every account, each labeled with its account."""
    row = await get_screener_row(db, user, symbol)
    stmt = select(ScreenerCommentary).where(
        ScreenerCommentary.user_id == user.id, ScreenerCommentary.screener_id == row.id,
    )
    account_filter = await resolve_account_filter(db, user, account_id)
    if account_filter is not None:
        stmt = stmt.where(ScreenerCommentary.account_id == account_filter)
    result = await db.execute(stmt.order_by(ScreenerCommentary.created_at.desc()))
    return result.scalars().all()


@router.post("/{symbol}/commentary", response_model=ScreenerCommentaryResponse, status_code=201)
async def add_screener_commentary(
    symbol: str, payload: ScreenerCommentaryCreate,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    row = await get_screener_row(db, user, symbol)
    account = await resolve_account(db, user, payload.account_id)
    entry = ScreenerCommentary(
        user_id=user.id, account_id=account.id, screener_id=row.id, note=payload.note, tags=payload.tags,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.put("/commentary/{comment_id}", response_model=ScreenerCommentaryResponse)
async def update_screener_commentary(
    comment_id: uuid.UUID, payload: ScreenerCommentaryUpdate,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    entry = await get_screener_commentary(db, user, comment_id)
    entry.note = payload.note
    entry.tags = payload.tags
    entry.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.delete("/commentary/{comment_id}", status_code=204)
async def delete_screener_commentary(
    comment_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    entry = await get_screener_commentary(db, user, comment_id)
    await db.delete(entry)
    await db.commit()
