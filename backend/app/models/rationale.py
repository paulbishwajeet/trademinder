import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Numeric, Date, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.database import Base

if TYPE_CHECKING:
    from app.models.trade import Trade


class Rationale(Base):
    __tablename__ = "rationale"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trade_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trades.id", ondelete="CASCADE"), nullable=False)

    macd_signal: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    macd_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rsi_14: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    rsi_result: Mapped[Optional[str]] = mapped_column(String(15), nullable=True)
    ma_200d: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    ma_50d: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    price_vs_ma200: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    price_vs_ma50: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    bollinger_upper: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    bollinger_mid: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    bollinger_lower: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    bollinger_position: Mapped[Optional[str]] = mapped_column(String(15), nullable=True)
    day_color: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    price_action: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    sentiment: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    next_earnings_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    fetch_status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    fetch_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    trade: Mapped["Trade"] = relationship(back_populates="rationale")

    __table_args__ = (
        UniqueConstraint("trade_id", name="idx_rationale_trade"),
    )
