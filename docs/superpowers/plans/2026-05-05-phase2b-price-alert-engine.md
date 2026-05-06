# TradeMinder Phase 2B — Price Fetcher + Alert Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add price fetching, P&L computation, an 8-rule alert engine, APScheduler, and a frontend alert feed to TradeMinder.

**Architecture:** Price fetcher fetches current prices via yfinance for all open trades, computes proxy P&L, and updates the DB every 15 minutes during market hours. Alert engine evaluates 8 rules per open trade and inserts deduplicated Alert rows. APScheduler AsyncIOScheduler runs both jobs inside the FastAPI process via lifespan. Frontend dashboard polls /api/alerts and displays a severity-grouped alert feed.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 async, yfinance, APScheduler 3.x (AsyncIOScheduler), pytest-asyncio, React 18, TypeScript, Tailwind CSS

---

## File Map

```
New files:
  backend/app/services/__init__.py
  backend/app/services/price_fetcher.py
  backend/app/services/alert_engine.py
  backend/app/scheduler.py
  backend/tests/test_price_fetcher.py
  backend/tests/test_alert_engine.py
  backend/tests/test_market_router_p2.py
  frontend/src/components/Dashboard/AlertFeed.tsx

Modified files:
  backend/pyproject.toml          — add apscheduler>=3.10.4,<4.0
  backend/app/routers/market.py   — replace /quote and /refresh stubs
  backend/app/main.py             — add lifespan for scheduler
  frontend/src/pages/DashboardPage.tsx — add AlertFeed, wire counts
```

---

## Task 1: Add APScheduler Dependency

- [ ] Edit `backend/pyproject.toml` — add `"apscheduler>=3.10.4,<4.0"` to dependencies list
- [ ] Run `cd /Users/bishwajeetpaul/workspace/github/TradeMinder/backend && source venv/bin/activate && pip install -e .`
- [ ] Verify: `python -c "from apscheduler.schedulers.asyncio import AsyncIOScheduler; print('ok')"`
- [ ] Commit: `git add backend/pyproject.toml && git commit -m "chore: add apscheduler dependency"`

---

## Task 2: Price Fetcher Service (TDD)

**Files:**
- Create: `backend/app/services/__init__.py` (empty)
- Create: `backend/tests/test_price_fetcher.py`
- Create: `backend/app/services/price_fetcher.py`

### Step 1: Write failing tests

- [ ] Create `backend/tests/test_price_fetcher.py`:

```python
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


def test_pnl_sell_covered_call_itm():
    # Strike 195, current price 200 → intrinsic = 5.00
    # (2.00 - 5.00) * 2 * 100 = -600.00
    trade = Trade(type="Sell", strategy="CoveredCall",
                  strike_price=Decimal("195.00"), premium=Decimal("2.00"), quantity=2)
    assert _compute_unrealized_pnl(trade, 200.0) == -600.0


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
```

### Step 2: Run tests — verify they fail

- [ ] `cd /Users/bishwajeetpaul/workspace/github/TradeMinder/backend && source venv/bin/activate && pytest tests/test_price_fetcher.py -v`

Expected: ImportError (module doesn't exist yet).

### Step 3: Create `app/services/__init__.py`

- [ ] Create `backend/app/services/__init__.py` (empty file)

### Step 4: Create `app/services/price_fetcher.py`

- [ ] Create `backend/app/services/price_fetcher.py`:

```python
# backend/app/services/price_fetcher.py
import yfinance as yf
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
```

### Step 5: Run tests

- [ ] `cd /Users/bishwajeetpaul/workspace/github/TradeMinder/backend && source venv/bin/activate && pytest tests/test_price_fetcher.py -v`

Expected: all PASS.

### Step 6: Run full suite

- [ ] `pytest tests/ -v`

Expected: all PASS.

### Step 7: Commit

- [ ] `cd /Users/bishwajeetpaul/workspace/github/TradeMinder && git add backend/app/services/__init__.py backend/app/services/price_fetcher.py backend/tests/test_price_fetcher.py && git commit -m "feat: price fetcher service with proxy P&L calculation + tests"`

---

## Task 3: Alert Engine Service (TDD)

**Files:**
- Create: `backend/tests/test_alert_engine.py`
- Create: `backend/app/services/alert_engine.py`

### Step 1: Write failing tests

- [ ] Create `backend/tests/test_alert_engine.py`:

```python
# backend/tests/test_alert_engine.py
import uuid
import pytest
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import AsyncClient

from app.models.trade import Trade
from app.models.alert import Alert
from app.models.rationale import Rationale
from app.services.alert_engine import run as run_alert_engine


TRADE_PAYLOAD = {
    "type": "Sell",
    "category": "Wheel",
    "strategy": "Put",
    "ticker": "AAPL",
    "open_date": str(date.today()),
    "strike_price": "190.00",
    "premium": "4.00",
    "quantity": 1,
}


async def _create_trade(client: AsyncClient) -> str:
    resp = await client.post("/api/trades", json=TRADE_PAYLOAD)
    assert resp.status_code == 201
    return resp.json()["id"]


async def _set_price_and_pnl(db: AsyncSession, trade_id: str,
                               current_price: float | None = None,
                               unrealized_pnl: float | None = None):
    stmt = select(Trade).where(Trade.id == uuid.UUID(trade_id))
    r = await db.execute(stmt)
    trade = r.scalar_one()
    if current_price is not None:
        trade.current_price = current_price
    if unrealized_pnl is not None:
        trade.unrealized_pnl = unrealized_pnl
    await db.commit()


async def test_profit_target_fires(client: AsyncClient, db_session: AsyncSession):
    trade_id = await _create_trade(client)
    # max_profit = 4.00 * 1 * 100 = 400; need pnl >= 200 (50%)
    await _set_price_and_pnl(db_session, trade_id, current_price=196.0, unrealized_pnl=210.0)

    result = await run_alert_engine(db_session)
    assert result["alerts_created"] >= 1

    stmt = select(Alert).where(
        Alert.trade_id == uuid.UUID(trade_id),
        Alert.alert_type == "profit_target",
    )
    r = await db_session.execute(stmt)
    assert r.scalar_one_or_none() is not None


async def test_profit_target_deduplicates(client: AsyncClient, db_session: AsyncSession):
    trade_id = await _create_trade(client)
    await _set_price_and_pnl(db_session, trade_id, current_price=196.0, unrealized_pnl=210.0)

    await run_alert_engine(db_session)
    await run_alert_engine(db_session)

    stmt = select(Alert).where(
        Alert.trade_id == uuid.UUID(trade_id),
        Alert.alert_type == "profit_target",
    )
    r = await db_session.execute(stmt)
    assert len(r.scalars().all()) == 1


async def test_stop_loss_fires(client: AsyncClient, db_session: AsyncSession):
    trade_id = await _create_trade(client)
    # max_profit = 400; stop_loss triggers at pnl <= -800
    await _set_price_and_pnl(db_session, trade_id, current_price=170.0, unrealized_pnl=-850.0)

    await run_alert_engine(db_session)

    stmt = select(Alert).where(
        Alert.trade_id == uuid.UUID(trade_id),
        Alert.alert_type == "stop_loss",
    )
    r = await db_session.execute(stmt)
    assert r.scalar_one_or_none() is not None


async def test_dte_critical_fires_and_not_threshold(client: AsyncClient, db_session: AsyncSession):
    payload = {**TRADE_PAYLOAD, "expiry_date": str(date.today() + timedelta(days=5))}
    resp = await client.post("/api/trades", json=payload)
    trade_id = resp.json()["id"]

    await run_alert_engine(db_session)

    stmt_critical = select(Alert).where(
        Alert.trade_id == uuid.UUID(trade_id),
        Alert.alert_type == "dte_critical",
    )
    r = await db_session.execute(stmt_critical)
    assert r.scalar_one_or_none() is not None

    # dte_threshold must NOT fire when dte <= 7
    stmt_threshold = select(Alert).where(
        Alert.trade_id == uuid.UUID(trade_id),
        Alert.alert_type == "dte_threshold",
    )
    r2 = await db_session.execute(stmt_threshold)
    assert r2.scalar_one_or_none() is None


async def test_dte_threshold_fires(client: AsyncClient, db_session: AsyncSession):
    payload = {**TRADE_PAYLOAD, "expiry_date": str(date.today() + timedelta(days=15))}
    resp = await client.post("/api/trades", json=payload)
    trade_id = resp.json()["id"]

    await run_alert_engine(db_session)

    stmt = select(Alert).where(
        Alert.trade_id == uuid.UUID(trade_id),
        Alert.alert_type == "dte_threshold",
    )
    r = await db_session.execute(stmt)
    assert r.scalar_one_or_none() is not None


async def test_earnings_approaching_fires(client: AsyncClient, db_session: AsyncSession):
    trade_id = await _create_trade(client)

    stmt = select(Rationale).where(Rationale.trade_id == uuid.UUID(trade_id))
    r = await db_session.execute(stmt)
    rationale = r.scalar_one()
    rationale.next_earnings_date = date.today() + timedelta(days=3)
    await db_session.commit()

    await run_alert_engine(db_session)

    stmt = select(Alert).where(
        Alert.trade_id == uuid.UUID(trade_id),
        Alert.alert_type == "earnings_approaching",
    )
    r = await db_session.execute(stmt)
    assert r.scalar_one_or_none() is not None


async def test_assignment_risk_fires(client: AsyncClient, db_session: AsyncSession):
    # Strike 190, current 191.5 → within 2%
    trade_id = await _create_trade(client)
    await _set_price_and_pnl(db_session, trade_id, current_price=191.5)

    await run_alert_engine(db_session)

    stmt = select(Alert).where(
        Alert.trade_id == uuid.UUID(trade_id),
        Alert.alert_type == "assignment_risk",
    )
    r = await db_session.execute(stmt)
    assert r.scalar_one_or_none() is not None


async def test_overdue_review_fires(client: AsyncClient, db_session: AsyncSession):
    trade_id = await _create_trade(client)

    # Age the trade by 6 days
    stmt = select(Trade).where(Trade.id == uuid.UUID(trade_id))
    r = await db_session.execute(stmt)
    trade = r.scalar_one()
    trade.created_at = datetime.now(timezone.utc) - timedelta(days=6)
    await db_session.commit()

    await run_alert_engine(db_session)

    stmt = select(Alert).where(
        Alert.trade_id == uuid.UUID(trade_id),
        Alert.alert_type == "overdue_review",
    )
    r = await db_session.execute(stmt)
    assert r.scalar_one_or_none() is not None


async def test_deep_itm_fires(client: AsyncClient, db_session: AsyncSession):
    payload = {**TRADE_PAYLOAD, "strategy": "CoveredCall", "strike_price": "190.00"}
    resp = await client.post("/api/trades", json=payload)
    trade_id = resp.json()["id"]
    # 202 is 6.3% above strike 190
    await _set_price_and_pnl(db_session, trade_id, current_price=202.0)

    await run_alert_engine(db_session)

    stmt = select(Alert).where(
        Alert.trade_id == uuid.UUID(trade_id),
        Alert.alert_type == "deep_itm",
    )
    r = await db_session.execute(stmt)
    assert r.scalar_one_or_none() is not None


async def test_no_alerts_for_closed_trade(client: AsyncClient, db_session: AsyncSession):
    trade_id = await _create_trade(client)
    await client.post(f"/api/trades/{trade_id}/close")

    result = await run_alert_engine(db_session)

    stmt = select(Alert).where(Alert.trade_id == uuid.UUID(trade_id))
    r = await db_session.execute(stmt)
    assert r.scalars().all() == []
```

### Step 2: Run tests — verify they fail

- [ ] `cd /Users/bishwajeetpaul/workspace/github/TradeMinder/backend && source venv/bin/activate && pytest tests/test_alert_engine.py -v`

Expected: ImportError.

### Step 3: Create `app/services/alert_engine.py`

- [ ] Create `backend/app/services/alert_engine.py`:

```python
# backend/app/services/alert_engine.py
import uuid
from datetime import date, datetime, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.alert import Alert
from app.models.commentary import Commentary
from app.models.trade import Trade


async def _alert_exists(db: AsyncSession, trade_id: uuid.UUID, alert_type: str) -> bool:
    stmt = select(Alert).where(
        Alert.trade_id == trade_id,
        Alert.alert_type == alert_type,
        Alert.is_dismissed == False,  # noqa: E712
        Alert.is_read == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


def _make_alert(trade_id: uuid.UUID, alert_type: str, severity: str,
                title: str, message: str) -> Alert:
    return Alert(trade_id=trade_id, alert_type=alert_type, severity=severity,
                 title=title, message=message)


async def _evaluate_trade(
    trade: Trade,
    last_commentary_at: datetime | None,
    db: AsyncSession,
) -> list[Alert]:
    alerts: list[Alert] = []
    ticker = trade.ticker

    # Rules 1 & 2: profit_target, stop_loss
    if (trade.unrealized_pnl is not None
            and trade.premium is not None
            and trade.strike_price is not None
            and trade.type == "Sell"):
        max_profit = float(trade.premium) * trade.quantity * 100
        pnl = float(trade.unrealized_pnl)

        if max_profit > 0:
            pnl_pct = pnl / max_profit
            if pnl_pct >= 0.50 and not await _alert_exists(db, trade.id, "profit_target"):
                alerts.append(_make_alert(
                    trade.id, "profit_target", "warning",
                    f"{ticker}: Profit target reached",
                    f"Unrealized P&L is ${pnl:.0f} ({pnl_pct * 100:.0f}% of max profit). Consider closing.",
                ))

        if pnl <= -(max_profit * 2) and not await _alert_exists(db, trade.id, "stop_loss"):
            alerts.append(_make_alert(
                trade.id, "stop_loss", "urgent",
                f"{ticker}: Stop loss triggered",
                f"Unrealized loss is ${abs(pnl):.0f} (2× premium received). Review immediately.",
            ))

    # Rules 3 & 4: dte_critical, dte_threshold
    if trade.expiry_date is not None:
        dte = (trade.expiry_date - date.today()).days
        if dte <= 7 and not await _alert_exists(db, trade.id, "dte_critical"):
            alerts.append(_make_alert(
                trade.id, "dte_critical", "urgent",
                f"{ticker}: {dte} DTE — critical",
                f"Option expires in {dte} days. Close, roll, or accept assignment.",
            ))
        elif dte <= 21 and not await _alert_exists(db, trade.id, "dte_threshold"):
            alerts.append(_make_alert(
                trade.id, "dte_threshold", "warning",
                f"{ticker}: {dte} DTE — approaching expiry",
                f"Option expires in {dte} days. Review your exit strategy.",
            ))

    # Rule 5: earnings_approaching
    if trade.rationale and trade.rationale.next_earnings_date:
        days_to_earnings = (trade.rationale.next_earnings_date - date.today()).days
        if 0 <= days_to_earnings <= 5 and not await _alert_exists(db, trade.id, "earnings_approaching"):
            alerts.append(_make_alert(
                trade.id, "earnings_approaching", "warning",
                f"{ticker}: Earnings in {days_to_earnings} days",
                f"Earnings on {trade.rationale.next_earnings_date}. Review position and IV risk.",
            ))

    # Rule 6: assignment_risk (Put within 2% of strike)
    if (trade.current_price is not None
            and trade.strike_price is not None
            and trade.strategy in ("Put", "PutCreditSpread")):
        current = float(trade.current_price)
        strike = float(trade.strike_price)
        if abs(strike - current) / strike <= 0.02 and not await _alert_exists(db, trade.id, "assignment_risk"):
            alerts.append(_make_alert(
                trade.id, "assignment_risk", "warning",
                f"{ticker}: Assignment risk — price near strike",
                f"Current price ${current:.2f} is within 2% of strike ${strike:.2f}.",
            ))

    # Rule 7: overdue_review (no commentary in 5+ days)
    baseline = last_commentary_at if last_commentary_at is not None else trade.created_at
    if baseline.tzinfo is None:
        baseline = baseline.replace(tzinfo=timezone.utc)
    days_since = (datetime.now(timezone.utc) - baseline).days
    if days_since >= 5 and not await _alert_exists(db, trade.id, "overdue_review"):
        alerts.append(_make_alert(
            trade.id, "overdue_review", "info",
            f"{ticker}: Overdue review",
            f"No commentary in {days_since} days. Log an update on this position.",
        ))

    # Rule 8: deep_itm (CoveredCall >5% above strike)
    if (trade.current_price is not None
            and trade.strike_price is not None
            and trade.strategy == "CoveredCall"):
        current = float(trade.current_price)
        strike = float(trade.strike_price)
        if (current - strike) / strike >= 0.05 and not await _alert_exists(db, trade.id, "deep_itm"):
            alerts.append(_make_alert(
                trade.id, "deep_itm", "urgent",
                f"{ticker}: Covered call deep ITM",
                f"Current price ${current:.2f} is >5% above strike ${strike:.2f}. High assignment risk.",
            ))

    return alerts


async def run(db: AsyncSession) -> dict:
    """Evaluate all 8 alert rules for all open trades. Returns alert counts."""
    stmt = (
        select(Trade)
        .where(Trade.status == "open")
        .options(selectinload(Trade.rationale))
    )
    result = await db.execute(stmt)
    trades = result.scalars().all()

    if not trades:
        return {"alerts_created": 0, "trades_evaluated": 0}

    trade_ids = [t.id for t in trades]
    commentary_stmt = (
        select(Commentary.trade_id, func.max(Commentary.created_at).label("last_at"))
        .where(Commentary.trade_id.in_(trade_ids))
        .group_by(Commentary.trade_id)
    )
    commentary_result = await db.execute(commentary_stmt)
    last_commentary: dict[uuid.UUID, datetime] = {
        row.trade_id: row.last_at for row in commentary_result
    }

    alerts_created = 0
    for trade in trades:
        new_alerts = await _evaluate_trade(trade, last_commentary.get(trade.id), db)
        for alert in new_alerts:
            db.add(alert)
            alerts_created += 1

    if alerts_created > 0:
        await db.commit()

    return {"alerts_created": alerts_created, "trades_evaluated": len(trades)}
```

### Step 4: Run alert engine tests

- [ ] `cd /Users/bishwajeetpaul/workspace/github/TradeMinder/backend && source venv/bin/activate && pytest tests/test_alert_engine.py -v`

Expected: all PASS.

### Step 5: Run full suite

- [ ] `pytest tests/ -v`

Expected: all PASS.

### Step 6: Commit

- [ ] `cd /Users/bishwajeetpaul/workspace/github/TradeMinder && git add backend/app/services/alert_engine.py backend/tests/test_alert_engine.py && git commit -m "feat: alert engine with 8 rules, deduplication + tests"`

---

## Task 4: Scheduler + Lifespan

**Files:**
- Create: `backend/app/scheduler.py`
- Modify: `backend/app/main.py`

### Step 1: Create `app/scheduler.py`

- [ ] Create `backend/app/scheduler.py`:

```python
# backend/app/scheduler.py
from datetime import datetime, time
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.database import AsyncSessionLocal

scheduler = AsyncIOScheduler(timezone="America/New_York")


def is_market_hours() -> bool:
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    return time(9, 30) <= now.time() <= time(16, 0)


async def price_refresh_job() -> None:
    if not is_market_hours():
        return
    from app.services.price_fetcher import refresh_open_trades
    async with AsyncSessionLocal() as db:
        await refresh_open_trades(db)


async def alert_engine_job() -> None:
    if not is_market_hours():
        return
    from app.services.alert_engine import run as run_alert_engine
    async with AsyncSessionLocal() as db:
        await run_alert_engine(db)


def start_scheduler(interval_minutes: int | None = None) -> None:
    minutes = interval_minutes or settings.price_refresh_interval_minutes
    scheduler.add_job(price_refresh_job, "interval", minutes=minutes, id="price_refresh")
    scheduler.add_job(alert_engine_job, "interval", minutes=minutes, seconds=30, id="alert_engine")
    scheduler.start()
```

### Step 2: Update `app/main.py` to add lifespan

- [ ] Replace the full contents of `backend/app/main.py` with:

```python
# backend/app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import trades, commentary, alerts, market, briefing
from app.scheduler import scheduler, start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="TradeMinder API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


app.include_router(trades.router)
app.include_router(commentary.router)
app.include_router(alerts.router)
app.include_router(market.router)
app.include_router(briefing.router)
```

### Step 3: Verify the app starts

- [ ] `cd /Users/bishwajeetpaul/workspace/github/TradeMinder/backend && source venv/bin/activate && python -c "from app.main import app; print('app loaded ok')"`

Expected: `app loaded ok`

### Step 4: Run full test suite

- [ ] `pytest tests/ -v`

Expected: all PASS. (Scheduler starts/stops during tests — this is fine since tests use a separate TestClient that doesn't trigger lifespan by default with httpx AsyncClient.)

### Step 5: Commit

- [ ] `cd /Users/bishwajeetpaul/workspace/github/TradeMinder && git add backend/app/scheduler.py backend/app/main.py && git commit -m "feat: APScheduler asyncio scheduler with market-hours guard + FastAPI lifespan"`

---

## Task 5: Market Router — Replace 501 Stubs (TDD)

**Files:**
- Create: `backend/tests/test_market_router_p2.py`
- Modify: `backend/app/routers/market.py`

### Step 1: Write failing tests

- [ ] Create `backend/tests/test_market_router_p2.py`:

```python
# backend/tests/test_market_router_p2.py
from unittest.mock import patch
from httpx import AsyncClient


async def test_quote_returns_price(client: AsyncClient):
    mock_result = {
        "ticker": "AAPL",
        "price": 192.43,
        "change_pct": -0.82,
        "last_updated": "2026-05-05T14:32:00Z",
    }
    with patch("app.routers.market.fetch_quote", return_value=mock_result):
        response = await client.get("/api/market/quote/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["ticker"] == "AAPL"
    assert data["price"] == 192.43


async def test_quote_lowercases_ticker(client: AsyncClient):
    mock_result = {
        "ticker": "AAPL",
        "price": 192.43,
        "change_pct": -0.82,
        "last_updated": "2026-05-05T14:32:00Z",
    }
    with patch("app.routers.market.fetch_quote", return_value=mock_result) as mock_fn:
        await client.get("/api/market/quote/aapl")
    # Verify it was called with uppercase
    mock_fn.assert_called_once_with("AAPL")


async def test_quote_returns_404_for_unknown_ticker(client: AsyncClient):
    with patch("app.routers.market.fetch_quote", return_value=None):
        response = await client.get("/api/market/quote/INVALID")
    assert response.status_code == 404


async def test_refresh_triggers_price_and_alert_engine(client: AsyncClient):
    price_result = {"trades_updated": 3, "tickers_fetched": 2, "errors": []}
    alert_result = {"alerts_created": 1, "trades_evaluated": 3}

    with patch("app.routers.market.refresh_open_trades", return_value=price_result), \
         patch("app.routers.market.run_alert_engine", return_value=alert_result):
        response = await client.post("/api/market/refresh")

    assert response.status_code == 200
    data = response.json()
    assert data["trades_updated"] == 3
    assert data["alerts_created"] == 1
    assert data["tickers_fetched"] == 2
    assert data["errors"] == []


async def test_options_still_501(client: AsyncClient):
    response = await client.get("/api/market/options/AAPL")
    assert response.status_code == 501


async def test_prefetch_still_501(client: AsyncClient):
    response = await client.post("/api/market/prefetch/AAPL")
    assert response.status_code == 501
```

### Step 2: Run tests — verify they fail

- [ ] `cd /Users/bishwajeetpaul/workspace/github/TradeMinder/backend && source venv/bin/activate && pytest tests/test_market_router_p2.py -v`

Expected: failures (quote returns 501, refresh returns 501).

### Step 3: Replace `app/routers/market.py`

- [ ] Replace the full contents of `backend/app/routers/market.py` with:

```python
# backend/app/routers/market.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.price_fetcher import fetch_quote, refresh_open_trades
from app.services.alert_engine import run as run_alert_engine

router = APIRouter(prefix="/api/market", tags=["market"])

NOT_IMPLEMENTED = JSONResponse({"detail": "not implemented"}, status_code=501)


@router.get("/quote/{ticker}")
async def get_quote(ticker: str):
    result = await fetch_quote(ticker.upper())
    if result is None:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker.upper()} not found")
    return result


@router.post("/refresh")
async def refresh_prices(db: AsyncSession = Depends(get_db)):
    price_result = await refresh_open_trades(db)
    alert_result = await run_alert_engine(db)
    return {
        "trades_updated": price_result["trades_updated"],
        "tickers_fetched": price_result["tickers_fetched"],
        "alerts_created": alert_result["alerts_created"],
        "errors": price_result["errors"],
    }


@router.get("/options/{ticker}")
async def get_options(ticker: str):
    return NOT_IMPLEMENTED


@router.post("/prefetch/{ticker}")
async def prefetch_indicators(ticker: str):
    return NOT_IMPLEMENTED
```

### Step 4: Run market router tests

- [ ] `cd /Users/bishwajeetpaul/workspace/github/TradeMinder/backend && source venv/bin/activate && pytest tests/test_market_router_p2.py -v`

Expected: all 6 PASS.

### Step 5: Run full suite

- [ ] `pytest tests/ -v`

Expected: all PASS.

### Step 6: Commit

- [ ] `cd /Users/bishwajeetpaul/workspace/github/TradeMinder && git add backend/app/routers/market.py backend/tests/test_market_router_p2.py && git commit -m "feat: market router — /quote and /refresh endpoints replace 501 stubs"`

---

## Task 6: Frontend Alert Feed

**Files:**
- Create: `frontend/src/components/Dashboard/AlertFeed.tsx`
- Modify: `frontend/src/pages/DashboardPage.tsx`

### Step 1: Create `AlertFeed.tsx`

- [ ] Create `frontend/src/components/Dashboard/AlertFeed.tsx`:

```tsx
// frontend/src/components/Dashboard/AlertFeed.tsx
import { useState, useEffect, useCallback } from 'react'
import type { Alert } from '../../types'
import { alertsApi } from '../../api/alerts'

const SEVERITY_STYLES: Record<string, string> = {
  urgent: 'border-l-4 border-red-500 bg-red-50',
  warning: 'border-l-4 border-yellow-500 bg-yellow-50',
  info: 'border-l-4 border-gray-400 bg-gray-50',
}

const SEVERITY_ORDER: Record<string, number> = { urgent: 0, warning: 1, info: 2 }

function timeAgo(iso: string): string {
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

interface Props {
  onCountChange?: (count: number) => void
}

export function AlertFeed({ onCountChange }: Props) {
  const [alerts, setAlerts] = useState<Alert[]>([])

  const load = useCallback(async () => {
    const data = await alertsApi.list()
    const sorted = [...data].sort(
      (a, b) => (SEVERITY_ORDER[a.severity] ?? 3) - (SEVERITY_ORDER[b.severity] ?? 3),
    )
    setAlerts(sorted)
    onCountChange?.(data.length)
  }, [onCountChange])

  useEffect(() => {
    load()
    const interval = setInterval(load, 60000)
    return () => clearInterval(interval)
  }, [load])

  const handleRead = async (id: string) => {
    await alertsApi.markRead(id)
    load()
  }

  const handleDismiss = async (id: string) => {
    await alertsApi.dismiss(id)
    load()
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4">
      <h2 className="text-sm font-semibold text-gray-700 mb-3">
        Alerts
        {alerts.length > 0 && (
          <span className="ml-2 px-1.5 py-0.5 bg-red-100 text-red-700 rounded text-xs">
            {alerts.length}
          </span>
        )}
      </h2>

      {alerts.length === 0 ? (
        <p className="text-sm text-gray-400">No active alerts.</p>
      ) : (
        <div className="space-y-2">
          {alerts.map(alert => (
            <div
              key={alert.id}
              className={`rounded p-3 ${SEVERITY_STYLES[alert.severity] ?? 'border-l-4 border-gray-400 bg-gray-50'} ${alert.is_read ? 'opacity-60' : ''}`}
            >
              <div className="flex justify-between items-start">
                <p className="text-sm font-medium text-gray-800">{alert.title}</p>
                <span className="text-xs text-gray-400 ml-2 shrink-0">{timeAgo(alert.triggered_at)}</span>
              </div>
              <p className="text-xs text-gray-600 mt-0.5">{alert.message}</p>
              <div className="flex gap-3 mt-2">
                {!alert.is_read && (
                  <button
                    onClick={() => handleRead(alert.id)}
                    className="text-xs text-blue-600 hover:underline"
                  >
                    Mark read
                  </button>
                )}
                <button
                  onClick={() => handleDismiss(alert.id)}
                  className="text-xs text-gray-500 hover:underline"
                >
                  Dismiss
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
```

### Step 2: Replace `DashboardPage.tsx`

- [ ] Replace the full contents of `frontend/src/pages/DashboardPage.tsx` with:

```tsx
// frontend/src/pages/DashboardPage.tsx
import { useState, useEffect } from 'react'
import { AlertFeed } from '../components/Dashboard/AlertFeed'
import { tradesApi } from '../api/trades'

export function DashboardPage() {
  const [openTradeCount, setOpenTradeCount] = useState<number | null>(null)
  const [alertCount, setAlertCount] = useState<number | null>(null)

  useEffect(() => {
    tradesApi.list({ status: 'open' }).then(trades => setOpenTradeCount(trades.length))
  }, [])

  const stats = [
    ['Active Trades', openTradeCount],
    ['Open Alerts', alertCount],
    ['Pending Review', '—'],
  ] as const

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="mt-1 text-gray-500">Morning briefing coming in Phase 3.</p>
      </div>

      <div className="grid grid-cols-3 gap-4">
        {stats.map(([label, value]) => (
          <div key={label} className="bg-white rounded-lg border border-gray-200 p-4">
            <p className="text-sm text-gray-500">{label}</p>
            <p className="text-3xl font-bold text-gray-900 mt-1">
              {value !== null && value !== undefined ? value : '—'}
            </p>
          </div>
        ))}
      </div>

      <AlertFeed onCountChange={setAlertCount} />
    </div>
  )
}
```

### Step 3: Verify TypeScript compiles

- [ ] `cd /Users/bishwajeetpaul/workspace/github/TradeMinder/frontend && npx tsc --noEmit`

Expected: no errors.

### Step 4: Commit

- [ ] `cd /Users/bishwajeetpaul/workspace/github/TradeMinder && git add frontend/src/components/Dashboard/AlertFeed.tsx frontend/src/pages/DashboardPage.tsx && git commit -m "feat: alert feed component on dashboard with severity grouping + polling"`
