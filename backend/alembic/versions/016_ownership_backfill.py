"""ownership columns, default account and backfill

Revision ID: 016
Revises: 015
Create Date: 2026-11-04

Adds user_id to every user-owned table and account_id to the account-scoped parents
(trades, wheel_sessions, trade_sessions) plus screener_commentary, backfilling everything
to the owner seeded in 015 and a new default "E*TRADE" account. Rescopes the global
uniqueness rules (category name, screener symbol, briefing date) to per-user.
schwab_tokens is app-level and untouched.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None

USER_OWNED_TABLES = [
    "trades", "rationale", "commentary", "categories", "alerts", "technical_signals",
    "wheel_sessions", "wheel_slots", "wheel_slot_legs", "wheel_premium_logs",
    "trade_sessions", "screener", "screener_commentary", "daily_briefings",
]

ACCOUNT_SCOPED_TABLES = ["trades", "wheel_sessions", "trade_sessions", "screener_commentary"]


def _owner_id(bind) -> str:
    owner = bind.execute(sa.text(
        "SELECT id FROM users WHERE role = 'admin' ORDER BY created_at, id LIMIT 1"
    )).scalar()
    if owner is None:
        raise RuntimeError("Migration 016 found no admin user; migration 015 should have seeded one.")
    return owner


def upgrade() -> None:
    bind = op.get_bind()
    owner_id = _owner_id(bind)

    account_id = bind.execute(
        sa.text(
            "INSERT INTO brokerage_accounts (user_id, broker, nickname, is_default, sort_order) "
            "VALUES (:uid, 'E*TRADE', 'E*TRADE', true, 0) RETURNING id"
        ),
        {"uid": owner_id},
    ).scalar()

    for table in USER_OWNED_TABLES:
        op.add_column(table, sa.Column("user_id", UUID(as_uuid=True), nullable=True))
        bind.execute(sa.text(f"UPDATE {table} SET user_id = :uid"), {"uid": owner_id})
        op.alter_column(table, "user_id", nullable=False)
        op.create_foreign_key(f"fk_{table}_user", table, "users", ["user_id"], ["id"], ondelete="CASCADE")
        op.create_index(f"idx_{table}_user", table, ["user_id"])

    for table in ACCOUNT_SCOPED_TABLES:
        op.add_column(table, sa.Column("account_id", UUID(as_uuid=True), nullable=True))
        bind.execute(sa.text(f"UPDATE {table} SET account_id = :aid"), {"aid": account_id})
        op.alter_column(table, "account_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_account", table, "brokerage_accounts", ["account_id"], ["id"], ondelete="RESTRICT",
        )
        op.create_index(f"idx_{table}_account", table, ["account_id"])

    bind.execute(
        sa.text("INSERT INTO screener_account_memberships (screener_id, account_id) SELECT id, :aid FROM screener"),
        {"aid": account_id},
    )
    bind.execute(
        sa.text("INSERT INTO account_categories (account_id, category_id) SELECT :aid, id FROM categories"),
        {"aid": account_id},
    )

    # Global uniqueness → per-user uniqueness
    op.drop_constraint("categories_name_key", "categories", type_="unique")
    op.create_unique_constraint("uq_categories_user_name", "categories", ["user_id", "name"])

    op.drop_index("idx_screener_symbol", table_name="screener")
    op.create_index("idx_screener_user_symbol", "screener", ["user_id", "symbol"], unique=True)

    # One open trade per E*TRADE symbol (003) becomes one per symbol per account: the same
    # contract can be open in two accounts, and other users' positions must never collide.
    op.drop_index("idx_trades_etrade_symbol_open", table_name="trades")
    op.create_index(
        "idx_trades_account_etrade_symbol_open", "trades", ["account_id", "etrade_symbol"], unique=True,
        postgresql_where=sa.text("etrade_symbol IS NOT NULL AND status = 'open'"),
    )

    # uq_daily_briefings_date was created as a unique index (001), not a constraint
    op.drop_index("uq_daily_briefings_date", table_name="daily_briefings")
    op.create_index("uq_daily_briefings_user_date", "daily_briefings", ["user_id", "briefing_date"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    owner_id = _owner_id(bind)

    for table in USER_OWNED_TABLES:
        foreign = bind.execute(
            sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE user_id <> :uid)"), {"uid": owner_id}
        ).scalar()
        if foreign:
            raise RuntimeError(
                f"Cannot downgrade 016: {table} holds rows owned by users other than the owner. "
                "Restoring global uniqueness would collide or merge their data. Remove those users' data first."
            )

    op.drop_index("uq_daily_briefings_user_date", table_name="daily_briefings")
    op.create_index("uq_daily_briefings_date", "daily_briefings", ["briefing_date"], unique=True)

    op.drop_index("idx_screener_user_symbol", table_name="screener")
    op.create_index("idx_screener_symbol", "screener", ["symbol"], unique=True)

    op.drop_index("idx_trades_account_etrade_symbol_open", table_name="trades")
    op.create_index(
        "idx_trades_etrade_symbol_open", "trades", ["etrade_symbol"], unique=True,
        postgresql_where=sa.text("etrade_symbol IS NOT NULL AND status = 'open'"),
    )

    op.drop_constraint("uq_categories_user_name", "categories", type_="unique")
    op.create_unique_constraint("categories_name_key", "categories", ["name"])

    for table in ACCOUNT_SCOPED_TABLES:
        op.drop_index(f"idx_{table}_account", table_name=table)
        op.drop_constraint(f"fk_{table}_account", table, type_="foreignkey")
        op.drop_column(table, "account_id")

    for table in USER_OWNED_TABLES:
        op.drop_index(f"idx_{table}_user", table_name=table)
        op.drop_constraint(f"fk_{table}_user", table, type_="foreignkey")
        op.drop_column(table, "user_id")

    # Back to the exact post-015 state: users exist, no accounts (join rows cascade).
    bind.execute(sa.text("DELETE FROM brokerage_accounts"))
