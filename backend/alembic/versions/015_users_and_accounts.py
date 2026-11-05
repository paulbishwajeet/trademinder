"""users, brokerage accounts, account categories, screener memberships

Revision ID: 015
Revises: 014
Create Date: 2026-11-04

Multi-account foundation, part 1. Seeds the owner as the first (admin) user from
OWNER_EMAIL / OWNER_DISPLAY_NAME. Ownership columns and backfill live in 016.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def _owner_settings() -> tuple[str, str]:
    from app.config import settings
    email = (settings.owner_email or "").strip()
    if not email:
        raise RuntimeError(
            "Migration 015 needs OWNER_EMAIL to seed the first user. "
            "Set OWNER_EMAIL (and optionally OWNER_DISPLAY_NAME) in .env or the environment, then re-run "
            "`alembic upgrade head`."
        )
    return email, (settings.owner_display_name or "Owner").strip() or "Owner"


def upgrade() -> None:
    owner_email, owner_name = _owner_settings()

    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("role", sa.String(10), nullable=False, server_default="user"),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("external_subject", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('admin', 'user')", name="ck_users_role"),
        sa.CheckConstraint("status IN ('pending', 'active', 'disabled')", name="ck_users_status"),
        sa.UniqueConstraint("external_subject", name="uq_users_external_subject"),
    )
    op.create_index("uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True)

    op.create_table(
        "brokerage_accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("broker", sa.String(30), nullable=False),
        sa.Column("nickname", sa.String(50), nullable=False),
        sa.Column("last_four", sa.String(4), nullable=True),
        sa.Column("external_ref", sa.String(100), nullable=True),
        sa.Column("default_category_id", UUID(as_uuid=True),
                  sa.ForeignKey("categories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_archived", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("last_four IS NULL OR last_four ~ '^[0-9]{4}$'", name="ck_brokerage_accounts_last_four"),
    )
    op.create_index("idx_brokerage_accounts_user", "brokerage_accounts", ["user_id"])
    op.create_index("idx_brokerage_accounts_default_category", "brokerage_accounts", ["default_category_id"])
    op.create_index("uq_brokerage_accounts_one_default", "brokerage_accounts", ["user_id"],
                    unique=True, postgresql_where=sa.text("is_default"))

    op.create_table(
        "account_categories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("account_id", UUID(as_uuid=True),
                  sa.ForeignKey("brokerage_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", UUID(as_uuid=True),
                  sa.ForeignKey("categories.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("account_id", "category_id", name="uq_account_categories_pair"),
    )
    op.create_index("idx_account_categories_account", "account_categories", ["account_id"])
    op.create_index("idx_account_categories_category", "account_categories", ["category_id"])

    op.create_table(
        "screener_account_memberships",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("screener_id", UUID(as_uuid=True),
                  sa.ForeignKey("screener.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", UUID(as_uuid=True),
                  sa.ForeignKey("brokerage_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("screener_id", "account_id", name="uq_screener_account_memberships_pair"),
    )
    op.create_index("idx_screener_memberships_screener", "screener_account_memberships", ["screener_id"])
    op.create_index("idx_screener_memberships_account", "screener_account_memberships", ["account_id"])

    op.get_bind().execute(
        sa.text(
            "INSERT INTO users (email, display_name, role, status) "
            "VALUES (:email, :name, 'admin', 'active')"
        ),
        {"email": owner_email, "name": owner_name},
    )


def downgrade() -> None:
    op.drop_index("idx_screener_memberships_account", table_name="screener_account_memberships")
    op.drop_index("idx_screener_memberships_screener", table_name="screener_account_memberships")
    op.drop_table("screener_account_memberships")
    op.drop_index("idx_account_categories_category", table_name="account_categories")
    op.drop_index("idx_account_categories_account", table_name="account_categories")
    op.drop_table("account_categories")
    op.drop_index("uq_brokerage_accounts_one_default", table_name="brokerage_accounts")
    op.drop_index("idx_brokerage_accounts_default_category", table_name="brokerage_accounts")
    op.drop_index("idx_brokerage_accounts_user", table_name="brokerage_accounts")
    op.drop_table("brokerage_accounts")
    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_table("users")
