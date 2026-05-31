# backend/tests/test_sessions.py
import pytest
from httpx import AsyncClient
from datetime import date

SESSION_PAYLOAD = {
    "ticker": "NVDA",
    "strategy": "WHEEL",
    "status": "put_open",
    "opened_at": str(date.today()),
}

TRADE_PAYLOAD = {
    "type": "Sell",
    "category": "WHEEL",
    "strategy": "Sell Put",
    "ticker": "NVDA",
    "open_date": str(date.today()),
    "expiry_date": "2026-06-20",
    "strike_price": "120.00",
    "quantity": 1,
    "premium": "2.50",
}


async def test_create_session(client: AsyncClient):
    response = await client.post("/api/sessions", json=SESSION_PAYLOAD)
    assert response.status_code == 201
    data = response.json()
    assert data["ticker"] == "NVDA"
    assert data["status"] == "put_open"
    assert data["rotation_number"] == 1
    assert data["parent_session_id"] is None


async def test_list_sessions_empty(client: AsyncClient):
    response = await client.get("/api/sessions")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_sessions_filters_by_strategy(client: AsyncClient):
    await client.post("/api/sessions", json=SESSION_PAYLOAD)
    response = await client.get("/api/sessions?strategy=WHEEL")
    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_list_sessions_filters_by_ticker(client: AsyncClient):
    await client.post("/api/sessions", json=SESSION_PAYLOAD)
    await client.post("/api/sessions", json={**SESSION_PAYLOAD, "ticker": "AAPL"})
    response = await client.get("/api/sessions?ticker=NVDA")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["ticker"] == "NVDA"


async def test_get_session_not_found(client: AsyncClient):
    response = await client.get("/api/sessions/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


async def test_get_session_with_no_legs(client: AsyncClient):
    session_resp = await client.post("/api/sessions", json=SESSION_PAYLOAD)
    session_id = session_resp.json()["id"]
    response = await client.get(f"/api/sessions/{session_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == session_id
    assert data["legs"] == []
    assert data["rotation_chain"] == []


async def test_patch_session_status(client: AsyncClient):
    session_resp = await client.post("/api/sessions", json=SESSION_PAYLOAD)
    session_id = session_resp.json()["id"]
    response = await client.patch(f"/api/sessions/{session_id}", json={"status": "shares_sitting"})
    assert response.status_code == 200
    assert response.json()["status"] == "shares_sitting"


async def test_patch_session_not_found(client: AsyncClient):
    response = await client.patch(
        "/api/sessions/00000000-0000-0000-0000-000000000000",
        json={"status": "shares_sitting"},
    )
    assert response.status_code == 404


async def test_session_lookup_no_existing(client: AsyncClient):
    response = await client.get("/api/sessions/lookup?ticker=NVDA&strategy=WHEEL")
    assert response.status_code == 200
    data = response.json()
    assert data["has_existing"] is False
    assert data["sessions"] == []


async def test_session_lookup_with_existing(client: AsyncClient):
    await client.post("/api/sessions", json=SESSION_PAYLOAD)
    response = await client.get("/api/sessions/lookup?ticker=NVDA&strategy=WHEEL")
    assert response.status_code == 200
    data = response.json()
    assert data["has_existing"] is True
    assert len(data["sessions"]) == 1


async def test_session_lookup_excludes_completed(client: AsyncClient):
    await client.post("/api/sessions", json={**SESSION_PAYLOAD, "status": "completed"})
    response = await client.get("/api/sessions/lookup?ticker=NVDA&strategy=WHEEL")
    assert response.status_code == 200
    assert response.json()["has_existing"] is False


async def test_rotation_chain(client: AsyncClient):
    parent_resp = await client.post("/api/sessions", json={**SESSION_PAYLOAD, "status": "completed"})
    parent_id = parent_resp.json()["id"]

    child_resp = await client.post("/api/sessions", json={
        **SESSION_PAYLOAD,
        "status": "put_open",
        "rotation_number": 2,
        "parent_session_id": parent_id,
    })
    child_id = child_resp.json()["id"]

    response = await client.get(f"/api/sessions/{child_id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data["rotation_chain"]) == 1
    assert data["rotation_chain"][0]["id"] == parent_id
    assert data["rotation_chain"][0]["rotation_number"] == 1
