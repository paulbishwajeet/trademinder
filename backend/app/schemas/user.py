import uuid
from pydantic import BaseModel, ConfigDict


class CurrentUserResponse(BaseModel):
    """Who the SPA is acting as (via the current-user seam). Used to gate admin-only UI."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None = None
    role: str
