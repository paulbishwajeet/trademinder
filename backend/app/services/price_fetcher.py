# backend/app/services/price_fetcher.py
import asyncio
import yfinance as yf
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trade import Trade


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


def _fetch_prices_from_yfinance(tickers: list[str]) -> dict[str, float]:
    """Batch-fetch last prices. Extracted for testability."""
    try:
        data = yf.Tickers(" ".join(tickers)).history(period="1d", interval="1m")
        if data.empty:
            return {}
        close = data["Close"]
        prices: dict[str, float] = {}
        for ticker in tickers:
            if ticker in close.columns:
                series = close[ticker].dropna()
                if not series.empty:
                    prices[ticker] = float(series.iloc[-1])
        return prices
    except Exception:
        return {}


async def fetch_quote(ticker: str) -> dict | None:
    """Fetch current price + day stats for a single ticker."""
    try:
        fast_info = yf.Ticker(ticker).fast_info
        price = fast_info.last_price
        if price is None:
            return None
        prev_close = fast_info.previous_close
        change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close else None
        return {
            "ticker": ticker,
            "price": round(float(price), 2),
            "change_pct": change_pct,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
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


def _fetch_one_rsi(ticker: str) -> tuple[str, float | None]:
    try:
        df = yf.download(ticker, period="45d", interval="1d", progress=False, auto_adjust=True)
        if df is None or df.empty:
            return ticker, None
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        return ticker, _compute_rsi_14(close)
    except Exception:
        return ticker, None


def _fetch_rsi_from_yfinance(tickers: list[str]) -> dict[str, float | None]:
    """Parallel RSI fetch — 5 workers keeps yfinance from throttling."""
    with ThreadPoolExecutor(max_workers=5) as ex:
        return dict(ex.map(_fetch_one_rsi, tickers))


async def fetch_rsi_batch(tickers: list[str]) -> dict[str, float | None]:
    """Async wrapper so the event loop is not blocked."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_rsi_from_yfinance, tickers)


async def refresh_open_trades(db: AsyncSession) -> dict:
    """Fetch prices for all open trades; update current_price, last_price_at, unrealized_pnl."""
    stmt = select(Trade).where(Trade.status == "open")
    result = await db.execute(stmt)
    trades = result.scalars().all()

    if not trades:
        return {"trades_updated": 0, "tickers_fetched": 0, "errors": []}

    tickers = list({t.ticker for t in trades})
    prices = _fetch_prices_from_yfinance(tickers)

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
