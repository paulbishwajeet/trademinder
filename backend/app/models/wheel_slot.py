import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text
from app.database import Base

if TYPE_CHECKING:
    from app.models.wheel_session import WheelSession
    from app.models.wheel_slot_leg import WheelSlotLeg
    from app.models.wheel_premium_log import WheelPremiumLog


class WheelSlot(Base):
    __tablename__ = "wheel_slots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("wheel_sessions.id", ondelete="CASCADE"), nullable=False)
    slot_number: Mapped[int] = mapped_column(Integer, nullable=False)
    contracts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    shares_held: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    needs_action: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rotation_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    session: Mapped["WheelSession"] = relationship("WheelSession", back_populates="slots")
    legs: Mapped[list["WheelSlotLeg"]] = relationship("WheelSlotLeg", back_populates="slot", cascade="all, delete-orphan")
    premium_logs: Mapped[list["WheelPremiumLog"]] = relationship("WheelPremiumLog", back_populates="slot", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_wheel_slots_session", "session_id"),
        Index("idx_wheel_slots_status", "status"),
        Index("idx_wheel_slots_needs_action", "needs_action", postgresql_where=text("needs_action = true")),
    )
