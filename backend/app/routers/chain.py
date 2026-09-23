# backend/app/routers/chain.py
import asyncio
import logging
from fastapi import APIRouter, HTTPException, Query
from app.services.chain_screener import compute_chain_screen
from app.schemas.chain import ChainScreenResponse

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chain", tags=["chain"])

SUPPORTED_STRATEGIES = {"sell_put"}


@router.get("/{ticker}", response_model=ChainScreenResponse)
async def get_chain_screen(
    ticker: str,
    strategy: str = Query("sell_put"),
    num_expiries: int = Query(3, ge=1, le=8),
    candidates_per_expiry: int = Query(3, ge=1, le=10),
    target_delta: float = Query(0.2, gt=0, lt=1),
    delta_tolerance: float = Query(0.1, gt=0, lt=1),
    min_arr_pct: float = Query(30.0, ge=0),
    min_volume: int = Query(200, ge=0),
    min_oi: int = Query(500, ge=0),
):
    if strategy not in SUPPORTED_STRATEGIES:
        raise HTTPException(status_code=400, detail=f"Strategy '{strategy}' not yet implemented")
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: compute_chain_screen(
                ticker, strategy, num_expiries, candidates_per_expiry,
                target_delta, delta_tolerance, min_arr_pct, min_volume, min_oi,
            ),
        )
    except Exception as exc:
        log.exception("Chain screen failed for %s", ticker)
        raise HTTPException(status_code=502, detail=f"Failed to screen chain: {exc}") from exc
    return result
