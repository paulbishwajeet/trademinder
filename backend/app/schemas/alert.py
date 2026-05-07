# backend/app/schemas/alert.py
import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    trade_id: uuid.UUID
    alert_type: str
    severity: str
    title: str
    message: str
    is_read: bool
    is_dismissed: bool
    triggered_at: datetime
    dismissed_at: Optional[datetime] = None
    snoozed_until: Optional[datetime] = None
