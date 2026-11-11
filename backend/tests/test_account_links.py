"""Part 3: E*TRADE account links (fingerprint ↔ brokerage account)."""
import hashlib

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from tests.conftest import make_user_with_account


def fp(number: str) -> str:
    """Same fingerprint the extension's service worker computes."""
    return hashlib.sha256(f"E*TRADE:{number}".encode()).hexdigest()


FP_A = fp("111111020")
FP_B = fp("222221020")  # same last four, different account
LABEL_A = "Individual Brokerage -1020"
LABEL_B = "Stock Plan (AVGO) -1020"


async def resolve(client: AsyncClient, fingerprint: str, label: str | None = None) -> dict:
    body = {"fingerprint": fingerprint, **({"label": label} if label else {})}
    resp = await client.post("/api/accounts/links/resolve", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def link(client: AsyncClient, account_id, fingerprint: str = FP_A, label: str = LABEL_A):
    return await client.post(f"/api/accounts/{account_id}/link", json={"fingerprint": fingerprint, "label": label})


async def create_linked(client: AsyncClient, fingerprint: str = FP_B, label: str = LABEL_B, nickname: str = "Stock Plan (AVGO)"):
    return await client.post("/api/accounts/links", json={
        "fingerprint": fingerprint, "label": label,
        "account": {"broker": "E*TRADE", "nickname": nickname, "last_four": "1020"},
    })


@pytest_asyncio.fixture
async def other():
    return await make_user_with_account("b@test.local", nickname="B")


async def test_unknown_fingerprint_is_unlinked(client):
    assert await resolve(client, FP_A, LABEL_A) == {"linked": False, "account": None, "is_archived": False}


async def test_link_existing_then_resolve(client, default_account):
    resp = await link(client, default_account.id)
    assert resp.status_code == 200
    body = resp.json()
    assert body["link"]["label"] == LABEL_A
    assert body["link"]["last_seen_at"] is not None
    assert "external_ref" not in body  # the fingerprint is never returned

    resolved = await resolve(client, FP_A, "Individual Brokerage (renamed) -1020")
    assert resolved["linked"] is True
    assert resolved["account"]["id"] == str(default_account.id)
    # Resolve refreshes the last label seen.
    listed = (await client.get("/api/accounts")).json()
    assert listed[0]["link"]["label"] == "Individual Brokerage (renamed) -1020"


async def test_relinking_same_pair_is_idempotent(client, default_account):
    assert (await link(client, default_account.id)).status_code == 200
    assert (await link(client, default_account.id)).status_code == 200


async def test_account_already_linked_elsewhere_is_rejected(client, default_account):
    await link(client, default_account.id, FP_A)
    resp = await link(client, default_account.id, FP_B, LABEL_B)
    assert resp.status_code == 409
    assert "already linked" in resp.json()["detail"]


async def test_fingerprint_already_linked_elsewhere_is_rejected(client, default_account):
    await link(client, default_account.id, FP_A)
    ira = (await client.post("/api/accounts", json={"broker": "E*TRADE", "nickname": "IRA"})).json()
    resp = await link(client, ira["id"], FP_A)
    assert resp.status_code == 409
    resp = await create_linked(client, FP_A, LABEL_A)
    assert resp.status_code == 409
    # The failed create-and-link left no account behind.
    assert [a["nickname"] for a in (await client.get("/api/accounts")).json()] == ["E*TRADE", "IRA"]


async def test_two_accounts_sharing_last_four_link_separately(client, default_account):
    await link(client, default_account.id, FP_A, LABEL_A)
    resp = await create_linked(client, FP_B, LABEL_B)
    assert resp.status_code == 201
    created = resp.json()
    assert created["nickname"] == "Stock Plan (AVGO)" and created["last_four"] == "1020"
    assert created["link"]["label"] == LABEL_B
    assert (await resolve(client, FP_A))["account"]["id"] == str(default_account.id)
    assert (await resolve(client, FP_B))["account"]["id"] == created["id"]


async def test_unlink_frees_both_sides(client, default_account):
    await link(client, default_account.id, FP_A)
    resp = await client.delete(f"/api/accounts/{default_account.id}/link")
    assert resp.status_code == 200 and resp.json()["link"] is None
    assert (await resolve(client, FP_A))["linked"] is False
    ira = (await client.post("/api/accounts", json={"broker": "E*TRADE", "nickname": "IRA"})).json()
    assert (await link(client, ira["id"], FP_A)).status_code == 200


async def test_archived_link_is_reported(client, default_account):
    ira = (await create_linked(client)).json()
    await client.post(f"/api/accounts/{ira['id']}/archive")
    resolved = await resolve(client, FP_B)
    assert resolved["linked"] is True and resolved["is_archived"] is True


async def test_fingerprints_are_unique_per_user_not_globally(client, default_account, other, act_as):
    await link(client, default_account.id, FP_A)
    act_as(other[0])
    # B can't see the owner's link …
    assert (await resolve(client, FP_A))["linked"] is False
    # … and may link the same E*TRADE account (e.g. a joint account) to their own account.
    assert (await link(client, other[1].id, FP_A)).status_code == 200
    assert (await resolve(client, FP_A))["account"]["id"] == str(other[1].id)
    # B can't link or unlink the owner's account.
    assert (await link(client, default_account.id, FP_B)).status_code == 404
    assert (await client.delete(f"/api/accounts/{default_account.id}/link")).status_code == 404


@pytest.mark.parametrize("bad", ["123456789", "A" * 64, fp("1")[:63], "e*trade:123456789"])
async def test_non_fingerprints_are_rejected(client, default_account, bad):
    assert (await link(client, default_account.id, bad)).status_code == 422
    assert (await client.post("/api/accounts/links/resolve", json={"fingerprint": bad})).status_code == 422


async def test_label_with_account_number_is_rejected(client, default_account):
    resp = await link(client, default_account.id, FP_A, "Individual Brokerage 123451020")
    assert resp.status_code == 422


async def test_db_refuses_a_raw_account_number(db_session, default_account):
    from sqlalchemy.exc import IntegrityError
    from app.models.brokerage_account import BrokerageAccount
    account = (await db_session.execute(
        select(BrokerageAccount).where(BrokerageAccount.id == default_account.id)
    )).scalar_one()
    account.external_ref = "123451020"
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
