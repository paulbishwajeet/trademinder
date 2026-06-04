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

# Used in Task 3 tests (test_create_trade_with_session_id etc.)
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


async def test_create_session_invalid_parent(client: AsyncClient):
    response = await client.post("/api/sessions", json={
        **SESSION_PAYLOAD,
        "parent_session_id": "00000000-0000-0000-0000-000000000000",
    })
    assert response.status_code == 404


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


async def test_create_trade_with_session_id(client: AsyncClient):
    session_resp = await client.post("/api/sessions", json=SESSION_PAYLOAD)
    session_id = session_resp.json()["id"]

    response = await client.post("/api/trades", json={**TRADE_PAYLOAD, "session_id": session_id})
    assert response.status_code == 201
    assert response.json()["session_id"] == session_id


async def test_create_trade_without_session_id_is_null(client: AsyncClient):
    response = await client.post("/api/trades", json=TRADE_PAYLOAD)
    assert response.status_code == 201
    assert response.json()["session_id"] is None


async def test_patch_trade_links_session(client: AsyncClient):
    session_resp = await client.post("/api/sessions", json=SESSION_PAYLOAD)
    session_id = session_resp.json()["id"]

    trade_resp = await client.post("/api/trades", json=TRADE_PAYLOAD)
    trade_id = trade_resp.json()["id"]

    patch_resp = await client.patch(f"/api/trades/{trade_id}", json={"session_id": session_id})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["session_id"] == session_id


async def test_get_session_includes_linked_trade(client: AsyncClient):
    session_resp = await client.post("/api/sessions", json=SESSION_PAYLOAD)
    session_id = session_resp.json()["id"]

    await client.post("/api/trades", json={**TRADE_PAYLOAD, "session_id": session_id})

    response = await client.get(f"/api/sessions/{session_id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data["legs"]) == 1
    assert data["legs"][0]["ticker"] == "NVDA"
    assert data["legs"][0]["strategy"] == "Sell Put"


async def test_session_lookup_no_strategy_returns_all_strategies(client: AsyncClient):
    """Omitting strategy= returns sessions across all strategies for the ticker."""
    await client.post("/api/sessions", json=SESSION_PAYLOAD)  # WHEEL put_open
    await client.post("/api/sessions", json={
        **SESSION_PAYLOAD,
        "strategy": "IRON_CONDOR",
        "status": "open",
    })
    response = await client.get("/api/sessions/lookup?ticker=NVDA")
    assert response.status_code == 200
    data = response.json()
    assert data["has_existing"] is True
    assert data["strategy"] is None   # strategy=None when no filter applied
    assert len(data["sessions"]) == 2


async def test_session_lookup_excludes_closed(client: AsyncClient):
    """Lookup does not return sessions with status='closed'."""
    await client.post("/api/sessions", json={
        **SESSION_PAYLOAD,
        "strategy": "IRON_CONDOR",
        "status": "closed",
    })
    response = await client.get("/api/sessions/lookup?ticker=NVDA")
    assert response.status_code == 200
    assert response.json()["has_existing"] is False


async def test_session_lookup_includes_legs(client: AsyncClient):
    """Lookup response embeds linked trade legs in each session."""
    session_resp = await client.post("/api/sessions", json={
        **SESSION_PAYLOAD,
        "strategy": "IRON_CONDOR",
        "status": "open",
    })
    session_id = session_resp.json()["id"]
    await client.post("/api/trades", json={**TRADE_PAYLOAD, "session_id": session_id})

    response = await client.get("/api/sessions/lookup?ticker=NVDA&strategy=IRON_CONDOR")
    assert response.status_code == 200
    data = response.json()
    assert len(data["sessions"]) == 1
    assert len(data["sessions"][0]["legs"]) == 1
    assert data["sessions"][0]["legs"][0]["strike_price"] == "120.00"
