"""Cross-account Dashboard summary. Every query filters by the current user."""
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.alert import Alert
from app.models.trade import Trade
from app.models.user import User
from app.models.wheel_premium_log import WheelPremiumLog
from app.models.wheel_session import WheelSession
from app.models.wheel_slot import WheelSlot
from app.models.wheel_slot_leg import WheelSlotLeg
from app.schemas.account import AccountSummary
from app.schemas.dashboard import (
    DashboardAccountCard, DashboardAlert, DashboardNeedsActionSlot, DashboardSummary,
)
from app.services.accounts import list_accounts

ET = ZoneInfo("America/New_York")


def _et_today(now: datetime | None = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(ET).date()


def _month_bounds(today: date) -> tuple[date, date]:
    start = today.replace(day=1)
    next_month = (start + timedelta(days=32)).replace(day=1)
    return start, next_month


async def _counts_by_account(db: AsyncSession, stmt) -> dict[uuid.UUID, int]:
    return {row[0]: row[1] for row in (await db.execute(stmt)).all()}


async def build_summary(db: AsyncSession, user: User, now: datetime | None = None) -> DashboardSummary:
    today = _et_today(now)
    month_start, next_month = _month_bounds(today)
    accounts = await list_accounts(db, user, include_archived=False)
    active_ids = [a.id for a in accounts]

    open_trades = await _counts_by_account(db, (
        select(Trade.account_id, func.count())
        .where(Trade.user_id == user.id, Trade.status == "open")
        .group_by(Trade.account_id)
    ))
    expiring = await _counts_by_account(db, (
        select(Trade.account_id, func.count())
        .where(
            Trade.user_id == user.id, Trade.status == "open",
            Trade.expiry_date >= today, Trade.expiry_date <= today + timedelta(days=7),
        )
        .group_by(Trade.account_id)
    ))
    active_wheels = await _counts_by_account(db, (
        select(WheelSession.account_id, func.count())
        .where(WheelSession.user_id == user.id, WheelSession.status == "active")
        .group_by(WheelSession.account_id)
    ))
    needing_action = await _counts_by_account(db, (
        select(WheelSession.account_id, func.count())
        .select_from(WheelSlot).join(WheelSession, WheelSlot.session_id == WheelSession.id)
        .where(WheelSlot.user_id == user.id, WheelSlot.needs_action.is_(True), WheelSession.status == "active")
        .group_by(WheelSession.account_id)
    ))
    premium_rows = (await db.execute(
        select(WheelSession.account_id, func.coalesce(func.sum(WheelPremiumLog.premium_amount), 0))
        .select_from(WheelPremiumLog)
        .join(WheelSlot, WheelPremiumLog.slot_id == WheelSlot.id)
        .join(WheelSession, WheelSlot.session_id == WheelSession.id)
        .where(
            WheelPremiumLog.user_id == user.id,
            WheelPremiumLog.event_date >= month_start, WheelPremiumLog.event_date < next_month,
        )
        .group_by(WheelSession.account_id)
    )).all()
    premium = {row[0]: Decimal(row[1]) for row in premium_rows}

    cards = [
        DashboardAccountCard(
            account=AccountSummary.model_validate(a),
            is_default=a.is_default,
            open_trades=open_trades.get(a.id, 0),
            active_wheels=active_wheels.get(a.id, 0),
            slots_needing_action=needing_action.get(a.id, 0),
            legs_expiring_7d=expiring.get(a.id, 0),
            net_premium_month=premium.get(a.id, Decimal("0")),
        )
        for a in accounts
    ]

    slots = (await db.execute(
        select(WheelSlot)
        .join(WheelSession, WheelSlot.session_id == WheelSession.id)
        .where(
            WheelSlot.user_id == user.id, WheelSlot.needs_action.is_(True),
            WheelSession.status == "active", WheelSession.account_id.in_(active_ids),
        )
        .options(selectinload(WheelSlot.legs).selectinload(WheelSlotLeg.trade))
        .order_by(WheelSession.ticker, WheelSlot.slot_number)
    )).scalars().all()
    needs_action = []
    for slot in slots:
        expiries = [l.trade.expiry_date for l in slot.legs if l.trade and l.trade.status == "open" and l.trade.expiry_date]
        needs_action.append(DashboardNeedsActionSlot(
            slot_id=slot.id, session_id=slot.session_id, slot_number=slot.slot_number,
            ticker=slot.session.ticker, status=slot.status,
            account=AccountSummary.model_validate(slot.account),
            open_leg_expiry=min(expiries) if expiries else None,
        ))

    day_start = datetime.combine(today, time.min, tzinfo=ET)
    utc_now = now or datetime.now(timezone.utc)
    alert_rows = (await db.execute(
        select(Alert)
        .join(Trade, Alert.trade_id == Trade.id)
        .where(
            Alert.user_id == user.id, Trade.user_id == user.id,
            Alert.is_dismissed.is_(False),
            (Alert.snoozed_until.is_(None)) | (Alert.snoozed_until <= utc_now),
            Alert.triggered_at >= day_start, Alert.triggered_at < day_start + timedelta(days=1),
        )
        .options(selectinload(Alert.trade))
        .order_by(Alert.triggered_at.desc(), Alert.id)
    )).scalars().all()
    alerts = [
        DashboardAlert(
            id=a.id, trade_id=a.trade_id, ticker=a.trade.ticker, alert_type=a.alert_type, severity=a.severity,
            title=a.title, message=a.message, is_read=a.is_read, triggered_at=a.triggered_at,
            account=AccountSummary.model_validate(a.trade.account),
        )
        for a in alert_rows
    ]

    return DashboardSummary(as_of=today, accounts=cards, needs_action=needs_action, alerts=alerts)
