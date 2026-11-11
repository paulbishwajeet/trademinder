"""login: user sessions, extension tokens, invite/approval audit on users

Revision ID: 018
Revises: 017
Create Date: 2026-11-05

Server-side sessions (only the SHA-256 of the cookie token is stored) and personal extension tokens
(hashed, revocable). users gains invited_by / approved_by / approved_at. No data table is touched.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("invited_by", UUID(as_uuid=True),
                                     sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.add_column("users", sa.Column("approved_by", UUID(as_uuid=True),
                                     sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.add_column("users", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "user_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("user_agent", sa.String(300), nullable=True),
    )
    op.create_index("idx_user_sessions_user", "user_sessions", ["user_id"])

    op.create_table(
        "extension_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_name", sa.String(100), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("token_prefix", sa.String(12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_extension_tokens_hash"),
    )
    op.create_index("idx_extension_tokens_user", "extension_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_extension_tokens_user", table_name="extension_tokens")
    op.drop_table("extension_tokens")
    op.drop_index("idx_user_sessions_user", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_column("users", "approved_at")
    op.drop_column("users", "approved_by")
    op.drop_column("users", "invited_by")
