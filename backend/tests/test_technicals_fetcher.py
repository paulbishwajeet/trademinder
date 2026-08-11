import pandas as pd
from unittest.mock import MagicMock, patch

from app.services.technicals_fetcher import fetch_technicals


def _make_daily_df(n: int, start_price: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    closes = [start_price + i * 0.1 for i in range(n)]
    return pd.DataFrame({
        "Open": closes, "High": closes, "Low": closes, "Close": closes,
        "Volume": [1_000_000] * n,
    }, index=idx)


def test_fetch_technicals_includes_ma20_and_ma100():
    daily_df = _make_daily_df(250)
    weekly_df = _make_daily_df(120)

    mock_client = MagicMock()
    mock_client.get_price_history.side_effect = [daily_df, weekly_df]

    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        result = fetch_technicals("AAPL")

    assert result["fetch_status"] == "ok"
    assert result["ma_20d"] is not None
    assert result["ma_100d"] is not None
    assert result["price_vs_ma20"] in ("above", "below")
    assert result["price_vs_ma100"] in ("above", "below")


def test_fetch_technicals_ma20_ma100_null_on_short_history():
    daily_df = _make_daily_df(15)
    weekly_df = _make_daily_df(15)

    mock_client = MagicMock()
    mock_client.get_price_history.side_effect = [daily_df, weekly_df]

    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        result = fetch_technicals("AAPL")

    assert result["ma_20d"] is None
    assert result["ma_100d"] is None
    assert result["price_vs_ma20"] is None
    assert result["price_vs_ma100"] is None
