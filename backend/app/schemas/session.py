# backend/app/schemas/session.py
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict


class SessionCreate(BaseModel):
    ticker: str
    strategy: str = "WHEEL"
    status: str
    opened_at: date
    rotation_number: int = 1
    parent_session_id: Optional[uuid.UUID] = None


class SessionUpdate(BaseModel):
    status: Optional[str] = None
    closed_at: Optional[date] = None


class SessionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticker: str
    strategy: str
    status: str
    rotation_number: int
    opened_at: date
    closed_at: Optional[date] = None
    parent_session_id: Optional[uuid.UUID] = None


class SessionLegItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    strategy: str
    ticker: str
    open_date: date
    expiry_date: Optional[date] = None
    strike_price: Optional[Decimal] = None
    quantity: int
    premium: Optional[Decimal] = None
    status: str


class SessionWithLegs(SessionSummary):
    legs: list[SessionLegItem] = []
    rotation_chain: list[SessionSummary] = []


class SessionLookupResponse(BaseModel):
    ticker: str
    strategy: str
    has_existing: bool
    sessions: list[SessionSummary]
