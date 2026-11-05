"""Part 2 backend: restore, reorder, delete guards, can_delete, and the Dashboard summary."""
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest_asyncio
from httpx import AsyncClient

from app.models.alert import Alert
from app.models.wheel_premium_log import WheelPremiumLog
from app.models.wheel_slot import WheelSlot
from tests.conftest import make_user_with_account

ET = ZoneInfo("America/New_York")
TODAY = datetime.now(timezone.utc).astimezone(ET).date()
PRECOMPUTED = {"price": "100.00", "fetch_status": "ok"}


def trade(**kw) -> dict:
    return {
        "type": "Sell", "category": "WHEEL", "strategy": "Put", "ticker": "AAPL",
        "open_date": str(TODAY), "expiry_date": str(TODAY + timedelta(days=30)), "strike_price": "100.00",
        "quantity": 1, "premium": "2.00", **kw,
    }


async def new_account(client: AsyncClient, nickname: str = "IRA", **kw) -> dict:
    resp = await client.post("/api/accounts", json={"broker": "Schwab", "nickname": nickname, **kw})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def ids_in_order(client: AsyncClient, include_archived: bool = False) -> list[str]:
    q = "?include_archived=true" if include_archived else ""
    return [a["id"] for a in (await client.get(f"/api/accounts{q}")).json()]


@pytest_asyncio.fixture
async def other():
    return await make_user_with_account("b@test.local", nickname="B")


# ── restore ─────────────────────────────────────────────────────────────────

async def test_restore_brings_archived_account_back(client, default_account):
    ira = await new_account(client)
    await client.post(f"/api/accounts/{ira['id']}/archive")
    assert ira["id"] not in await ids_in_order(client)
    resp = await client.post(f"/api/accounts/{ira['id']}/restore")
    assert resp.status_code == 200 and resp.json()["is_archived"] is False
    assert ira["id"] in await ids_in_order(client)
    # restoring does not steal the default
    assert [a["id"] for a in (await client.get("/api/accounts")).json() if a["is_default"]] == [str(default_account.id)]


async def test_restore_of_active_account_is_a_noop(client, default_account):
    resp = await client.post(f"/api/accounts/{default_account.id}/restore")
    assert resp.status_code == 200 and resp.json()["is_default"] is True


# ── delete guards and can_delete ────────────────────────────────────────────

async def test_can_delete_reflects_contents(client, default_account):
    ira = await new_account(client)
    assert ira["can_delete"] is True
    await client.post("/api/trades", json=trade(account_id=ira["id"]))
    listed = {a["id"]: a for a in (await client.get("/api/accounts")).json()}
    assert listed[ira["id"]]["can_delete"] is False


async def test_delete_blocked_by_each_kind_of_data(client, default_account):
    today = str(TODAY)
    makers = {
        "trade": lambda aid: client.post("/api/trades", json=trade(account_id=aid)),
        "wheel": lambda aid: client.post("/api/wheel", json={"ticker": "AAPL", "opened_at": today, "account_id": aid}),
        "spread": lambda aid: client.post("/api/sessions", json={
            "ticker": "SPY", "strategy": "IRON_CONDOR", "status": "open", "opened_at": today, "account_id": aid}),
        "membership": lambda aid: client.post("/api/screener", json={
            "symbol": f"M{aid[:3].upper()}", "precomputed": PRECOMPUTED, "account_id": aid}),
    }
    for kind, make in makers.items():
        acct = await new_account(client, nickname=kind)
        assert (await make(acct["id"])).status_code == 201, kind
        resp = await client.delete(f"/api/accounts/{acct['id']}")
        assert resp.status_code == 409, kind
        assert "archive" in resp.json()["detail"]


async def test_delete_blocked_by_screener_note(client, default_account):
    await client.post("/api/screener", json={"symbol": "AAPL", "precomputed": PRECOMPUTED})
    ira = await new_account(client)
    note = await client.post("/api/screener/AAPL/commentary", json={"note": "ira view", "account_id": ira["id"]})
    assert note.status_code == 201
    assert (await client.delete(f"/api/accounts/{ira['id']}")).status_code == 409


async def test_empty_archived_account_can_be_deleted(client, default_account):
    ira = await new_account(client)
    await client.post(f"/api/accounts/{ira['id']}/archive")
    assert (await client.delete(f"/api/accounts/{ira['id']}")).status_code == 204
    assert ira["id"] not in await ids_in_order(client, include_archived=True)


async def test_last_active_account_guards_still_hold(client, default_account):
    ira = await new_account(client)
    await client.post(f"/api/accounts/{ira['id']}/archive")
    assert (await client.post(f"/api/accounts/{default_account.id}/archive")).status_code == 400
    assert (await client.delete(f"/api/accounts/{default_account.id}")).status_code == 400


async def test_new_accounts_default_to_the_end(client, default_account):
    a = await new_account(client, nickname="A")
    b = await new_account(client, nickname="B")
    assert await ids_in_order(client) == [str(default_account.id), a["id"], b["id"]]


# ── reorder ─────────────────────────────────────────────────────────────────

async def test_reorder_persists(client, default_account):
    a = await new_account(client, nickname="A")
    b = await new_account(client, nickname="B")
    wanted = [b["id"], str(default_account.id), a["id"]]
    resp = await client.put("/api/accounts/order", json={"account_ids": wanted})
    assert resp.status_code == 200
    assert [x["id"] for x in resp.json()] == wanted
    assert await ids_in_order(client) == wanted


async def test_reorder_keeps_unlisted_archived_accounts_after(client, default_account):
    a = await new_account(client, nickname="A")
    arch = await new_account(client, nickname="Old")
    await client.post(f"/api/accounts/{arch['id']}/archive")
    resp = await client.put("/api/accounts/order", json={"account_ids": [a["id"], str(default_account.id)]})
    assert resp.status_code == 200
    assert await ids_in_order(client, include_archived=True) == [a["id"], str(default_account.id), arch["id"]]


async def test_reorder_rejects_bad_lists(client, default_account, other):
    a = await new_account(client, nickname="A")
    d = str(default_account.id)
    assert (await client.put("/api/accounts/order", json={"account_ids": [a["id"]]})).status_code == 400
    assert (await client.put("/api/accounts/order", json={"account_ids": [a["id"], d, a["id"]]})).status_code == 400
    assert (await client.put("/api/accounts/order", json={"account_ids": [a["id"], d, str(uuid.uuid4())]})).status_code == 404
    foreign = str(other[1].id)
    assert (await client.put("/api/accounts/order", json={"account_ids": [a["id"], d, foreign]})).status_code == 404


# ── dashboard summary ───────────────────────────────────────────────────────

async def _wheel_with_slot(client, account_id: str, ticker: str) -> tuple[dict, dict]:
    wheel = (await client.post("/api/wheel", json={"ticker": ticker, "opened_at": str(TODAY), "account_id": account_id})).json()
    slot = (await client.post(f"/api/wheel/{wheel['id']}/slots", json={"status": "awaiting_sold_put"})).json()
    return wheel, slot


async def test_dashboard_summary_numbers(client, db_session, owner, default_account):
    ira = await new_account(client)
    main = str(default_account.id)

    # main: 2 open trades (one expiring in 3 days), 1 closed; ira: 1 open trade expiring today
    expiring = (await client.post("/api/trades", json=trade(expiry_date=str(TODAY + timedelta(days=3))))).json()
    await client.post("/api/trades", json=trade(ticker="MSFT"))
    closed = (await client.post("/api/trades", json=trade(ticker="TSLA", expiry_date=str(TODAY + timedelta(days=1))))).json()
    await client.post(f"/api/trades/{closed['id']}/close", json={})
    await client.post("/api/trades", json=trade(ticker="NVDA", expiry_date=str(TODAY), account_id=ira["id"]))
    await client.post("/api/trades", json=trade(ticker="AMD", expiry_date=str(TODAY + timedelta(days=8)), account_id=ira["id"]))

    # wheels: main has 2 active (one with a needs-action slot holding the expiring leg); ira has 1
    w1, s1 = await _wheel_with_slot(client, main, "AAPL")
    await client.post(f"/api/wheel/slots/{s1['id']}/legs", json={"trade_id": expiring["id"], "leg_role": "sold_put"})
    await _wheel_with_slot(client, main, "MSFT")
    w3, s3 = await _wheel_with_slot(client, ira["id"], "NVDA")
    closed_wheel, s4 = await _wheel_with_slot(client, ira["id"], "OLD")
    await client.patch(f"/api/wheel/{closed_wheel['id']}", json={"status": "closed"})

    for slot_id in (s1["id"], s3["id"], s4["id"]):  # s4 is in a closed wheel → excluded
        slot = await db_session.get(WheelSlot, uuid.UUID(slot_id))
        slot.needs_action = True

    # premium: link_leg logged premium*quantity = +2.00 on main (opened today); add a -50 buyback this month and +999 last month
    month_start = TODAY.replace(day=1)
    db_session.add(WheelPremiumLog(user_id=owner.id, slot_id=uuid.UUID(s1["id"]), rotation_number=1,
                                   premium_amount=Decimal("-50.00"), event_type="put_bought_back", event_date=TODAY))
    db_session.add(WheelPremiumLog(user_id=owner.id, slot_id=uuid.UUID(s1["id"]), rotation_number=1,
                                   premium_amount=Decimal("999.00"), event_type="put_sold",
                                   event_date=month_start - timedelta(days=1)))
    db_session.add(WheelPremiumLog(user_id=owner.id, slot_id=uuid.UUID(s3["id"]), rotation_number=1,
                                   premium_amount=Decimal("75.50"), event_type="put_sold", event_date=month_start))

    # alerts: one today on main, one today dismissed, one yesterday, one today on ira
    today_noon = datetime.combine(TODAY, time(12), tzinfo=ET)
    def alert(trade_id, when, **kw):
        return Alert(user_id=owner.id, trade_id=uuid.UUID(trade_id), alert_type="dte_critical", severity="urgent",
                     title="t", message="m", triggered_at=when, **kw)
    ira_trades = (await client.get(f"/api/trades?account_id={ira['id']}")).json()
    db_session.add_all([
        alert(expiring["id"], today_noon),
        alert(expiring["id"], today_noon, is_dismissed=True),
        alert(expiring["id"], today_noon - timedelta(days=1)),
        alert(next(t["id"] for t in ira_trades if t["ticker"] == "NVDA"), today_noon - timedelta(hours=1)),
    ])
    await db_session.commit()

    data = (await client.get("/api/dashboard/summary")).json()
    assert data["as_of"] == str(TODAY)
    cards = {c["account"]["id"]: c for c in data["accounts"]}
    assert list(cards) == [main, ira["id"]]
    assert cards[main] | {"account": None} == {
        "account": None, "is_default": True, "open_trades": 2, "active_wheels": 2,
        "slots_needing_action": 1, "legs_expiring_7d": 1, "net_premium_month": "-48.00",
    }
    assert cards[ira["id"]]["open_trades"] == 2
    assert cards[ira["id"]]["active_wheels"] == 1
    assert cards[ira["id"]]["slots_needing_action"] == 1
    assert cards[ira["id"]]["legs_expiring_7d"] == 1
    assert cards[ira["id"]]["net_premium_month"] == "75.50"

    needs = {n["slot_id"]: n for n in data["needs_action"]}
    assert set(needs) == {s1["id"], s3["id"]}
    assert needs[s1["id"]]["open_leg_expiry"] == expiring["expiry_date"]
    assert needs[s1["id"]]["account"]["id"] == main and needs[s1["id"]]["ticker"] == "AAPL"
    assert needs[s3["id"]]["open_leg_expiry"] is None and needs[s3["id"]]["account"]["nickname"] == "IRA"

    assert [(a["ticker"], a["account"]["nickname"]) for a in data["alerts"]] == [("AAPL", "E*TRADE"), ("NVDA", "IRA")]


async def test_dashboard_skips_archived_accounts(client, default_account):
    ira = await new_account(client)
    await client.post(f"/api/accounts/{ira['id']}/archive")
    data = (await client.get("/api/dashboard/summary")).json()
    assert [c["account"]["id"] for c in data["accounts"]] == [str(default_account.id)]


async def test_dashboard_is_isolated_per_user(client, db_session, owner, default_account, other, act_as):
    t = (await client.post("/api/trades", json=trade())).json()
    _, slot = await _wheel_with_slot(client, str(default_account.id), "AAPL")
    (await db_session.get(WheelSlot, uuid.UUID(slot["id"]))).needs_action = True
    db_session.add(Alert(user_id=owner.id, trade_id=uuid.UUID(t["id"]), alert_type="x", severity="info",
                         title="t", message="m", triggered_at=datetime.now(timezone.utc)))
    await db_session.commit()

    act_as(other[0])
    data = (await client.get("/api/dashboard/summary")).json()
    assert [c["account"]["id"] for c in data["accounts"]] == [str(other[1].id)]
    card = data["accounts"][0]
    assert (card["open_trades"], card["active_wheels"], card["slots_needing_action"], card["net_premium_month"]) == (0, 0, 0, "0")
    assert data["needs_action"] == [] and data["alerts"] == []


async def test_other_user_cannot_restore_or_reorder_owner_accounts(client, default_account, other, act_as):
    ira = await new_account(client)
    await client.post(f"/api/accounts/{ira['id']}/archive")
    act_as(other[0])
    assert (await client.post(f"/api/accounts/{ira['id']}/restore")).status_code == 404
    resp = await client.put("/api/accounts/order", json={"account_ids": [str(other[1].id), str(default_account.id)]})
    assert resp.status_code == 404
