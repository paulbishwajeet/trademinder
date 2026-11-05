"""add SPECULATIVE strategy category

Revision ID: 014
Revises: 013
Create Date: 2026-10-16
"""
from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO categories (name, color, icon, is_system, sort_order) VALUES
          ('SPECULATIVE', '#D946EF', '🎲', true, 12)
        ON CONFLICT (name) DO NOTHING
    """)


def downgrade() -> None:
    # Detach any trades pointing at it before deleting (FK has no ON DELETE rule).
    op.execute("""
        UPDATE trades SET category_id = NULL
        WHERE category_id IN (SELECT id FROM categories WHERE name = 'SPECULATIVE')
    """)
    op.execute("DELETE FROM categories WHERE name = 'SPECULATIVE' AND is_system = true")
