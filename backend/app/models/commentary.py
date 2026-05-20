import uuid
from datetime import date, datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import Date, Text, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.sql import func, text
from app.database import Base

if TYPE_CHECKING:
    from app.models.trade import Trade
    from app.models.rationale import Rationale


class Commentary(Base):
    __tablename__ = "commentary"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trade_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trades.id", ondelete="CASCADE"), nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    note: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    trade: Mapped["Trade"] = relationship(back_populates="commentary")
    rationale: Mapped[Optional["Rationale"]] = relationship(
        back_populates="commentary",
        foreign_keys="[Rationale.commentary_id]",
        cascade="all, delete-orphan",
        uselist=False,
    )

    __table_args__ = (
        Index("idx_commentary_trade", "trade_id"),
        Index("idx_commentary_date", text("entry_date DESC")),
    )
