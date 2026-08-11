import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict


class ScreenerFetchedFields(BaseModel):
    """Every field `fetch_screener_row` computes. Shared by the preview response,
    the `precomputed` commit payload, and (via inheritance) the persisted row response."""
    sector: Optional[str] = None
    price: Optional[Decimal] = None
    prev_close: Optional[Decimal] = None
    change_pct: Optional[Decimal] = None
    iv_rank: Optional[Decimal] = None
    iv_percentile: Optional[Decimal] = None
    rsi_14: Optional[Decimal] = None
    macd_weekly_signal: Optional[str] = None
    macd_daily_signal: Optional[str] = None
    ma_20d: Optional[Decimal] = None
    ma_50d: Optional[Decimal] = None
    ma_100d: Optional[Decimal] = None
    ma_200d: Optional[Decimal] = None
    bollinger_upper: Optional[Decimal] = None
    bollinger_mid: Optional[Decimal] = None
    bollinger_lower: Optional[Decimal] = None
    bollinger_position: Optional[str] = None
    next_earnings_date: Optional[date] = None
    volume_spikes: Optional[list[dict]] = None
    fetch_status: Optional[str] = None
    fetch_error: Optional[str] = None


class ScreenerPreviewResponse(ScreenerFetchedFields):
    symbol: str
    already_tracked: bool


class ScreenerRowCreate(BaseModel):
    symbol: str
    category: Optional[str] = None
    precomputed: Optional[ScreenerFetchedFields] = None


class ScreenerRowPatch(BaseModel):
    sector: Optional[str] = None
    category: Optional[str] = None


class ScreenerRowResponse(ScreenerFetchedFields):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    symbol: str
    category: Optional[str] = None
    last_fetched_at: Optional[datetime] = None
    created_at: datetime


class ScreenerCommentaryCreate(BaseModel):
    note: str
    tags: Optional[list[str]] = None


class ScreenerCommentaryUpdate(BaseModel):
    note: str
    tags: Optional[list[str]] = None


class ScreenerCommentaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    screener_id: uuid.UUID
    note: str
    tags: Optional[list[str]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class ScreenerJobError(BaseModel):
    symbol: str
    error: str


class ScreenerJobStatus(BaseModel):
    job_id: str
    status: str
    total: int
    completed: int
    errors: list[ScreenerJobError] = []
