from fastapi import APIRouter, Depends

from app.deps import get_signed_in_user
from app.models.user import User
from app.schemas.user import CurrentUserResponse

router = APIRouter(prefix="/api", tags=["me"])


@router.get("/me", response_model=CurrentUserResponse)
async def me(user: User = Depends(get_signed_in_user)):
    """The one route a pending user may call (the SPA shows the waiting page from it)."""
    return user
