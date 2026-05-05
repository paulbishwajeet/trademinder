import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Integer, Numeric, Date, Text, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text
from app.database import Base

if TYPE_CHECKING:
    from app.models.rationale import Rationale
    from app.models.commentary import Commentary
    from app.models.alert import Alert


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wheel_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    type: Mapped[str] = mapped_column(String(10), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    strategy: Mapped[str] = mapped_column(String(30), nullable=False)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    open_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    closed_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    strike_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    premium: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    collateral: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    exit_strategy: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    signal_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open")
    current_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    last_price_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    unrealized_pnl: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    rationale: Mapped[Optional["Rationale"]] = relationship(back_populates="trade", cascade="all, delete-orphan", uselist=False)
    commentary: Mapped[list["Commentary"]] = relationship(back_populates="trade", cascade="all, delete-orphan", order_by="Commentary.created_at.desc()")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="trade", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_trades_ticker", "ticker"),
        Index("idx_trades_wheel_id", "wheel_id"),
        Index("idx_trades_status", "status"),
        Index("idx_trades_expiry", "expiry_date", postgresql_where=text("expiry_date IS NOT NULL")),
    )
