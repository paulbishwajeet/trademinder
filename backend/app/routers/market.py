# backend/app/routers/market.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.price_fetcher import fetch_quote, refresh_open_trades
from app.services.alert_engine import run as run_alert_engine

router = APIRouter(prefix="/api/market", tags=["market"])

NOT_IMPLEMENTED = JSONResponse({"detail": "not implemented"}, status_code=501)


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


@router.get("/options/{ticker}")
async def get_options(ticker: str):
    return NOT_IMPLEMENTED


@router.post("/prefetch/{ticker}")
async def prefetch_indicators(ticker: str):
    return NOT_IMPLEMENTED
