import uuid
from datetime import date
from decimal import Decimal
from app.schemas.wheel import (
    WheelSessionCreate, WheelSessionSummary, WheelSessionDetail,
    WheelSlotCreate, WheelSlotSummary,
    WheelSlotLegCreate, WheelSlotLegItem,
    WheelResolveRequest,
    WheelPremiumLogItem, WheelActiveSlotItem,
)


def test_session_create_defaults():
    sc = WheelSessionCreate(ticker="NVDA", opened_at=date.today())
    assert sc.total_shares == 0


def test_resolve_request_cc_expired_otm():
    r = WheelResolveRequest(outcome="cc_expired_otm")
    assert r.new_trade_id is None
    assert r.buyback_cost is None


def test_resolve_request_rolled():
    r = WheelResolveRequest(
        outcome="cc_rolled",
        new_trade_id=uuid.uuid4(),
        buyback_cost=Decimal("1.50"),
    )
    assert r.buyback_cost == Decimal("1.50")
