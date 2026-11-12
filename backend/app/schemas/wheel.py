import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.schemas.commentary import CommentaryResponse
from app.schemas.account import AccountSummary


class WheelSessionCreate(BaseModel):
    account_id: Optional[uuid.UUID] = None  # None → the user's default account
    ticker: str
    total_shares: int = 0
    opened_at: date


_TICKER = re.compile(r"[A-Z0-9.\-/]{1,10}")


class WheelSessionUpdate(BaseModel):
    ticker: Optional[str] = None  # changeable only while the wheel has no slots (enforced in the router)
    total_shares: Optional[int] = Field(None, ge=0)
    opened_at: Optional[date] = None
    status: Optional[str] = None
    closed_at: Optional[date] = None

    @field_validator("ticker")
    @classmethod
    def _normalise_ticker(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip().upper()
        if not _TICKER.fullmatch(value):
            raise ValueError("Ticker must be 1–10 letters, digits, '.', '-' or '/'")
        return value


class WheelSessionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    account_id: uuid.UUID
    account: AccountSummary
    ticker: str
    total_shares: int
    status: str
    opened_at: date
    closed_at: Optional[date] = None


class WheelSlotCreate(BaseModel):
    contracts: int = 1
    shares_held: int = 0
    status: str


class WheelSlotUpdate(BaseModel):
    contracts: int


class WheelSlotSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    session_id: uuid.UUID
    account_id: uuid.UUID
    account: AccountSummary
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
    account_id: uuid.UUID
    account: AccountSummary
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
    # True while market data is offline: stock_current_price and legs' trade_current_price are null.
    market_data_offline: bool = False


class WheelSlotHistoryEntry(CommentaryResponse):
    origin: str  # "slot" | "leg"
    leg_role: Optional[str] = None
    rotation_number: Optional[int] = None


class WheelSlotHistoryResponse(BaseModel):
    items: list[WheelSlotHistoryEntry]
    total: int
    has_more: bool
