import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Boolean, Integer, DateTime, ForeignKey, Index, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text
from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.category import Category


class BrokerageAccount(Base):
    """A brokerage account owned by one user. Only the last four digits of the
    account number are ever stored."""
    __tablename__ = "brokerage_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    broker: Mapped[str] = mapped_column(String(30), nullable=False)
    nickname: Mapped[str] = mapped_column(String(50), nullable=False)
    last_four: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    # Links a broker-side account (e.g. an E*TRADE dropdown entry) in Part 3.
    external_ref: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    default_category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user: Mapped["User"] = relationship(back_populates="accounts")
    category_links: Mapped[list["AccountCategory"]] = relationship(
        back_populates="account", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def category_ids(self) -> list[uuid.UUID]:
        return [link.category_id for link in self.category_links]

    __table_args__ = (
        CheckConstraint("last_four IS NULL OR last_four ~ '^[0-9]{4}$'", name="ck_brokerage_accounts_last_four"),
        Index("idx_brokerage_accounts_user", "user_id"),
        Index("idx_brokerage_accounts_default_category", "default_category_id"),
        Index("uq_brokerage_accounts_one_default", "user_id", unique=True, postgresql_where=text("is_default")),
    )


class AccountCategory(Base):
    """Which of the user's categories an account uses."""
    __tablename__ = "account_categories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brokerage_accounts.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )

    account: Mapped["BrokerageAccount"] = relationship(back_populates="category_links")

    __table_args__ = (
        UniqueConstraint("account_id", "category_id", name="uq_account_categories_pair"),
        Index("idx_account_categories_account", "account_id"),
        Index("idx_account_categories_category", "category_id"),
    )


class ScreenerAccountMembership(Base):
    """Which accounts a (per-user) screener symbol belongs to."""
    __tablename__ = "screener_account_memberships"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    screener_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("screener.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brokerage_accounts.id", ondelete="CASCADE"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("screener_id", "account_id", name="uq_screener_account_memberships_pair"),
        Index("idx_screener_memberships_screener", "screener_id"),
        Index("idx_screener_memberships_account", "account_id"),
    )
