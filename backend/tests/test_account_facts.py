"""Account facts (migration 019): fields on the accounts endpoints, derived fields, combination rules
on the merged result, timestamps, clearing, ownership and the database check constraints."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.conftest import TestSessionLocal, make_user_with_account

ROTH_CASH = {"tax_treatment": "roth_ira", "account_purpose": "long_term", "margin_type": "cash", "options_tier": "covered"}
TAXABLE_MARGIN = {
    "tax_treatment": "taxable", "account_purpose": "trading", "margin_type": "margin", "options_tier": "uncovered",
}


async def _patch(client, account_id, body):
    return await client.patch(f"/api/accounts/{account_id}", json=body)


async def _get(client, account_id):
    r = await client.get("/api/accounts")
    return next(a for a in r.json() if a["id"] == str(account_id))


# ── Defaults and derived fields ──────────────────────────────────────────

async def test_existing_account_starts_with_every_fact_unset(client, default_account):
    a = await _get(client, default_account.id)
    for field in ("tax_treatment", "account_purpose", "margin_type", "options_tier", "options_level_label",
                  "net_liquidation_value", "cash_balance", "values_as_of", "facts_updated_at",
                  "account_tax_status"):
        assert a[field] is None, field
    assert a["facts_complete"] is False


async def test_create_with_facts_and_money_as_strings(client):
    r = await client.post("/api/accounts", json={
        "broker": "Schwab", "nickname": "Roth", **ROTH_CASH, "options_level_label": " Level 1 ",
        "net_liquidation_value": "125000.5", "cash_balance": 4000,
    })
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["account_tax_status"] == "tax_advantaged"
    assert a["account_purpose"] == "long_term"
    assert a["facts_complete"] is True
    assert a["options_level_label"] == "Level 1"
    assert a["net_liquidation_value"] == "125000.50"
    assert a["cash_balance"] == "4000.00"
    assert a["facts_updated_at"] is not None
    assert a["values_as_of"] is not None


async def test_create_without_facts_leaves_timestamps_unset(client):
    r = await client.post("/api/accounts", json={"broker": "Schwab", "nickname": "Plain"})
    a = r.json()
    assert a["facts_complete"] is False
    assert a["facts_updated_at"] is None and a["values_as_of"] is None


@pytest.mark.parametrize("treatment,status", [
    ("taxable", "taxable"),
    ("traditional_ira", "tax_advantaged"),
    ("roth_ira", "tax_advantaged"),
    ("other_tax_advantaged", "tax_advantaged"),
])
async def test_account_tax_status_uses_kb_spelling(client, default_account, treatment, status):
    r = await _patch(client, default_account.id, {"tax_treatment": treatment})
    assert r.status_code == 200, r.text
    assert r.json()["account_tax_status"] == status


async def test_facts_complete_needs_all_four_core_facts(client, default_account):
    for field in ROTH_CASH:
        partial = {k: v for k, v in ROTH_CASH.items() if k != field}
        await _patch(client, default_account.id, {**ROTH_CASH, field: None})
        assert (await _get(client, default_account.id))["facts_complete"] is False, partial
    r = await _patch(client, default_account.id, ROTH_CASH)
    assert r.json()["facts_complete"] is True  # label and money are optional


async def test_unknown_enumeration_value_is_rejected(client, default_account):
    r = await _patch(client, default_account.id, {"options_tier": "level_3"})
    assert r.status_code == 422


# ── Combination rules ────────────────────────────────────────────────────

@pytest.mark.parametrize("treatment", ["traditional_ira", "roth_ira", "other_tax_advantaged"])
@pytest.mark.parametrize("margin", ["margin", "portfolio_margin"])
async def test_tax_advantaged_rejects_margin(client, default_account, treatment, margin):
    r = await _patch(client, default_account.id, {"tax_treatment": treatment, "margin_type": margin})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "tax_advantaged_margin"
    assert set(body["fields"]) == {"tax_treatment", "margin_type"}
    assert body["detail"]


async def test_tax_advantaged_allows_limited_margin(client, default_account):
    r = await _patch(client, default_account.id, {"tax_treatment": "roth_ira", "margin_type": "limited_margin"})
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("margin", ["cash", "limited_margin"])
async def test_uncovered_requires_margin(client, default_account, margin):
    r = await _patch(client, default_account.id, {"options_tier": "uncovered", "margin_type": margin})
    assert r.status_code == 422
    assert r.json()["code"] == "uncovered_requires_margin"
    assert set(r.json()["fields"]) == {"options_tier", "margin_type"}


async def test_unusual_combinations_are_allowed(client, default_account):
    # A taxable long-term account with margin and uncovered options is unusual, not impossible.
    r = await _patch(client, default_account.id, {**TAXABLE_MARGIN, "account_purpose": "long_term"})
    assert r.status_code == 200, r.text
    r = await _patch(client, default_account.id, {"margin_type": "portfolio_margin"})
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("field", ["net_liquidation_value", "cash_balance"])
async def test_negative_money_is_rejected(client, default_account, field):
    r = await _patch(client, default_account.id, {field: "-1.00"})
    assert r.status_code == 422
    assert r.json()["code"] == "negative_value"
    assert r.json()["fields"] == [field]


@pytest.mark.parametrize("value", ["1.234", "1234567890123"])
async def test_money_out_of_range_is_rejected(client, default_account, value):
    r = await _patch(client, default_account.id, {"cash_balance": value})
    assert r.status_code == 422
    assert r.json()["code"] == "invalid_value"


async def test_partial_update_validated_against_stored_values(client, default_account):
    assert (await _patch(client, default_account.id, ROTH_CASH)).status_code == 200
    # Only margin_type in the request: invalid only once merged with the stored Roth IRA.
    r = await _patch(client, default_account.id, {"margin_type": "margin"})
    assert r.status_code == 422 and r.json()["code"] == "tax_advantaged_margin"
    # Nothing was stored by the failed request.
    a = await _get(client, default_account.id)
    assert a["margin_type"] == "cash"
    # Fixing both fields in one request is fine.
    r = await _patch(client, default_account.id, {"tax_treatment": "taxable", "margin_type": "margin"})
    assert r.status_code == 200, r.text


async def test_partial_update_uncovered_then_downgrade_margin(client, default_account):
    assert (await _patch(client, default_account.id, TAXABLE_MARGIN)).status_code == 200
    r = await _patch(client, default_account.id, {"margin_type": "cash"})
    assert r.status_code == 422 and r.json()["code"] == "uncovered_requires_margin"
    r = await _patch(client, default_account.id, {"options_tier": "spreads", "margin_type": "cash"})
    assert r.status_code == 200, r.text


async def test_create_rejects_impossible_combination(client):
    r = await client.post("/api/accounts", json={
        "broker": "Fidelity", "nickname": "IRA", "tax_treatment": "traditional_ira", "margin_type": "portfolio_margin",
    })
    assert r.status_code == 422 and r.json()["code"] == "tax_advantaged_margin"
    names = [a["nickname"] for a in (await client.get("/api/accounts")).json()]
    assert "IRA" not in names


# ── Timestamps ───────────────────────────────────────────────────────────

async def test_facts_updated_at_moves_only_on_a_fact_change(client, default_account):
    first = (await _patch(client, default_account.id, ROTH_CASH)).json()["facts_updated_at"]
    assert first is not None

    for body in ({"nickname": "Renamed"}, {"sort_order": 7}, ROTH_CASH, {"cash_balance": "10.00"}):
        a = (await _patch(client, default_account.id, body)).json()
        assert a["facts_updated_at"] == first, body

    a = (await _patch(client, default_account.id, {"options_level_label": "Level 2"})).json()
    assert a["facts_updated_at"] != first
    second = a["facts_updated_at"]
    a = (await _patch(client, default_account.id, {"options_tier": "spreads"})).json()
    assert a["facts_updated_at"] != second


async def test_values_as_of_moves_only_when_a_money_value_changes(client, default_account):
    a = (await _patch(client, default_account.id, {"net_liquidation_value": "50000"})).json()
    stamped = a["values_as_of"]
    assert stamped is not None
    assert a["facts_updated_at"] is None  # money isn't a fact for staleness

    a = (await _patch(client, default_account.id, {"net_liquidation_value": "50000.00", "nickname": "X"})).json()
    assert a["values_as_of"] == stamped
    a = (await _patch(client, default_account.id, {"tax_treatment": "taxable"})).json()
    assert a["values_as_of"] == stamped
    a = (await _patch(client, default_account.id, {"cash_balance": "100"})).json()
    assert a["values_as_of"] != stamped


# ── Clearing ─────────────────────────────────────────────────────────────

async def test_explicit_null_clears_a_fact(client, default_account):
    before = (await _patch(client, default_account.id, {**ROTH_CASH, "options_level_label": "Level 1"})).json()
    a = (await _patch(client, default_account.id, {"tax_treatment": None, "options_level_label": None})).json()
    assert a["tax_treatment"] is None and a["account_tax_status"] is None
    assert a["options_level_label"] is None
    assert a["facts_complete"] is False
    assert a["facts_updated_at"] != before["facts_updated_at"]
    assert a["margin_type"] == "cash"  # untouched


async def test_blank_label_is_stored_as_null(client, default_account):
    a = (await _patch(client, default_account.id, {"options_level_label": "   "})).json()
    assert a["options_level_label"] is None


async def test_clearing_both_money_values_clears_values_as_of(client, default_account):
    await _patch(client, default_account.id, {"net_liquidation_value": "1000", "cash_balance": "10"})
    a = (await _patch(client, default_account.id, {"net_liquidation_value": None})).json()
    assert a["net_liquidation_value"] is None and a["values_as_of"] is not None
    a = (await _patch(client, default_account.id, {"cash_balance": None})).json()
    assert a["values_as_of"] is None


# ── Ownership ────────────────────────────────────────────────────────────

async def test_cannot_edit_another_users_facts(client, act_as, owner):
    other, other_account = await make_user_with_account("other@test.local", nickname="Theirs")
    r = await _patch(client, other_account.id, {"tax_treatment": "taxable"})
    assert r.status_code == 404
    ids = [a["id"] for a in (await client.get("/api/accounts")).json()]
    assert str(other_account.id) not in ids
    async with TestSessionLocal() as s:
        stored = await s.scalar(text("SELECT tax_treatment FROM brokerage_accounts WHERE id = :id"),
                                {"id": other_account.id})
    assert stored is None


# ── Database check constraints ───────────────────────────────────────────

@pytest.mark.parametrize("column,bad", [
    ("tax_treatment", "ira"),
    ("account_purpose", "income"),
    ("margin_type", "reg_t"),
    ("options_tier", "level_2"),
    ("net_liquidation_value", -5),
    ("cash_balance", -0.01),
])
async def test_database_check_constraints(default_account, column, bad):
    async with TestSessionLocal() as s:
        with pytest.raises(IntegrityError):
            await s.execute(text(f"UPDATE brokerage_accounts SET {column} = :v WHERE id = :id"),
                            {"v": bad, "id": default_account.id})
            await s.flush()
        await s.rollback()


async def test_database_accepts_every_valid_value(default_account):
    from app.services import account_facts as af
    async with TestSessionLocal() as s:
        for column, values in (("tax_treatment", af.TAX_TREATMENTS), ("account_purpose", af.ACCOUNT_PURPOSES),
                               ("margin_type", af.MARGIN_TYPES), ("options_tier", af.OPTIONS_TIERS)):
            for v in values:
                await s.execute(text(f"UPDATE brokerage_accounts SET {column} = :v WHERE id = :id"),
                                {"v": v, "id": default_account.id})
        await s.rollback()
