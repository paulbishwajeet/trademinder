from fastapi import APIRouter, Depends

from app.deps import get_current_user
from app.models.user import User
from app.schemas.user import CurrentUserResponse

router = APIRouter(prefix="/api", tags=["me"])


@router.get("/me", response_model=CurrentUserResponse)
async def me(user: User = Depends(get_current_user)):
    return user
