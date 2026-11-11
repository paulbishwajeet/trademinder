"""make commentary.trade_id nullable, add slot_id for slot-level notes

Revision ID: 012
Revises: 011
Create Date: 2026-09-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('commentary', 'trade_id', nullable=True)
    op.add_column('commentary', sa.Column(
        'slot_id', postgresql.UUID(as_uuid=True),
        sa.ForeignKey('wheel_slots.id', ondelete='CASCADE'), nullable=True,
    ))
    op.create_index('idx_commentary_slot', 'commentary', ['slot_id'])
    op.create_check_constraint(
        'ck_commentary_trade_xor_slot',
        'commentary',
        '(trade_id IS NOT NULL AND slot_id IS NULL) OR (trade_id IS NULL AND slot_id IS NOT NULL)',
    )


def downgrade() -> None:
    op.drop_constraint('ck_commentary_trade_xor_slot', 'commentary', type_='check')
    op.drop_index('idx_commentary_slot', table_name='commentary')
    op.drop_column('commentary', 'slot_id')
    op.alter_column('commentary', 'trade_id', nullable=False)
