"""add screener and screener_commentary tables

Revision ID: 010
Revises: 009
Create Date: 2026-08-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'screener',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('symbol', sa.String(10), nullable=False),
        sa.Column('sector', sa.String(50), nullable=True),
        sa.Column('category', sa.String(50), nullable=True),
        sa.Column('price', sa.Numeric(10, 2), nullable=True),
        sa.Column('prev_close', sa.Numeric(10, 2), nullable=True),
        sa.Column('change_pct', sa.Numeric(6, 2), nullable=True),
        sa.Column('iv_rank', sa.Numeric(5, 2), nullable=True),
        sa.Column('iv_percentile', sa.Numeric(5, 2), nullable=True),
        sa.Column('rsi_14', sa.Numeric(5, 2), nullable=True),
        sa.Column('macd_weekly_signal', sa.String(10), nullable=True),
        sa.Column('macd_daily_signal', sa.String(10), nullable=True),
        sa.Column('ma_20d', sa.Numeric(10, 2), nullable=True),
        sa.Column('ma_50d', sa.Numeric(10, 2), nullable=True),
        sa.Column('ma_100d', sa.Numeric(10, 2), nullable=True),
        sa.Column('ma_200d', sa.Numeric(10, 2), nullable=True),
        sa.Column('bollinger_upper', sa.Numeric(10, 2), nullable=True),
        sa.Column('bollinger_mid', sa.Numeric(10, 2), nullable=True),
        sa.Column('bollinger_lower', sa.Numeric(10, 2), nullable=True),
        sa.Column('bollinger_position', sa.String(15), nullable=True),
        sa.Column('next_earnings_date', sa.Date(), nullable=True),
        sa.Column('volume_spikes', postgresql.JSONB, nullable=True),
        sa.Column('last_fetched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('fetch_status', sa.String(10), nullable=True),
        sa.Column('fetch_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('idx_screener_symbol', 'screener', ['symbol'], unique=True)

    op.create_table(
        'screener_commentary',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'screener_id', postgresql.UUID(as_uuid=True),
            sa.ForeignKey('screener.id', ondelete='CASCADE'), nullable=False,
        ),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('tags', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('idx_screener_commentary_screener', 'screener_commentary', ['screener_id'])


def downgrade() -> None:
    op.drop_index('idx_screener_commentary_screener', table_name='screener_commentary')
    op.drop_table('screener_commentary')
    op.drop_index('idx_screener_symbol', table_name='screener')
    op.drop_table('screener')
