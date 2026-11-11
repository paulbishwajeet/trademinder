# backend/app/routers/alerts.py
import uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services.ownership import get_alert
from app.models.alert import Alert
from app.schemas.alert import AlertResponse

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


class SnoozeRequest(BaseModel):
    hours: int = 24


@router.get("", response_model=list[AlertResponse])
async def list_alerts(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    stmt = (
        select(Alert)
        .where(
            Alert.user_id == user.id,
            Alert.is_dismissed == False,  # noqa: E712
            (Alert.snoozed_until == None) | (Alert.snoozed_until <= now),  # noqa: E711
        )
        .order_by(Alert.triggered_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/trade/{trade_id}", response_model=list[AlertResponse])
async def get_trade_alerts(trade_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    # Unknown and foreign trades both yield [] (pre-existing contract) — the user filter keeps it leak-free.
    stmt = select(Alert).where(Alert.trade_id == trade_id, Alert.user_id == user.id).order_by(Alert.triggered_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/{alert_id}/read", response_model=AlertResponse)
async def mark_read(alert_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    alert = await get_alert(db, user, alert_id)
    alert.is_read = True
    await db.commit()
    await db.refresh(alert)
    return alert


@router.post("/{alert_id}/dismiss", response_model=AlertResponse)
async def dismiss_alert(alert_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    alert = await get_alert(db, user, alert_id)
    alert.is_dismissed = True
    alert.dismissed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(alert)
    return alert


@router.post("/{alert_id}/snooze", response_model=AlertResponse)
async def snooze_alert(alert_id: uuid.UUID, payload: SnoozeRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    alert = await get_alert(db, user, alert_id)
    alert.snoozed_until = datetime.now(timezone.utc) + timedelta(hours=payload.hours)
    await db.commit()
    await db.refresh(alert)
    return alert
