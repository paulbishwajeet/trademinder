"""In-app Schwab reconnect, phase 1: state, redirect URL parsing, code exchange + token write, error mapping,
admin-only access, and that nothing sensitive is logged. Schwab is always mocked."""
import asyncio
import logging
import secrets
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.config import settings
from app.services import market_data, schwab_reconnect
from app.services.auth import sign_state
from app.services.schwab_client import SchwabClient
from app.services.schwab_oauth import REDIRECT_URI, RedirectUrlError, authorize_url, parse_redirect_url
from tests.conftest import TEST_DATABASE_URL, TestSessionLocal, make_user_with_account

CODE = "C0.b2F1dGgyLmJkYy5zY2h3YWIuY29t.SECRETCODE%40"   # as Schwab sends it: an encoded '@'
DECODED_CODE = "C0.b2F1dGgyLmJkYy5zY2h3YWIuY29t.SECRETCODE@"
ACCESS = "ACCESS-TOKEN-should-never-be-logged"
REFRESH = "REFRESH-TOKEN-should-never-be-logged"


class FakeResponse:
    def __init__(self, status_code: int, body):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    monkeypatch.setattr(settings, "schwab_app_key", "app-key")
    monkeypatch.setattr(settings, "schwab_app_secret", "app-secret")
    schwab_reconnect._pending.clear()
    yield
    schwab_reconnect._pending.clear()


@pytest.fixture
def provider(monkeypatch):
    client = SchwabClient("app-key", "app-secret", TEST_DATABASE_URL)
    monkeypatch.setattr(market_data, "_provider", client)
    return client


@pytest.fixture
def schwab(monkeypatch):
    """Mocked token endpoint. Set .response (a FakeResponse or an exception); .calls records each POST's form."""
    class Mock:
        response = FakeResponse(200, {"access_token": ACCESS, "refresh_token": REFRESH, "expires_in": 1800})
        calls: list = []

        def post(self, url, headers=None, data=None, timeout=None):
            self.calls.append({"url": url, "data": data})
            if isinstance(self.response, Exception):
                raise self.response
            return self.response

    mock = Mock()
    mock.calls = []
    monkeypatch.setattr(httpx, "post", mock.post)
    return mock


async def _seed_expired_row():
    from app.models.schwab_token import SchwabToken
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    async with TestSessionLocal() as s:
        s.add(SchwabToken(id=1, access_token="old-a", refresh_token="old-r",
                          access_expires_at=past, refresh_expires_at=past))
        await s.commit()


async def _token_row():
    from app.models.schwab_token import SchwabToken
    async with TestSessionLocal() as s:
        return await s.get(SchwabToken, 1)


def _state_from(url: str) -> str:
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]


def _redirect(state: str | None, code: str | None = CODE, base: str = REDIRECT_URI) -> str:
    parts = []
    if code is not None:
        parts.append(f"code={code}")
    if state is not None:
        parts.append(f"state={urllib.parse.quote(state)}")
    return f"{base}?{'&'.join(parts)}&session=abc"


async def _start(client) -> str:
    resp = await client.post("/api/market-data/reconnect/start")
    assert resp.status_code == 200, resp.text
    return _state_from(resp.json()["authorize_url"])


# ── authorize URL and state ────────────────────────────────────────────────

async def test_start_returns_cli_url_plus_state(client):
    resp = await client.post("/api/market-data/reconnect/start")
    body = resp.json()
    url = body["authorize_url"]
    state = _state_from(url)
    # Exactly the CLI's URL, with the state appended.
    assert url == authorize_url("app-key", state)
    assert url.startswith(authorize_url("app-key") + "&state=")
    expires = datetime.fromisoformat(body["state_expires_at"])
    assert timedelta(minutes=9) < expires - datetime.now(timezone.utc) <= timedelta(minutes=10)


async def test_state_round_trip_and_single_use(client, provider, schwab):
    state = await _start(client)
    first = await client.post("/api/market-data/reconnect/complete", json={"redirect_url": _redirect(state)})
    assert first.status_code == 200, first.text
    again = await client.post("/api/market-data/reconnect/complete", json={"redirect_url": _redirect(state)})
    assert again.status_code == 409 and again.json()["code"] == "state_invalid"
    assert len(schwab.calls) == 1  # the replay never reached Schwab


async def test_expired_state(client, owner, schwab):
    nonce = secrets.token_urlsafe(16)
    state = sign_state({"p": "schwab_reconnect", "uid": str(owner.id), "n": nonce}, ttl_seconds=-5)
    schwab_reconnect._remember(nonce, time.time() + 60)
    resp = await client.post("/api/market-data/reconnect/complete", json={"redirect_url": _redirect(state)})
    assert resp.status_code == 409 and resp.json()["code"] == "state_expired"
    assert schwab.calls == []


async def test_state_bound_to_the_admin_who_started(client, act_as, schwab):
    state = await _start(client)  # started by the owner
    other_admin, _ = await make_user_with_account("admin2@test.local", role="admin")
    act_as(other_admin)
    resp = await client.post("/api/market-data/reconnect/complete", json={"redirect_url": _redirect(state)})
    assert resp.status_code == 409 and resp.json()["code"] == "state_invalid"
    assert schwab.calls == []


@pytest.mark.parametrize("state", [
    "not-a-state",
    "eyJwIjoic2Nod2FiX3JlY29ubmVjdCJ9.forgedmac",
])
async def test_forged_state(client, schwab, state):
    resp = await client.post("/api/market-data/reconnect/complete", json={"redirect_url": _redirect(state)})
    assert resp.status_code == 409 and resp.json()["code"] == "state_invalid"
    assert schwab.calls == []


async def test_login_state_is_not_a_reconnect_state(client, owner, schwab):
    # Correctly signed with the same secret, but a login-shaped payload (no purpose).
    state = sign_state({"state": "x", "nonce": "y", "verifier": "z", "uid": str(owner.id), "n": "abc"})
    resp = await client.post("/api/market-data/reconnect/complete", json={"redirect_url": _redirect(state)})
    assert resp.json()["code"] == "state_invalid"


async def test_state_unknown_to_this_process(client, owner, schwab):
    """A validly signed state this process never issued (e.g. issued before a restart)."""
    state = sign_state({"p": "schwab_reconnect", "uid": str(owner.id), "n": "never-issued"}, ttl_seconds=600)
    resp = await client.post("/api/market-data/reconnect/complete", json={"redirect_url": _redirect(state)})
    assert resp.json()["code"] == "state_invalid"


# ── redirect URL validation ────────────────────────────────────────────────

@pytest.mark.parametrize("url,reason", [
    ("https://evil.example.com/callback?code=x&state=y", "bad_url"),
    ("https://127.0.0.1:9999/callback?code=x&state=y", "bad_url"),
    ("http://127.0.0.1:8765/callback?code=x&state=y", "bad_url"),
    ("https://127.0.0.1:8765/other?code=x&state=y", "bad_url"),
    ("https://127.0.0.1:notaport/callback?code=x", "bad_url"),
    ("just some text", "bad_url"),
    ("", "bad_url"),
    (REDIRECT_URI + "?code=x&state=y&" + "a" * 5000, "bad_url"),
    (REDIRECT_URI + "?state=y", "missing_code"),
    (REDIRECT_URI + "?code=x", "missing_state"),
    (REDIRECT_URI + "?error=access_denied&state=y", "authorization_denied"),
])
def test_parse_redirect_url_rejects(url, reason):
    with pytest.raises(RedirectUrlError) as exc:
        parse_redirect_url(url)
    assert exc.value.reason == reason


def test_parse_redirect_url_decodes_the_at_sign():
    code, state = parse_redirect_url(f"  {REDIRECT_URI}?code={CODE}&state=s1&session=z  ")
    assert code == DECODED_CODE and state == "s1"
    # The CLI's mode: no state required.
    assert parse_redirect_url(f"{REDIRECT_URI}/?code={CODE}", require_state=False) == (DECODED_CODE, None)


async def test_bad_url_does_not_consume_the_state(client, provider, schwab):
    state = await _start(client)
    wrong = await client.post("/api/market-data/reconnect/complete",
                              json={"redirect_url": _redirect(state, base="https://127.0.0.1:8765/elsewhere")})
    assert wrong.status_code == 400 and wrong.json()["code"] == "bad_url"
    missing = await client.post("/api/market-data/reconnect/complete", json={"redirect_url": _redirect(state, code=None)})
    assert missing.status_code == 400 and missing.json()["code"] == "missing_code"
    ok = await client.post("/api/market-data/reconnect/complete", json={"redirect_url": _redirect(state)})
    assert ok.status_code == 200


async def test_overlong_url_is_not_echoed(client):
    pasted = REDIRECT_URI + "?code=SECRET&state=x&" + "a" * 5000
    resp = await client.post("/api/market-data/reconnect/complete", json={"redirect_url": pasted})
    assert resp.status_code == 400 and resp.json()["code"] == "bad_url"
    assert "SECRET" not in resp.text


# ── exchange + token write ─────────────────────────────────────────────────

async def test_success_writes_row_and_leaves_offline_mode(client, provider, schwab):
    await _seed_expired_row()
    loop = asyncio.get_running_loop()
    assert await loop.run_in_executor(None, provider.refresh_offline_state) is True
    before = await client.get("/api/market-data/status")
    assert before.json()["state"] == "offline"

    state = await _start(client)
    resp = await client.post("/api/market-data/reconnect/complete", json={"redirect_url": _redirect(state)})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "ok" and body["last_error"] is None
    assert 167.5 < body["hours_remaining"] <= 168
    # No tokens in the response.
    assert ACCESS not in resp.text and REFRESH not in resp.text

    # The CLI's exact exchange, with the decoded code.
    assert schwab.calls[0]["data"] == {"grant_type": "authorization_code", "code": DECODED_CODE,
                                       "redirect_uri": REDIRECT_URI}

    row = await _token_row()
    assert row.access_token == ACCESS and row.refresh_token == REFRESH
    assert timedelta(days=6, hours=23) < row.refresh_expires_at - datetime.now(timezone.utc) <= timedelta(days=7)

    # Online immediately: no wait for the one-minute token-row recheck.
    assert provider.is_offline() is False
    assert (await client.get("/api/market-data/status")).json()["state"] == "ok"


@pytest.mark.parametrize("response,code,status", [
    (FakeResponse(400, {"error": "invalid_grant", "error_description": "code expired"}), "code_expired", 400),
    (FakeResponse(401, {"error": "invalid_client"}), "code_expired", 400),
    (FakeResponse(500, "upstream exploded"), "schwab_unreachable", 502),
    (FakeResponse(200, ValueError("not json")), "schwab_unreachable", 502),
    (httpx.ConnectError("boom"), "schwab_unreachable", 502),
    (httpx.ReadTimeout("slow"), "schwab_unreachable", 502),
])
async def test_schwab_error_mapping(client, provider, schwab, response, code, status):
    await _seed_expired_row()
    schwab.response = response
    state = await _start(client)
    resp = await client.post("/api/market-data/reconnect/complete", json={"redirect_url": _redirect(state)})
    assert resp.status_code == status and resp.json()["code"] == code
    assert resp.json()["detail"]
    row = await _token_row()
    assert row.refresh_token == "old-r"  # nothing written


async def test_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "schwab_app_secret", "")
    resp = await client.post("/api/market-data/reconnect/start")
    assert resp.status_code == 409 and resp.json()["code"] == "not_configured"


# ── access ─────────────────────────────────────────────────────────────────

async def test_non_admin_and_anonymous_are_refused(client, anon_client, act_as, schwab):
    pilot, _ = await make_user_with_account("pilot@test.local")
    act_as(pilot)
    assert (await client.post("/api/market-data/reconnect/start")).status_code == 403
    assert (await client.post("/api/market-data/reconnect/complete",
                              json={"redirect_url": _redirect("x")})).status_code == 403
    assert (await anon_client.post("/api/market-data/reconnect/start")).status_code == 401
    assert (await anon_client.post("/api/market-data/reconnect/complete",
                                   json={"redirect_url": _redirect("x")})).status_code == 401
    assert schwab.calls == []


# ── logging ────────────────────────────────────────────────────────────────

async def test_nothing_sensitive_is_logged(client, provider, schwab, owner, caplog):
    caplog.set_level(logging.DEBUG)
    state = await _start(client)
    pasted = _redirect(state)
    ok = await client.post("/api/market-data/reconnect/complete", json={"redirect_url": pasted})
    assert ok.status_code == 200

    schwab.response = FakeResponse(400, {"error": "invalid_grant", "error_description": f"bad code {DECODED_CODE}"})
    state2 = await _start(client)
    failed = await client.post("/api/market-data/reconnect/complete", json={"redirect_url": _redirect(state2)})
    assert failed.json()["code"] == "code_expired"

    text = caplog.text
    for secret in (CODE, DECODED_CODE, "SECRETCODE", ACCESS, REFRESH, state, state2, pasted, "app-secret"):
        assert secret not in text
    assert f"Schwab reconnected by user {owner.id}; refresh token expires" in text
    assert f"Schwab reconnect failed for user {owner.id}: code_expired (HTTP 400 invalid_grant)" in text
    # Schwab's response body never reaches the response either.
    assert DECODED_CODE not in failed.text


# ── the CLI shares the same code ───────────────────────────────────────────

def test_cli_uses_the_shared_oauth_module(monkeypatch):
    import importlib.util
    import pathlib
    from app.services import schwab_oauth
    for name in ("SCHWAB_APP_KEY", "SCHWAB_APP_SECRET", "DATABASE_URL"):
        monkeypatch.setenv(name, "x")
    path = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "schwab_auth.py"
    spec = importlib.util.spec_from_file_location("schwab_auth_cli", path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    assert cli.exchange_code is schwab_oauth.exchange_code
    assert cli.store_tokens is schwab_oauth.store_tokens
    assert cli.authorize_url("KEY") == (
        "https://api.schwabapi.com/v1/oauth/authorize?response_type=code&client_id=KEY"
        "&redirect_uri=https%3A%2F%2F127.0.0.1%3A8765%2Fcallback"
    )
    # The module the CLI relies on must stay free of app settings.
    source = pathlib.Path(schwab_oauth.__file__).read_text()
    assert "from app" not in source and "import app" not in source
