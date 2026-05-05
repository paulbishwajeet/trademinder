# backend/app/schemas/trade.py
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Optional
from pydantic import BaseModel, ConfigDict, Field


class RationaleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    trade_id: uuid.UUID
    macd_signal: Optional[str] = None
    macd_notes: Optional[str] = None
    rsi_14: Optional[Decimal] = None
    rsi_result: Optional[str] = None
    ma_200d: Optional[Decimal] = None
    ma_50d: Optional[Decimal] = None
    price_vs_ma200: Optional[str] = None
    price_vs_ma50: Optional[str] = None
    bollinger_upper: Optional[Decimal] = None
    bollinger_mid: Optional[Decimal] = None
    bollinger_lower: Optional[Decimal] = None
    bollinger_position: Optional[str] = None
    day_color: Optional[str] = None
    price_action: Optional[str] = None
    sentiment: Optional[str] = None
    next_earnings_date: Optional[date] = None
    fetch_status: str
    fetch_error: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime


class TradeCreate(BaseModel):
    wheel_id: Optional[uuid.UUID] = None
    type: Annotated[str, Field(min_length=1, max_length=10)]
    category: Annotated[str, Field(min_length=1, max_length=20)]
    strategy: Annotated[str, Field(min_length=1, max_length=30)]
    ticker: Annotated[str, Field(min_length=1, max_length=10)]
    open_date: date
    expiry_date: Optional[date] = None
    strike_price: Optional[Annotated[Decimal, Field(ge=0)]] = None
    quantity: Annotated[int, Field(gt=0)]
    premium: Optional[Annotated[Decimal, Field(ge=0)]] = None
    collateral: Optional[Annotated[Decimal, Field(ge=0)]] = None
    exit_strategy: Optional[str] = None
    signal_action: Optional[str] = None
    rationale_notes: Optional[str] = None  # stored in rationale.notes


class TradeUpdate(BaseModel):
    exit_strategy: Optional[str] = None
    signal_action: Optional[str] = None
    status: Optional[str] = None
    current_price: Optional[Decimal] = None
    unrealized_pnl: Optional[Decimal] = None


class TradeListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    wheel_id: Optional[uuid.UUID] = None
    type: str
    category: str
    strategy: str
    ticker: str
    open_date: date
    expiry_date: Optional[date] = None
    closed_date: Optional[date] = None
    strike_price: Optional[Decimal] = None
    quantity: int
    premium: Optional[Decimal] = None
    status: str
    current_price: Optional[Decimal] = None
    unrealized_pnl: Optional[Decimal] = None
    created_at: datetime
    updated_at: datetime


class TradeResponse(TradeListItem):
    collateral: Optional[Decimal] = None
    exit_strategy: Optional[str] = None
    signal_action: Optional[str] = None
    last_price_at: Optional[datetime] = None
    rationale: Optional[RationaleResponse] = None
