import uuid
from datetime import date, datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Integer, Date, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func, text
from app.database import Base

if TYPE_CHECKING:
    from app.models.trade import Trade


class TradeSession(Base):
    __tablename__ = "trade_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    strategy: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    rotation_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("trade_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    opened_at: Mapped[date] = mapped_column(Date, nullable=False)
    closed_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    legs: Mapped[list["Trade"]] = relationship(
        "Trade",
        back_populates="session",
        foreign_keys="Trade.session_id",
    )

    __table_args__ = (
        Index("idx_trade_sessions_ticker_strategy", "ticker", "strategy"),
        Index("idx_trade_sessions_status", "status"),
        Index(
            "idx_trade_sessions_parent",
            "parent_session_id",
            postgresql_where=text("parent_session_id IS NOT NULL"),
        ),
    )
