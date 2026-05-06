# backend/tests/test_price_fetcher.py
import pytest
from unittest.mock import patch, MagicMock
from decimal import Decimal
from datetime import date
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.price_fetcher import (
    _compute_unrealized_pnl,
    _fetch_prices_from_yfinance,
    fetch_quote,
    refresh_open_trades,
)
from app.models.trade import Trade


# --- Pure function tests (no DB) ---

def test_pnl_sell_put_itm():
    # Strike 190, current price 185 → intrinsic = 5.00
    # (3.50 - 5.00) * 1 * 100 = -150.00
    trade = Trade(type="Sell", strategy="Put",
                  strike_price=Decimal("190.00"), premium=Decimal("3.50"), quantity=1)
    assert _compute_unrealized_pnl(trade, 185.0) == -150.0


def test_pnl_sell_put_otm():
    # Strike 190, current price 200 → intrinsic = 0
    # (3.50 - 0) * 1 * 100 = 350.00
    trade = Trade(type="Sell", strategy="Put",
                  strike_price=Decimal("190.00"), premium=Decimal("3.50"), quantity=1)
    assert _compute_unrealized_pnl(trade, 200.0) == 350.0


def test_pnl_sell_put_credit_spread():
    # PutCreditSpread uses same formula as Put
    # Strike 190, current price 185 → intrinsic = 5.00
    # (3.50 - 5.00) * 1 * 100 = -150.00
    trade = Trade(type="Sell", strategy="PutCreditSpread",
                  strike_price=Decimal("190.00"), premium=Decimal("3.50"), quantity=1)
    assert _compute_unrealized_pnl(trade, 185.0) == -150.0


def test_pnl_sell_covered_call_itm():
    # Strike 195, current price 200 → intrinsic = 5.00
    # (2.00 - 5.00) * 2 * 100 = -600.00
    trade = Trade(type="Sell", strategy="CoveredCall",
                  strike_price=Decimal("195.00"), premium=Decimal("2.00"), quantity=2)
    assert _compute_unrealized_pnl(trade, 200.0) == -600.0


def test_pnl_sell_call_itm():
    # Bare Call uses same formula as CoveredCall
    # Strike 195, current price 200 → intrinsic = 5.00
    # (2.00 - 5.00) * 1 * 100 = -300.00
    trade = Trade(type="Sell", strategy="Call",
                  strike_price=Decimal("195.00"), premium=Decimal("2.00"), quantity=1)
    assert _compute_unrealized_pnl(trade, 200.0) == -300.0


def test_pnl_null_for_missing_strike():
    trade = Trade(type="Sell", strategy="Put",
                  strike_price=None, premium=Decimal("3.50"), quantity=1)
    assert _compute_unrealized_pnl(trade, 185.0) is None


def test_pnl_null_for_missing_premium():
    trade = Trade(type="Sell", strategy="Put",
                  strike_price=Decimal("190.00"), premium=None, quantity=1)
    assert _compute_unrealized_pnl(trade, 185.0) is None


def test_pnl_null_for_stock():
    trade = Trade(type="Buy", strategy="Stock",
                  strike_price=None, premium=None, quantity=100)
    assert _compute_unrealized_pnl(trade, 185.0) is None


# --- fetch_quote (mock yfinance) ---

async def test_fetch_quote_success():
    mock_info = MagicMock()
    mock_info.last_price = 192.43
    mock_info.previous_close = 194.04

    with patch("app.services.price_fetcher.yf.Ticker") as mock_cls:
        mock_cls.return_value.fast_info = mock_info
        result = await fetch_quote("AAPL")

    assert result is not None
    assert result["ticker"] == "AAPL"
    assert result["price"] == 192.43
    assert "change_pct" in result
    assert "last_updated" in result


async def test_fetch_quote_returns_none_when_price_missing():
    mock_info = MagicMock()
    mock_info.last_price = None

    with patch("app.services.price_fetcher.yf.Ticker") as mock_cls:
        mock_cls.return_value.fast_info = mock_info
        result = await fetch_quote("INVALID")

    assert result is None


async def test_fetch_quote_returns_none_on_exception():
    with patch("app.services.price_fetcher.yf.Ticker", side_effect=Exception("network error")):
        result = await fetch_quote("AAPL")
    assert result is None


# --- refresh_open_trades (mock _fetch_prices_from_yfinance) ---

async def test_refresh_updates_trade_price(client: AsyncClient, db_session: AsyncSession):
    from datetime import date as dt
    resp = await client.post("/api/trades", json={
        "type": "Sell", "category": "Wheel", "strategy": "Put",
        "ticker": "AAPL", "open_date": str(dt.today()),
        "strike_price": "190.00", "premium": "3.50", "quantity": 1,
    })
    assert resp.status_code == 201

    with patch("app.services.price_fetcher._fetch_prices_from_yfinance", return_value={"AAPL": 195.0}):
        result = await refresh_open_trades(db_session)

    assert result["trades_updated"] == 1
    assert result["tickers_fetched"] == 1
    assert result["errors"] == []


async def test_refresh_skips_closed_trades(client: AsyncClient, db_session: AsyncSession):
    from datetime import date as dt
    resp = await client.post("/api/trades", json={
        "type": "Sell", "category": "Wheel", "strategy": "Put",
        "ticker": "MSFT", "open_date": str(dt.today()),
        "strike_price": "400.00", "premium": "5.00", "quantity": 1,
    })
    trade_id = resp.json()["id"]
    await client.post(f"/api/trades/{trade_id}/close")

    with patch("app.services.price_fetcher._fetch_prices_from_yfinance", return_value={"MSFT": 405.0}):
        result = await refresh_open_trades(db_session)

    assert result["trades_updated"] == 0


async def test_refresh_records_error_for_missing_ticker(client: AsyncClient, db_session: AsyncSession):
    from datetime import date as dt
    await client.post("/api/trades", json={
        "type": "Sell", "category": "Wheel", "strategy": "Put",
        "ticker": "AAPL", "open_date": str(dt.today()),
        "strike_price": "190.00", "premium": "3.50", "quantity": 1,
    })

    with patch("app.services.price_fetcher._fetch_prices_from_yfinance", return_value={}):
        result = await refresh_open_trades(db_session)

    assert result["trades_updated"] == 0
    assert len(result["errors"]) == 1
    assert "AAPL" in result["errors"][0]


async def test_refresh_leaves_existing_price_unchanged_when_ticker_missing(client: AsyncClient, db_session: AsyncSession):
    from datetime import date as dt
    from sqlalchemy import select as sa_select
    import uuid
    from app.models.trade import Trade as TradeModel

    resp = await client.post("/api/trades", json={
        "type": "Sell", "category": "Wheel", "strategy": "Put",
        "ticker": "AAPL", "open_date": str(dt.today()),
        "strike_price": "190.00", "premium": "3.50", "quantity": 1,
    })
    trade_id = resp.json()["id"]

    # Seed an existing current_price
    stmt = sa_select(TradeModel).where(TradeModel.id == uuid.UUID(trade_id))
    r = await db_session.execute(stmt)
    t = r.scalar_one()
    t.current_price = 188.0
    await db_session.commit()

    # Now refresh with empty prices (ticker not found)
    with patch("app.services.price_fetcher._fetch_prices_from_yfinance", return_value={}):
        result = await refresh_open_trades(db_session)

    assert result["trades_updated"] == 0

    # Existing price must be unchanged
    await db_session.refresh(t)
    assert float(t.current_price) == 188.0
