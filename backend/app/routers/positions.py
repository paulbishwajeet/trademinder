# backend/app/routers/positions.py
import uuid
from datetime import date, datetime, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from fastapi import APIRouter, Depends

from app.database import get_db
from app.models.trade import Trade
from app.models.alert import Alert
from app.models.commentary import Commentary
from app.models.signal import TechnicalSignal
from app.schemas.positions import (
    PositionsStatusRequest, PositionStatus, ActiveSignal, DashboardTodayItem
)

router = APIRouter(prefix="/api", tags=["positions"])


@router.post("/positions/status")
async def positions_status(
    payload: PositionsStatusRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, PositionStatus]:
    tickers = list({p.ticker.upper() for p in payload.positions})

    # Load open trades for all tickers, eagerly load rationale, category_obj, signals
    stmt = (
        select(Trade)
        .where(Trade.status == "open", Trade.ticker.in_(tickers))
        .options(
            selectinload(Trade.rationale),
            selectinload(Trade.category_obj),
            selectinload(Trade.signals),
        )
    )
    result = await db.execute(stmt)
    trades_by_ticker: dict[str, list[Trade]] = {}
    for trade in result.scalars().all():
        trades_by_ticker.setdefault(trade.ticker, []).append(trade)

    # Get highest-severity active (non-dismissed, non-snoozed) alert per trade
    trade_ids = [t.id for trades in trades_by_ticker.values() for t in trades]
    now = datetime.now(timezone.utc)

    alert_stmt = (
        select(Alert)
        .where(
            Alert.trade_id.in_(trade_ids),
            Alert.is_dismissed == False,  # noqa: E712
            (Alert.snoozed_until == None) | (Alert.snoozed_until <= now),  # noqa: E711
        )
        .order_by(
            Alert.trade_id,
            # Severity order: urgent first
            Alert.severity,
        )
    )
    alert_result = await db.execute(alert_stmt)
    best_alert: dict[uuid.UUID, Alert] = {}
    severity_order = {"urgent": 0, "warning": 1, "info": 2, "ok": 3}
    for alert in alert_result.scalars().all():
        prev = best_alert.get(alert.trade_id)
        if prev is None or severity_order.get(alert.severity, 9) < severity_order.get(prev.severity, 9):
            best_alert[alert.trade_id] = alert

    # Get latest commentary + count per trade
    commentary_stmt = (
        select(
            Commentary.trade_id,
            func.count(Commentary.id).label("cnt"),
            func.max(Commentary.created_at).label("last_at"),
        )
        .where(Commentary.trade_id.in_(trade_ids))
        .group_by(Commentary.trade_id)
    )
    commentary_result = await db.execute(commentary_stmt)
    commentary_info: dict[uuid.UUID, dict] = {
        row.trade_id: {"count": row.cnt, "last_at": row.last_at}
        for row in commentary_result
    }

    # Get the actual last note text
    last_note_stmt = (
        select(Commentary)
        .where(Commentary.trade_id.in_(trade_ids))
        .order_by(Commentary.trade_id, Commentary.created_at.desc())
        .distinct(Commentary.trade_id)
    )
    last_note_result = await db.execute(last_note_stmt)
    last_notes: dict[uuid.UUID, Commentary] = {
        c.trade_id: c for c in last_note_result.scalars().all()
    }

    # Build response
    response: dict[str, PositionStatus] = {}

    for pos_input in payload.positions:
        ticker = pos_input.ticker.upper()
        key = pos_input.full_symbol or ticker

        trades = trades_by_ticker.get(ticker, [])
        if not trades:
            response[key] = PositionStatus(ticker=ticker, full_symbol=pos_input.full_symbol)
            continue

        # Direct match on etrade_symbol (set when trade is added via extension modal).
        # One E*TRADE symbol maps to exactly one open position — no reconstruction needed.
        trade = None
        if pos_input.full_symbol:
            trade = next((t for t in trades if t.etrade_symbol == pos_input.full_symbol), None)

        # Fallback: reconstruct match from instrument type + strike + expiry
        if trade is None:
            trade = _pick_best_trade(trades, pos_input)

        alert = best_alert.get(trade.id)
        cat = trade.category_obj
        c_info = commentary_info.get(trade.id, {})
        last_note_obj = last_notes.get(trade.id)
        active_sigs = [
            ActiveSignal(type=s.signal_type, notes=s.notes, signal_value=s.signal_value)
            for s in trade.signals if s.is_active
        ]

        dte = None
        if trade.expiry_date:
            dte = (trade.expiry_date - date.today()).days

        response[key] = PositionStatus(
            ticker=ticker,
            full_symbol=pos_input.full_symbol,
            trade_id=trade.id,
            category_id=cat.id if cat else None,
            category_name=cat.name if cat else None,
            category_color=cat.color if cat else None,
            category_icon=cat.icon if cat else None,
            alert_severity=alert.severity if alert else None,
            alert_type=alert.alert_type if alert else None,
            alert_title=alert.title if alert else None,
            alert_id=alert.id if alert else None,
            last_note=last_note_obj.note if last_note_obj else None,
            last_note_date=last_note_obj.entry_date if last_note_obj else None,
            commentary_count=c_info.get("count", 0),
            active_signals=active_sigs,
            rsi_14=trade.rationale.rsi_14 if trade.rationale else None,
            macd_signal=trade.rationale.macd_signal if trade.rationale else None,
            bollinger_position=trade.rationale.bollinger_position if trade.rationale else None,
            strategy=trade.strategy,
            strike_price=trade.strike_price,
            dte=dte,
            exit_strategy=trade.exit_strategy,
        )

    return response


def _pick_best_trade(trades: list[Trade], pos_input) -> Trade:
    """Pick the most relevant trade for a position.

    Matching order:
    1. Narrow by instrument type (stock vs call vs put) so a stock row never
       accidentally matches a covered-call trade on the same ticker.
    2. Within the narrowed set, match by strike + expiry for options.
    3. Fallback: most recently created (handles the single-trade common case).
    """
    if len(trades) == 1:
        return trades[0]

    # Step 1: filter by instrument type derived from the DOM row.
    # pos_input.type comes from the extension: "Stock", "Call", "Put", or "Option".
    # Trade.strategy is a free-form string, but it always contains the keyword.
    pos_type = (pos_input.type or "").lower()
    if pos_type == "stock":
        narrowed = [t for t in trades if "stock" in t.strategy.lower()]
    elif pos_type == "call":
        narrowed = [t for t in trades if "call" in t.strategy.lower() or "leap" in t.strategy.lower()]
    elif pos_type == "put":
        narrowed = [t for t in trades if "put" in t.strategy.lower()]
    else:
        narrowed = trades  # "Option" or unknown — skip type filter

    candidates = narrowed if narrowed else trades  # don't lose all candidates on a miss

    if len(candidates) == 1:
        return candidates[0]

    # Step 2: for options, match by strike + expiry (uniquely identifies a contract).
    if pos_input.strike and pos_input.expiry:
        for t in candidates:
            if (t.strike_price is not None
                    and abs(float(t.strike_price) - pos_input.strike) < 0.01
                    and t.expiry_date == pos_input.expiry):
                return t

    # Step 3: fallback — most recently created
    return max(candidates, key=lambda t: t.created_at)


@router.get("/dashboard/today", response_model=list[DashboardTodayItem])
async def dashboard_today(db: AsyncSession = Depends(get_db)):
    """Return action queue: open trades with active alerts, sorted by urgency."""
    now = datetime.now(timezone.utc)
    severity_order = {"urgent": 0, "warning": 1, "info": 2, "ok": 3}

    stmt = (
        select(Alert)
        .join(Trade, Alert.trade_id == Trade.id)
        .where(
            Trade.status == "open",
            Alert.is_dismissed == False,  # noqa: E712
            (Alert.snoozed_until == None) | (Alert.snoozed_until <= now),  # noqa: E711
        )
        .options(selectinload(Alert.trade).selectinload(Trade.category_obj))
        .order_by(Alert.triggered_at.desc())
    )
    result = await db.execute(stmt)
    alerts = result.scalars().all()

    # Deduplicate: one entry per trade (highest severity alert wins)
    seen: dict[uuid.UUID, DashboardTodayItem] = {}
    for alert in alerts:
        trade = alert.trade
        existing = seen.get(trade.id)
        if existing is None or severity_order.get(alert.severity, 9) < severity_order.get(existing.alert_severity, 9):
            dte = (trade.expiry_date - date.today()).days if trade.expiry_date else None
            cat = trade.category_obj
            seen[trade.id] = DashboardTodayItem(
                trade_id=trade.id,
                ticker=trade.ticker,
                strategy=trade.strategy,
                alert_severity=alert.severity,
                alert_type=alert.alert_type,
                alert_title=alert.title,
                alert_id=alert.id,
                dte=dte,
                category_name=cat.name if cat else None,
                category_icon=cat.icon if cat else None,
            )

    # Sort by severity
    items = sorted(seen.values(), key=lambda x: severity_order.get(x.alert_severity, 9))
    return items
