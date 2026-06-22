import pytest
from httpx import AsyncClient
from datetime import date

SESSION_PAYLOAD = {"ticker": "NVDA", "total_shares": 100, "opened_at": str(date.today())}
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


async def test_create_wheel_session(client: AsyncClient):
    resp = await client.post("/api/wheel", json=SESSION_PAYLOAD)
    assert resp.status_code == 201
    data = resp.json()
    assert data["ticker"] == "NVDA"
    assert data["total_shares"] == 100
    assert data["status"] == "active"


async def test_list_wheel_sessions(client: AsyncClient):
    await client.post("/api/wheel", json=SESSION_PAYLOAD)
    resp = await client.get("/api/wheel")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_get_wheel_session_detail(client: AsyncClient):
    create_resp = await client.post("/api/wheel", json=SESSION_PAYLOAD)
    session_id = create_resp.json()["id"]
    resp = await client.get(f"/api/wheel/{session_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["slots"] == []
    assert data["total_premium"] == "0"


async def test_get_wheel_session_not_found(client: AsyncClient):
    resp = await client.get("/api/wheel/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


async def test_close_wheel_session(client: AsyncClient):
    create_resp = await client.post("/api/wheel", json=SESSION_PAYLOAD)
    session_id = create_resp.json()["id"]
    resp = await client.patch(f"/api/wheel/{session_id}", json={"status": "closed", "closed_at": str(date.today())})
    assert resp.status_code == 200
    assert resp.json()["status"] == "closed"


async def test_add_slot(client: AsyncClient):
    create_resp = await client.post("/api/wheel", json=SESSION_PAYLOAD)
    session_id = create_resp.json()["id"]
    resp = await client.post(f"/api/wheel/{session_id}/slots", json={
        "contracts": 1, "shares_held": 100, "status": "awaiting_cc",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["slot_number"] == 1
    assert data["status"] == "awaiting_cc"
    assert data["contracts"] == 1


async def test_add_second_slot_increments_number(client: AsyncClient):
    create_resp = await client.post("/api/wheel", json=SESSION_PAYLOAD)
    session_id = create_resp.json()["id"]
    await client.post(f"/api/wheel/{session_id}/slots", json={"contracts": 1, "shares_held": 100, "status": "awaiting_cc"})
    resp = await client.post(f"/api/wheel/{session_id}/slots", json={"contracts": 1, "shares_held": 0, "status": "awaiting_sold_put"})
    assert resp.json()["slot_number"] == 2


async def test_link_leg_to_slot(client: AsyncClient):
    sess_resp = await client.post("/api/wheel", json=SESSION_PAYLOAD)
    session_id = sess_resp.json()["id"]
    slot_resp = await client.post(f"/api/wheel/{session_id}/slots", json={"contracts": 1, "shares_held": 100, "status": "awaiting_cc"})
    slot_id = slot_resp.json()["id"]
    trade_resp = await client.post("/api/trades", json=CC_TRADE)
    trade_id = trade_resp.json()["id"]
    link_resp = await client.post(f"/api/wheel/slots/{slot_id}/legs", json={
        "trade_id": trade_id, "leg_role": "covered_call",
    })
    assert link_resp.status_code == 201
    assert link_resp.json()["leg_role"] == "covered_call"
    assert link_resp.json()["trade_id"] == trade_id


async def test_link_leg_updates_slot_status_to_cc_active(client: AsyncClient):
    sess_resp = await client.post("/api/wheel", json=SESSION_PAYLOAD)
    session_id = sess_resp.json()["id"]
    slot_resp = await client.post(f"/api/wheel/{session_id}/slots", json={"contracts": 1, "shares_held": 100, "status": "awaiting_cc"})
    slot_id = slot_resp.json()["id"]
    trade_resp = await client.post("/api/trades", json=CC_TRADE)
    trade_id = trade_resp.json()["id"]
    await client.post(f"/api/wheel/slots/{slot_id}/legs", json={"trade_id": trade_id, "leg_role": "covered_call"})
    detail = await client.get(f"/api/wheel/{session_id}")
    assert detail.json()["slots"][0]["status"] == "cc_active"


async def test_link_sold_put_updates_slot_status(client: AsyncClient):
    sess_resp = await client.post("/api/wheel", json=SESSION_PAYLOAD)
    session_id = sess_resp.json()["id"]
    slot_resp = await client.post(f"/api/wheel/{session_id}/slots", json={"contracts": 1, "shares_held": 0, "status": "awaiting_sold_put"})
    slot_id = slot_resp.json()["id"]
    trade_resp = await client.post("/api/trades", json=PUT_TRADE)
    trade_id = trade_resp.json()["id"]
    await client.post(f"/api/wheel/slots/{slot_id}/legs", json={"trade_id": trade_id, "leg_role": "sold_put"})
    detail = await client.get(f"/api/wheel/{session_id}")
    assert detail.json()["slots"][0]["status"] == "sold_put_active"


async def test_link_leg_logs_premium(client: AsyncClient):
    sess_resp = await client.post("/api/wheel", json=SESSION_PAYLOAD)
    session_id = sess_resp.json()["id"]
    slot_resp = await client.post(f"/api/wheel/{session_id}/slots", json={"contracts": 1, "shares_held": 100, "status": "awaiting_cc"})
    slot_id = slot_resp.json()["id"]
    trade_resp = await client.post("/api/trades", json=CC_TRADE)
    trade_id = trade_resp.json()["id"]
    await client.post(f"/api/wheel/slots/{slot_id}/legs", json={"trade_id": trade_id, "leg_role": "covered_call"})
    detail = await client.get(f"/api/wheel/{session_id}")
    logs = detail.json()["slots"][0]["premium_logs"]
    assert len(logs) == 1
    assert logs[0]["event_type"] == "cc_sold"
    assert logs[0]["premium_amount"] == "3.50"


async def test_active_slots_endpoint(client: AsyncClient):
    sess_resp = await client.post("/api/wheel", json=SESSION_PAYLOAD)
    session_id = sess_resp.json()["id"]
    await client.post(f"/api/wheel/{session_id}/slots", json={"contracts": 1, "shares_held": 100, "status": "awaiting_cc"})
    resp = await client.get("/api/wheel/active-slots")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["ticker"] == "NVDA"
