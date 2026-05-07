# backend/app/schemas/positions.py
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel


class PositionInput(BaseModel):
    ticker: str
    full_symbol: Optional[str] = None  # e.g. "NVDA--271217C00185000"
    type: Optional[str] = None         # "Put", "Call", "Stock", "Option"
    strike: Optional[float] = None
    expiry: Optional[date] = None
    is_itm: bool = False


class PositionsStatusRequest(BaseModel):
    positions: list[PositionInput]


class ActiveSignal(BaseModel):
    type: str
    notes: Optional[str] = None
    signal_value: Optional[Decimal] = None


class PositionStatus(BaseModel):
    ticker: str
    full_symbol: Optional[str] = None
    trade_id: Optional[uuid.UUID] = None
    # Category
    category_id: Optional[uuid.UUID] = None
    category_name: Optional[str] = None
    category_color: Optional[str] = None
    category_icon: Optional[str] = None
    # Alert
    alert_severity: Optional[str] = None  # "urgent", "warning", "info", "ok"
    alert_type: Optional[str] = None
    alert_title: Optional[str] = None
    alert_id: Optional[uuid.UUID] = None
    # Commentary
    last_note: Optional[str] = None
    last_note_date: Optional[date] = None
    commentary_count: int = 0
    # Signals
    active_signals: list[ActiveSignal] = []
    # Rationale snapshot
    rsi_14: Optional[Decimal] = None
    macd_signal: Optional[str] = None
    bollinger_position: Optional[str] = None
    # Trade details
    strategy: Optional[str] = None
    strike_price: Optional[Decimal] = None
    dte: Optional[int] = None
    exit_strategy: Optional[str] = None


class DashboardTodayItem(BaseModel):
    trade_id: uuid.UUID
    ticker: str
    strategy: Optional[str] = None
    alert_severity: str
    alert_type: str
    alert_title: str
    alert_id: uuid.UUID
    dte: Optional[int] = None
    category_name: Optional[str] = None
    category_icon: Optional[str] = None
