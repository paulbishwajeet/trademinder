"""Part 3: positions/status and positions/reconcile account scoping."""
import uuid
from datetime import date

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert

SYMBOL = "NVDA--260919P00120000"
PUT = {
    "type": "Sell", "category": "WHEEL", "strategy": "Sell Put", "ticker": "NVDA",
    "open_date": str(date.today()), "expiry_date": "2026-09-19", "strike_price": "120.00",
    "quantity": 1, "premium": "3.00", "etrade_symbol": SYMBOL,
}
ROW = {"ticker": "NVDA", "full_symbol": SYMBOL, "type": "Put", "strike": 120.0, "expiry": "2026-09-19"}


async def status(client: AsyncClient, account_id=None, rows=(ROW,)) -> dict:
    body = {"positions": list(rows), **({"account_id": str(account_id)} if account_id else {})}
    resp = await client.post("/api/positions/status", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def two_accounts_holding_nvda(client, default_account):
    ira = (await client.post("/api/accounts", json={"broker": "E*TRADE", "nickname": "IRA"})).json()
    a = (await client.post("/api/trades", json=PUT)).json()
    b = (await client.post("/api/trades", json={**PUT, "account_id": ira["id"]})).json()
    return ira, a, b


async def test_status_with_account_matches_only_that_account(client, default_account):
    ira, a, b = await two_accounts_holding_nvda(client, default_account)
    s = (await status(client, default_account.id))[SYMBOL]
    assert s["trade_id"] == a["id"]
    assert s["account"]["id"] == str(default_account.id)
    assert [m["trade_id"] for m in s["matches"]] == [a["id"]]

    s = (await status(client, ira["id"]))[SYMBOL]
    assert s["trade_id"] == b["id"]
    assert [m["account"]["nickname"] for m in s["matches"]] == ["IRA"]


async def test_status_with_account_ignores_other_accounts(client, default_account):
    ira = (await client.post("/api/accounts", json={"broker": "E*TRADE", "nickname": "IRA"})).json()
    await client.post("/api/trades", json={**PUT, "account_id": ira["id"]})
    s = (await status(client, default_account.id))[SYMBOL]
    assert s["trade_id"] is None and s["matches"] == [] and s["account"] is None


async def test_status_without_account_matches_every_account(client, default_account, db_session: AsyncSession, owner):
    ira, a, b = await two_accounts_holding_nvda(client, default_account)
    s = (await status(client))[SYMBOL]
    # No alerts: primary follows account order (default account first).
    assert s["trade_id"] == a["id"]
    assert [m["trade_id"] for m in s["matches"]] == [a["id"], b["id"]]
    assert [m["account"]["nickname"] for m in s["matches"]] == ["E*TRADE", "IRA"]

    # An urgent alert on the IRA trade makes it the primary match.
    db_session.add(Alert(user_id=owner.id, trade_id=uuid.UUID(b["id"]), alert_type="dte_threshold",
                         severity="urgent", title="t", message="m"))
    await db_session.commit()
    s = (await status(client))[SYMBOL]
    assert s["trade_id"] == b["id"] and s["alert_severity"] == "urgent"
    assert s["account"]["nickname"] == "IRA"
    assert [m["alert_severity"] for m in s["matches"]] == ["urgent", None]


async def test_all_view_lists_only_accounts_whose_trade_matches(client, default_account):
    """Matching runs per account: the default account's NVDA put at another strike is not a match."""
    ira = (await client.post("/api/accounts", json={"broker": "E*TRADE", "nickname": "IRA"})).json()
    await client.post("/api/trades", json={**PUT, "etrade_symbol": None, "strike_price": "100.00"})
    b = (await client.post("/api/trades", json={**PUT, "account_id": ira["id"]})).json()
    s = (await status(client))[SYMBOL]
    assert s["trade_id"] == b["id"]
    assert [m["account"]["nickname"] for m in s["matches"]] == ["IRA"]


async def test_status_with_foreign_or_unknown_account_is_404(client):
    resp = await client.post("/api/positions/status", json={"account_id": str(uuid.uuid4()), "positions": [ROW]})
    assert resp.status_code == 404


async def test_reconcile_requires_account(client):
    resp = await client.post("/api/positions/reconcile", json={"positions": [ROW]})
    assert resp.status_code == 422


async def test_reconcile_rejects_unknown_and_archived_accounts(client, default_account):
    resp = await client.post("/api/positions/reconcile", json={"account_id": str(uuid.uuid4()), "positions": []})
    assert resp.status_code == 404
    ira = (await client.post("/api/accounts", json={"broker": "E*TRADE", "nickname": "IRA"})).json()
    await client.post(f"/api/accounts/{ira['id']}/archive")
    resp = await client.post("/api/positions/reconcile", json={"account_id": ira["id"], "positions": []})
    assert resp.status_code == 404


async def test_reconcile_in_a_never_closes_b(client, default_account, db_session: AsyncSession):
    from app.models.trade import Trade
    ira, a, b = await two_accounts_holding_nvda(client, default_account)
    # A's snapshot no longer has NVDA → only A's trade is backdated.
    resp = await client.post("/api/positions/reconcile", json={"account_id": str(default_account.id), "positions": []})
    assert [s["id"] for s in resp.json()["stale_backend"]] == [a["id"]]
    db_session.expire_all()
    assert (await db_session.get(Trade, uuid.UUID(b["id"]))).last_etrade_seen is None
    # Unmatched rows are reported against A only: B's identical trade doesn't absorb them.
    resp = await client.post("/api/positions/reconcile", json={
        "account_id": str(default_account.id), "positions": [{**ROW, "full_symbol": "AMD--260919P00100000", "ticker": "AMD"}],
    })
    assert [u["ticker"] for u in resp.json()["unmatched_etrade"]] == ["AMD"]


async def test_active_slots_scoped_and_labelled(client, default_account):
    ira = (await client.post("/api/accounts", json={"broker": "E*TRADE", "nickname": "IRA"})).json()
    for account_id in (str(default_account.id), ira["id"]):
        wheel = (await client.post("/api/wheel", json={"ticker": "NVDA", "opened_at": str(date.today()), "account_id": account_id})).json()
        await client.post(f"/api/wheel/{wheel['id']}/slots", json={"status": "awaiting_sold_put"})
    all_slots = (await client.get("/api/wheel/active-slots")).json()
    assert sorted(s["account"]["nickname"] for s in all_slots) == ["E*TRADE", "IRA"]
    ira_slots = (await client.get(f"/api/wheel/active-slots?account_id={ira['id']}")).json()
    assert [s["account"]["nickname"] for s in ira_slots] == ["IRA"]
