"""categories and extensions

Revision ID: 002
Revises: 001
Create Date: 2026-05-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(50), nullable=False, unique=True),
        sa.Column("color", sa.String(7), nullable=False, server_default="#6B7280"),
        sa.Column("icon", sa.String(10), nullable=True),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="99"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.execute("""
        INSERT INTO categories (name, color, icon, is_system, sort_order) VALUES
          ('Wheel',           '#3B82F6', '🔄', true, 1),
          ('Speculative',     '#EF4444', '🎲', true, 2),
          ('Momentum',        '#F59E0B', '🚀', true, 3),
          ('Short Term',      '#8B5CF6', '⚡', true, 4),
          ('Long Term',       '#10B981', '🌱', true, 5),
          ('Coach Suggested', '#EC4899', '🎓', true, 6)
    """)

    op.add_column("trades", sa.Column("category_id", UUID(as_uuid=True),
                                       sa.ForeignKey("categories.id"), nullable=True))
    op.add_column("alerts", sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "technical_signals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("trade_id", UUID(as_uuid=True), sa.ForeignKey("trades.id", ondelete="CASCADE"), nullable=False),
        sa.Column("signal_type", sa.String(30), nullable=False),
        sa.Column("signal_value", sa.Numeric(10, 4), nullable=True),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("notes", sa.Text, nullable=True),
    )
    op.create_index("idx_signals_trade", "technical_signals", ["trade_id"])
    op.create_index("idx_signals_active", "technical_signals", ["is_active"],
                    postgresql_where=sa.text("is_active"))


def downgrade() -> None:
    op.drop_index("idx_signals_active", "technical_signals")
    op.drop_index("idx_signals_trade", "technical_signals")
    op.drop_table("technical_signals")
    op.drop_column("alerts", "snoozed_until")
    op.drop_column("trades", "category_id")
    op.drop_table("categories")
