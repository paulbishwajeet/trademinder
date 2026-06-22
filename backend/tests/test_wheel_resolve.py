import pytest
from httpx import AsyncClient
from datetime import date

SESSION_P = {"ticker": "NVDA", "total_shares": 100, "opened_at": str(date.today())}
CC_TRADE = {
    "type": "Sell", "category": "WHEEL", "strategy": "Covered Call",
    "ticker": "NVDA", "open_date": str(date.today()),
    "expiry_date": "2026-07-18", "strike_price": "150.00",
    "quantity": 1, "premium": "3.50",
}
PUT_TRADE = {
    "type": "Sell", "category": "WHEEL", "strategy": "Sell Put",
    "ticker": "NVDA", "open_date": str(date.today()),
    "expiry_date": "2026-07-18", "strike_price": "120.00",
    "quantity": 1, "premium": "2.00",
}
STOCK_TRADE = {
    "type": "Buy", "category": "WHEEL", "strategy": "Stock",
    "ticker": "NVDA", "open_date": str(date.today()),
    "quantity": 100, "premium": "0",
}


async def _setup_cc_active(client: AsyncClient):
    sess = await client.post("/api/wheel", json=SESSION_P)
    session_id = sess.json()["id"]
    slot = await client.post(f"/api/wheel/{session_id}/slots", json={"contracts": 1, "shares_held": 100, "status": "awaiting_cc"})
    slot_id = slot.json()["id"]
    trade = await client.post("/api/trades", json=CC_TRADE)
    trade_id = trade.json()["id"]
    await client.post(f"/api/wheel/slots/{slot_id}/legs", json={"trade_id": trade_id, "leg_role": "covered_call"})
    return session_id, slot_id, trade_id


async def _setup_put_active(client: AsyncClient):
    sess = await client.post("/api/wheel", json={**SESSION_P, "total_shares": 0})
    session_id = sess.json()["id"]
    slot = await client.post(f"/api/wheel/{session_id}/slots", json={"contracts": 1, "shares_held": 0, "status": "awaiting_sold_put"})
    slot_id = slot.json()["id"]
    trade = await client.post("/api/trades", json=PUT_TRADE)
    trade_id = trade.json()["id"]
    await client.post(f"/api/wheel/slots/{slot_id}/legs", json={"trade_id": trade_id, "leg_role": "sold_put"})
    return session_id, slot_id, trade_id


async def test_resolve_cc_expired_otm(client: AsyncClient):
    session_id, slot_id, _ = await _setup_cc_active(client)
    resp = await client.post(f"/api/wheel/slots/{slot_id}/resolve", json={"outcome": "cc_expired_otm"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "awaiting_cc"
    assert data["needs_action"] is False
    assert data["shares_held"] == 100
    assert data["rotation_number"] == 1


async def test_resolve_cc_expired_itm(client: AsyncClient):
    session_id, slot_id, _ = await _setup_cc_active(client)
    resp = await client.post(f"/api/wheel/slots/{slot_id}/resolve", json={"outcome": "cc_expired_itm"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "awaiting_sold_put"
    assert data["shares_held"] == 0
    assert data["rotation_number"] == 2


async def test_resolve_cc_expired_itm_reduces_session_shares(client: AsyncClient):
    session_id, slot_id, _ = await _setup_cc_active(client)
    await client.post(f"/api/wheel/slots/{slot_id}/resolve", json={"outcome": "cc_expired_itm"})
    sess = await client.get(f"/api/wheel/{session_id}")
    assert sess.json()["total_shares"] == 0


async def test_resolve_cc_bought_back(client: AsyncClient):
    session_id, slot_id, _ = await _setup_cc_active(client)
    resp = await client.post(f"/api/wheel/slots/{slot_id}/resolve", json={
        "outcome": "cc_bought_back", "buyback_cost": "1.50",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "awaiting_cc"
    detail = await client.get(f"/api/wheel/{session_id}")
    logs = detail.json()["slots"][0]["premium_logs"]
    buyback_log = [l for l in logs if l["event_type"] == "cc_bought_back"]
    assert len(buyback_log) == 1
    assert buyback_log[0]["premium_amount"] == "-1.50"


async def test_resolve_cc_rolled(client: AsyncClient):
    session_id, slot_id, _ = await _setup_cc_active(client)
    new_cc = await client.post("/api/trades", json={
        **CC_TRADE, "expiry_date": "2026-08-15", "strike_price": "155.00", "premium": "4.00",
    })
    new_trade_id = new_cc.json()["id"]
    resp = await client.post(f"/api/wheel/slots/{slot_id}/resolve", json={
        "outcome": "cc_rolled", "new_trade_id": new_trade_id, "buyback_cost": "2.00",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "cc_active"
    detail = await client.get(f"/api/wheel/{session_id}")
    logs = detail.json()["slots"][0]["premium_logs"]
    assert any(l["event_type"] == "cc_bought_back" for l in logs)
    assert any(l["event_type"] == "cc_sold" and l["premium_amount"] == "4.00" for l in logs)


async def test_resolve_put_expired_otm(client: AsyncClient):
    _, slot_id, _ = await _setup_put_active(client)
    resp = await client.post(f"/api/wheel/slots/{slot_id}/resolve", json={"outcome": "put_expired_otm"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "awaiting_sold_put"
    assert resp.json()["shares_held"] == 0


async def test_resolve_put_assigned(client: AsyncClient):
    session_id, slot_id, _ = await _setup_put_active(client)
    stock = await client.post("/api/trades", json=STOCK_TRADE)
    stock_id = stock.json()["id"]
    resp = await client.post(f"/api/wheel/slots/{slot_id}/resolve", json={
        "outcome": "put_assigned", "new_trade_id": stock_id,
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "awaiting_cc"
    assert resp.json()["shares_held"] == 100
    sess = await client.get(f"/api/wheel/{session_id}")
    assert sess.json()["total_shares"] == 100


async def test_resolve_put_bought_back(client: AsyncClient):
    _, slot_id, _ = await _setup_put_active(client)
    resp = await client.post(f"/api/wheel/slots/{slot_id}/resolve", json={
        "outcome": "put_bought_back", "buyback_cost": "0.80",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "awaiting_sold_put"


async def test_resolve_put_rolled(client: AsyncClient):
    _, slot_id, _ = await _setup_put_active(client)
    new_put = await client.post("/api/trades", json={
        **PUT_TRADE, "expiry_date": "2026-08-15", "strike_price": "115.00", "premium": "2.50",
    })
    new_trade_id = new_put.json()["id"]
    resp = await client.post(f"/api/wheel/slots/{slot_id}/resolve", json={
        "outcome": "put_rolled", "new_trade_id": new_trade_id, "buyback_cost": "1.00",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "sold_put_active"
