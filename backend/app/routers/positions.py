# backend/app/routers/positions.py
import uuid
from datetime import date, datetime, timezone, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from fastapi import APIRouter, Depends

from app.database import get_db
from app.deps import get_current_user, market_data_flag
from app.models.user import User
from app.services.ownership import get_account, resolve_account_filter
from app.models.trade import Trade
from app.models.alert import Alert
from app.models.commentary import Commentary
from app.models.signal import TechnicalSignal
from app.schemas.positions import (
    PositionsStatusRequest, PositionStatus, PositionMatch, ActiveSignal, DashboardTodayItem,
    ReconcileRequest, ReconcileResponse, UnmatchedEtradeItem, StaleBackendItem,
)

router = APIRouter(prefix="/api", tags=["positions"])


@router.post("/positions/status")
async def positions_status(
    payload: PositionsStatusRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    # Everything here comes from the DB (rationale snapshot, alerts, signal rows); the header lets
    # the extension show its "Market data offline" notice.
    offline: bool = Depends(market_data_flag),
) -> dict[str, PositionStatus]:
    # With account_id: only that account's trades (a single linked E*TRADE account).
    # Without: every account of the user (E*TRADE's All view); each match carries its account.
    account_filter = await resolve_account_filter(db, user, payload.account_id)
    tickers = list({p.ticker.upper() for p in payload.positions})

    # Load open trades for all tickers, eagerly load rationale, category_obj, signals
    conditions = [Trade.user_id == user.id, Trade.status == "open", Trade.ticker.in_(tickers)]
    if account_filter is not None:
        conditions.append(Trade.account_id == account_filter)
    stmt = (
        select(Trade)
        .where(*conditions)
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
            Alert.user_id == user.id,
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
        .where(Commentary.user_id == user.id, Commentary.trade_id.in_(trade_ids))
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
        .where(Commentary.user_id == user.id, Commentary.trade_id.in_(trade_ids))
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

        # Match within each account separately: one E*TRADE row is one position in one account,
        # so a trade in account A must never stand in for the same symbol in account B.
        trades_by_account: dict[uuid.UUID, list[Trade]] = {}
        for t in trades_by_ticker.get(ticker, []):
            trades_by_account.setdefault(t.account_id, []).append(t)
        matched = [
            m for m in (_match_trade(account_trades, pos_input) for account_trades in trades_by_account.values())
            if m is not None
        ]
        if not matched:
            response[key] = PositionStatus(ticker=ticker, full_symbol=pos_input.full_symbol)
            continue

        # Primary = most severe alert, then the user's account order.
        matched.sort(key=lambda t: (
            severity_order.get(best_alert[t.id].severity, 9) if t.id in best_alert else 9,
            t.account.sort_order,
            t.account.created_at,
        ))
        trade = matched[0]
        matches = [
            PositionMatch(
                account=t.account,
                trade_id=t.id,
                category_name=t.category_obj.name if t.category_obj else None,
                category_color=t.category_obj.color if t.category_obj else None,
                alert_severity=best_alert[t.id].severity if t.id in best_alert else None,
            )
            for t in matched
        ]

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
            account=trade.account,
            matches=matches,
        )

    return response


def _match_trade(trades: list[Trade], pos_input) -> Trade | None:
    """The open trade (all from one account) that a position row stands for, or None."""
    # Direct match on etrade_symbol (set when trade is added via extension modal).
    # One E*TRADE symbol maps to exactly one open position — no reconstruction needed.
    if pos_input.full_symbol:
        direct = next((t for t in trades if t.etrade_symbol == pos_input.full_symbol), None)
        if direct is not None:
            return direct
    # Fallback: reconstruct match from instrument type + strike + expiry.
    # Use strict=True so untracked legs of a multi-leg position (e.g. iron
    # condor) don't inherit the badge/commentary of the one tracked leg.
    return _pick_best_trade(trades, pos_input, strict=True)


@router.post("/positions/reconcile", response_model=ReconcileResponse)
async def reconcile_positions(
    payload: ReconcileRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReconcileResponse:
    # Reconcile must only ever touch (match or backdate-close) the named account's trades — never
    # another account's or user's. The account is required and must be active.
    account = await get_account(db, user, payload.account_id, include_archived=False)

    # Single query: all open trades in the account (needed for both matching and stale detection)
    all_open_stmt = select(Trade).where(
        Trade.user_id == user.id,
        Trade.account_id == account.id,
        Trade.status == "open",
    )
    all_result = await db.execute(all_open_stmt)
    all_open_trades = all_result.scalars().all()

    ticker_trades: dict[str, list[Trade]] = {}
    for trade in all_open_trades:
        ticker_trades.setdefault(trade.ticker, []).append(trade)

    matched_ids: set = set()
    unmatched_etrade: list[UnmatchedEtradeItem] = []

    for pos in payload.positions:
        ticker = pos.ticker.upper()
        candidates = ticker_trades.get(ticker, [])

        trade = None
        if pos.full_symbol and candidates:
            trade = next((t for t in candidates if t.etrade_symbol == pos.full_symbol), None)
        if trade is None and candidates:
            trade = _pick_best_trade(candidates, pos, strict=True)

        if trade is None:
            unmatched_etrade.append(UnmatchedEtradeItem(
                ticker=ticker,
                full_symbol=pos.full_symbol,
                option_type=pos.type,
                strike=pos.strike,
                expiry=pos.expiry,
            ))
        else:
            matched_ids.add(trade.id)

    # The extension scrolls the full E*TRADE grid before calling this endpoint
    # (collectAllPositions in content.js), so payload.positions is a complete
    # snapshot of open positions — not just what happened to be rendered at
    # click time. That means an unmatched trade is genuinely gone from
    # E*TRADE, not just off-screen, so it's safe to backdate unconditionally.
    #
    # Eligibility check: last_etrade_seen is not None (previously matched by a
    # reconcile) OR etrade_symbol is not None (added via the extension modal,
    # so it's a confirmed E*TRADE position even if reconcile never once caught
    # it before it closed). Trades with neither are manual entries with no
    # confirmed link to E*TRADE and must never be flagged stale.
    now = datetime.now(timezone.utc)
    for trade in all_open_trades:
        if trade.id in matched_ids:
            trade.last_etrade_seen = now
        elif trade.last_etrade_seen is not None or trade.etrade_symbol is not None:
            trade.last_etrade_seen = now - timedelta(days=2)
    await db.commit()

    stale_threshold = now - timedelta(days=1)
    stale_backend = [
        StaleBackendItem(
            id=t.id,
            ticker=t.ticker,
            type=t.type,
            strategy=t.strategy,
            quantity=t.quantity,
            open_date=t.open_date,
            last_etrade_seen=t.last_etrade_seen,
        )
        for t in all_open_trades
        if t.id not in matched_ids
        and t.last_etrade_seen is not None
        and t.last_etrade_seen < stale_threshold
    ]

    return ReconcileResponse(unmatched_etrade=unmatched_etrade, stale_backend=stale_backend)


def _pick_best_trade(trades: list[Trade], pos_input, strict: bool = False) -> Trade | None:
    """Pick the most relevant trade for a position.

    Matching order:
    1. Narrow by instrument type (stock vs call vs put) so a stock row never
       accidentally matches a covered-call trade on the same ticker.
    2. Within the narrowed set, match by strike + expiry for options.
    3. Fallback: most recently created (handles the single-trade common case).

    When strict=True (used by reconcile), steps 1-2 run but step 3 is replaced
    with returning None. This prevents one tracked leg of a multi-leg position
    (e.g., an iron condor) from absorbing all untracked legs of the same ticker.
    The len==1 shortcuts are also skipped in strict mode so type+strike+expiry
    filtering always runs.
    """
    if not strict and len(trades) == 1:
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

    # In strict mode, only skip the single-candidate shortcut when the position
    # carries no strike/expiry (stocks). For options we must verify against
    # strike+expiry before claiming a match, otherwise one tracked leg would
    # absorb all untracked legs of the same ticker (e.g. iron condor).
    has_option_details = bool(pos_input.strike and pos_input.expiry)
    if len(candidates) == 1 and (not strict or not has_option_details):
        return candidates[0]

    # Step 2: for options, match by strike + expiry (uniquely identifies a contract).
    if pos_input.strike and pos_input.expiry:
        for t in candidates:
            if (t.strike_price is not None
                    and abs(float(t.strike_price) - pos_input.strike) < 0.01
                    and t.expiry_date == pos_input.expiry):
                return t

    if strict:
        # No confident match — treat as untracked so the + Add pill appears
        return None

    # Step 3: fallback — most recently created
    return max(candidates, key=lambda t: t.created_at)


@router.get("/dashboard/today", response_model=list[DashboardTodayItem])
async def dashboard_today(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return action queue: open trades with active alerts, sorted by urgency."""
    now = datetime.now(timezone.utc)
    severity_order = {"urgent": 0, "warning": 1, "info": 2, "ok": 3}

    stmt = (
        select(Alert)
        .join(Trade, Alert.trade_id == Trade.id)
        .where(
            Alert.user_id == user.id,
            Trade.user_id == user.id,
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
