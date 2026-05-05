# backend/app/routers/alerts.py
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.alert import Alert
from app.schemas.alert import AlertResponse

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertResponse])
async def list_alerts(db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Alert)
        .where(Alert.is_dismissed == False)  # noqa: E712
        .order_by(Alert.triggered_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/trade/{trade_id}", response_model=list[AlertResponse])
async def get_trade_alerts(trade_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = select(Alert).where(Alert.trade_id == trade_id).order_by(Alert.triggered_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/{alert_id}/read", response_model=AlertResponse)
async def mark_read(alert_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = select(Alert).where(Alert.id == alert_id)
    result = await db.execute(stmt)
    alert = result.scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.is_read = True
    await db.commit()
    await db.refresh(alert)
    return alert


@router.post("/{alert_id}/dismiss", response_model=AlertResponse)
async def dismiss_alert(alert_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = select(Alert).where(Alert.id == alert_id)
    result = await db.execute(stmt)
    alert = result.scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.is_dismissed = True
    alert.dismissed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(alert)
    return alert
