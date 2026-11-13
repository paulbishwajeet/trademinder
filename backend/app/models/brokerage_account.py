import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Boolean, Integer, DateTime, Numeric, ForeignKey, Index, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text
from app.database import Base
from app.services import account_facts

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
    # E*TRADE link fingerprint: hex SHA-256 of broker + full account number, computed by the
    # extension. The full account number is never stored.
    external_ref: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    external_label: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    external_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    default_category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Account facts (migration 019): gates later guidance reads. Every fact is optional; null = not set.
    # Vocabulary and combination rules: app.services.account_facts.
    tax_treatment: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    account_purpose: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    margin_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    options_tier: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    options_level_label: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    net_liquidation_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    cash_balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    # Set by the service: values_as_of when a money value changes, facts_updated_at when a fact does.
    values_as_of: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    facts_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="accounts")
    category_links: Mapped[list["AccountCategory"]] = relationship(
        back_populates="account", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def category_ids(self) -> list[uuid.UUID]:
        return [link.category_id for link in self.category_links]

    @property
    def link(self) -> Optional[dict]:
        """The E*TRADE link as the UI sees it (never the fingerprint itself)."""
        if self.external_ref is None:
            return None
        return {"label": self.external_label, "last_seen_at": self.external_seen_at}

    @property
    def account_tax_status(self) -> Optional[str]:
        """The KB's key: taxable | tax_advantaged | None when tax_treatment is unset."""
        return account_facts.tax_status(self.tax_treatment)

    @property
    def facts_complete(self) -> bool:
        return account_facts.facts_complete({f: getattr(self, f) for f in account_facts.REQUIRED_FACTS})

    __table_args__ = (
        CheckConstraint("last_four IS NULL OR last_four ~ '^[0-9]{4}$'", name="ck_brokerage_accounts_last_four"),
        CheckConstraint(
            "external_ref IS NULL OR external_ref ~ '^[0-9a-f]{64}$'", name="ck_brokerage_accounts_external_ref",
        ),
        *(
            CheckConstraint(
                f"{column} IS NULL OR {column} IN ({', '.join(repr(v) for v in values)})",
                name=f"ck_brokerage_accounts_{column}",
            )
            for column, values in (
                ("tax_treatment", account_facts.TAX_TREATMENTS),
                ("account_purpose", account_facts.ACCOUNT_PURPOSES),
                ("margin_type", account_facts.MARGIN_TYPES),
                ("options_tier", account_facts.OPTIONS_TIERS),
            )
        ),
        *(
            CheckConstraint(f"{column} IS NULL OR {column} >= 0", name=f"ck_brokerage_accounts_{column}_non_negative")
            for column in account_facts.MONEY_FIELDS
        ),
        Index("idx_brokerage_accounts_user", "user_id"),
        Index("idx_brokerage_accounts_default_category", "default_category_id"),
        Index("uq_brokerage_accounts_one_default", "user_id", unique=True, postgresql_where=text("is_default")),
        Index(
            "uq_brokerage_accounts_user_external_ref", "user_id", "external_ref",
            unique=True, postgresql_where=text("external_ref IS NOT NULL"),
        ),
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
