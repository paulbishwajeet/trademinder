"""Account goal and preferences: the vocabulary, effective-limit resolution and the rules.

Facts (app.services.account_facts) are gates; these are weights. Every field is optional; null means
"not set", and for the three defaulted limits it means "use the house default". The KB will match on
these field names and values, so keep them as written.

The value lists and ranges are repeated in migration 020 on purpose (migrations never import app code).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, Optional

from app.services import house_defaults
from app.services.account_facts import AccountFactsError

OBJECTIVES = ("income", "growth", "mixed")
ASSIGNMENT_STANCES = ("willing", "selective", "unwilling")

# Changing any of these moves goals_updated_at.
GOAL_FIELDS = (
    "objective", "assignment_stance", "monthly_premium_target", "annual_yield_target_pct", "max_position_pct",
    "max_speculative_position_pct", "max_margin_used_pct", "min_cash_reserve_pct", "defensive_at_loss_pct",
)
# Both set → goals_complete.
REQUIRED_GOALS = ("objective", "assignment_stance")

# Percent fields: (lowest allowed, lowest is inclusive). The top is always 100 inclusive.
PCT_RANGES: dict[str, tuple[Decimal, bool]] = {
    "annual_yield_target_pct": (Decimal(0), True),
    "max_position_pct": (Decimal(0), False),
    "max_speculative_position_pct": (Decimal(0), False),
    "max_margin_used_pct": (Decimal(0), True),
    "min_cash_reserve_pct": (Decimal(0), True),
    "defensive_at_loss_pct": (Decimal(0), False),
}
MAX_PCT = Decimal(100)
# numeric(12, 2)
MAX_MONEY_INTEGER_DIGITS = 10

LIMIT_DEFAULTS: dict[str, Decimal] = {
    "max_position_pct": house_defaults.MAX_POSITION_PCT,
    "max_speculative_position_pct": house_defaults.MAX_SPECULATIVE_POSITION_PCT,
    "max_margin_used_pct": house_defaults.MAX_MARGIN_USED_PCT,
}

LABELS = {
    "monthly_premium_target": "Monthly premium target",
    "annual_yield_target_pct": "Annual yield target",
    "max_position_pct": "Max position size",
    "max_speculative_position_pct": "Max speculative position size",
    "max_margin_used_pct": "Max margin used",
    "min_cash_reserve_pct": "Minimum cash reserve",
    "defensive_at_loss_pct": "Defensive at loss",
}


def goals_complete(values: Mapping[str, Any]) -> bool:
    return all(values.get(field) is not None for field in REQUIRED_GOALS)


_CENTS = Decimal("0.01")


def _limit(stored: Optional[Decimal], effective: Decimal, source: str, default: Decimal) -> dict:
    # Same scale as the numeric(5,2) columns, so "10.00" whatever the value's origin.
    return {"stored": stored, "effective": effective.quantize(_CENTS), "source": source,
            "default": default.quantize(_CENTS)}


def effective_limits(values: Mapping[str, Any]) -> dict[str, dict]:
    """{limit: {stored, effective, source, default}} for the three defaulted limits.

    source: account (the stored value) | default (the house default) | cash_account (margin limit on
    a cash account: 0) | position_limit (the speculative default capped at a tighter position limit).
    """
    position_stored = values.get("max_position_pct")
    position_default = LIMIT_DEFAULTS["max_position_pct"]
    position = (
        _limit(position_stored, position_stored, "account", position_default)
        if position_stored is not None else _limit(None, position_default, "default", position_default)
    )

    spec_stored = values.get("max_speculative_position_pct")
    spec_default = LIMIT_DEFAULTS["max_speculative_position_pct"]
    if spec_stored is not None:
        speculative = _limit(spec_stored, spec_stored, "account", spec_default)
    elif spec_default > position["effective"]:
        speculative = _limit(None, position["effective"], "position_limit", spec_default)
    else:
        speculative = _limit(None, spec_default, "default", spec_default)

    margin_stored = values.get("max_margin_used_pct")
    margin_default = LIMIT_DEFAULTS["max_margin_used_pct"]
    if margin_stored is not None:
        margin = _limit(margin_stored, margin_stored, "account", margin_default)
    elif values.get("margin_type") == "cash":
        margin = _limit(None, Decimal(0), "cash_account", margin_default)
    else:
        margin = _limit(None, margin_default, "default", margin_default)

    return {
        "max_position_pct": position,
        "max_speculative_position_pct": speculative,
        "max_margin_used_pct": margin,
    }


def _pct(value: Decimal) -> str:
    """10.00 → "10", 2.50 → "2.5"."""
    return format(value.normalize(), "f")


def _check_decimal(field: str, value: Decimal, max_integer_digits: int) -> None:
    _sign, digits, exponent = value.as_tuple()
    decimals = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    if decimals > 2 or len(digits) - decimals > max_integer_digits:
        raise AccountFactsError("invalid_value", f"{LABELS[field]} can have at most 2 decimals.", [field])


def validate(values: Mapping[str, Any]) -> None:
    """Validate the merged facts + goals (stored values plus the request). Only contradictions are
    rejected; merely unusual combinations pass."""
    target = values.get("monthly_premium_target")
    if target is not None:
        if target < 0:
            raise AccountFactsError("negative_value", "Monthly premium target can't be negative.",
                                    ["monthly_premium_target"])
        _check_decimal("monthly_premium_target", target, MAX_MONEY_INTEGER_DIGITS)

    for field, (low, low_inclusive) in PCT_RANGES.items():
        value = values.get(field)
        if value is None:
            continue
        too_low = value < low if low_inclusive else value <= low
        if too_low or value > MAX_PCT:
            bound = "from 0 to 100" if low_inclusive else "above 0 and at most 100"
            raise AccountFactsError("out_of_range", f"{LABELS[field]} must be {bound} (%).", [field])
        _check_decimal(field, value, 3)

    margin_limit = values.get("max_margin_used_pct")
    if values.get("margin_type") == "cash" and margin_limit is not None and margin_limit > 0:
        raise AccountFactsError(
            "cash_account_margin",
            "A cash account can't use margin. Clear the margin limit (or set it to 0), or choose a margin type "
            "that allows borrowing.",
            ["max_margin_used_pct", "margin_type"],
        )

    spec = values.get("max_speculative_position_pct")
    if spec is not None:
        position = effective_limits(values)["max_position_pct"]
        if spec > position["effective"]:
            where = "your" if position["source"] == "account" else "the default"
            raise AccountFactsError(
                "speculative_above_position",
                f"The speculative position limit ({_pct(spec)}%) can't be above {where} position limit "
                f"({_pct(position['effective'])}%).",
                ["max_speculative_position_pct", "max_position_pct"],
            )
