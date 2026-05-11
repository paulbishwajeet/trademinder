"""add etrade_symbol to trades

Revision ID: 003
Revises: 002
Create Date: 2026-05-07
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trades", sa.Column("etrade_symbol", sa.String(30), nullable=True))
    # Partial unique index: only one open trade per etrade_symbol at a time.
    # Closed/expired trades are excluded so historical records don't block re-entry.
    op.create_index(
        "idx_trades_etrade_symbol_open",
        "trades",
        ["etrade_symbol"],
        unique=True,
        postgresql_where=sa.text("etrade_symbol IS NOT NULL AND status = 'open'"),
    )


def downgrade() -> None:
    op.drop_index("idx_trades_etrade_symbol_open", table_name="trades")
    op.drop_column("trades", "etrade_symbol")
