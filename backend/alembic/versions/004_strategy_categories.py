"""replace strategy category labels

Revision ID: 004
Revises: 003
Create Date: 2026-05-18
"""
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Remove old system categories (NULL out FK first to avoid FK violation)
    op.execute("""
        UPDATE trades SET category_id = NULL
        WHERE category_id IN (
          SELECT id FROM categories
          WHERE is_system = true
          AND name IN ('Wheel', 'Speculative', 'Momentum', 'Short Term', 'Long Term', 'Coach Suggested')
        )
    """)
    op.execute("""
        DELETE FROM categories WHERE is_system = true
          AND name IN ('Wheel', 'Speculative', 'Momentum', 'Short Term', 'Long Term', 'Coach Suggested')
    """)

    # 2. Insert 10 new system categories
    op.execute("""
        INSERT INTO categories (name, color, icon, is_system, sort_order) VALUES
          ('WHEEL',          '#3B82F6', '🔄', true,  1),
          ('SWING',          '#06B6D4', '📈', true,  2),
          ('HOLD',           '#10B981', '🌱', true,  3),
          ('LEAP',           '#8B5CF6', '🚀', true,  4),
          ('PUT_SPREAD',     '#F59E0B', '📉', true,  5),
          ('CALL_SPREAD',    '#F97316', '📈', true,  6),
          ('IRON_CONDOR',    '#EF4444', '🦅', true,  7),
          ('IRON_BUTTERFLY', '#EC4899', '🦋', true,  8),
          ('SKIP',           '#6B7280', '⏭',  true,  9),
          ('HOPS',           '#84CC16', '🌿', true, 10)
    """)

    # 3. Remap category string on existing trades
    op.execute("""
        UPDATE trades SET category = CASE category
          WHEN 'Wheel'           THEN 'WHEEL'
          WHEN 'Long Term'       THEN 'HOLD'
          WHEN 'Short Term'      THEN 'SWING'
          WHEN 'Speculative'     THEN 'SKIP'
          WHEN 'Momentum'        THEN 'SWING'
          WHEN 'Coach Suggested' THEN 'SKIP'
          ELSE category
        END
    """)

    # 4. Update category_id FK to point to new categories
    op.execute("""
        UPDATE trades t
        SET category_id = c.id
        FROM categories c
        WHERE c.name = t.category
    """)


def downgrade() -> None:
    # 1. Restore old system categories
    op.execute("""
        INSERT INTO categories (name, color, icon, is_system, sort_order) VALUES
          ('Wheel',           '#3B82F6', '🔄', true, 1),
          ('Speculative',     '#EF4444', '🎲', true, 2),
          ('Momentum',        '#F59E0B', '🚀', true, 3),
          ('Short Term',      '#8B5CF6', '⚡', true, 4),
          ('Long Term',       '#10B981', '🌱', true, 5),
          ('Coach Suggested', '#EC4899', '🎓', true, 6)
        ON CONFLICT (name) DO NOTHING
    """)

    # 2. Remap trades back (new-only categories fall back to Wheel)
    op.execute("""
        UPDATE trades SET category = CASE category
          WHEN 'WHEEL'          THEN 'Wheel'
          WHEN 'HOLD'           THEN 'Long Term'
          WHEN 'SWING'          THEN 'Short Term'
          WHEN 'SKIP'           THEN 'Speculative'
          WHEN 'LEAP'           THEN 'Wheel'
          WHEN 'PUT_SPREAD'     THEN 'Wheel'
          WHEN 'CALL_SPREAD'    THEN 'Wheel'
          WHEN 'IRON_CONDOR'    THEN 'Speculative'
          WHEN 'IRON_BUTTERFLY' THEN 'Speculative'
          WHEN 'HOPS'           THEN 'Wheel'
          ELSE category
        END
    """)

    # 3. NULL-out category_id for trades still pointing at new system categories
    op.execute("""
        UPDATE trades SET category_id = NULL
        WHERE category_id IN (
          SELECT id FROM categories
          WHERE is_system = true
          AND name IN (
            'WHEEL','SWING','HOLD','LEAP','PUT_SPREAD','CALL_SPREAD',
            'IRON_CONDOR','IRON_BUTTERFLY','SKIP','HOPS'
          )
        )
    """)

    # 4. Remove new system categories (safe — no FK references remain)
    op.execute("""
        DELETE FROM categories WHERE is_system = true
          AND name IN (
            'WHEEL','SWING','HOLD','LEAP','PUT_SPREAD','CALL_SPREAD',
            'IRON_CONDOR','IRON_BUTTERFLY','SKIP','HOPS'
          )
    """)

    # 5. Restore category_id FK to point at the re-inserted old categories
    op.execute("""
        UPDATE trades t
        SET category_id = c.id
        FROM categories c
        WHERE c.name = t.category
    """)
