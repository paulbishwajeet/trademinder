# backend/app/routers/screener.py
import asyncio
import uuid
from datetime import datetime, timezone
from functools import partial

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.screener import Screener
from app.schemas.screener import (
    ScreenerFetchedFields,
    ScreenerRowCreate,
    ScreenerRowResponse,
    ScreenerRowPatch,
    ScreenerPreviewResponse,
)
from app.services.screener_fetcher import fetch_screener_row

router = APIRouter(prefix="/api/screener", tags=["screener"])

_SCREENER_FIELDS = list(ScreenerFetchedFields.model_fields.keys())


async def _get_row_or_404(symbol: str, db: AsyncSession) -> Screener:
    stmt = select(Screener).where(Screener.symbol == symbol.upper())
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{symbol.upper()} is not tracked")
    return row


@router.get("", response_model=list[ScreenerRowResponse])
async def list_screener(db: AsyncSession = Depends(get_db)):
    stmt = select(Screener).order_by(Screener.symbol)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/preview/{ticker}", response_model=ScreenerPreviewResponse)
async def preview_screener(ticker: str, db: AsyncSession = Depends(get_db)):
    symbol = ticker.upper()
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, fetch_screener_row, symbol)
    existing = await db.execute(select(Screener.id).where(Screener.symbol == symbol))
    already_tracked = existing.scalar_one_or_none() is not None
    return {**data, "symbol": symbol, "already_tracked": already_tracked}


@router.post("", response_model=ScreenerRowResponse, status_code=201)
async def add_screener_symbol(payload: ScreenerRowCreate, db: AsyncSession = Depends(get_db)):
    symbol = payload.symbol.upper()
    existing = await db.execute(select(Screener).where(Screener.symbol == symbol))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"{symbol} is already tracked")

    if payload.precomputed is not None:
        data = payload.precomputed.model_dump()
    else:
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(None, fetch_screener_row, symbol)
        data = ScreenerFetchedFields(**raw).model_dump()

    row = Screener(
        symbol=symbol,
        category=payload.category,
        last_fetched_at=datetime.now(timezone.utc),
        **{k: data.get(k) for k in _SCREENER_FIELDS},
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.post("/{symbol}/fetch", response_model=ScreenerRowResponse)
async def fetch_screener_symbol(symbol: str, db: AsyncSession = Depends(get_db)):
    row = await _get_row_or_404(symbol, db)
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
async def delete_screener_symbol(symbol: str, db: AsyncSession = Depends(get_db)):
    row = await _get_row_or_404(symbol, db)
    await db.delete(row)
    await db.commit()


@router.patch("/{symbol}", response_model=ScreenerRowResponse)
async def patch_screener_symbol(symbol: str, payload: ScreenerRowPatch, db: AsyncSession = Depends(get_db)):
    row = await _get_row_or_404(symbol, db)
    if payload.sector is not None:
        row.sector = payload.sector
    if payload.category is not None:
        row.category = payload.category
    await db.commit()
    await db.refresh(row)
    return row
