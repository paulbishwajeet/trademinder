"""Accounts API and account-resolution rules."""
from datetime import date, datetime, timezone

from httpx import AsyncClient
from sqlalchemy import select

TRADE = {
    "type": "Sell", "category": "WHEEL", "strategy": "Put", "ticker": "AAPL",
    "open_date": str(date.today()), "expiry_date": "2026-12-18", "strike_price": "180.00",
    "quantity": 1, "premium": "2.00",
}
PRECOMPUTED = {"price": "100.00", "fetch_status": "ok"}


async def _new_account(client: AsyncClient, **kw) -> dict:
    resp = await client.post("/api/accounts", json={"broker": "E*TRADE", "nickname": "E*TRADE Wheel", **kw})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _accounts(client: AsyncClient, include_archived: bool = False) -> list[dict]:
    return (await client.get(f"/api/accounts?include_archived={str(include_archived).lower()}")).json()


# ── listing / creating ──────────────────────────────────────────────────────

async def test_list_returns_default_account(client, default_account):
    accounts = await _accounts(client)
    assert [a["id"] for a in accounts] == [str(default_account.id)]
    assert accounts[0]["is_default"] is True


async def test_create_and_sort_order(client):
    await _new_account(client, nickname="Z IRA", sort_order=5)
    await _new_account(client, nickname="A Taxable", sort_order=1, broker="Schwab", last_four="1234")
    nicknames = [a["nickname"] for a in await _accounts(client)]
    assert nicknames == ["E*TRADE", "A Taxable", "Z IRA"]


async def test_last_four_rejects_anything_but_four_digits(client):
    for bad in ["12345", "12a4", "123456789012"]:
        resp = await client.post("/api/accounts", json={"broker": "Fidelity", "nickname": "x", "last_four": bad})
        assert resp.status_code == 422


async def test_new_account_uses_all_categories_by_default(client):
    cat = (await client.post("/api/categories", json={"name": "HOLD"})).json()
    acct = await _new_account(client)
    assert acct["category_ids"] == [cat["id"]]


async def test_new_category_links_to_every_active_account(client, default_account):
    second = await _new_account(client)
    cat = (await client.post("/api/categories", json={"name": "SWING"})).json()
    for acct in await _accounts(client):
        assert cat["id"] in acct["category_ids"], acct["nickname"]
    assert second["id"] != str(default_account.id)


# ── single default ──────────────────────────────────────────────────────────

async def test_setting_new_default_clears_old(client, default_account):
    second = await _new_account(client)
    resp = await client.patch(f"/api/accounts/{second['id']}", json={"is_default": True})
    assert resp.status_code == 200 and resp.json()["is_default"] is True
    defaults = [a["id"] for a in await _accounts(client) if a["is_default"]]
    assert defaults == [second["id"]]


async def test_create_with_is_default_moves_default(client):
    second = await _new_account(client, is_default=True)
    defaults = [a["id"] for a in await _accounts(client) if a["is_default"]]
    assert defaults == [second["id"]]


async def test_cannot_unset_the_only_default(client, default_account):
    resp = await client.patch(f"/api/accounts/{default_account.id}", json={"is_default": False})
    assert resp.status_code == 400


# ── default account / default category on create ───────────────────────────

async def test_trade_without_account_goes_to_default(client, default_account):
    trade = (await client.post("/api/trades", json=TRADE)).json()
    assert trade["account_id"] == str(default_account.id)
    assert trade["account"] == {"id": str(default_account.id), "nickname": "E*TRADE", "broker": "E*TRADE", "last_four": None}


async def test_trade_with_account_and_list_filter(client, default_account):
    second = await _new_account(client)
    t1 = (await client.post("/api/trades", json=TRADE)).json()
    t2 = (await client.post("/api/trades", json={**TRADE, "account_id": second["id"]})).json()
    assert t2["account_id"] == second["id"]

    all_ids = {t["id"] for t in (await client.get("/api/trades")).json()}
    assert all_ids == {t1["id"], t2["id"]}  # absent account_id = all accounts (today's UI)
    only_second = [t["id"] for t in (await client.get(f"/api/trades?account_id={second['id']}")).json()]
    assert only_second == [t2["id"]]


async def test_default_category_applies_when_category_omitted(client, default_account):
    cat = (await client.post("/api/categories", json={"name": "LEAP"})).json()
    resp = await client.patch(f"/api/accounts/{default_account.id}", json={"default_category_id": cat["id"]})
    assert resp.status_code == 200
    payload = {k: v for k, v in TRADE.items() if k != "category"}
    trade = (await client.post("/api/trades", json=payload)).json()
    assert trade["category"] == "LEAP"
    detail = (await client.get(f"/api/trades/{trade['id']}")).json()
    assert detail["category"] == "LEAP"


async def test_explicit_category_wins_over_default(client, default_account):
    cat = (await client.post("/api/categories", json={"name": "LEAP"})).json()
    await client.patch(f"/api/accounts/{default_account.id}", json={"default_category_id": cat["id"]})
    trade = (await client.post("/api/trades", json=TRADE)).json()
    assert trade["category"] == "WHEEL"


async def test_category_required_without_account_default(client):
    payload = {k: v for k, v in TRADE.items() if k != "category"}
    assert (await client.post("/api/trades", json=payload)).status_code == 422


async def test_default_category_must_be_in_account_categories(client, default_account):
    cat = (await client.post("/api/categories", json={"name": "HOPS"})).json()
    await client.put(f"/api/accounts/{default_account.id}/categories", json={"category_ids": []})
    resp = await client.patch(f"/api/accounts/{default_account.id}", json={"default_category_id": cat["id"]})
    assert resp.status_code == 400


async def test_removing_default_category_from_list_clears_it(client, default_account):
    cat = (await client.post("/api/categories", json={"name": "HOPS"})).json()
    await client.patch(f"/api/accounts/{default_account.id}", json={"default_category_id": cat["id"]})
    resp = await client.put(f"/api/accounts/{default_account.id}/categories", json={"category_ids": []})
    assert resp.status_code == 200
    assert resp.json()["category_ids"] == []
    assert resp.json()["default_category_id"] is None


async def test_wheel_and_spread_creation_use_default_or_named_account(client, default_account):
    second = await _new_account(client)
    w1 = (await client.post("/api/wheel", json={"ticker": "NVDA", "opened_at": str(date.today())})).json()
    w2 = (await client.post("/api/wheel", json={"ticker": "NVDA", "opened_at": str(date.today()),
                                                "account_id": second["id"]})).json()
    assert w1["account_id"] == str(default_account.id) and w2["account_id"] == second["id"]
    assert w1["account"]["nickname"] == "E*TRADE"
    assert len((await client.get("/api/wheel")).json()) == 2
    assert [w["id"] for w in (await client.get(f"/api/wheel?account_id={second['id']}")).json()] == [w2["id"]]

    slot = (await client.post(f"/api/wheel/{w2['id']}/slots", json={"status": "awaiting_sold_put"})).json()
    assert slot["account_id"] == second["id"]
    detail = (await client.get(f"/api/wheel/{w2['id']}")).json()
    assert detail["slots"][0]["account"]["id"] == second["id"]

    s1 = (await client.post("/api/sessions", json={"ticker": "SPY", "strategy": "IRON_CONDOR", "status": "open",
                                                   "opened_at": str(date.today())})).json()
    assert s1["account_id"] == str(default_account.id)
    s2 = (await client.post("/api/sessions", json={"ticker": "SPY", "strategy": "IRON_CONDOR", "status": "open",
                                                   "opened_at": str(date.today()), "account_id": second["id"]})).json()
    listed = (await client.get(f"/api/sessions?strategy=IRON_CONDOR&account_id={second['id']}")).json()
    assert [s["id"] for s in listed] == [s2["id"]]


async def test_wheel_leg_must_be_in_wheel_account(client):
    second = await _new_account(client)
    wheel = (await client.post("/api/wheel", json={"ticker": "AAPL", "opened_at": str(date.today())})).json()
    slot = (await client.post(f"/api/wheel/{wheel['id']}/slots", json={"status": "awaiting_sold_put"})).json()
    trade = (await client.post("/api/trades", json={**TRADE, "account_id": second["id"]})).json()
    resp = await client.post(f"/api/wheel/slots/{slot['id']}/legs", json={"trade_id": trade["id"], "leg_role": "sold_put"})
    assert resp.status_code == 400


# ── archive / delete ────────────────────────────────────────────────────────

async def test_last_active_account_cannot_be_archived_or_deleted(client, default_account):
    assert (await client.post(f"/api/accounts/{default_account.id}/archive")).status_code == 400
    assert (await client.delete(f"/api/accounts/{default_account.id}")).status_code == 400


async def test_archiving_default_moves_default_and_hides_account(client, default_account):
    second = await _new_account(client)
    resp = await client.post(f"/api/accounts/{default_account.id}/archive")
    assert resp.status_code == 200 and resp.json()["is_archived"] is True and resp.json()["is_default"] is False
    active = await _accounts(client)
    assert [a["id"] for a in active] == [second["id"]] and active[0]["is_default"] is True
    assert len(await _accounts(client, include_archived=True)) == 2


async def test_archived_account_rejects_new_writes_but_lists_history(client, default_account):
    second = await _new_account(client)
    trade = (await client.post("/api/trades", json={**TRADE, "account_id": second["id"]})).json()
    await client.post(f"/api/accounts/{second['id']}/archive")
    assert (await client.post("/api/trades", json={**TRADE, "account_id": second["id"]})).status_code == 404
    listed = (await client.get(f"/api/trades?account_id={second['id']}")).json()
    assert [t["id"] for t in listed] == [trade["id"]]


async def test_account_with_data_can_only_be_archived(client):
    second = await _new_account(client)
    await client.post("/api/wheel", json={"ticker": "AAPL", "opened_at": str(date.today()), "account_id": second["id"]})
    assert (await client.delete(f"/api/accounts/{second['id']}")).status_code == 409
    assert (await client.post(f"/api/accounts/{second['id']}/archive")).status_code == 200


async def test_empty_account_can_be_deleted(client):
    second = await _new_account(client)
    assert (await client.delete(f"/api/accounts/{second['id']}")).status_code == 204
    assert second["id"] not in [a["id"] for a in await _accounts(client, include_archived=True)]


# ── screener memberships and per-account notes ──────────────────────────────

async def test_screener_membership_lifecycle(client, default_account):
    second = await _new_account(client, nickname="IRA")
    row = (await client.post("/api/screener", json={"symbol": "AAPL", "precomputed": PRECOMPUTED})).json()
    assert row["account_ids"] == [str(default_account.id)]
    # already in the default account → 409, as before
    assert (await client.post("/api/screener", json={"symbol": "AAPL", "precomputed": PRECOMPUTED})).status_code == 409
    # same symbol in another account → same row, one more membership
    row2 = (await client.post("/api/screener", json={"symbol": "AAPL", "account_id": second["id"]})).json()
    assert row2["id"] == row["id"] and set(row2["account_ids"]) == {str(default_account.id), second["id"]}

    await client.post("/api/screener", json={"symbol": "MSFT", "precomputed": PRECOMPUTED})
    assert [r["symbol"] for r in (await client.get("/api/screener")).json()] == ["AAPL", "MSFT"]
    assert [r["symbol"] for r in (await client.get(f"/api/screener?account_id={second['id']}")).json()] == ["AAPL"]

    # removing from one account keeps the row; removing from the last deletes it
    assert (await client.delete(f"/api/screener/AAPL?account_id={second['id']}")).status_code == 204
    assert [r["symbol"] for r in (await client.get("/api/screener")).json()] == ["AAPL", "MSFT"]
    assert (await client.delete(f"/api/screener/AAPL?account_id={second['id']}")).status_code == 404
    assert (await client.delete(f"/api/screener/AAPL?account_id={default_account.id}")).status_code == 204
    assert [r["symbol"] for r in (await client.get("/api/screener")).json()] == ["MSFT"]


async def test_screener_notes_are_per_account(client, default_account):
    ira = await _new_account(client, nickname="IRA")
    await client.post("/api/screener", json={"symbol": "AAPL", "precomputed": PRECOMPUTED})
    n1 = (await client.post("/api/screener/AAPL/commentary", json={"note": "taxable"})).json()
    n2 = (await client.post("/api/screener/AAPL/commentary", json={"note": "ira", "account_id": ira["id"]})).json()
    assert n1["account_id"] == str(default_account.id) and n1["account"]["nickname"] == "E*TRADE"
    assert n2["account"]["nickname"] == "IRA"

    everything = (await client.get("/api/screener/AAPL/commentary")).json()
    assert {n["note"]: n["account"]["nickname"] for n in everything} == {"taxable": "E*TRADE", "ira": "IRA"}
    only_ira = (await client.get(f"/api/screener/AAPL/commentary?account_id={ira['id']}")).json()
    assert [n["note"] for n in only_ira] == ["ira"]


async def test_fetch_all_fetches_each_symbol_once(client, monkeypatch):
    import app.routers.screener as screener_router
    captured = {}

    async def _capture(job_id, user_id, symbols, session_factory=None):
        captured["symbols"] = symbols
    monkeypatch.setattr(screener_router, "_run_fetch_all_job", _capture)

    ira = await _new_account(client, nickname="IRA")
    await client.post("/api/screener", json={"symbol": "AAPL", "precomputed": PRECOMPUTED})
    await client.post("/api/screener", json={"symbol": "AAPL", "account_id": ira["id"]})
    job = (await client.post("/api/screener/fetch-all")).json()
    import asyncio
    await asyncio.sleep(0)
    assert job["total"] == 1 and captured["symbols"] == ["AAPL"]


# ── scheduler writes carry the owner ────────────────────────────────────────

async def test_alert_and_signal_engines_stamp_owner(client, db_session, owner):
    from app.models.alert import Alert
    from app.models.signal import TechnicalSignal
    from app.services.alert_engine import run as run_alerts
    from app.services.signal_engine import run as run_signals

    trade = (await client.post("/api/trades", json={**TRADE, "expiry_date": str(date.today())})).json()
    await client.put(f"/api/trades/{trade['id']}/rationale", json={"rsi_14": "25"})
    assert (await run_alerts(db_session))["alerts_created"] >= 1
    await run_signals(db_session)

    alerts = (await db_session.execute(select(Alert))).scalars().all()
    signals = (await db_session.execute(select(TechnicalSignal))).scalars().all()
    assert alerts and all(a.user_id == owner.id for a in alerts)
    assert signals and all(s.user_id == owner.id for s in signals)
