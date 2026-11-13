"""Account goal and preferences (migration 020): effective limits and their source, clearing back to
the house default, the cash-margin and speculative rules in every edit order, ranges, goals_complete,
timestamp isolation from the facts, ownership, and the database check constraints."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.services import house_defaults
from tests.conftest import TestSessionLocal, make_user_with_account

LIMITS = ("max_position_pct", "max_speculative_position_pct", "max_margin_used_pct")
DEFAULTS = {
    "max_position_pct": house_defaults.MAX_POSITION_PCT,
    "max_speculative_position_pct": house_defaults.MAX_SPECULATIVE_POSITION_PCT,
    "max_margin_used_pct": house_defaults.MAX_MARGIN_USED_PCT,
}


def _d(value) -> str:
    """The JSON string a Decimal percent serializes to (numeric(5,2))."""
    return f"{float(value):.2f}"


async def _patch(client, account_id, body):
    return await client.patch(f"/api/accounts/{account_id}", json=body)


async def _get(client, account_id):
    r = await client.get("/api/accounts")
    return next(a for a in r.json() if a["id"] == str(account_id))


# ── Defaults and resolution ──────────────────────────────────────────────

async def test_unset_account_resolves_every_limit_to_the_house_default(client, default_account):
    a = await _get(client, default_account.id)
    for limit in LIMITS:
        info = a["limits"][limit]
        assert info == {"stored": None, "effective": _d(DEFAULTS[limit]), "source": "default",
                        "default": _d(DEFAULTS[limit])}, limit
        assert a[limit] is None  # defaults are never written to the row
    assert a["goals_complete"] is False and a["goals_updated_at"] is None
    for field in ("objective", "assignment_stance", "monthly_premium_target", "annual_yield_target_pct",
                  "min_cash_reserve_pct", "defensive_at_loss_pct"):
        assert a[field] is None


@pytest.mark.parametrize("limit,value", [
    ("max_position_pct", "8"), ("max_speculative_position_pct", "2.5"), ("max_margin_used_pct", "20"),
])
async def test_override_then_clear_back_to_default(client, default_account, limit, value):
    a = (await _patch(client, default_account.id, {limit: value})).json()
    assert a[limit] == _d(value)
    assert a["limits"][limit] == {"stored": _d(value), "effective": _d(value), "source": "account",
                                  "default": _d(DEFAULTS[limit])}
    a = (await _patch(client, default_account.id, {limit: None})).json()
    assert a[limit] is None
    assert a["limits"][limit]["source"] == "default"
    assert a["limits"][limit]["effective"] == _d(DEFAULTS[limit])
    async with TestSessionLocal() as s:
        assert await s.scalar(text(f"SELECT {limit} FROM brokerage_accounts WHERE id = :id"),
                              {"id": default_account.id}) is None


async def test_changing_a_default_reaches_accounts_without_an_override(client, default_account, monkeypatch):
    from app.services import account_goals
    monkeypatch.setitem(account_goals.LIMIT_DEFAULTS, "max_position_pct", house_defaults.MAX_POSITION_PCT + 2)
    a = await _get(client, default_account.id)
    assert a["limits"]["max_position_pct"]["effective"] == _d(house_defaults.MAX_POSITION_PCT + 2)


async def test_cash_account_margin_limit_is_zero_and_says_why(client, default_account):
    a = (await _patch(client, default_account.id, {"margin_type": "cash"})).json()
    assert a["limits"]["max_margin_used_pct"] == {"stored": None, "effective": "0.00", "source": "cash_account",
                                                  "default": _d(DEFAULTS["max_margin_used_pct"])}
    # An explicit 0 on a cash account is consistent, so it's allowed.
    a = (await _patch(client, default_account.id, {"max_margin_used_pct": "0"})).json()
    assert a["limits"]["max_margin_used_pct"]["source"] == "account"
    assert a["limits"]["max_margin_used_pct"]["effective"] == "0.00"


async def test_speculative_default_is_capped_by_a_tighter_position_limit(client, default_account):
    a = (await _patch(client, default_account.id, {"max_position_pct": "2"})).json()
    spec = a["limits"]["max_speculative_position_pct"]
    assert spec["stored"] is None and spec["effective"] == "2.00" and spec["source"] == "position_limit"


# ── Cash-margin rule, both orders ────────────────────────────────────────

async def test_cash_account_rejects_a_margin_limit(client, default_account):
    await _patch(client, default_account.id, {"margin_type": "cash"})
    r = await _patch(client, default_account.id, {"max_margin_used_pct": "25"})
    assert r.status_code == 422
    assert r.json()["code"] == "cash_account_margin"
    assert set(r.json()["fields"]) == {"max_margin_used_pct", "margin_type"}


async def test_switching_to_cash_with_a_margin_limit_is_refused(client, default_account):
    a = (await _patch(client, default_account.id, {"margin_type": "margin", "max_margin_used_pct": "25"})).json()
    assert a["limits"]["max_margin_used_pct"]["effective"] == "25.00"
    r = await _patch(client, default_account.id, {"margin_type": "cash"})
    assert r.status_code == 422 and r.json()["code"] == "cash_account_margin"
    assert (await _get(client, default_account.id))["margin_type"] == "margin"  # nothing stored
    # Clearing the limit in the same request makes the switch valid.
    r = await _patch(client, default_account.id, {"margin_type": "cash", "max_margin_used_pct": None})
    assert r.status_code == 200, r.text
    assert r.json()["limits"]["max_margin_used_pct"]["source"] == "cash_account"


async def test_create_rejects_cash_account_with_margin_limit(client):
    r = await client.post("/api/accounts", json={
        "broker": "Fidelity", "nickname": "Cash", "margin_type": "cash", "max_margin_used_pct": "10",
    })
    assert r.status_code == 422 and r.json()["code"] == "cash_account_margin"


# ── Speculative rule ─────────────────────────────────────────────────────

async def test_speculative_above_explicit_position_limit_is_refused(client, default_account):
    await _patch(client, default_account.id, {"max_position_pct": "5"})
    r = await _patch(client, default_account.id, {"max_speculative_position_pct": "6"})
    assert r.status_code == 422 and r.json()["code"] == "speculative_above_position"
    assert set(r.json()["fields"]) == {"max_speculative_position_pct", "max_position_pct"}
    assert (await _patch(client, default_account.id, {"max_speculative_position_pct": "5"})).status_code == 200


async def test_speculative_above_default_position_limit_is_refused(client, default_account):
    r = await _patch(client, default_account.id, {"max_speculative_position_pct": "12"})
    assert r.status_code == 422 and r.json()["code"] == "speculative_above_position"
    assert "default" in r.json()["detail"]
    assert (await _patch(client, default_account.id, {"max_speculative_position_pct": "10"})).status_code == 200


async def test_lowering_or_clearing_the_position_limit_below_speculative_is_refused(client, default_account):
    await _patch(client, default_account.id, {"max_position_pct": "20", "max_speculative_position_pct": "15"})
    r = await _patch(client, default_account.id, {"max_position_pct": "12"})
    assert r.status_code == 422 and r.json()["code"] == "speculative_above_position"
    # Clearing falls back to the default (10), which is below 15 too.
    r = await _patch(client, default_account.id, {"max_position_pct": None})
    assert r.status_code == 422 and r.json()["code"] == "speculative_above_position"


# ── Ranges and unusual combinations ──────────────────────────────────────

@pytest.mark.parametrize("field,bad", [
    ("annual_yield_target_pct", "-1"), ("annual_yield_target_pct", "101"),
    ("max_position_pct", "0"), ("max_position_pct", "100.01"),
    ("max_speculative_position_pct", "0"),
    ("max_margin_used_pct", "-0.5"), ("max_margin_used_pct", "150"),
    ("min_cash_reserve_pct", "101"),
    ("defensive_at_loss_pct", "0"), ("defensive_at_loss_pct", "120"),
])
async def test_percent_out_of_range(client, default_account, field, bad):
    r = await _patch(client, default_account.id, {field: bad})
    assert r.status_code == 422
    assert r.json()["code"] == "out_of_range" and r.json()["fields"] == [field]


@pytest.mark.parametrize("field,good", [
    ("annual_yield_target_pct", "0"), ("annual_yield_target_pct", "100"), ("max_position_pct", "100"),
    ("max_margin_used_pct", "0"), ("min_cash_reserve_pct", "0"), ("defensive_at_loss_pct", "0.5"),
])
async def test_percent_range_edges_are_accepted(client, default_account, field, good):
    assert (await _patch(client, default_account.id, {field: good})).status_code == 200


async def test_monthly_target_negative_and_decimals(client, default_account):
    r = await _patch(client, default_account.id, {"monthly_premium_target": "-5"})
    assert r.status_code == 422 and r.json()["code"] == "negative_value"
    r = await _patch(client, default_account.id, {"monthly_premium_target": "10.555"})
    assert r.status_code == 422 and r.json()["code"] == "invalid_value"
    a = (await _patch(client, default_account.id, {"monthly_premium_target": "1500"})).json()
    assert a["monthly_premium_target"] == "1500.00"


async def test_unusual_combinations_are_allowed(client, default_account):
    r = await _patch(client, default_account.id, {
        "objective": "growth", "monthly_premium_target": "2000", "min_cash_reserve_pct": "90",
        "max_margin_used_pct": "90", "assignment_stance": "unwilling",
    })
    assert r.status_code == 200, r.text


async def test_unknown_enumeration_value_is_rejected(client, default_account):
    assert (await _patch(client, default_account.id, {"objective": "yolo"})).status_code == 422
    assert (await _patch(client, default_account.id, {"assignment_stance": "maybe"})).status_code == 422


# ── goals_complete and timestamps ────────────────────────────────────────

async def test_goals_complete_needs_objective_and_stance(client, default_account):
    a = (await _patch(client, default_account.id, {"objective": "income"})).json()
    assert a["goals_complete"] is False
    a = (await _patch(client, default_account.id, {"assignment_stance": "willing"})).json()
    assert a["goals_complete"] is True
    a = (await _patch(client, default_account.id, {"objective": None})).json()
    assert a["goals_complete"] is False


async def test_goals_updated_at_moves_only_on_a_goal_change(client, default_account):
    first = (await _patch(client, default_account.id, {"objective": "income"})).json()
    stamp = first["goals_updated_at"]
    assert stamp is not None
    assert first["facts_updated_at"] is None  # a goal edit never touches the facts' timestamp

    for body in ({"nickname": "Renamed"}, {"objective": "income"}, {"tax_treatment": "taxable"},
                 {"cash_balance": "10"}):
        a = (await _patch(client, default_account.id, body)).json()
        assert a["goals_updated_at"] == stamp, body

    a = (await _patch(client, default_account.id, {"max_position_pct": "8"})).json()
    assert a["goals_updated_at"] != stamp
    stamp2 = a["goals_updated_at"]
    a = (await _patch(client, default_account.id, {"max_position_pct": "8.00"})).json()
    assert a["goals_updated_at"] == stamp2  # same value
    a = (await _patch(client, default_account.id, {"max_position_pct": None})).json()
    assert a["goals_updated_at"] != stamp2  # clearing is a change


async def test_fact_edit_does_not_move_goals_updated_at_and_vice_versa(client, default_account):
    a = (await _patch(client, default_account.id, {"tax_treatment": "taxable", "objective": "mixed"})).json()
    facts_t, goals_t = a["facts_updated_at"], a["goals_updated_at"]
    a = (await _patch(client, default_account.id, {"margin_type": "margin"})).json()
    assert a["facts_updated_at"] != facts_t and a["goals_updated_at"] == goals_t
    facts_t = a["facts_updated_at"]
    a = (await _patch(client, default_account.id, {"assignment_stance": "selective"})).json()
    assert a["goals_updated_at"] != goals_t and a["facts_updated_at"] == facts_t


# ── Ownership ────────────────────────────────────────────────────────────

async def test_cannot_see_or_edit_another_users_goals(client):
    _other, other_account = await make_user_with_account("other@test.local", nickname="Theirs")
    r = await _patch(client, other_account.id, {"objective": "income", "max_position_pct": "5"})
    assert r.status_code == 404
    ids = [a["id"] for a in (await client.get("/api/accounts")).json()]
    assert str(other_account.id) not in ids
    async with TestSessionLocal() as s:
        row = (await s.execute(text("SELECT objective, max_position_pct FROM brokerage_accounts WHERE id = :id"),
                               {"id": other_account.id})).one()
    assert tuple(row) == (None, None)


# ── Database check constraints ───────────────────────────────────────────

@pytest.mark.parametrize("column,bad", [
    ("objective", "risky"),
    ("assignment_stance", "never"),
    ("monthly_premium_target", -1),
    ("annual_yield_target_pct", 101),
    ("max_position_pct", 0),
    ("max_speculative_position_pct", 100.5),
    ("max_margin_used_pct", -1),
    ("min_cash_reserve_pct", 100.01),
    ("defensive_at_loss_pct", 0),
])
async def test_database_check_constraints(default_account, column, bad):
    async with TestSessionLocal() as s:
        with pytest.raises(IntegrityError):
            await s.execute(text(f"UPDATE brokerage_accounts SET {column} = :v WHERE id = :id"),
                            {"v": bad, "id": default_account.id})
        await s.rollback()
