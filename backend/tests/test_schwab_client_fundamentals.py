from unittest.mock import MagicMock, patch

from app.services.schwab_client import SchwabClient


def _make_client() -> SchwabClient:
    client = SchwabClient.__new__(SchwabClient)  # bypass __init__ (no token setup needed for this test)
    return client


def test_get_instrument_fundamentals_returns_fundamental_dict():
    client = _make_client()
    mock_response = {
        "instruments": [
            {"symbol": "AAPL", "fundamental": {"symbol": "AAPL", "peRatio": 30.5}}
        ]
    }
    with patch.object(client, "_get", return_value=mock_response) as mock_get:
        result = client.get_instrument_fundamentals("aapl")
    mock_get.assert_called_once_with(
        "/marketdata/v1/instruments", {"symbol": "AAPL", "projection": "fundamental"}
    )
    assert result == {"symbol": "AAPL", "peRatio": 30.5}


def test_get_instrument_fundamentals_returns_empty_dict_when_not_found():
    client = _make_client()
    with patch.object(client, "_get", return_value={"instruments": []}):
        result = client.get_instrument_fundamentals("ZZZZ")
    assert result == {}
