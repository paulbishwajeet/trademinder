"""Schwab token follower: production's secret-only export, dev pulling instead of refreshing (single-flight,
one-minute rate limit, one retry after a 401, offline integration), reconnect disabled in follower mode, the
status fields, and no tokens or secret in logs. Schwab and production are mocked; nothing is called for real."""
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services import market_data as market_data_module
from app.services import schwab_client as sc
from app.services.market_data_errors import MarketDataUnavailable
from app.services.schwab_client import SCHWAB_TOKEN_URL, SchwabAPIError, SchwabClient

PROD = "https://tm.example.test"
SECRET = "s" * 40
DB_URL = "postgresql+asyncpg://u:p@localhost/db"


def now():
    return datetime.now(timezone.utc)


class FakeTokenDB:
    """Stands in for asyncpg: serves the schwab_tokens row (or none) and records writes."""

    def __init__(self, row: dict | None):
        self.row = row
        self.writes = 0

    @classmethod
    def with_tokens(cls, access_left=timedelta(minutes=20), refresh_left=timedelta(days=5), access="AT-OLD"):
        return cls({"access_token": access, "refresh_token": "RT-OLD", "access_expires_at": now() + access_left,
                    "refresh_expires_at": now() + refresh_left, "updated_at": now() - timedelta(hours=1)})

    async def connect(self, *_a, **_k):
        db = self

        class Conn:
            async def fetchrow(self, sql, *args):
                return None if db.row is None else dict(db.row)

            async def execute(self, sql, *args):
                db.writes += 1
                db.row = {"access_token": args[0], "refresh_token": args[1], "access_expires_at": args[2],
                          "refresh_expires_at": args[3], "updated_at": now()}

            async def close(self):
                pass

        return Conn()


def json_resp(status, payload):
    resp = MagicMock(status_code=status, text=str(payload))
    resp.json.return_value = payload
    return resp


def export_payload(access="AT-NEW", refresh="RT-PROD", access_left=timedelta(minutes=29)):
    return {"access_token": access, "refresh_token": refresh,
            "access_expires_at": (now() + access_left).isoformat(),
            "refresh_expires_at": (now() + timedelta(days=6)).isoformat()}


class Posts:
    """httpx.post stand-in that tells production pulls from Schwab token calls apart."""

    def __init__(self, prod_responses=None, schwab_response=None, delay=0.0):
        self.prod_responses = list(prod_responses or [])
        self.schwab_response = schwab_response
        self.prod_calls = 0
        self.schwab_calls = 0
        self.delay = delay
        self.headers_seen = []

    def __call__(self, url, **kwargs):
        if url == SCHWAB_TOKEN_URL:
            self.schwab_calls += 1
            return self.schwab_response
        assert url == f"{PROD}/api/market-data/sync/tokens"
        assert kwargs.get("follow_redirects") is False
        self.headers_seen.append(kwargs.get("headers", {}))
        self.prod_calls += 1
        if self.delay:
            time.sleep(self.delay)
        nxt = self.prod_responses.pop(0) if len(self.prod_responses) > 1 else self.prod_responses[0]
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def follower():
    return SchwabClient("", "", DB_URL, sync_url=PROD, sync_secret=SECRET)


def patched(db, posts, gets=None):
    return (
        patch("app.services.schwab_client.asyncpg.connect", side_effect=db.connect),
        patch("app.services.schwab_client.httpx.post", side_effect=posts),
        patch("app.services.schwab_client.httpx.get", side_effect=gets or [json_resp(200, {})] * 50),
    )


# ── follower: pulls instead of refreshing ────────────────────────────────

def test_follower_pulls_near_expiry_and_never_calls_schwab_token_endpoint():
    db = FakeTokenDB.with_tokens(access_left=timedelta(minutes=2))
    posts = Posts([json_resp(200, export_payload())])
    client = follower()
    a, b, c = patched(db, posts)
    with a, b, c as get:
        client.get_quotes(["AAPL"])
    assert posts.schwab_calls == 0 and posts.prod_calls == 1
    assert posts.headers_seen[0] == {"X-Token-Sync-Secret": SECRET}
    assert db.row["access_token"] == "AT-NEW" and db.row["refresh_token"] == "RT-PROD"
    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer AT-NEW"
    status = client.status()
    assert status.token_source == "production" and status.last_pull_outcome == "ok" and not status.offline


def test_follower_with_no_token_row_pulls_it():
    db = FakeTokenDB(None)
    posts = Posts([json_resp(200, export_payload())])
    client = follower()
    a, b, c = patched(db, posts)
    with a, b, c:
        client.get_quotes(["AAPL"])
    assert posts.prod_calls == 1 and posts.schwab_calls == 0 and db.writes == 1


def test_follower_with_expired_local_refresh_token_pulls():
    db = FakeTokenDB.with_tokens(refresh_left=timedelta(hours=-1))
    posts = Posts([json_resp(200, export_payload())])
    client = follower()
    a, b, c = patched(db, posts)
    with a, b, c:
        client.get_quotes(["AAPL"])
    assert posts.prod_calls == 1 and not client.is_offline()


def test_401_triggers_exactly_one_pull_and_one_retry():
    db = FakeTokenDB.with_tokens()  # 20 min left: no pull needed before the call
    posts = Posts([json_resp(200, export_payload())])
    gets = [json_resp(401, {"error": "unauthorized"}), json_resp(200, {"AAPL": {"quote": {"lastPrice": 1}}})]
    client = follower()
    a, b, c = patched(db, posts, gets)
    with a, b, c as get:
        assert client.get_quotes(["AAPL"]) == {"AAPL": {"lastPrice": 1}}
    assert posts.prod_calls == 1 and posts.schwab_calls == 0
    assert get.call_count == 2
    assert get.call_args_list[1].kwargs["headers"]["Authorization"] == "Bearer AT-NEW"


def test_second_401_after_the_retry_is_reported_not_looped():
    db = FakeTokenDB.with_tokens()
    posts = Posts([json_resp(200, export_payload())])
    gets = [json_resp(401, {}), json_resp(401, {})]
    client = follower()
    a, b, c = patched(db, posts, gets)
    with a, b, c as get, pytest.raises(SchwabAPIError):
        client.get_quotes(["AAPL"])
    assert get.call_count == 2 and posts.prod_calls == 1


def test_concurrent_callers_cause_one_pull():
    db = FakeTokenDB.with_tokens(access_left=timedelta(minutes=-1))
    posts = Posts([json_resp(200, export_payload())], delay=0.2)
    client = follower()
    errors = []
    a, b, c = patched(db, posts)
    with a, b, c:
        def call():
            try:
                client.get_quotes(["AAPL"])
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(exc)
        threads = [threading.Thread(target=call) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert errors == []
    assert posts.prod_calls == 1 and posts.schwab_calls == 0


def test_unreachable_goes_offline_rate_limits_then_recovers(monkeypatch):
    import httpx
    clock = [1000.0]
    monkeypatch.setattr(sc.time, "monotonic", lambda: clock[0])
    db = FakeTokenDB.with_tokens(access_left=timedelta(minutes=-1))
    posts = Posts([httpx.ConnectError("down")])
    client = follower()
    a, b, c = patched(db, posts)
    with a, b, c as get:
        with pytest.raises(MarketDataUnavailable):
            client.get_quotes(["AAPL"])
        assert client.is_offline() and posts.prod_calls == 1
        assert client.status().last_pull_outcome == "unreachable"

        # Within the minute: no further pull, still offline.
        clock[0] += 30
        with pytest.raises(MarketDataUnavailable):
            client.get_quotes(["AAPL"])
        assert client.refresh_offline_state() is True
        assert posts.prod_calls == 1 and get.call_count == 0

        # After the minute: production is back, the next call pulls and recovers.
        clock[0] += 31
        posts.prod_responses = [json_resp(200, export_payload())]
        client.get_quotes(["AAPL"])
        assert posts.prod_calls == 2 and not client.is_offline()
        assert client.status().last_pull_outcome == "ok"


def test_status_check_recovers_an_offline_follower(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(sc.time, "monotonic", lambda: clock[0])
    db = FakeTokenDB(None)
    posts = Posts([json_resp(503, {"code": "upstream_offline"})])
    client = follower()
    a, b, c = patched(db, posts)
    with a, b, c:
        assert client.refresh_offline_state() is True
        status = client.status()
        assert status.offline and status.last_pull_outcome == "upstream_offline"
        assert "reconnect in production" in status.last_error
        clock[0] += 61
        posts.prod_responses = [json_resp(200, export_payload())]
        assert client.refresh_offline_state() is False


@pytest.mark.parametrize("response,outcome", [
    (json_resp(401, {"code": "sync_unauthorized"}), "unauthorized"),
    (json_resp(404, {"detail": "Not Found"}), "disabled"),
    (json_resp(503, {"code": "upstream_offline"}), "upstream_offline"),
    (json_resp(502, {"code": "upstream_error"}), "unreachable"),
    (json_resp(200, {"access_token": "x"}), "invalid_response"),
])
def test_pull_failures_enter_offline_mode(response, outcome):
    db = FakeTokenDB.with_tokens(access_left=timedelta(minutes=-1))
    posts = Posts([response])
    client = follower()
    a, b, c = patched(db, posts)
    with a, b, c, pytest.raises(MarketDataUnavailable):
        client.get_quotes(["AAPL"])
    assert client.is_offline() and client.status().last_pull_outcome == outcome
    assert db.writes == 0


def test_pull_now_is_rate_limited(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(sc.time, "monotonic", lambda: clock[0])
    db = FakeTokenDB.with_tokens()
    posts = Posts([json_resp(200, export_payload())])
    client = follower()
    a, b, c = patched(db, posts)
    with a, b, c:
        client.pull_now()
        with pytest.raises(sc.PullRateLimited) as exc:
            client.pull_now()
        assert 0 < exc.value.retry_after_seconds <= 60
        clock[0] += 60
        client.pull_now()
    assert posts.prod_calls == 2


def test_logs_never_contain_tokens_or_the_secret(caplog):
    caplog.set_level(logging.DEBUG)
    db = FakeTokenDB.with_tokens(access_left=timedelta(minutes=-1))
    posts = Posts([json_resp(200, export_payload(access="AT-SECRET-VALUE", refresh="RT-SECRET-VALUE"))])
    client = follower()
    a, b, c = patched(db, posts)
    with a, b, c:
        client.get_quotes(["AAPL"])
    text = caplog.text
    assert "Schwab token pull from production: ok" in text
    for secret in ("AT-SECRET-VALUE", "RT-SECRET-VALUE", SECRET, "AT-OLD", "RT-OLD"):
        assert secret not in text


# ── normal mode keeps refreshing, and now retries after a 401 ───────────

def schwab_refresh_ok():
    return json_resp(200, {"access_token": "AT-REFRESHED", "expires_in": 1800})


def test_normal_mode_refreshes_near_expiry_and_never_pulls():
    db = FakeTokenDB.with_tokens(access_left=timedelta(minutes=2))
    posts = Posts(schwab_response=schwab_refresh_ok())
    client = SchwabClient("key", "secret", DB_URL)
    a, b, c = patched(db, posts)
    with a, b, c:
        client.get_quotes(["AAPL"])
    assert posts.schwab_calls == 1 and posts.prod_calls == 0
    assert client.status().token_source == "self" and client.status().last_pull_at is None


def test_normal_mode_401_refreshes_once_and_retries_once():
    db = FakeTokenDB.with_tokens()
    posts = Posts(schwab_response=schwab_refresh_ok())
    gets = [json_resp(401, {}), json_resp(200, {})]
    client = SchwabClient("key", "secret", DB_URL)
    a, b, c = patched(db, posts, gets)
    with a, b, c as get:
        client.get_quotes(["AAPL"])
    assert posts.schwab_calls == 1 and get.call_count == 2
    assert get.call_args_list[1].kwargs["headers"]["Authorization"] == "Bearer AT-REFRESHED"


def test_export_tokens_refreshes_when_less_than_ten_minutes_left():
    db = FakeTokenDB.with_tokens(access_left=timedelta(minutes=8))  # > 5 (normal) but < 10 (export)
    posts = Posts(schwab_response=schwab_refresh_ok())
    client = SchwabClient("key", "secret", DB_URL)
    a, b, c = patched(db, posts)
    with a, b, c:
        tokens = client.export_tokens()
    assert posts.schwab_calls == 1
    assert tokens.access_token == "AT-REFRESHED"
    assert tokens.access_expires_at - now() > timedelta(minutes=10)


def test_export_tokens_does_not_refresh_with_enough_left():
    db = FakeTokenDB.with_tokens(access_left=timedelta(minutes=25))
    posts = Posts(schwab_response=schwab_refresh_ok())
    client = SchwabClient("key", "secret", DB_URL)
    a, b, c = patched(db, posts)
    with a, b, c:
        assert client.export_tokens().access_token == "AT-OLD"
    assert posts.schwab_calls == 0


def test_export_tokens_offline_raises():
    db = FakeTokenDB.with_tokens(refresh_left=timedelta(hours=-1))
    client = SchwabClient("key", "secret", DB_URL)
    a, b, c = patched(db, Posts())
    with a, b, c, pytest.raises(MarketDataUnavailable):
        client.export_tokens()


# ── endpoints ────────────────────────────────────────────────────────────

@pytest.fixture
def provider(monkeypatch):
    """Install a SchwabClient (normal mode) as the app's provider, on a fake token DB."""
    holder = {}

    def install(client, db, posts=None):
        monkeypatch.setattr(market_data_module, "_provider", client)
        for p in patched(db, posts or Posts()):
            p.start()
            holder.setdefault("patches", []).append(p)
        return client

    yield install
    for p in holder.get("patches", []):
        p.stop()


@pytest.fixture
def export_enabled(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "schwab_token_sync_secret", SECRET)
    monkeypatch.setattr(settings, "schwab_token_sync_url", "")


@pytest.fixture
def follower_mode(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "schwab_token_sync_secret", SECRET)
    monkeypatch.setattr(settings, "schwab_token_sync_url", PROD)


async def test_export_is_404_when_disabled(anon_client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "schwab_token_sync_secret", "")
    r = await anon_client.post("/api/market-data/sync/tokens", headers={"X-Token-Sync-Secret": SECRET})
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


async def test_export_is_404_on_a_follower(anon_client, follower_mode):
    r = await anon_client.post("/api/market-data/sync/tokens", headers={"X-Token-Sync-Secret": SECRET})
    assert r.status_code == 404


async def test_export_rejects_missing_or_wrong_secret(anon_client, client, export_enabled, provider):
    db = FakeTokenDB.with_tokens()
    provider(SchwabClient("key", "secret", DB_URL), db)
    assert (await anon_client.post("/api/market-data/sync/tokens")).status_code == 401
    r = await anon_client.post("/api/market-data/sync/tokens", headers={"X-Token-Sync-Secret": "x" * 40})
    assert r.status_code == 401 and r.json()["code"] == "sync_unauthorized"
    # A signed-in admin session doesn't open it either.
    r = await client.post("/api/market-data/sync/tokens")
    assert r.status_code == 401


async def test_export_returns_the_pair_and_refreshes_when_near_expiry(anon_client, export_enabled, provider):
    db = FakeTokenDB.with_tokens(access_left=timedelta(minutes=7))
    posts = Posts(schwab_response=schwab_refresh_ok())
    provider(SchwabClient("key", "secret", DB_URL), db, posts)
    r = await anon_client.post("/api/market-data/sync/tokens", headers={"X-Token-Sync-Secret": SECRET})
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert set(body) == {"access_token", "refresh_token", "access_expires_at", "refresh_expires_at"}
    assert body["access_token"] == "AT-REFRESHED" and body["refresh_token"] == "RT-OLD"
    assert posts.schwab_calls == 1


async def test_export_returns_upstream_offline_not_stale_tokens(anon_client, export_enabled, provider):
    db = FakeTokenDB.with_tokens(refresh_left=timedelta(hours=-2))
    provider(SchwabClient("key", "secret", DB_URL), db)
    r = await anon_client.post("/api/market-data/sync/tokens", headers={"X-Token-Sync-Secret": SECRET})
    assert r.status_code == 503 and r.json()["code"] == "upstream_offline"
    assert "AT-OLD" not in r.text and "RT-OLD" not in r.text


async def test_reconnect_endpoints_are_409_in_follower_mode(client, follower_mode):
    r = await client.post("/api/market-data/reconnect/start")
    assert r.status_code == 409 and r.json()["code"] == "token_follower"
    r = await client.post("/api/market-data/reconnect/complete",
                          json={"redirect_url": "https://127.0.0.1:8765/callback?code=x&state=y"})
    assert r.status_code == 409 and r.json()["code"] == "token_follower"


async def test_pull_now_is_409_in_normal_mode(client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "schwab_token_sync_url", "")
    r = await client.post("/api/market-data/sync/pull")
    assert r.status_code == 409 and r.json()["code"] == "not_follower"


async def test_pull_now_and_status_in_follower_mode(client, follower_mode, provider, monkeypatch):
    clock = [5000.0]
    monkeypatch.setattr(sc.time, "monotonic", lambda: clock[0])
    db = FakeTokenDB.with_tokens()
    posts = Posts([json_resp(200, export_payload(access="AT-NOT-FOR-BROWSERS"))])
    provider(follower(), db, posts)
    r = await client.post("/api/market-data/sync/pull")
    assert r.status_code == 200
    body = r.json()
    assert body["token_source"] == "production" and body["last_pull_outcome"] == "ok"
    assert body["last_pull_at"] is not None
    assert "AT-NOT-FOR-BROWSERS" not in r.text and "RT-PROD" not in r.text
    r = await client.post("/api/market-data/sync/pull")
    assert r.status_code == 429 and r.json()["code"] == "pull_rate_limited"
    status = (await client.get("/api/market-data/status")).json()
    assert status["token_source"] == "production"


async def test_pull_now_is_admin_only(client, act_as, follower_mode):
    from tests.conftest import make_user_with_account
    user, _ = await make_user_with_account("plain@test.local")
    act_as(user)
    assert (await client.post("/api/market-data/sync/pull")).status_code == 403


# ── settings ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kwargs,ok", [
    ({"schwab_token_sync_url": PROD, "schwab_token_sync_secret": SECRET}, True),
    ({"schwab_token_sync_url": "http://localhost:5441", "schwab_token_sync_secret": SECRET}, True),
    ({"schwab_token_sync_secret": SECRET}, True),          # production: export only
    ({}, True),                                             # standalone: today's behavior
    ({"schwab_token_sync_url": PROD}, False),               # follower needs the secret
    ({"schwab_token_sync_url": PROD, "schwab_token_sync_secret": "short"}, False),
    ({"schwab_token_sync_secret": "a" * 31}, False),
    ({"schwab_token_sync_url": "http://tm.example.test", "schwab_token_sync_secret": SECRET}, False),
    ({"schwab_token_sync_url": "https://tm.example.test/path", "schwab_token_sync_secret": SECRET}, False),
])
def test_settings_validation(kwargs, ok):
    from app.config import Settings
    if ok:
        s = Settings(**kwargs)
        assert s.token_follower == bool(kwargs.get("schwab_token_sync_url"))
        assert s.token_export_enabled == (bool(kwargs.get("schwab_token_sync_secret")) and not s.token_follower)
    else:
        with pytest.raises(ValueError):
            Settings(**kwargs)
