# backend/app/services/alert_engine.py
import uuid
from typing import Optional
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


def _make_alert(trade: Trade, alert_type: str, severity: str,
                title: str, message: str) -> Alert:
    # Alerts are owned by the trade's user.
    return Alert(user_id=trade.user_id, trade_id=trade.id, alert_type=alert_type, severity=severity,
                 title=title, message=message)


async def _evaluate_trade(
    trade: Trade,
    last_commentary_at: datetime | None,
    db: AsyncSession,
    market_offline: bool = False,
) -> list[Alert]:
    """market_offline: skip the rules that read stored prices / P&L (1, 2, 6, 8) — those values
    stop updating while market data is offline. The database-only rules (DTE, earnings, review)
    keep running."""
    alerts: list[Alert] = []
    ticker = trade.ticker
    market_ok = not market_offline

    # Rules 1 & 2: profit_target, stop_loss
    if (market_ok and trade.unrealized_pnl is not None
            and trade.premium is not None
            and trade.strike_price is not None
            and trade.type == "Sell"):
        max_profit = float(trade.premium) * trade.quantity * 100
        pnl = float(trade.unrealized_pnl)

        if max_profit > 0:
            pnl_pct = pnl / max_profit
            if pnl_pct >= 0.50 and not await _alert_exists(db, trade.id, "profit_target"):
                alerts.append(_make_alert(
                    trade, "profit_target", "warning",
                    f"{ticker}: Profit target reached",
                    f"Unrealized P&L is ${pnl:.0f} ({pnl_pct * 100:.0f}% of max profit). Consider closing.",
                ))

        if pnl <= -(max_profit * 2) and not await _alert_exists(db, trade.id, "stop_loss"):
            alerts.append(_make_alert(
                trade, "stop_loss", "urgent",
                f"{ticker}: Stop loss triggered",
                f"Unrealized loss is ${abs(pnl):.0f} (2× premium received). Review immediately.",
            ))

    # Rules 3 & 4: dte_critical, dte_threshold
    if trade.expiry_date is not None:
        dte = (trade.expiry_date - date.today()).days
        if dte <= 7 and not await _alert_exists(db, trade.id, "dte_critical"):
            alerts.append(_make_alert(
                trade, "dte_critical", "urgent",
                f"{ticker}: {dte} DTE — critical",
                f"Option expires in {dte} days. Close, roll, or accept assignment.",
            ))
        elif dte <= 21 and not await _alert_exists(db, trade.id, "dte_threshold"):
            alerts.append(_make_alert(
                trade, "dte_threshold", "warning",
                f"{ticker}: {dte} DTE — approaching expiry",
                f"Option expires in {dte} days. Review your exit strategy.",
            ))

    # Rule 5: earnings_approaching
    if trade.rationale and trade.rationale.next_earnings_date:
        days_to_earnings = (trade.rationale.next_earnings_date - date.today()).days
        if 0 <= days_to_earnings <= 5 and not await _alert_exists(db, trade.id, "earnings_approaching"):
            alerts.append(_make_alert(
                trade, "earnings_approaching", "warning",
                f"{ticker}: Earnings in {days_to_earnings} days",
                f"Earnings on {trade.rationale.next_earnings_date}. Review position and IV risk.",
            ))

    # Rule 6: assignment_risk (Put within 2% of strike)
    if (market_ok and trade.current_price is not None
            and trade.strike_price is not None
            and trade.strategy in ("Put", "PutCreditSpread")):
        current = float(trade.current_price)
        strike = float(trade.strike_price)
        if abs(strike - current) / strike <= 0.02 and not await _alert_exists(db, trade.id, "assignment_risk"):
            alerts.append(_make_alert(
                trade, "assignment_risk", "warning",
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
            trade, "overdue_review", "info",
            f"{ticker}: Overdue review",
            f"No commentary in {days_since} days. Log an update on this position.",
        ))

    # Rule 8: deep_itm (CoveredCall >5% above strike)
    if (market_ok and trade.current_price is not None
            and trade.strike_price is not None
            and trade.strategy == "CoveredCall"):
        current = float(trade.current_price)
        strike = float(trade.strike_price)
        if (current - strike) / strike >= 0.05 and not await _alert_exists(db, trade.id, "deep_itm"):
            alerts.append(_make_alert(
                trade, "deep_itm", "urgent",
                f"{ticker}: Covered call deep ITM",
                f"Current price ${current:.2f} is >5% above strike ${strike:.2f}. High assignment risk.",
            ))

    return alerts


async def run(db: AsyncSession, user_id: Optional[uuid.UUID] = None, market_offline: bool = False) -> dict:
    """Evaluate all 8 alert rules for all open trades (every user's, or one user's when
    user_id is given — used by the manual refresh endpoint). Returns alert counts.
    With market_offline, only the database-only rules run (see _evaluate_trade)."""
    stmt = (
        select(Trade)
        .where(Trade.status == "open")
        .options(selectinload(Trade.rationale))
    )
    if user_id is not None:
        stmt = stmt.where(Trade.user_id == user_id)
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
        new_alerts = await _evaluate_trade(trade, last_commentary.get(trade.id), db, market_offline)
        for alert in new_alerts:
            db.add(alert)
            alerts_created += 1

    if alerts_created > 0:
        await db.commit()

    return {"alerts_created": alerts_created, "trades_evaluated": len(trades)}
