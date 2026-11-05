import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel

from app.schemas.account import AccountSummary


class DashboardAccountCard(BaseModel):
    account: AccountSummary
    is_default: bool
    open_trades: int
    active_wheels: int
    slots_needing_action: int
    legs_expiring_7d: int
    # Σ signed wheel premium logs dated in the current US/Eastern calendar month
    net_premium_month: Decimal


class DashboardNeedsActionSlot(BaseModel):
    slot_id: uuid.UUID
    session_id: uuid.UUID
    slot_number: int
    ticker: str
    status: str
    account: AccountSummary
    open_leg_expiry: Optional[date] = None


class DashboardAlert(BaseModel):
    id: uuid.UUID
    trade_id: uuid.UUID
    ticker: str
    alert_type: str
    severity: str
    title: str
    message: str
    is_read: bool
    triggered_at: datetime
    account: AccountSummary


class DashboardSummary(BaseModel):
    as_of: date  # US/Eastern date the "today" / "this month" windows refer to
    accounts: list[DashboardAccountCard]
    needs_action: list[DashboardNeedsActionSlot]
    alerts: list[DashboardAlert]
    # Nothing in the summary is live market data; the flag lets the page show the offline state.
    market_data_offline: bool = False
