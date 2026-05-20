import uuid
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict
from app.schemas.trade import RationaleCreate, RationaleResponse


class CommentaryCreate(BaseModel):
    note: str
    tags: Optional[list[str]] = None
    rationale: Optional[RationaleCreate] = None


class CommentaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    trade_id: uuid.UUID
    entry_date: date
    note: str
    tags: Optional[list[str]] = None
    created_at: datetime
    rationale: Optional[RationaleResponse] = None
