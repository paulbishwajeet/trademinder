# backend/app/schemas/trade.py
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict


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
    type: str
    category: str
    strategy: str
    ticker: str
    open_date: date
    expiry_date: Optional[date] = None
    strike_price: Optional[Decimal] = None
    quantity: int
    premium: Optional[Decimal] = None
    collateral: Optional[Decimal] = None
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
