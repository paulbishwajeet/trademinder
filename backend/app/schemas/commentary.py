# backend/app/schemas/commentary.py
import uuid
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class CommentaryCreate(BaseModel):
    note: str
    tags: Optional[list[str]] = None


class CommentaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    trade_id: uuid.UUID
    entry_date: date
    note: str
    tags: Optional[list[str]] = None
    created_at: datetime
