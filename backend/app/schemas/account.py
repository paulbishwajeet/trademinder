import uuid
from datetime import datetime
from typing import Annotated, Optional
from pydantic import BaseModel, ConfigDict, Field

# Broker is free text; this is the list the UI offers.
KNOWN_BROKERS = ["E*TRADE", "Schwab", "Fidelity", "Robinhood", "Other"]

LastFour = Annotated[str, Field(pattern=r"^[0-9]{4}$")]


class AccountSummary(BaseModel):
    """Compact account label embedded in trade / wheel / spread responses."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nickname: str
    broker: str
    last_four: Optional[str] = None


class AccountResponse(AccountSummary):
    external_ref: Optional[str] = None
    default_category_id: Optional[uuid.UUID] = None
    is_default: bool
    sort_order: int
    is_archived: bool
    created_at: datetime
    category_ids: list[uuid.UUID] = []


class AccountCreate(BaseModel):
    broker: Annotated[str, Field(min_length=1, max_length=30)]
    nickname: Annotated[str, Field(min_length=1, max_length=50)]
    last_four: Optional[LastFour] = None
    sort_order: int = 0
    is_default: bool = False
    # None → the account uses every category in the user's library
    category_ids: Optional[list[uuid.UUID]] = None
    default_category_id: Optional[uuid.UUID] = None


class AccountUpdate(BaseModel):
    broker: Optional[Annotated[str, Field(min_length=1, max_length=30)]] = None
    nickname: Optional[Annotated[str, Field(min_length=1, max_length=50)]] = None
    last_four: Optional[LastFour] = None
    sort_order: Optional[int] = None
    default_category_id: Optional[uuid.UUID] = None
    # Only `true` is meaningful: it moves the default here. Unset by defaulting another account.
    is_default: Optional[bool] = None


class AccountCategoriesUpdate(BaseModel):
    category_ids: list[uuid.UUID]
