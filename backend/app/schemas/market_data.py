from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

MarketDataState = Literal["ok", "expiring", "critical", "offline"]


class MarketDataStatusResponse(BaseModel):
    provider: str
    state: MarketDataState
    refresh_expires_at: Optional[datetime] = None
    hours_remaining: Optional[float] = None   # negative once expired
    last_success_at: Optional[datetime] = None
    last_error: Optional[str] = None           # short, never contains tokens or response bodies


class ReconnectStartResponse(BaseModel):
    authorize_url: str
    state_expires_at: datetime


class ReconnectCompleteRequest(BaseModel):
    # No max_length here: a 422 would echo the pasted URL back. The service rejects > 4096 chars as bad_url.
    redirect_url: str
