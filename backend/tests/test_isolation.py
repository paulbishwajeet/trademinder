"""A second user must see nothing of the owner's data — through services and through routers.
Foreign ids are always 404 (never 403), indistinguishable from ids that don't exist."""
import uuid
from datetime import date

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert
from app.services import ownership, accounts as accounts_service
from app.schemas.account import AccountUpdate
from tests.conftest import make_user_with_account

PUT_TRADE = {
    "type": "Sell", "category": "WHEEL", "strategy": "Put", "ticker": "NVDA",
    "open_date": str(date.today()), "expiry_date": "2026-12-18", "strike_price": "120.00",
    "quantity": 1, "premium": "3.00", "etrade_symbol": "NVDA--261218P00120000",
}
PRECOMPUTED = {"price": "100.00", "fetch_status": "ok"}


@pytest_asyncio.fixture
async def other():
    return await make_user_with_account("b@test.local", nickname="B Brokerage")


@pytest_asyncio.fixture
async def owner_data(client: AsyncClient, db_session: AsyncSession, owner, default_account):
    """One of everything, created by the owner."""
    cat = (await client.post("/api/categories", json={"name": "OWNERCAT"})).json()
    trade = (await client.post("/api/trades", json=PUT_TRADE)).json()
    comment = (await client.post(f"/api/trades/{trade['id']}/commentary", json={"note": "owner note"})).json()
    wheel = (await client.post("/api/wheel", json={"ticker": "NVDA", "opened_at": str(date.today())})).json()
    slot = (await client.post(f"/api/wheel/{wheel['id']}/slots", json={"status": "awaiting_sold_put"})).json()
    await client.post(f"/api/wheel/slots/{slot['id']}/legs", json={"trade_id": trade["id"], "leg_role": "sold_put"})
    spread = (await client.post("/api/sessions", json={
        "ticker": "SPY", "strategy": "IRON_CONDOR", "status": "open", "opened_at": str(date.today()),
    })).json()
    screener = (await client.post("/api/screener", json={"symbol": "AAPL", "precomputed": PRECOMPUTED})).json()
    note = (await client.post("/api/screener/AAPL/commentary", json={"note": "taxable: hold"})).json()

    alert = Alert(user_id=owner.id, trade_id=uuid.UUID(trade["id"]), alert_type="dte_threshold",
                  severity="warning", title="t", message="m")
    db_session.add(alert)
    await db_session.commit()

    return {
        "category": cat, "trade": trade, "comment": comment, "wheel": wheel, "slot": slot,
        "spread": spread, "screener": screener, "note": note, "alert_id": str(alert.id),
        "account_id": str(default_account.id),
    }


# ── services ────────────────────────────────────────────────────────────────

async def test_services_hide_owner_rows_from_other_user(db_session, owner_data, other):
    user_b, _ = other
    d = owner_data
    lookups = [
        ownership.get_trade(db_session, user_b, uuid.UUID(d["trade"]["id"])),
        ownership.get_wheel_session(db_session, user_b, uuid.UUID(d["wheel"]["id"])),
        ownership.get_slot(db_session, user_b, uuid.UUID(d["slot"]["id"])),
        ownership.get_trade_session(db_session, user_b, uuid.UUID(d["spread"]["id"])),
        ownership.get_category(db_session, user_b, uuid.UUID(d["category"]["id"])),
        ownership.get_alert(db_session, user_b, uuid.UUID(d["alert_id"])),
        ownership.get_commentary(db_session, user_b, uuid.UUID(d["comment"]["id"])),
        ownership.get_screener_commentary(db_session, user_b, uuid.UUID(d["note"]["id"])),
        ownership.get_screener_row(db_session, user_b, "AAPL"),
        ownership.get_account(db_session, user_b, uuid.UUID(d["account_id"])),
        ownership.resolve_account(db_session, user_b, uuid.UUID(d["account_id"])),
        ownership.resolve_account_filter(db_session, user_b, uuid.UUID(d["account_id"])),
        accounts_service.update_account(db_session, user_b, uuid.UUID(d["account_id"]), AccountUpdate(nickname="x")),
        accounts_service.archive_account(db_session, user_b, uuid.UUID(d["account_id"])),
    ]
    for coro in lookups:
        with pytest.raises(HTTPException) as exc:
            await coro
        assert exc.value.status_code == 404


async def test_service_lists_exclude_owner_rows(db_session, owner_data, other):
    user_b, account_b = other
    accounts = await accounts_service.list_accounts(db_session, user_b, include_archived=True)
    assert [a.id for a in accounts] == [account_b.id]
    assert (await ownership.get_default_account(db_session, user_b)).id == account_b.id


# ── routers: lists return nothing ───────────────────────────────────────────

async def test_lists_are_empty_for_other_user(client, owner_data, other, act_as):
    act_as(other[0])
    d = owner_data
    for url in [
        "/api/trades", "/api/trades?stale=true", f"/api/trades/wheel/{uuid.uuid4()}",
        "/api/wheel", "/api/wheel/active-slots", "/api/sessions?strategy=", "/api/sessions/active",
        "/api/categories", "/api/screener", "/api/alerts", "/api/dashboard/today",
        f"/api/trades/{d['trade']['id']}/commentary", f"/api/trades/{d['trade']['id']}/signals",
        f"/api/alerts/trade/{d['trade']['id']}",
    ]:
        resp = await client.get(url)
        assert resp.status_code == 200, url
        assert resp.json() == [], url

    lookup = (await client.get("/api/sessions/lookup?ticker=SPY")).json()
    assert lookup["has_existing"] is False
    account_ids = [a["id"] for a in (await client.get("/api/accounts?include_archived=true")).json()]
    assert account_ids == [str(other[1].id)]


# ── routers: foreign ids are 404 ────────────────────────────────────────────

async def test_foreign_ids_are_404(client, owner_data, other, act_as):
    act_as(other[0])
    d = owner_data
    t, w, s, sp = d["trade"]["id"], d["wheel"]["id"], d["slot"]["id"], d["spread"]["id"]
    acct = d["account_id"]
    calls = [
        ("GET", f"/api/trades/{t}", None),
        ("PATCH", f"/api/trades/{t}", {"premium": "1.00"}),
        ("POST", f"/api/trades/{t}/close", {}),
        ("PATCH", f"/api/trades/{t}/category", {"category_id": None}),
        ("PUT", f"/api/trades/{t}/rationale", {"notes": "x"}),
        ("POST", f"/api/trades/{t}/commentary", {"note": "x"}),
        ("GET", f"/api/trades/{t}/commentary/summary", None),
        ("DELETE", f"/api/trades/{t}", None),
        ("DELETE", f"/api/commentary/{d['comment']['id']}", None),
        ("GET", f"/api/wheel/{w}", None),
        ("PATCH", f"/api/wheel/{w}", {"total_shares": 1}),
        ("POST", f"/api/wheel/{w}/slots", {"status": "awaiting_sold_put"}),
        ("PATCH", f"/api/wheel/slots/{s}", {"contracts": 2}),
        ("POST", f"/api/wheel/slots/{s}/legs", {"trade_id": t, "leg_role": "sold_put"}),
        ("POST", f"/api/wheel/slots/{s}/resolve", {"outcome": "put_expired_otm"}),
        ("POST", f"/api/wheel/slots/{s}/commentary", {"note": "x"}),
        ("GET", f"/api/wheel/slots/{s}/history", None),
        ("DELETE", f"/api/wheel/slots/{s}", None),
        ("GET", f"/api/sessions/{sp}", None),
        ("PATCH", f"/api/sessions/{sp}", {"status": "closed"}),
        ("POST", "/api/sessions", {"ticker": "SPY", "strategy": "IRON_CONDOR", "status": "open",
                                   "opened_at": str(date.today()), "parent_session_id": sp}),
        ("PATCH", f"/api/categories/{d['category']['id']}", {"color": "#000000"}),
        ("DELETE", f"/api/categories/{d['category']['id']}", None),
        ("POST", f"/api/alerts/{d['alert_id']}/read", None),
        ("POST", f"/api/alerts/{d['alert_id']}/dismiss", None),
        ("POST", f"/api/alerts/{d['alert_id']}/snooze", {"hours": 1}),
        ("GET", "/api/screener/AAPL/commentary", None),
        ("POST", "/api/screener/AAPL/commentary", {"note": "x"}),
        ("PUT", f"/api/screener/commentary/{d['note']['id']}", {"note": "x"}),
        ("DELETE", f"/api/screener/commentary/{d['note']['id']}", None),
        ("PATCH", "/api/screener/AAPL", {"category": "x"}),
        ("POST", "/api/screener/AAPL/fetch", None),
        ("DELETE", "/api/screener/AAPL", None),
        ("PATCH", f"/api/accounts/{acct}", {"nickname": "stolen"}),
        ("PUT", f"/api/accounts/{acct}/categories", {"category_ids": []}),
        ("POST", f"/api/accounts/{acct}/archive", None),
        ("DELETE", f"/api/accounts/{acct}", None),
        # account resolution: naming another user's account is a 404, for lists and writes
        ("GET", f"/api/trades?account_id={acct}", None),
        ("GET", f"/api/wheel?account_id={acct}", None),
        ("GET", f"/api/wheel/active-slots?account_id={acct}", None),
        ("GET", f"/api/sessions?account_id={acct}", None),
        ("GET", f"/api/screener?account_id={acct}", None),
        ("POST", "/api/trades", {**PUT_TRADE, "account_id": acct}),
        ("POST", "/api/wheel", {"ticker": "X", "opened_at": str(date.today()), "account_id": acct}),
        ("POST", "/api/sessions", {"ticker": "X", "strategy": "IRON_CONDOR", "status": "open",
                                   "opened_at": str(date.today()), "account_id": acct}),
        ("POST", "/api/screener", {"symbol": "MSFT", "precomputed": PRECOMPUTED, "account_id": acct}),
    ]
    for method, url, body in calls:
        resp = await client.request(method, url, json=body)
        assert resp.status_code == 404, (method, url, resp.status_code, resp.text)


async def test_other_user_cannot_attach_owner_rows_to_their_own(client, owner_data, other, act_as):
    act_as(other[0])
    d = owner_data
    my_wheel = (await client.post("/api/wheel", json={"ticker": "NVDA", "opened_at": str(date.today())})).json()
    my_slot = (await client.post(f"/api/wheel/{my_wheel['id']}/slots", json={"status": "awaiting_sold_put"})).json()
    resp = await client.post(f"/api/wheel/slots/{my_slot['id']}/legs",
                             json={"trade_id": d["trade"]["id"], "leg_role": "sold_put"})
    assert resp.status_code == 404

    resp = await client.post("/api/trades", json={**PUT_TRADE, "session_id": d["spread"]["id"]})
    assert resp.status_code == 404

    my_trade = (await client.post("/api/trades", json=PUT_TRADE)).json()
    resp = await client.patch(f"/api/trades/{my_trade['id']}/category", json={"category_id": d["category"]["id"]})
    assert resp.status_code == 404


async def test_other_user_gets_independent_copies(client, owner_data, other, act_as):
    """Same category name / screener symbol / wheel ticker are allowed per user and never shared."""
    act_as(other[0])
    assert (await client.post("/api/categories", json={"name": "OWNERCAT"})).status_code == 201
    resp = await client.post("/api/screener", json={"symbol": "AAPL", "precomputed": PRECOMPUTED})
    assert resp.status_code == 201
    assert resp.json()["id"] != owner_data["screener"]["id"]
    assert (await client.get("/api/screener/AAPL/commentary")).json() == []


async def test_extension_endpoints_are_scoped_to_user(client, owner_data, other, act_as, db_session):
    act_as(other[0])
    status = (await client.post("/api/positions/status", json={"positions": [
        {"ticker": "NVDA", "full_symbol": PUT_TRADE["etrade_symbol"], "type": "Put"},
    ]})).json()
    assert status[PUT_TRADE["etrade_symbol"]]["trade_id"] is None

    resp = await client.post("/api/positions/reconcile", json={"positions": []})
    assert resp.status_code == 200
    assert resp.json()["stale_backend"] == []

    from app.models.trade import Trade
    db_session.expire_all()
    owner_trade = await db_session.get(Trade, uuid.UUID(owner_data["trade"]["id"]))
    assert owner_trade.last_etrade_seen is None  # B's reconcile never touched the owner's trade


async def test_screener_job_status_is_owner_only(client, owner_data, other, act_as, monkeypatch):
    import app.routers.screener as screener_router

    async def _noop(*args, **kwargs):
        return None
    monkeypatch.setattr(screener_router, "_run_fetch_all_job", _noop)
    job = (await client.post("/api/screener/fetch-all")).json()
    assert job["total"] == 1
    assert (await client.get(f"/api/screener/jobs/{job['job_id']}")).status_code == 200
    act_as(other[0])
    assert (await client.get(f"/api/screener/jobs/{job['job_id']}")).status_code == 404


async def test_commentary_summary_cache_does_not_leak(client, owner, owner_data, other, act_as):
    import app.routers.commentary as commentary_router
    from datetime import datetime, timezone
    trade_id = owner_data["trade"]["id"]
    # Prime the cache as if the owner had generated a summary.
    commentary_router._summary_cache.clear()
    commentary_router._summary_cache[f"{owner.id}:{trade_id}"] = (
        "secret summary", [], datetime.now(timezone.utc),
    )
    act_as(other[0])
    resp = await client.get(f"/api/trades/{trade_id}/commentary/summary")
    assert resp.status_code == 404
    assert "secret" not in resp.text
