"""add last_etrade_seen to trades

Revision ID: 007
Revises: 006
Create Date: 2026-06-01
"""
from alembic import op
import sqlalchemy as sa

revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'trades',
        sa.Column('last_etrade_seen', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        'idx_trades_status_last_etrade_seen',
        'trades',
        ['status', 'last_etrade_seen'],
    )


def downgrade() -> None:
    op.drop_index('idx_trades_status_last_etrade_seen', 'trades')
    op.drop_column('trades', 'last_etrade_seen')
