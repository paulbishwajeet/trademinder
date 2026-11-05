import uuid
from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["admin", "user"]
Status = Literal["pending", "active", "disabled"]


class AdminUserResponse(BaseModel):
    """Account-management fields only — never trading data, counts or account contents."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    role: Role
    status: Status
    created_at: datetime
    last_login_at: Optional[datetime] = None
    has_signed_in: bool = False      # a Google identity is linked
    invited_by: Optional[uuid.UUID] = None
    approved_by: Optional[uuid.UUID] = None
    approved_at: Optional[datetime] = None


Email = Annotated[str, Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)]


class InviteRequest(BaseModel):
    email: Email
    role: Role = "user"


class RoleUpdate(BaseModel):
    role: Role


class ExtensionConnectRequest(BaseModel):
    redirect_uri: str = Field(max_length=200)
    device_name: str = Field(min_length=1, max_length=100)


class ExtensionConnectResponse(BaseModel):
    redirect_to: str


class ExtensionTokenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_name: str
    token_prefix: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
