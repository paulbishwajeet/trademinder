"""Part 4: market data provider boundary — banner state, offline detection, status endpoint."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services.market_data import (
    STATE_CRITICAL, STATE_EXPIRING, STATE_OFFLINE, STATE_OK, compute_state,
)
from app.services.market_data_errors import MarketDataUnavailable
from app.services.schwab_client import SchwabAPIError, SchwabClient

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


# ── banner state ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("hours, expected", [
    (200, STATE_OK),
    (72.01, STATE_OK),
    (72, STATE_EXPIRING),       # "72 down to 24": 72 itself is amber
    (48, STATE_EXPIRING),
    (24, STATE_EXPIRING),       # exactly 24 is still amber; red is "under 24"
    (23.99, STATE_CRITICAL),
    (1, STATE_CRITICAL),
    (0.01, STATE_CRITICAL),
    (0, STATE_OFFLINE),
    (-5, STATE_OFFLINE),
])
def test_state_thresholds(hours, expected):
    assert compute_state(NOW + timedelta(hours=hours), offline=False, now=NOW) == expected


def test_state_offline_flag_wins_and_missing_expiry_is_offline():
    assert compute_state(NOW + timedelta(days=5), offline=True, now=NOW) == STATE_OFFLINE
    assert compute_state(None, offline=False, now=NOW) == STATE_OFFLINE


# ── provider offline detection ──────────────────────────────────────────────

class FakeTokenDB:
    """Stands in for asyncpg: serves the schwab_tokens row and records writes."""

    def __init__(self, refresh_expires_at, access_expires_at=None, updated_at=None):
        self.row = {
            "access_token": "AT", "refresh_token": "RT",
            "access_expires_at": access_expires_at or (datetime.now(timezone.utc) - timedelta(minutes=1)),
            "refresh_expires_at": refresh_expires_at,
            "updated_at": updated_at or datetime(2026, 11, 1, tzinfo=timezone.utc),
        }

    async def connect(self, *_a, **_k):
        db = self

        class Conn:
            async def fetchrow(self, sql, *args):
                return dict(db.row)

            async def execute(self, sql, *args):
                db.row.update(access_token=args[0], refresh_token=args[1],
                              access_expires_at=args[2], refresh_expires_at=args[3],
                              updated_at=datetime.now(timezone.utc))

            async def close(self):
                pass

        return Conn()

    def cli_reauth(self):
        """What scripts/schwab_auth.py does: new tokens, fresh 7-day expiry, updated_at = NOW()."""
        now = datetime.now(timezone.utc)
        self.row.update(access_token="AT2", refresh_token="RT2",
                        access_expires_at=now + timedelta(minutes=30),
                        refresh_expires_at=now + timedelta(days=7), updated_at=now)


def ok_json(payload):
    resp = MagicMock(status_code=200)
    resp.json.return_value = payload
    return resp


def make_client():
    return SchwabClient("key", "secret", "postgresql+asyncpg://u:p@localhost/db")


def test_expired_refresh_token_goes_offline_without_calling_schwab():
    db = FakeTokenDB(refresh_expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
    client = make_client()
    with patch("app.services.schwab_client.asyncpg.connect", side_effect=db.connect), \
         patch("app.services.schwab_client.httpx.post") as post, \
         patch("app.services.schwab_client.httpx.get") as get:
        with pytest.raises(MarketDataUnavailable):
            client.get_quotes(["AAPL"])
        assert client.is_offline()
        for _ in range(5):
            with pytest.raises(MarketDataUnavailable):
                client.get_quotes(["AAPL"])
        assert post.call_count == 0 and get.call_count == 0


def test_invalid_grant_refresh_goes_offline_and_stops_calling():
    db = FakeTokenDB(refresh_expires_at=datetime.now(timezone.utc) + timedelta(days=3))
    client = make_client()
    rejected = MagicMock(status_code=400, text='{"error":"invalid_grant"}')
    rejected.json.return_value = {"error": "invalid_grant", "error_description": "refresh token invalid"}
    with patch("app.services.schwab_client.asyncpg.connect", side_effect=db.connect), \
         patch("app.services.schwab_client.httpx.post", return_value=rejected) as post, \
         patch("app.services.schwab_client.httpx.get") as get:
        with pytest.raises(MarketDataUnavailable):
            client.get_price_history("AAPL", "year", 1, "daily", 1)
        with pytest.raises(MarketDataUnavailable):
            client.get_option_chain("AAPL")
        assert post.call_count == 1  # the one failing refresh, then nothing
        assert get.call_count == 0
    status = client.status()
    assert status.offline is True
    assert "invalid_grant" in status.last_error and "RT" not in status.last_error


def test_transient_refresh_failure_is_not_offline():
    db = FakeTokenDB(refresh_expires_at=datetime.now(timezone.utc) + timedelta(days=3))
    client = make_client()
    with patch("app.services.schwab_client.asyncpg.connect", side_effect=db.connect), \
         patch("app.services.schwab_client.httpx.post", return_value=MagicMock(status_code=500, text="boom")):
        with pytest.raises(SchwabAPIError):
            client.get_quotes(["AAPL"])
    assert not client.is_offline()


def test_per_ticker_errors_stay_schwab_api_errors():
    db = FakeTokenDB(refresh_expires_at=datetime.now(timezone.utc) + timedelta(days=3),
                     access_expires_at=datetime.now(timezone.utc) + timedelta(minutes=30))
    client = make_client()
    with patch("app.services.schwab_client.asyncpg.connect", side_effect=db.connect), \
         patch("app.services.schwab_client.httpx.get", return_value=MagicMock(status_code=400, text="not optionable")):
        with pytest.raises(SchwabAPIError) as exc:
            client.get_option_chain("BRK.B")
    assert not isinstance(exc.value, MarketDataUnavailable)
    assert not client.is_offline()


def test_resumes_after_token_row_changes(monkeypatch):
    db = FakeTokenDB(refresh_expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
    client = make_client()
    clock = {"t": 1000.0}
    monkeypatch.setattr("app.services.schwab_client.time.monotonic", lambda: clock["t"])
    with patch("app.services.schwab_client.asyncpg.connect", side_effect=db.connect), \
         patch("app.services.schwab_client.httpx.get", return_value=ok_json({"AAPL": {"quote": {"lastPrice": 200}}})) as get:
        with pytest.raises(MarketDataUnavailable):
            client.get_quotes(["AAPL"])

        db.cli_reauth()
        clock["t"] += 30  # under a minute: the row isn't re-read yet, still offline, still no calls
        with pytest.raises(MarketDataUnavailable):
            client.get_quotes(["AAPL"])
        assert get.call_count == 0

        clock["t"] += 31  # past the minute: row re-read, changed → back online
        assert client.get_quotes(["AAPL"]) == {"AAPL": {"lastPrice": 200}}
        assert not client.is_offline()
        assert get.call_count == 1
    assert client.status().last_success_at is not None


def test_unchanged_row_stays_offline_after_recheck(monkeypatch):
    db = FakeTokenDB(refresh_expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
    client = make_client()
    clock = {"t": 1000.0}
    monkeypatch.setattr("app.services.schwab_client.time.monotonic", lambda: clock["t"])
    with patch("app.services.schwab_client.asyncpg.connect", side_effect=db.connect), \
         patch("app.services.schwab_client.httpx.get") as get:
        with pytest.raises(MarketDataUnavailable):
            client.get_quotes(["AAPL"])
        clock["t"] += 120
        with pytest.raises(MarketDataUnavailable):
            client.get_quotes(["AAPL"])
        assert get.call_count == 0


def test_missing_app_key_is_offline():
    client = SchwabClient("", "", "postgresql+asyncpg://u:p@localhost/db")
    with pytest.raises(MarketDataUnavailable):
        client.get_quotes(["AAPL"])
    assert client.status().offline is True


def test_offline_transition_logged_once(caplog):
    db = FakeTokenDB(refresh_expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
    client = make_client()
    with patch("app.services.schwab_client.asyncpg.connect", side_effect=db.connect):
        for _ in range(10):
            with pytest.raises(MarketDataUnavailable):
                client.get_quotes(["AAPL"])
    assert sum("Market data offline" in r.message for r in caplog.records) == 1


def test_unknown_provider_setting_is_rejected():
    from pydantic import ValidationError
    from app.config import Settings
    with pytest.raises(ValidationError):
        Settings(market_data_provider="polygon")
    assert Settings(market_data_provider="Schwab").market_data_provider == "schwab"


# ── endpoints ───────────────────────────────────────────────────────────────

class StubProvider:
    name = "schwab"

    def __init__(self, status):
        self._status = status

    def status(self):
        return self._status

    def is_offline(self):
        return self._status.offline


async def test_status_endpoint(client, owner, monkeypatch):
    from app.services import market_data
    from app.services.market_data import ProviderStatus
    expires = datetime.now(timezone.utc) + timedelta(hours=50)
    stub = StubProvider(ProviderStatus("schwab", False, expires, None, None))
    monkeypatch.setattr("app.routers.market_data.get_market_data", lambda: stub)
    # the owner seeded by conftest is a plain user: promote to admin for this test
    owner.role = "admin"
    body = (await client.get("/api/market-data/status")).json()
    assert body["provider"] == "schwab" and body["state"] == "expiring"
    assert 49.5 < body["hours_remaining"] <= 50
    owner.role = "user"
    assert (await client.get("/api/market-data/status")).status_code == 403
    assert market_data  # imported for the monkeypatch path


async def test_me_endpoint(client, owner):
    body = (await client.get("/api/me")).json()
    assert body["id"] == str(owner.id) and body["role"] == owner.role
