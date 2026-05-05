"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    op.create_table(
        "trades",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("wheel_id", UUID(as_uuid=True), nullable=True),
        sa.Column("type", sa.String(10), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("strategy", sa.String(30), nullable=False),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("open_date", sa.Date, nullable=False),
        sa.Column("expiry_date", sa.Date, nullable=True),
        sa.Column("closed_date", sa.Date, nullable=True),
        sa.Column("strike_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("premium", sa.Numeric(10, 2), nullable=True),
        sa.Column("collateral", sa.Numeric(12, 2), nullable=True),
        sa.Column("exit_strategy", sa.Text, nullable=True),
        sa.Column("signal_action", sa.Text, nullable=True),
        sa.Column("status", sa.String(10), nullable=False, server_default="open"),
        sa.Column("current_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("last_price_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unrealized_pnl", sa.Numeric(10, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_trades_ticker", "trades", ["ticker"])
    op.create_index("idx_trades_wheel_id", "trades", ["wheel_id"])
    op.create_index("idx_trades_status", "trades", ["status"])
    op.create_index(
        "idx_trades_expiry", "trades", ["expiry_date"],
        postgresql_where=sa.text("expiry_date IS NOT NULL"),
    )

    op.create_table(
        "rationale",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("trade_id", UUID(as_uuid=True), sa.ForeignKey("trades.id", ondelete="CASCADE"), nullable=False),
        sa.Column("macd_signal", sa.String(10), nullable=True),
        sa.Column("macd_notes", sa.Text, nullable=True),
        sa.Column("rsi_14", sa.Numeric(5, 2), nullable=True),
        sa.Column("rsi_result", sa.String(15), nullable=True),
        sa.Column("ma_200d", sa.Numeric(10, 2), nullable=True),
        sa.Column("ma_50d", sa.Numeric(10, 2), nullable=True),
        sa.Column("price_vs_ma200", sa.String(10), nullable=True),
        sa.Column("price_vs_ma50", sa.String(10), nullable=True),
        sa.Column("bollinger_upper", sa.Numeric(10, 2), nullable=True),
        sa.Column("bollinger_mid", sa.Numeric(10, 2), nullable=True),
        sa.Column("bollinger_lower", sa.Numeric(10, 2), nullable=True),
        sa.Column("bollinger_position", sa.String(15), nullable=True),
        sa.Column("day_color", sa.String(5), nullable=True),
        sa.Column("price_action", sa.String(10), nullable=True),
        sa.Column("sentiment", sa.String(10), nullable=True),
        sa.Column("next_earnings_date", sa.Date, nullable=True),
        sa.Column("fetch_status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("fetch_error", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_rationale_trade", "rationale", ["trade_id"], unique=True)

    op.create_table(
        "commentary",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("trade_id", UUID(as_uuid=True), sa.ForeignKey("trades.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entry_date", sa.Date, nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("note", sa.Text, nullable=False),
        sa.Column("tags", ARRAY(sa.String), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_commentary_trade", "commentary", ["trade_id"])
    op.create_index("idx_commentary_date", "commentary", [sa.text("entry_date DESC")])

    op.create_table(
        "alerts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("trade_id", UUID(as_uuid=True), sa.ForeignKey("trades.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alert_type", sa.String(30), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("is_read", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_dismissed", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_alerts_trade", "alerts", ["trade_id"])
    op.create_index(
        "idx_alerts_unread", "alerts", ["is_read", "is_dismissed"],
        postgresql_where=sa.text("NOT is_dismissed"),
    )

    op.create_table(
        "daily_briefings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("briefing_date", sa.Date, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("trade_count", sa.Integer, nullable=True),
        sa.Column("alert_count", sa.Integer, nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("uq_daily_briefings_date", "daily_briefings", ["briefing_date"], unique=True)


def downgrade() -> None:
    # pgcrypto extension is intentionally left installed — it may be shared
    # across schemas/databases and is harmless to leave in place.
    op.drop_table("daily_briefings")
    op.drop_table("alerts")
    op.drop_table("commentary")
    op.drop_table("rationale")
    op.drop_table("trades")
