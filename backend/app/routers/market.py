# backend/app/routers/market.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.price_fetcher import fetch_quote, refresh_open_trades, fetch_rsi_batch
from app.services.alert_engine import run as run_alert_engine

router = APIRouter(prefix="/api/market", tags=["market"])


class RsiRequest(BaseModel):
    tickers: list[str]

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


@router.post("/rsi")
async def get_rsi_batch(payload: RsiRequest) -> dict[str, float | None]:
    """Fetch RSI-14 for a list of tickers. Returns { ticker: rsi } map."""
    tickers = [t.upper() for t in payload.tickers if t.strip()]
    if not tickers:
        return {}
    return await fetch_rsi_batch(tickers)


@router.get("/options/{ticker}")
async def get_options(ticker: str):
    return NOT_IMPLEMENTED


@router.post("/prefetch/{ticker}")
async def prefetch_indicators(ticker: str):
    return NOT_IMPLEMENTED
