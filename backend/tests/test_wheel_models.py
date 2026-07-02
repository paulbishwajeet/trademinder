from app.models.wheel_session import WheelSession
from app.models.wheel_slot import WheelSlot
from app.models.wheel_slot_leg import WheelSlotLeg
from app.models.wheel_premium_log import WheelPremiumLog


def test_wheel_models_importable():
    assert WheelSession.__tablename__ == "wheel_sessions"
    assert WheelSlot.__tablename__ == "wheel_slots"
    assert WheelSlotLeg.__tablename__ == "wheel_slot_legs"
    assert WheelPremiumLog.__tablename__ == "wheel_premium_logs"
