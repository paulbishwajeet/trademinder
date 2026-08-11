import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Numeric, Date, Text, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.database import Base

if TYPE_CHECKING:
    from app.models.screener_commentary import ScreenerCommentary


class Screener(Base):
    __tablename__ = "screener"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    sector: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    prev_close: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    change_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    iv_rank: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    iv_percentile: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    rsi_14: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    macd_weekly_signal: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    macd_daily_signal: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    ma_20d: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    ma_50d: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    ma_100d: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    ma_200d: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    bollinger_upper: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    bollinger_mid: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    bollinger_lower: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    bollinger_position: Mapped[Optional[str]] = mapped_column(String(15), nullable=True)
    next_earnings_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    volume_spikes: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    last_fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    fetch_status: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    fetch_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    commentary: Mapped[list["ScreenerCommentary"]] = relationship(
        back_populates="screener",
        cascade="all, delete-orphan",
        order_by="ScreenerCommentary.created_at.desc()",
    )

    __table_args__ = (
        Index("idx_screener_symbol", "symbol", unique=True),
    )
