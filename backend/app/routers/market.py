# backend/app/routers/market.py
import asyncio
from functools import partial
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.alert_engine import run as run_alert_engine
from app.services.options_scanner import run_scan
from app.services.price_fetcher import fetch_quote, fetch_rsi_batch, refresh_open_trades

router = APIRouter(prefix="/api/market", tags=["market"])


class RsiRequest(BaseModel):
    tickers: list[str]


@router.get("/quote/{ticker}")
async def get_quote(ticker: str):
    result = await fetch_quote(ticker.upper())
    if result is None:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker.upper()} not found")
    return result


@router.post("/refresh")
async def refresh_prices(db: AsyncSession = Depends(get_db)):
    price_result = await refresh_open_trades(db)
    alert_result = await run_alert_engine(db)
    return {
        "trades_updated": price_result["trades_updated"],
        "tickers_fetched": price_result["tickers_fetched"],
        "alerts_created": alert_result["alerts_created"],
        "errors": price_result["errors"],
    }


@router.post("/rsi")
async def get_rsi_batch(payload: RsiRequest) -> dict[str, dict | None]:
    tickers = [t.upper() for t in payload.tickers if t.strip()]
    if not tickers:
        return {}
    return await fetch_rsi_batch(tickers)


@router.get("/options/{ticker}")
async def get_options(
    ticker: str,
    opt_type: Literal["calls", "puts", "both"] = Query("both", alias="type"),
    min_dte: int = Query(365, ge=1),
    min_oi: int = Query(25, ge=0),
    max_delta: float = Query(0.70, gt=0, le=1.0),
):
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            partial(run_scan, ticker.upper(), opt_type, min_dte, min_oi, max_delta),
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/prefetch/{ticker}")
async def prefetch_indicators(ticker: str):
    return JSONResponse({"detail": "not implemented"}, status_code=501)
