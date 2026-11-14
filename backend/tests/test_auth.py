"""Part 5: Google sign-in, sessions, extension tokens, admin, and the auth boundary."""
import re
import urllib.parse
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import settings
from app.models.auth import ExtensionToken, UserSession
from app.models.user import User
from app.services import auth as auth_service
from app.services import google_oidc
from tests.conftest import make_user_with_account, session_token_for

EXT_ID = "abcdefghijklmnopabcdefghijklmnop"  # 32 chars a–p, like a real Chrome extension id
EXT_REDIRECT = f"https://{EXT_ID}.chromiumapp.org/"
TRADE = {"type": "Buy", "category": "WHEEL", "strategy": "Stock", "ticker": "AAPL",
         "open_date": str(date.today()), "quantity": 100}


@pytest.fixture(autouse=True)
def google_configured(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "test-client.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_client_secret", "test-secret")
    monkeypatch.setattr(settings, "extension_ids", EXT_ID)


async def google_sign_in(anon_client, monkeypatch, sub, email, verified=True, name="Someone", nonce=None):
    """Drive the real login → callback flow; Google's token endpoint and ID-token check are mocked."""
    start = await anon_client.get("/api/auth/google/login", params={"next": "/accounts"})
    assert start.status_code == 302
    query = urllib.parse.parse_qs(urllib.parse.urlparse(start.headers["location"]).query)
    assert query["scope"] == ["openid email profile"] and query["code_challenge_method"] == ["S256"]
    saved = auth_service.read_state(anon_client.cookies.get(auth_service.LOGIN_STATE_COOKIE))

    async def fake_exchange(code, verifier):
        assert verifier == saved["verifier"]
        return "fake-id-token"

    monkeypatch.setattr(google_oidc, "exchange_code", fake_exchange)
    monkeypatch.setattr(google_oidc, "verify_id_token", lambda tok: {
        "iss": "https://accounts.google.com", "sub": sub, "email": email, "email_verified": verified,
        "name": name, "nonce": nonce if nonce is not None else saved["nonce"],
    })
    return await anon_client.get("/api/auth/google/callback", params={"code": "c", "state": query["state"][0]})


# ── sign-in rules ───────────────────────────────────────────────────────────

async def test_owner_first_sign_in_binds_subject_and_keeps_data(client, anon_client, owner, db_session, monkeypatch):
    trade = (await client.post("/api/trades", json=TRADE)).json()
    resp = await google_sign_in(anon_client, monkeypatch, "google-sub-owner", "OWNER@test.local")
    assert resp.status_code == 302 and resp.headers["location"] == "/accounts"
    assert "httponly" in resp.headers["set-cookie"].lower() and "samesite=lax" in resp.headers["set-cookie"].lower()

    db_session.expire_all()
    row = await db_session.get(User, owner.id)
    assert row.external_subject == "google-sub-owner" and row.last_login_at is not None
    assert [t["id"] for t in (await anon_client.get("/api/trades")).json()] == [trade["id"]]
    me = (await anon_client.get("/api/me")).json()
    assert me["id"] == str(owner.id) and me["role"] == "admin" and me["status"] == "active"

    # A different Google account with the same email never takes over the row.
    anon_client.cookies.clear()
    again = await google_sign_in(anon_client, monkeypatch, "another-sub", "owner@test.local")
    assert again.headers["location"] == "/signin?error=email_linked_to_another_google_account"


async def test_invited_user_active_on_first_sign_in(client, anon_client, monkeypatch):
    invited = await client.post("/api/admin/users/invite", json={"email": "pilot@gmail.com"})
    assert invited.status_code == 201 and invited.json()["status"] == "active"
    resp = await google_sign_in(anon_client, monkeypatch, "sub-pilot", "pilot@gmail.com", name="Pilot")
    assert resp.headers["location"] == "/accounts"
    me = (await anon_client.get("/api/me")).json()
    assert me["status"] == "active" and me["display_name"] == "Pilot"
    assert len((await anon_client.get("/api/categories")).json()) == 12  # default library seeded
    assert (await anon_client.get("/api/trades")).json() == []            # an empty app


async def test_unknown_user_is_pending_and_blocked(anon_client, monkeypatch):
    resp = await google_sign_in(anon_client, monkeypatch, "sub-stranger", "stranger@gmail.com")
    assert resp.headers["location"] == "/waiting"
    assert (await anon_client.get("/api/me")).json()["status"] == "pending"
    for path in ("/api/trades", "/api/accounts", "/api/wheel", "/api/screener", "/api/dashboard/summary"):
        r = await anon_client.get(path)
        assert r.status_code == 403 and r.json()["detail"] == "Waiting for approval", path


async def test_rejected_login_cases(anon_client, monkeypatch):
    r = await google_sign_in(anon_client, monkeypatch, "s1", "x@gmail.com", verified=False)
    assert r.headers["location"] == "/signin?error=email_not_verified"
    r = await google_sign_in(anon_client, monkeypatch, "s2", "y@gmail.com", nonce="wrong")
    assert r.headers["location"] == "/signin?error=nonce_mismatch"
    r = await anon_client.get("/api/auth/google/callback", params={"code": "c", "state": "forged"})
    assert r.headers["location"] == "/signin?error=invalid_state"
    assert "tm_session" not in anon_client.cookies


async def test_disabled_user_refused_at_sign_in(anon_client, monkeypatch):
    user, _ = await make_user_with_account("gone@gmail.com", status="disabled")
    r = await google_sign_in(anon_client, monkeypatch, "sub-gone", "gone@gmail.com")
    assert r.headers["location"] == "/signin?error=disabled"


def test_safe_next_blocks_open_redirects():
    assert auth_service.safe_next("/wheel?x=1") == "/wheel?x=1"
    for bad in (None, "", "https://evil.com", "//evil.com", "/\\evil.com", "evil"):
        assert auth_service.safe_next(bad) == "/"


# ── sessions ────────────────────────────────────────────────────────────────

async def test_logout_ends_the_session(anon_client, monkeypatch):
    await google_sign_in(anon_client, monkeypatch, "sub-l", "l@gmail.com")
    token = anon_client.cookies.get("tm_session")
    assert (await anon_client.post("/api/auth/logout")).status_code == 204
    anon_client.cookies.set("tm_session", token)  # replay the old cookie
    assert (await anon_client.get("/api/me")).status_code == 401


async def test_session_slides_and_expires(anon_client, db_session, owner):
    token = await session_token_for(owner)
    row = await db_session.get(UserSession, auth_service.hash_token(token))
    row.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    row.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    await db_session.commit()

    resp = await anon_client.get("/api/me", headers={"cookie": f"tm_session={token}"})
    assert resp.status_code == 200
    assert "max-age=2592000" in resp.headers["set-cookie"].lower()  # cookie re-issued for 30 days
    db_session.expire_all()
    row = await db_session.get(UserSession, auth_service.hash_token(token))
    assert row.expires_at > datetime.now(timezone.utc) + timedelta(days=29)

    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.commit()
    assert (await anon_client.get("/api/me", headers={"cookie": f"tm_session={token}"})).status_code == 401
    db_session.expire_all()
    assert await db_session.get(UserSession, auth_service.hash_token(token)) is None


async def test_only_the_hash_is_stored(owner, db_session):
    token = await session_token_for(owner)
    hashes = (await db_session.execute(select(UserSession.token_hash))).scalars().all()
    assert token not in hashes and auth_service.hash_token(token) in hashes


# ── extension tokens ────────────────────────────────────────────────────────

async def connect(client, redirect=EXT_REDIRECT, name="Work laptop"):
    return await client.post("/api/extension/connect", json={"redirect_uri": redirect, "device_name": name})


@pytest.mark.parametrize("redirect", [
    "https://ponmlkjihgfedcbaponmlkjihgfedcba.chromiumapp.org/",   # not allow-listed
    f"http://{EXT_ID}.chromiumapp.org/",                           # not https
    f"https://{EXT_ID}.chromiumapp.org/callback",                  # extra path
    f"https://{EXT_ID}.chromiumapp.org/?x=1",                      # query
    f"https://{EXT_ID}.chromiumapp.org",                           # no trailing slash
    f"https://{EXT_ID}.chromiumapp.org.evil.com/",                 # suffix trick
    f"https://{EXT_ID.upper()}.chromiumapp.org/",                  # not a Chrome id
    "https://evil.com/",
])
async def test_connect_rejects_non_allow_listed_redirects(client, redirect):
    assert (await connect(client, redirect)).status_code == 400


async def test_connect_issues_token_to_allow_listed_extension(client, anon_client, owner, db_session):
    resp = await connect(client)
    assert resp.status_code == 200
    redirect_to = resp.json()["redirect_to"]
    assert redirect_to.startswith(EXT_REDIRECT + "#")
    fragment = urllib.parse.parse_qs(urllib.parse.urlparse(redirect_to).fragment)
    token = fragment["token"][0]
    assert token.startswith("tme_") and fragment["email"] == [owner.email]

    bearer = {"authorization": f"Bearer {token}"}
    assert (await anon_client.get("/api/accounts", headers=bearer)).status_code == 200
    listed = (await client.get("/api/extension/tokens")).json()
    assert listed[0]["device_name"] == "Work laptop" and listed[0]["last_used_at"] is not None
    assert listed[0]["token_prefix"] == token[:8] and "token_hash" not in listed[0]
    # A bearer token can't mint more tokens
    assert (await anon_client.post("/api/extension/connect", headers=bearer,
                                   json={"redirect_uri": EXT_REDIRECT, "device_name": "x"})).status_code == 403


async def test_revoking_a_token_signs_the_extension_out(client, anon_client):
    token = urllib.parse.parse_qs(urllib.parse.urlparse((await connect(client)).json()["redirect_to"]).fragment)["token"][0]
    bearer = {"authorization": f"Bearer {token}"}
    token_id = (await client.get("/api/extension/tokens")).json()[0]["id"]
    assert (await client.delete(f"/api/extension/tokens/{token_id}")).status_code == 204
    assert (await anon_client.get("/api/accounts", headers=bearer)).status_code == 401
    assert (await client.get("/api/extension/tokens")).json() == []

    # Sign out from the extension itself: revoke the current bearer token
    token2 = urllib.parse.parse_qs(urllib.parse.urlparse((await connect(client)).json()["redirect_to"]).fragment)["token"][0]
    b2 = {"authorization": f"Bearer {token2}"}
    assert (await anon_client.delete("/api/extension/tokens/current", headers=b2)).status_code == 204
    assert (await anon_client.get("/api/accounts", headers=b2)).status_code == 401


async def test_tokens_are_per_user(client, act_as):
    await connect(client)
    other, _ = await make_user_with_account("b@test.local")
    act_as(other)
    assert (await client.get("/api/extension/tokens")).json() == []
    act_as(None)


# ── admin ───────────────────────────────────────────────────────────────────

async def test_disabling_kills_sessions_and_tokens(client, anon_client, act_as):
    user, _ = await make_user_with_account("pilot@test.local")
    act_as(user)
    token = urllib.parse.parse_qs(urllib.parse.urlparse((await connect(client)).json()["redirect_to"]).fragment)["token"][0]
    cookie = {"cookie": f"tm_session={await session_token_for(user)}"}
    assert (await anon_client.get("/api/accounts", headers=cookie)).status_code == 200

    act_as(await _owner_user())  # back to the owner (admin)
    assert (await client.post(f"/api/admin/users/{user.id}/disable")).json()["status"] == "disabled"
    assert (await anon_client.get("/api/accounts", headers=cookie)).status_code == 401
    assert (await anon_client.get("/api/accounts", headers={"authorization": f"Bearer {token}"})).status_code == 401

    # Re-enabled: a fresh sign-in is needed (old credentials stay dead)
    assert (await client.post(f"/api/admin/users/{user.id}/enable")).json()["status"] == "active"
    assert (await anon_client.get("/api/accounts", headers=cookie)).status_code == 401


async def _owner_user():
    from tests.conftest import TestSessionLocal
    async with TestSessionLocal() as s:
        return (await s.execute(select(User).where(User.email == "owner@test.local"))).scalar_one()


async def test_approve_and_reject_pending(client, anon_client, monkeypatch, db_session):
    await google_sign_in(anon_client, monkeypatch, "sub-p", "p@gmail.com")
    pending = (await client.get("/api/admin/users", params={"status": "pending"})).json()
    assert [u["email"] for u in pending] == ["p@gmail.com"]
    approved = (await client.post(f"/api/admin/users/{pending[0]['id']}/approve")).json()
    assert approved["status"] == "active" and approved["approved_by"] is not None
    assert (await anon_client.get("/api/trades")).status_code == 200

    anon_client.cookies.clear()
    await google_sign_in(anon_client, monkeypatch, "sub-q", "q@gmail.com")
    q = (await client.get("/api/admin/users", params={"status": "pending"})).json()[0]
    assert (await client.post(f"/api/admin/users/{q['id']}/reject")).json()["status"] == "disabled"
    assert (await anon_client.get("/api/me")).status_code == 401  # session gone


async def test_self_and_last_admin_protection(client, owner, act_as):
    assert (await client.post(f"/api/admin/users/{owner.id}/disable")).status_code == 400
    assert (await client.patch(f"/api/admin/users/{owner.id}/role", json={"role": "user"})).status_code == 400
    second, _ = await make_user_with_account("second@test.local", role="admin")
    # With two active admins, one may demote the other — never themselves, never to zero admins.
    assert (await client.patch(f"/api/admin/users/{second.id}/role", json={"role": "user"})).json()["role"] == "user"
    assert (await client.patch(f"/api/admin/users/{second.id}/role", json={"role": "admin"})).json()["role"] == "admin"
    act_as(second)
    assert (await client.post(f"/api/admin/users/{owner.id}/disable")).status_code == 200
    # second is now the last active admin
    assert (await client.patch(f"/api/admin/users/{second.id}/role", json={"role": "user"})).status_code == 400
    assert (await client.post(f"/api/admin/users/{second.id}/disable")).status_code == 400


async def test_admin_responses_carry_no_trading_data(client, act_as):
    user, account = await make_user_with_account("trader@test.local")
    act_as(user)
    await client.post("/api/trades", json=TRADE)
    act_as(await _owner_user())
    allowed = {"id", "email", "display_name", "role", "status", "created_at", "last_login_at",
               "has_signed_in", "invited_by", "approved_by", "approved_at"}
    users = (await client.get("/api/admin/users")).json()
    assert users and all(set(u) == allowed for u in users)
    assert "AAPL" not in str(users) and str(account.id) not in str(users)


async def test_non_admin_gets_403_on_admin_routes(client, act_as):
    user, _ = await make_user_with_account("plain@test.local")
    act_as(user)
    assert (await client.get("/api/admin/users")).status_code == 403
    assert (await client.get("/api/market-data/status")).status_code == 403


# ── the boundary ────────────────────────────────────────────────────────────

EXEMPT = {"/health", "/api/auth/google/login", "/api/auth/google/callback", "/api/auth/logout",
          "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json",
          # Server to server: authenticated by the token sync secret header instead (404 when disabled, 401
          # without the secret) — covered in test_schwab_token_follower.py.
          "/api/market-data/sync/tokens"}


def test_every_route_requires_credentials():
    from fastapi.routing import APIRoute
    from fastapi.testclient import TestClient
    from app.main import app

    checked = 0
    tc = TestClient(app, raise_server_exceptions=True)  # no `with`: don't run the lifespan (scheduler, priming)
    for route in app.routes:
        if not isinstance(route, APIRoute) or route.path in EXEMPT:
            continue
        path = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), route.path)
        for method in route.methods - {"HEAD", "OPTIONS"}:
            resp = tc.request(method, path, json={})
            assert resp.status_code == 401, f"{method} {route.path} → {resp.status_code}"
            checked += 1
    assert checked > 80
