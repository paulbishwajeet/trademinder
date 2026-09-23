# backend/app/schemas/chain.py
from typing import Optional
from pydantic import BaseModel


class ChainFactor(BaseModel):
    name: str
    points: float
    max: float
    detail: str


class ChainCandidate(BaseModel):
    strike: float
    delta: float
    last: float
    bid: float
    ask: float
    spread_pct: float
    volume: int
    open_interest: int
    arr_pct: float
    breakeven: float
    downside_cushion_pct: float
    capital_required: float
    score: float
    factors: list[ChainFactor]


class ChainExpiry(BaseModel):
    expiration_date: str
    dte: int
    day_of_week: str
    earnings_in_window: bool
    earnings_date: Optional[str] = None
    candidates: list[ChainCandidate]


class SpTimingSignalSummary(BaseModel):
    ticker: str
    score: float
    grade: str
    iv_percentile: Optional[float] = None
    atm_iv: Optional[float] = None
    spot_price: Optional[float] = None
    factors: list[dict] = []
    commentary: Optional[str] = None
    strike_hint: Optional[str] = None
    caution: Optional[str] = None
    cached_at: str
    fetch_status: str
    fetch_error: Optional[str] = None


class ChainScreenResponse(BaseModel):
    ticker: str
    spot: Optional[float] = None
    strategy: str
    sp_timing_signal: Optional[SpTimingSignalSummary] = None
    iv_percentile: Optional[float] = None
    fetched_at: str
    expiries: list[ChainExpiry]
