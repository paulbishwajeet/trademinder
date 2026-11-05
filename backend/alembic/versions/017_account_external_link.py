"""E*TRADE account link: fingerprint constraint, last label and last seen

Revision ID: 017
Revises: 016
Create Date: 2026-11-04

brokerage_accounts.external_ref (reserved in 015, unused until now) holds the E*TRADE link
fingerprint: lowercase hex SHA-256 of broker + full account number, computed by the extension.
The full account number is never stored; the check constraint refuses anything that is not a
fingerprint. Fingerprints are unique per user. external_label / external_seen_at record the
dropdown label and when the extension last saw it.
"""
from alembic import op
import sqlalchemy as sa

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("brokerage_accounts", sa.Column("external_label", sa.String(100), nullable=True))
    op.add_column("brokerage_accounts", sa.Column("external_seen_at", sa.DateTime(timezone=True), nullable=True))
    # external_ref was reserved but never written; clear anything that isn't a fingerprint.
    op.execute("UPDATE brokerage_accounts SET external_ref = NULL WHERE external_ref !~ '^[0-9a-f]{64}$'")
    op.create_check_constraint(
        "ck_brokerage_accounts_external_ref",
        "brokerage_accounts",
        "external_ref IS NULL OR external_ref ~ '^[0-9a-f]{64}$'",
    )
    op.create_index(
        "uq_brokerage_accounts_user_external_ref", "brokerage_accounts", ["user_id", "external_ref"],
        unique=True, postgresql_where=sa.text("external_ref IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_brokerage_accounts_user_external_ref", table_name="brokerage_accounts")
    op.drop_constraint("ck_brokerage_accounts_external_ref", "brokerage_accounts", type_="check")
    op.drop_column("brokerage_accounts", "external_seen_at")
    op.drop_column("brokerage_accounts", "external_label")
