"""add commentary_id to rationale

Revision ID: 005
Revises: 004
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rationale",
        sa.Column("commentary_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_rationale_commentary_id",
        "rationale", "commentary",
        ["commentary_id"], ["id"],
        ondelete="CASCADE",
    )
    # Drop old unique index on trade_id
    op.drop_index("idx_rationale_trade", "rationale")
    # Partial unique index: only one entry-time rationale per trade
    op.execute(
        "CREATE UNIQUE INDEX idx_rationale_trade_entry "
        "ON rationale (trade_id) WHERE commentary_id IS NULL"
    )
    op.create_index("idx_rationale_commentary", "rationale", ["commentary_id"])


def downgrade() -> None:
    op.drop_index("idx_rationale_commentary", "rationale")
    op.execute("DROP INDEX IF EXISTS idx_rationale_trade_entry")
    op.create_index("idx_rationale_trade", "rationale", ["trade_id"], unique=True)
    op.drop_constraint("fk_rationale_commentary_id", "rationale", type_="foreignkey")
    op.drop_column("rationale", "commentary_id")
