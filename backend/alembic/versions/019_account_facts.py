"""Account facts: tax treatment, purpose, margin type, options tier, optional balances

Revision ID: 019
Revises: 018
Create Date: 2026-11-13

Per-brokerage-account facts that later guidance reads as gates. Every column is nullable and null
means "not set": existing accounts are left unset (no guessing). Enumerations are plain strings with
named check constraints, so the downgrade is a clean drop. The value lists are written out here
rather than imported, so this migration never changes when app code does.
"""
from alembic import op
import sqlalchemy as sa

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None

TABLE = "brokerage_accounts"

ENUM_CHECKS = {
    "tax_treatment": ("taxable", "traditional_ira", "roth_ira", "other_tax_advantaged"),
    "account_purpose": ("trading", "long_term"),
    "margin_type": ("cash", "limited_margin", "margin", "portfolio_margin"),
    "options_tier": ("none", "covered", "cash_secured_and_long", "spreads", "uncovered"),
}
MONEY_COLUMNS = ("net_liquidation_value", "cash_balance")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IS NULL OR {column} IN ({quoted})"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("tax_treatment", sa.String(30), nullable=True))
    op.add_column(TABLE, sa.Column("account_purpose", sa.String(20), nullable=True))
    op.add_column(TABLE, sa.Column("margin_type", sa.String(20), nullable=True))
    op.add_column(TABLE, sa.Column("options_tier", sa.String(30), nullable=True))
    op.add_column(TABLE, sa.Column("options_level_label", sa.String(40), nullable=True))
    op.add_column(TABLE, sa.Column("net_liquidation_value", sa.Numeric(14, 2), nullable=True))
    op.add_column(TABLE, sa.Column("cash_balance", sa.Numeric(14, 2), nullable=True))
    op.add_column(TABLE, sa.Column("values_as_of", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLE, sa.Column("facts_updated_at", sa.DateTime(timezone=True), nullable=True))
    for column, values in ENUM_CHECKS.items():
        op.create_check_constraint(f"ck_{TABLE}_{column}", TABLE, _in_list(column, values))
    for column in MONEY_COLUMNS:
        op.create_check_constraint(f"ck_{TABLE}_{column}_non_negative", TABLE, f"{column} IS NULL OR {column} >= 0")


def downgrade() -> None:
    for column in MONEY_COLUMNS:
        op.drop_constraint(f"ck_{TABLE}_{column}_non_negative", TABLE, type_="check")
    for column in ENUM_CHECKS:
        op.drop_constraint(f"ck_{TABLE}_{column}", TABLE, type_="check")
    for column in (
        "facts_updated_at", "values_as_of", "cash_balance", "net_liquidation_value",
        "options_level_label", "options_tier", "margin_type", "account_purpose", "tax_treatment",
    ):
        op.drop_column(TABLE, column)
