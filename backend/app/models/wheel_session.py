import uuid
from datetime import date, datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Integer, Date, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.database import Base

if TYPE_CHECKING:
    from app.models.wheel_slot import WheelSlot


class WheelSession(Base):
    __tablename__ = "wheel_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    total_shares: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    opened_at: Mapped[date] = mapped_column(Date, nullable=False)
    closed_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    slots: Mapped[list["WheelSlot"]] = relationship("WheelSlot", back_populates="session", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_wheel_sessions_ticker", "ticker"),
        Index("idx_wheel_sessions_status", "status"),
    )
