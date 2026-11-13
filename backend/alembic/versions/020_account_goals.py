"""Account goal and preferences: objective, assignment stance, targets and risk limits

Revision ID: 020
Revises: 019
Create Date: 2026-11-13

Per-brokerage-account goal and preferences that later guidance reads as weights (facts, migration
019, are the gates). Every column is nullable and null means "not set"; for the three defaulted
limits it means "use the house default" (app.services.house_defaults), which is never written here.
Percent values are stored as percent (10 means 10%). Cross-field rules live in the service because
they depend on defaults. The value lists and ranges are written out rather than imported, so this
migration never changes when app code does.
"""
from alembic import op
import sqlalchemy as sa

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None

TABLE = "brokerage_accounts"

ENUM_CHECKS = {
    "objective": ("income", "growth", "mixed"),
    "assignment_stance": ("willing", "selective", "unwilling"),
}
# column -> SQL condition on a non-null value
RANGE_CHECKS = {
    "monthly_premium_target": "{c} >= 0",
    "annual_yield_target_pct": "{c} >= 0 AND {c} <= 100",
    "max_position_pct": "{c} > 0 AND {c} <= 100",
    "max_speculative_position_pct": "{c} > 0 AND {c} <= 100",
    "max_margin_used_pct": "{c} >= 0 AND {c} <= 100",
    "min_cash_reserve_pct": "{c} >= 0 AND {c} <= 100",
    "defensive_at_loss_pct": "{c} > 0 AND {c} <= 100",
}
PCT_COLUMNS = (
    "annual_yield_target_pct", "max_position_pct", "max_speculative_position_pct", "max_margin_used_pct",
    "min_cash_reserve_pct", "defensive_at_loss_pct",
)


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("objective", sa.String(10), nullable=True))
    op.add_column(TABLE, sa.Column("assignment_stance", sa.String(12), nullable=True))
    op.add_column(TABLE, sa.Column("monthly_premium_target", sa.Numeric(12, 2), nullable=True))
    for column in PCT_COLUMNS:
        op.add_column(TABLE, sa.Column(column, sa.Numeric(5, 2), nullable=True))
    op.add_column(TABLE, sa.Column("goals_updated_at", sa.DateTime(timezone=True), nullable=True))
    for column, values in ENUM_CHECKS.items():
        quoted = ", ".join(f"'{v}'" for v in values)
        op.create_check_constraint(f"ck_{TABLE}_{column}", TABLE, f"{column} IS NULL OR {column} IN ({quoted})")
    for column, condition in RANGE_CHECKS.items():
        op.create_check_constraint(
            f"ck_{TABLE}_{column}_range", TABLE, f"{column} IS NULL OR ({condition.format(c=column)})",
        )


def downgrade() -> None:
    for column in RANGE_CHECKS:
        op.drop_constraint(f"ck_{TABLE}_{column}_range", TABLE, type_="check")
    for column in ENUM_CHECKS:
        op.drop_constraint(f"ck_{TABLE}_{column}", TABLE, type_="check")
    for column in ("goals_updated_at", *reversed(PCT_COLUMNS), "monthly_premium_target", "assignment_stance", "objective"):
        op.drop_column(TABLE, column)
