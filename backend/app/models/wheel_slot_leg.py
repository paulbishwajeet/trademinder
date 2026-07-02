import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Integer, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.database import Base

if TYPE_CHECKING:
    from app.models.wheel_slot import WheelSlot
    from app.models.trade import Trade


class WheelSlotLeg(Base):
    __tablename__ = "wheel_slot_legs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("wheel_slots.id", ondelete="CASCADE"), nullable=False)
    trade_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trades.id", ondelete="CASCADE"), nullable=False)
    leg_role: Mapped[str] = mapped_column(String(20), nullable=False)
    rotation_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    slot: Mapped["WheelSlot"] = relationship("WheelSlot", back_populates="legs")
    trade: Mapped["Trade"] = relationship("Trade", back_populates="wheel_slot_legs")

    __table_args__ = (
        Index("idx_wheel_slot_legs_slot", "slot_id"),
        Index("idx_wheel_slot_legs_trade", "trade_id"),
    )
