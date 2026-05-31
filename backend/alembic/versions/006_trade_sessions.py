"""create trade_sessions table and add session_id to trades

Revision ID: 006
Revises: 005
Create Date: 2026-05-31
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trade_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("strategy", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("rotation_number", sa.Integer, nullable=False, server_default="1"),
        sa.Column("parent_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("opened_at", sa.Date, nullable=False),
        sa.Column("closed_at", sa.Date, nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_session_id"], ["trade_sessions.id"],
            name="fk_trade_sessions_parent",
            ondelete="SET NULL",
        ),
    )
    op.create_index("idx_trade_sessions_ticker_strategy", "trade_sessions", ["ticker", "strategy"])
    op.create_index("idx_trade_sessions_status", "trade_sessions", ["status"])
    op.execute(
        "CREATE INDEX idx_trade_sessions_parent ON trade_sessions (parent_session_id) "
        "WHERE parent_session_id IS NOT NULL"
    )

    op.add_column(
        "trades",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_trades_session_id",
        "trades", "trade_sessions",
        ["session_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_trades_session_id", "trades", ["session_id"],
        postgresql_where=sa.text("session_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_trades_session_id", "trades")
    op.drop_constraint("fk_trades_session_id", "trades", type_="foreignkey")
    op.drop_column("trades", "session_id")
    op.execute("DROP INDEX IF EXISTS idx_trade_sessions_parent")
    op.drop_index("idx_trade_sessions_status", "trade_sessions")
    op.drop_index("idx_trade_sessions_ticker_strategy", "trade_sessions")
    op.drop_table("trade_sessions")
