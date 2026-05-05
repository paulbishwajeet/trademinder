# backend/app/routers/market.py
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/market", tags=["market"])

NOT_IMPLEMENTED = JSONResponse({"detail": "not implemented"}, status_code=501)


@router.get("/quote/{ticker}")
async def get_quote(ticker: str):
    return NOT_IMPLEMENTED


@router.get("/options/{ticker}")
async def get_options(ticker: str):
    return NOT_IMPLEMENTED


@router.post("/refresh")
async def refresh_prices():
    return NOT_IMPLEMENTED


@router.post("/prefetch/{ticker}")
async def prefetch_indicators(ticker: str):
    return NOT_IMPLEMENTED
