"""wheel v2 — session, slot, leg, premium_log tables

Revision ID: 008
Revises: 007
Create Date: 2026-06-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wheel_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("total_shares", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("opened_at", sa.Date, nullable=False),
        sa.Column("closed_at", sa.Date, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_wheel_sessions_ticker", "wheel_sessions", ["ticker"])
    op.create_index("idx_wheel_sessions_status", "wheel_sessions", ["status"])

    op.create_table(
        "wheel_slots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slot_number", sa.Integer, nullable=False),
        sa.Column("contracts", sa.Integer, nullable=False, server_default="1"),
        sa.Column("shares_held", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("needs_action", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("rotation_number", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["wheel_sessions.id"], name="fk_wheel_slots_session", ondelete="CASCADE"),
    )
    op.create_index("idx_wheel_slots_session", "wheel_slots", ["session_id"])
    op.create_index("idx_wheel_slots_status", "wheel_slots", ["status"])
    op.create_index("idx_wheel_slots_needs_action", "wheel_slots", ["needs_action"], postgresql_where=sa.text("needs_action = true"))

    op.create_table(
        "wheel_slot_legs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("slot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trade_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("leg_role", sa.String(20), nullable=False),
        sa.Column("rotation_number", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["slot_id"], ["wheel_slots.id"], name="fk_wheel_slot_legs_slot", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"], name="fk_wheel_slot_legs_trade", ondelete="CASCADE"),
    )
    op.create_index("idx_wheel_slot_legs_slot", "wheel_slot_legs", ["slot_id"])
    op.create_index("idx_wheel_slot_legs_trade", "wheel_slot_legs", ["trade_id"])

    op.create_table(
        "wheel_premium_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("slot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("leg_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rotation_number", sa.Integer, nullable=False),
        sa.Column("premium_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("event_date", sa.Date, nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["slot_id"], ["wheel_slots.id"], name="fk_wheel_premium_logs_slot", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["leg_id"], ["wheel_slot_legs.id"], name="fk_wheel_premium_logs_leg", ondelete="SET NULL"),
    )
    op.create_index("idx_wheel_premium_logs_slot", "wheel_premium_logs", ["slot_id"])
    op.create_index("idx_wheel_premium_logs_event_date", "wheel_premium_logs", ["event_date"])


def downgrade() -> None:
    op.drop_table("wheel_premium_logs")
    op.drop_table("wheel_slot_legs")
    op.drop_table("wheel_slots")
    op.drop_table("wheel_sessions")
