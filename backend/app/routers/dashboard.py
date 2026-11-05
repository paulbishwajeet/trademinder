from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, market_data_flag
from app.models.user import User
from app.schemas.dashboard import DashboardSummary
from app.services.dashboard import build_summary

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def dashboard_summary(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
    offline: bool = Depends(market_data_flag),
):
    summary = await build_summary(db, user)
    return summary.model_copy(update={"market_data_offline": offline})
