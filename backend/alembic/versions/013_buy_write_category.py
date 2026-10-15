"""add BUY_WRITE strategy category

Revision ID: 013
Revises: 012
Create Date: 2026-10-15
"""
from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO categories (name, color, icon, is_system, sort_order) VALUES
          ('BUY_WRITE', '#14B8A6', '📝', true, 11)
        ON CONFLICT (name) DO NOTHING
    """)


def downgrade() -> None:
    # Detach any trades pointing at it before deleting (FK has no ON DELETE rule).
    op.execute("""
        UPDATE trades SET category_id = NULL
        WHERE category_id IN (SELECT id FROM categories WHERE name = 'BUY_WRITE')
    """)
    op.execute("DELETE FROM categories WHERE name = 'BUY_WRITE' AND is_system = true")
