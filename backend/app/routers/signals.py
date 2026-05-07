# backend/app/routers/signals.py
import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.signal import TechnicalSignal

router = APIRouter(prefix="/api", tags=["signals"])


@router.get("/trades/{trade_id}/signals")
async def get_trade_signals(trade_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = select(TechnicalSignal).where(TechnicalSignal.trade_id == trade_id).order_by(TechnicalSignal.triggered_at.desc())
    result = await db.execute(stmt)
    signals = result.scalars().all()
    return [
        {
            "id": str(s.id),
            "signal_type": s.signal_type,
            "signal_value": float(s.signal_value) if s.signal_value else None,
            "triggered_at": s.triggered_at.isoformat(),
            "is_active": s.is_active,
            "notes": s.notes,
        }
        for s in signals
    ]


@router.post("/market/signals/refresh")
async def refresh_signals(db: AsyncSession = Depends(get_db)):
    from app.services.signal_engine import run as run_signal_engine
    result = await run_signal_engine(db)
    return result
