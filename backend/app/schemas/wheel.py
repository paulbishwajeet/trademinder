import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict


class WheelSessionCreate(BaseModel):
    ticker: str
    total_shares: int = 0
    opened_at: date


class WheelSessionUpdate(BaseModel):
    total_shares: Optional[int] = None
    status: Optional[str] = None
    closed_at: Optional[date] = None


class WheelSessionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    ticker: str
    total_shares: int
    status: str
    opened_at: date
    closed_at: Optional[date] = None


class WheelSlotCreate(BaseModel):
    contracts: int = 1
    shares_held: int = 0
    status: str


class WheelSlotSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    session_id: uuid.UUID
    slot_number: int
    contracts: int
    shares_held: int
    status: str
    needs_action: bool
    rotation_number: int


class WheelSlotLegCreate(BaseModel):
    trade_id: uuid.UUID
    leg_role: str


class WheelSlotLegItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    slot_id: uuid.UUID
    trade_id: uuid.UUID
    leg_role: str
    rotation_number: int
    trade_type: Optional[str] = None
    trade_strategy: Optional[str] = None
    trade_ticker: Optional[str] = None
    trade_open_date: Optional[date] = None
    trade_expiry_date: Optional[date] = None
    trade_strike_price: Optional[Decimal] = None
    trade_quantity: Optional[int] = None
    trade_premium: Optional[Decimal] = None
    trade_current_price: Optional[Decimal] = None
    trade_status: Optional[str] = None
    trade_etrade_symbol: Optional[str] = None


class WheelResolveRequest(BaseModel):
    outcome: str
    new_trade_id: Optional[uuid.UUID] = None
    buyback_cost: Optional[Decimal] = None
    notes: Optional[str] = None


class WheelPremiumLogItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    slot_id: uuid.UUID
    leg_id: Optional[uuid.UUID] = None
    rotation_number: int
    premium_amount: Decimal
    event_type: str
    event_date: date
    notes: Optional[str] = None
    created_at: datetime


class WheelActiveSlotItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    session_id: uuid.UUID
    slot_number: int
    contracts: int
    shares_held: int
    status: str
    needs_action: bool
    rotation_number: int
    ticker: str
    etrade_symbols: list[str] = []


class WheelSlotDetail(WheelSlotSummary):
    legs: list[WheelSlotLegItem] = []
    premium_logs: list[WheelPremiumLogItem] = []
    total_premium: Decimal = Decimal("0")


class WheelSessionDetail(WheelSessionSummary):
    slots: list[WheelSlotDetail] = []
    total_premium: Decimal = Decimal("0")
    stock_cost_basis: Optional[Decimal] = None
    stock_current_price: Optional[Decimal] = None
