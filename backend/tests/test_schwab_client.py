# backend/tests/test_schwab_client.py
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone
import pandas as pd
import pytest


def _make_client():
    from app.services.schwab_client import SchwabClient
    client = SchwabClient("key", "secret", "postgresql://user:pass@localhost/test")
    client._Session = MagicMock()
    return client


def _future(minutes=60):
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def _past(minutes=10):
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)


def test_get_quotes_returns_mapped_result():
    from app.services.schwab_client import SchwabClient
    client = _make_client()
    client._access_token = "tok"
    client._access_expires_at = _future()
    client._refresh_expires_at = _future(minutes=48 * 60)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "AAPL": {"quote": {"lastPrice": 189.84, "closePrice": 188.33}}
    }

    with patch("app.services.schwab_client.httpx.get", return_value=mock_resp):
        result = client.get_quotes(["AAPL"])

    assert "AAPL" in result
    assert result["AAPL"]["lastPrice"] == 189.84


def test_get_price_history_returns_dataframe():
    client = _make_client()
    client._access_token = "tok"
    client._access_expires_at = _future()
    client._refresh_expires_at = _future(minutes=48 * 60)

    candles = [
        {"datetime": 1704067200000, "open": 186.0, "high": 190.0, "low": 185.0, "close": 189.0, "volume": 50000000},
        {"datetime": 1704153600000, "open": 189.0, "high": 192.0, "low": 188.0, "close": 191.0, "volume": 45000000},
    ]
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"symbol": "AAPL", "empty": False, "candles": candles}

    with patch("app.services.schwab_client.httpx.get", return_value=mock_resp):
        df = client.get_price_history("AAPL", "year", 1, "daily", 1)

    assert not df.empty
    assert "Close" in df.columns
    assert len(df) == 2
    assert float(df["Close"].iloc[-1]) == 191.0


def test_get_price_history_empty_candles_returns_empty_df():
    client = _make_client()
    client._access_token = "tok"
    client._access_expires_at = _future()
    client._refresh_expires_at = _future(minutes=48 * 60)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"symbol": "AAPL", "empty": True, "candles": []}

    with patch("app.services.schwab_client.httpx.get", return_value=mock_resp):
        df = client.get_price_history("AAPL", "year", 1, "daily", 1)

    assert df.empty


def test_token_refresh_called_when_access_token_expired():
    client = _make_client()
    client._access_token = "old_tok"
    client._access_expires_at = _past()
    client._refresh_token = "refresh_tok"
    client._refresh_expires_at = _future(minutes=48 * 60)

    refresh_resp = MagicMock()
    refresh_resp.status_code = 200
    refresh_resp.json.return_value = {
        "access_token": "new_tok",
        "refresh_token": "new_refresh",
        "expires_in": 1800,
    }

    mock_session_ctx = MagicMock()
    mock_session_ctx.__enter__ = MagicMock(return_value=mock_session_ctx)
    mock_session_ctx.__exit__ = MagicMock(return_value=False)
    client._Session.return_value = mock_session_ctx

    with patch("app.services.schwab_client.httpx.post", return_value=refresh_resp):
        client._ensure_valid_token()

    assert client._access_token == "new_tok"


def test_api_error_raises_schwab_api_error():
    from app.services.schwab_client import SchwabAPIError
    client = _make_client()
    client._access_token = "tok"
    client._access_expires_at = _future()
    client._refresh_expires_at = _future(minutes=48 * 60)

    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"

    with patch("app.services.schwab_client.httpx.get", return_value=mock_resp):
        with pytest.raises(SchwabAPIError):
            client.get_quotes(["AAPL"])


def test_schwab_alias_maps_spx():
    client = _make_client()
    client._access_token = "tok"
    client._access_expires_at = _future()
    client._refresh_expires_at = _future(minutes=48 * 60)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "$SPX.X": {"quote": {"lastPrice": 5000.0, "closePrice": 4980.0}}
    }

    captured_params: dict = {}

    def capture_get(url, **kwargs):
        captured_params.update(kwargs.get("params", {}))
        return mock_resp

    with patch("app.services.schwab_client.httpx.get", side_effect=capture_get):
        result = client.get_quotes(["SPX"])

    assert "$SPX.X" in captured_params["symbols"]
    assert "SPX" in result


def test_get_quotes_no_tokens_raises():
    from app.services.schwab_client import SchwabClient, SchwabAPIError
    client = SchwabClient("key", "secret", "postgresql://user:pass@localhost/test")

    mock_session_ctx = MagicMock()
    mock_session_ctx.__enter__ = MagicMock(return_value=mock_session_ctx)
    mock_session_ctx.__exit__ = MagicMock(return_value=False)
    mock_session_ctx.execute.return_value.fetchone.return_value = None
    client._Session = MagicMock(return_value=mock_session_ctx)

    with pytest.raises(SchwabAPIError, match="No Schwab tokens"):
        client.get_quotes(["AAPL"])
