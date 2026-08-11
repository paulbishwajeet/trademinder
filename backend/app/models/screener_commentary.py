import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import Text, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.sql import func
from app.database import Base

if TYPE_CHECKING:
    from app.models.screener import Screener


class ScreenerCommentary(Base):
    __tablename__ = "screener_commentary"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    screener_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("screener.id", ondelete="CASCADE"), nullable=False
    )
    note: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    screener: Mapped["Screener"] = relationship(back_populates="commentary")

    __table_args__ = (
        Index("idx_screener_commentary_screener", "screener_id"),
    )
