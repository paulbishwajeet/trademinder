import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Integer, Numeric, Date, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.database import Base

if TYPE_CHECKING:
    from app.models.wheel_slot import WheelSlot


class WheelPremiumLog(Base):
    __tablename__ = "wheel_premium_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("wheel_slots.id", ondelete="CASCADE"), nullable=False)
    leg_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("wheel_slot_legs.id", ondelete="SET NULL"), nullable=True)
    rotation_number: Mapped[int] = mapped_column(Integer, nullable=False)
    premium_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    slot: Mapped["WheelSlot"] = relationship("WheelSlot", back_populates="premium_logs")

    __table_args__ = (
        Index("idx_wheel_premium_logs_slot", "slot_id"),
        Index("idx_wheel_premium_logs_event_date", "event_date"),
    )
