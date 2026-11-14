"""Account facts: the vocabulary and the combination rules.

Facts are per brokerage account and describe what the account is allowed to do (gates). Every fact
is optional; null means "not set". The KB matches on `account_tax_status` (taxable, tax_advantaged)
and `account_purpose` (trading, long_term), so those spellings are fixed.

The value lists are repeated in migration 019 on purpose (migrations never import app code).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, Optional

TAX_TREATMENTS = ("taxable", "traditional_ira", "roth_ira", "other_tax_advantaged")
TAX_ADVANTAGED = ("traditional_ira", "roth_ira", "other_tax_advantaged")
ACCOUNT_PURPOSES = ("trading", "long_term")
MARGIN_TYPES = ("cash", "limited_margin", "margin", "portfolio_margin")
# Cumulative, broker-neutral: each tier allows everything below it.
OPTIONS_TIERS = ("none", "covered", "cash_secured_and_long", "spreads", "uncovered")

# Changing any of these moves facts_updated_at. Money values have their own values_as_of.
FACT_FIELDS = ("tax_treatment", "account_purpose", "margin_type", "options_tier", "options_level_label")
MONEY_FIELDS = ("net_liquidation_value", "cash_balance")
# All four set → facts_complete. The level label and the money values are optional.
REQUIRED_FACTS = ("tax_treatment", "account_purpose", "margin_type", "options_tier")

# numeric(14, 2)
MAX_MONEY_INTEGER_DIGITS = 12


class AccountFactsError(Exception):
    """An impossible combination or value. The API returns 422 {detail, code, fields}."""

    def __init__(self, code: str, detail: str, fields: list[str]):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.fields = fields


def tax_status(tax_treatment: Optional[str]) -> Optional[str]:
    """The KB's account_tax_status: taxable | tax_advantaged | None when unset."""
    if tax_treatment is None:
        return None
    return "taxable" if tax_treatment == "taxable" else "tax_advantaged"


def facts_complete(facts: Mapping[str, Any]) -> bool:
    return all(facts.get(field) is not None for field in REQUIRED_FACTS)


def _check_money(field: str, value: Optional[Decimal]) -> None:
    if value is None:
        return
    label = "Net liquidation value" if field == "net_liquidation_value" else "Cash balance"
    if value < 0:
        raise AccountFactsError("negative_value", f"{label} can't be negative.", [field])
    sign, digits, exponent = value.as_tuple()
    decimals = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    if decimals > 2 or len(digits) - decimals > MAX_MONEY_INTEGER_DIGITS:
        raise AccountFactsError("invalid_value", f"{label} must be a dollar amount with at most 2 decimals.", [field])


def validate(facts: Mapping[str, Any]) -> None:
    """Validate the merged facts (stored values plus the request). Only impossible combinations are
    rejected; a rule fires only when both of its fields are set."""
    for field in MONEY_FIELDS:
        _check_money(field, facts.get(field))

    tax = facts.get("tax_treatment")
    margin = facts.get("margin_type")
    tier = facts.get("options_tier")
    if tax in TAX_ADVANTAGED and margin in ("margin", "portfolio_margin"):
        raise AccountFactsError(
            "tax_advantaged_margin",
            "A tax-advantaged account can't use margin or portfolio margin. Choose cash or limited margin.",
            ["tax_treatment", "margin_type"],
        )
    if tier == "uncovered" and margin in ("cash", "limited_margin"):
        raise AccountFactsError(
            "uncovered_requires_margin",
            "Uncovered options need a margin or portfolio margin account.",
            ["options_tier", "margin_type"],
        )
