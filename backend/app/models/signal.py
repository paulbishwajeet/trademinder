# backend/app/models/signal.py
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Boolean, Numeric, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text
from app.database import Base

if TYPE_CHECKING:
    from app.models.trade import Trade


class TechnicalSignal(Base):
    __tablename__ = "technical_signals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trade_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trades.id", ondelete="CASCADE"), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(30), nullable=False)
    signal_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    trade: Mapped["Trade"] = relationship(back_populates="signals")

    __table_args__ = (
        Index("idx_signals_trade", "trade_id"),
        Index("idx_signals_active", "is_active", postgresql_where=text("is_active")),
    )
