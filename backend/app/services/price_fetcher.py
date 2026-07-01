# backend/app/services/price_fetcher.py
import asyncio
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trade import Trade
from app.services.schwab_client import get_schwab_client, SchwabAPIError  # noqa: F401


def _compute_unrealized_pnl(trade: Trade, current_price: float) -> float | None:
    """Proxy P&L using intrinsic value. Returns None when data is missing."""
    if trade.premium is None or trade.strike_price is None:
        return None
    premium = float(trade.premium)
    strike = float(trade.strike_price)
    qty = trade.quantity
    if trade.type == "Sell" and trade.strategy in ("Put", "PutCreditSpread"):
        return round((premium - max(strike - current_price, 0)) * qty * 100, 2)
    if trade.type == "Sell" and trade.strategy in ("Call", "CoveredCall"):
        return round((premium - max(current_price - strike, 0)) * qty * 100, 2)
    return None


def _compute_rsi_14(close: pd.Series) -> float | None:
    """RSI-14 using Wilder's exponential smoothing (alpha = 1/14)."""
    close = close.dropna()
    if len(close) < 15:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    last_loss = float(avg_loss.iloc[-1])
    if last_loss == 0:
        return 100.0
    rs = float(avg_gain.iloc[-1]) / last_loss
    return round(100 - (100 / (1 + rs)), 2)


def _fetch_prices_from_schwab(tickers: list[str]) -> dict[str, float]:
    """Batch-fetch last prices via Schwab quotes API."""
    try:
        client = get_schwab_client()
        quotes = client.get_quotes(tickers)
        return {t: float(q["lastPrice"]) for t, q in quotes.items() if "lastPrice" in q}
    except Exception:
        return {}


async def fetch_quote(ticker: str) -> dict | None:
    """Fetch current price + day stats for a single ticker."""
    try:
        loop = asyncio.get_running_loop()

        def _sync():
            client = get_schwab_client()
            return client.get_quotes([ticker]).get(ticker)

        quote = await loop.run_in_executor(None, _sync)
        if quote is None:
            return None
        price = quote.get("lastPrice")
        if price is None:
            return None
        prev_close = quote.get("closePrice")
        change_pct = round((float(price) - float(prev_close)) / float(prev_close) * 100, 2) if prev_close else None
        return {
            "ticker": ticker,
            "price": round(float(price), 2),
            "change_pct": change_pct,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        return None


def _fetch_rsi_from_schwab(tickers: list[str]) -> dict[str, dict | None]:
    """Batch RSI fetch using Schwab price history — parallel per-ticker calls."""
    result: dict[str, dict | None] = {t: None for t in tickers}
    if not tickers:
        return result
    try:
        client = get_schwab_client()
    except Exception:
        return result

    def fetch_one(ticker: str) -> tuple[str, dict | None]:
        try:
            df = client.get_price_history(ticker, "month", 2, "daily", 1)
            if df is None or df.empty:
                return ticker, None
            close = df["Close"].dropna()
            if close.empty:
                return ticker, None
            price = round(float(close.iloc[-1]), 2)
            rsi = _compute_rsi_14(close)
            return ticker, {"rsi": rsi, "price": price}
        except Exception:
            return ticker, None

    with ThreadPoolExecutor(max_workers=min(len(tickers), 10)) as executor:
        pairs = list(executor.map(fetch_one, tickers))
    for ticker, data in pairs:
        result[ticker] = data
    return result


async def fetch_rsi_batch(tickers: list[str]) -> dict[str, dict | None]:
    """Async wrapper so the event loop is not blocked."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch_rsi_from_schwab, tickers)


async def refresh_open_trades(db: AsyncSession) -> dict:
    """Fetch prices for all open trades; update current_price, last_price_at, unrealized_pnl."""
    stmt = select(Trade).where(Trade.status == "open")
    result = await db.execute(stmt)
    trades = result.scalars().all()

    if not trades:
        return {"trades_updated": 0, "tickers_fetched": 0, "errors": []}

    tickers = list({t.ticker for t in trades})
    prices = _fetch_prices_from_schwab(tickers)

    errors: list[str] = []
    now = datetime.now(timezone.utc)
    trades_updated = 0

    for trade in trades:
        price = prices.get(trade.ticker)
        if price is None:
            errors.append(f"No price for {trade.ticker}")
            continue
        trade.current_price = price
        trade.last_price_at = now
        trade.unrealized_pnl = _compute_unrealized_pnl(trade, price)
        trades_updated += 1

    if trades_updated > 0:
        await db.commit()

    return {"trades_updated": trades_updated, "tickers_fetched": len(prices), "errors": errors}
