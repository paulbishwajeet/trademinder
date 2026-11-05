"""Part 4: behaviour while market data is offline (pure 503s, mixed endpoints, stale caches,
scheduler, signal engine) and the provider import boundary."""
import ast
import pathlib
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.services import market_data
from app.services.market_data import ProviderStatus
from app.services.market_data_errors import MarketDataUnavailable


class FakeProvider:
    """Stands in for the configured provider; offline raises like SchwabClient does."""
    name = "schwab"

    def __init__(self, offline: bool):
        self.offline = offline
        self.calls = 0

    def _call(self, *a, **k):
        self.calls += 1
        if self.offline:
            raise MarketDataUnavailable("Schwab refresh token expired")
        raise AssertionError("online market calls are not expected in these tests")

    get_quotes = get_price_history = get_option_chain = get_instrument_fundamentals = _call

    def is_offline(self):
        return self.offline

    def refresh_offline_state(self):
        return self.offline

    def status(self):
        return ProviderStatus(self.name, self.offline, None, None, None)


@pytest.fixture
def offline(monkeypatch):
    provider = FakeProvider(offline=True)
    monkeypatch.setattr(market_data, "_provider", provider)
    return provider


@pytest.fixture
def online(monkeypatch):
    provider = FakeProvider(offline=False)
    monkeypatch.setattr(market_data, "_provider", provider)
    return provider


@pytest.fixture(autouse=True)
def _clear_signal_caches():
    from app.services import cc_signal, cc_timing_signal, sp_timing_signal
    for cache in (cc_signal._combined_signal_cache, cc_timing_signal._cc_timing_cache, sp_timing_signal._sp_timing_cache):
        cache.clear()
    yield
    for cache in (cc_signal._combined_signal_cache, cc_timing_signal._cc_timing_cache, sp_timing_signal._sp_timing_cache):
        cache.clear()


PUT = {
    "type": "Sell", "category": "WHEEL", "strategy": "Sell Put", "ticker": "NVDA",
    "open_date": str(date.today()), "expiry_date": str(date.today() + timedelta(days=30)),
    "strike_price": "120.00", "quantity": 1, "premium": "3.00", "etrade_symbol": "NVDA--261218P00120000",
}
STOCK = {"type": "Buy", "category": "WHEEL", "strategy": "Stock", "ticker": "NVDA",
         "open_date": str(date.today()), "quantity": 100, "premium": "110.00"}


async def _priced(db_session, trade_id: str, price: str, pnl: str | None = None):
    from app.models.trade import Trade
    trade = await db_session.get(Trade, uuid.UUID(trade_id))
    trade.current_price = Decimal(price)
    trade.unrealized_pnl = Decimal(pnl) if pnl else None
    trade.last_price_at = datetime.now(timezone.utc)
    await db_session.commit()


# ── pure market endpoints → 503 market_data_offline ─────────────────────────

@pytest.mark.parametrize("method, path, body", [
    ("get", "/api/market/quote/NVDA", None),
    ("post", "/api/market/rsi", {"tickers": ["NVDA", "AMD"]}),
    ("get", "/api/market/technicals/NVDA", None),
    ("get", "/api/market/macd-crossover/NVDA", None),
    ("get", "/api/market/rsi-crossover/NVDA", None),
    ("get", "/api/market/volume-spikes/NVDA", None),
    ("get", "/api/market/cc-signal/NVDA", None),
    ("get", "/api/market/sp-signal/NVDA", None),
    ("get", "/api/market/combined-signal/NVDA", None),
    ("get", "/api/market/cc-timing-signal/NVDA", None),
    ("get", "/api/market/sp-timing-signal/NVDA", None),
    ("get", "/api/market/option-price/NVDA?strike=120&expiry=2026-12-18&option_type=put", None),
    ("get", "/api/chain/NVDA", None),
    ("get", "/api/screener/preview/NVDA", None),
])
async def test_pure_market_endpoints_return_503(client, offline, method, path, body):
    resp = await getattr(client, method)(path, **({"json": body} if body is not None else {}))
    assert resp.status_code == 503, resp.text
    assert resp.json() == {"detail": "Market data offline", "code": "market_data_offline"}


async def test_manual_price_refresh_503_and_prices_kept(client, db_session, offline):
    trade = (await client.post("/api/trades", json=PUT)).json()
    await _priced(db_session, trade["id"], "118.50")
    resp = await client.post("/api/market/refresh")
    assert resp.status_code == 503 and resp.json()["code"] == "market_data_offline"
    from app.models.trade import Trade
    db_session.expire_all()
    assert (await db_session.get(Trade, uuid.UUID(trade["id"]))).current_price == Decimal("118.50")


# ── stale caches ────────────────────────────────────────────────────────────

async def test_cached_timing_signal_served_stale(client, offline):
    from app.services import cc_timing_signal, sp_timing_signal
    as_of = "2026-11-03T15:00:00+00:00"
    old = time.time() - 6 * 3600  # older than the 4h TTL
    cc_timing_signal._cc_timing_cache["NVDA"] = ({"ticker": "NVDA", "score": 61, "cached_at": as_of}, old)
    sp_timing_signal._sp_timing_cache["NVDA"] = ({"ticker": "NVDA", "score": 40, "cached_at": as_of}, old)
    for path in ("/api/market/cc-timing-signal/NVDA", "/api/market/sp-timing-signal/NVDA?refresh=true"):
        body = (await client.get(path)).json()
        assert body["score"] in (61, 40) and body["stale"] is True and body["as_of"] == as_of


async def test_cached_combined_signal_served_stale(client, offline):
    from app.services import cc_signal
    as_of = "2026-11-03T15:00:00+00:00"
    cc_signal._combined_signal_cache["NVDA"] = (
        {"cc": {"grade": "sell", "cached_at": as_of}, "sp": {"grade": "wait", "cached_at": as_of}},
        time.time() - 6 * 3600,
    )
    body = (await client.get("/api/market/combined-signal/NVDA")).json()
    assert body["cc"]["stale"] is True and body["cc"]["as_of"] == as_of and body["sp"]["grade"] == "wait"
    assert (await client.get("/api/market/cc-signal/NVDA")).json()["grade"] == "sell"


# ── mixed endpoints: database data, market fields null, flag set ────────────

async def test_trades_offline(client, db_session, offline):
    trade = (await client.post("/api/trades", json=PUT)).json()
    await _priced(db_session, trade["id"], "118.50", "150.00")

    resp = await client.get("/api/trades")
    assert resp.headers["X-Market-Data-Offline"] == "true"
    item = resp.json()[0]
    assert item["ticker"] == "NVDA" and item["strike_price"] == "120.00"
    assert item["current_price"] is None and item["unrealized_pnl"] is None

    detail = await client.get(f"/api/trades/{trade['id']}")
    body = detail.json()
    assert detail.headers["X-Market-Data-Offline"] == "true" and body["market_data_offline"] is True
    assert body["current_price"] is None and body["unrealized_pnl"] is None and body["last_price_at"] is not None

    # Stored prices were not wiped
    from app.models.trade import Trade
    db_session.expire_all()
    assert (await db_session.get(Trade, uuid.UUID(trade["id"]))).current_price == Decimal("118.50")


async def test_trades_online_keep_prices(client, db_session, online):
    trade = (await client.post("/api/trades", json=PUT)).json()
    await _priced(db_session, trade["id"], "118.50", "150.00")
    resp = await client.get("/api/trades")
    assert resp.headers["X-Market-Data-Offline"] == "false"
    assert resp.json()[0]["current_price"] == "118.50"
    assert (await client.get(f"/api/trades/{trade['id']}")).json()["market_data_offline"] is False


async def test_wheel_detail_offline(client, db_session, offline):
    stock = (await client.post("/api/trades", json=STOCK)).json()
    await _priced(db_session, stock["id"], "118.50")
    put = (await client.post("/api/trades", json=PUT)).json()
    await _priced(db_session, put["id"], "2.10")
    wheel = (await client.post("/api/wheel", json={"ticker": "NVDA", "opened_at": str(date.today())})).json()
    slot = (await client.post(f"/api/wheel/{wheel['id']}/slots", json={"status": "awaiting_sold_put"})).json()
    await client.post(f"/api/wheel/slots/{slot['id']}/legs", json={"trade_id": put["id"], "leg_role": "sold_put"})

    resp = await client.get(f"/api/wheel/{wheel['id']}")
    body = resp.json()
    assert resp.headers["X-Market-Data-Offline"] == "true" and body["market_data_offline"] is True
    assert body["stock_current_price"] is None
    legs = body["slots"][0]["legs"]
    assert legs[0]["trade_id"] == put["id"] and legs[0]["trade_current_price"] is None
    assert body["stock_cost_basis"] is not None  # database values still there


async def test_active_slots_positions_dashboard_offline(client, offline, default_account):
    trade = (await client.post("/api/trades", json=PUT)).json()
    wheel = (await client.post("/api/wheel", json={"ticker": "NVDA", "opened_at": str(date.today())})).json()
    await client.post(f"/api/wheel/{wheel['id']}/slots", json={"status": "awaiting_sold_put"})

    slots = await client.get("/api/wheel/active-slots")
    assert slots.headers["X-Market-Data-Offline"] == "true" and slots.json()[0]["ticker"] == "NVDA"

    status = await client.post("/api/positions/status", json={"positions": [
        {"ticker": "NVDA", "full_symbol": PUT["etrade_symbol"], "type": "Put"},
    ]})
    assert status.headers["X-Market-Data-Offline"] == "true"
    assert status.json()[PUT["etrade_symbol"]]["trade_id"] == trade["id"]

    summary = await client.get("/api/dashboard/summary")
    assert summary.headers["X-Market-Data-Offline"] == "true"
    body = summary.json()
    assert body["market_data_offline"] is True and body["accounts"][0]["open_trades"] == 1


async def test_screener_offline(client, offline):
    # Adding a symbol still works offline: tracked now, data fetched later
    added = await client.post("/api/screener", json={"symbol": "AAPL"})
    assert added.status_code == 201
    assert added.json()["fetch_status"] == "error" and added.json()["last_fetched_at"] is None

    listed = await client.get("/api/screener")
    assert listed.headers["X-Market-Data-Offline"] == "true"
    assert listed.json()[0]["symbol"] == "AAPL" and listed.json()[0]["stale"] is True

    # A single refresh is a pure market call: 503, nothing overwritten
    assert (await client.post("/api/screener/AAPL/fetch")).status_code == 503


async def test_screener_fetch_all_offline_keeps_stored_data(client, db_session, owner, offline):
    from app.models.screener import Screener
    from app.routers import screener as screener_router
    from tests.conftest import TestSessionLocal
    precomputed = {"price": 200.0, "rsi_14": 55.0, "fetch_status": "ok"}
    await client.post("/api/screener", json={"symbol": "AAPL", "precomputed": precomputed})
    job_id = "job-offline"
    screener_router._jobs[job_id] = {"user_id": owner.id, "status": "running", "total": 1, "completed": 0, "errors": []}
    await screener_router._run_fetch_all_job(job_id, owner.id, ["AAPL"], session_factory=TestSessionLocal)
    job = screener_router._jobs.pop(job_id)
    assert job["status"] == "done" and job["errors"][0]["error"] == "Market data offline"
    db_session.expire_all()
    row = (await db_session.execute(select(Screener).where(Screener.symbol == "AAPL"))).scalar_one()
    assert float(row.price) == 200.0 and float(row.rsi_14) == 55.0


async def test_non_market_features_keep_working(client, offline):
    trade = (await client.post("/api/trades", json=PUT)).json()
    assert (await client.post(f"/api/trades/{trade['id']}/commentary", json={"note": "holding"})).status_code == 201
    assert (await client.get(f"/api/trades/{trade['id']}/commentary")).status_code == 200
    assert (await client.get("/api/accounts")).status_code == 200
    assert (await client.get("/api/categories")).status_code == 200


# ── scheduler + engines ─────────────────────────────────────────────────────

async def test_signals_not_deactivated_while_offline(client, db_session, offline):
    from app.models.signal import TechnicalSignal
    from app.models.trade import Trade
    from app.models.rationale import Rationale
    from app.services.signal_engine import run as run_signal_engine
    trade = (await client.post("/api/trades", json=PUT)).json()
    tid = uuid.UUID(trade["id"])
    t = await db_session.get(Trade, tid)
    rationale = (await db_session.execute(select(Rationale).where(Rationale.trade_id == tid))).scalars().first()
    if rationale is None:
        rationale = Rationale(user_id=t.user_id, trade_id=tid)
        db_session.add(rationale)
    rationale.ma_200d, rationale.rsi_14 = Decimal("100"), Decimal("25")
    t.current_price = Decimal("130")
    await db_session.commit()
    await run_signal_engine(db_session); db_session.expire_all()  # online run: above_ma200 + rsi_oversold active

    def active():
        return db_session.execute(select(TechnicalSignal.signal_type).where(
            TechnicalSignal.trade_id == tid, TechnicalSignal.is_active.is_(True)))

    assert {"above_ma200", "rsi_oversold"} <= set((await active()).scalars())

    # Offline, with the price that would flip above_ma200 off: price rules are not evaluated.
    t = await db_session.get(Trade, tid)
    t.current_price = Decimal("90")
    await db_session.commit()
    db_session.expire_all()
    result = await run_signal_engine(db_session, market_offline=True)
    assert result["deactivated"] == 0
    assert "above_ma200" in set((await active()).scalars())

    # Missing data never deactivates either (only a real evaluation does).
    t = await db_session.get(Trade, tid)
    t.current_price = None
    await db_session.commit()
    db_session.expire_all()
    assert (await run_signal_engine(db_session))["deactivated"] == 0
    db_session.expire_all()
    t = await db_session.get(Trade, tid)
    t.current_price = Decimal("90")
    await db_session.commit()
    db_session.expire_all()
    assert (await run_signal_engine(db_session))["deactivated"] == 1  # real data: below MA200


async def test_alert_engine_skips_price_rules_offline(client, db_session, offline):
    from app.models.alert import Alert
    from app.services.alert_engine import run as run_alert_engine
    trade = (await client.post("/api/trades", json={**PUT, "expiry_date": str(date.today() + timedelta(days=5))})).json()
    await _priced(db_session, trade["id"], "120.50", "250.00")  # would trigger profit_target
    await run_alert_engine(db_session, market_offline=True)
    types = set((await db_session.execute(select(Alert.alert_type).where(Alert.trade_id == uuid.UUID(trade["id"])))).scalars())
    assert "dte_critical" in types          # database-only rules still run
    assert "profit_target" not in types


async def test_scheduler_skips_price_refresh_offline(monkeypatch, offline, caplog):
    from app import scheduler
    monkeypatch.setattr(scheduler, "is_market_hours", lambda: True)
    monkeypatch.setattr(scheduler, "_offline_logged", False)
    called = []
    monkeypatch.setattr("app.services.price_fetcher.refresh_open_trades", lambda *a, **k: called.append(1))
    for _ in range(3):
        await scheduler.price_refresh_job()
    assert called == [] and offline.calls == 0
    assert sum("market data offline" in r.message for r in caplog.records) == 1


# ── boundary ────────────────────────────────────────────────────────────────

def test_only_the_provider_module_imports_schwab_client():
    """Nothing outside the market data boundary may import SchwabClient (or the Schwab module's
    factory). Callers use app.services.market_data.get_market_data()."""
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    allowed = {root / "services" / "market_data.py", root / "services" / "schwab_client.py"}
    offenders = []
    for path in root.rglob("*.py"):
        if path in allowed:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "app.services.schwab_client":
                offenders.append(f"{path.relative_to(root)}: from schwab_client import {[a.name for a in node.names]}")
            elif isinstance(node, ast.Import) and any(a.name == "app.services.schwab_client" for a in node.names):
                offenders.append(f"{path.relative_to(root)}: import app.services.schwab_client")
            elif isinstance(node, ast.Name) and node.id == "SchwabClient":
                offenders.append(f"{path.relative_to(root)}: uses SchwabClient")
    assert offenders == []
