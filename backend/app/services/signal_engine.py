# backend/app/services/signal_engine.py
import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.trade import Trade
from app.models.signal import TechnicalSignal


def _num(value) -> float | None:
    return None if value is None else float(value)


def _rationale_value(t: Trade, field: str):
    return getattr(t.rationale, field) if t.rationale is not None else None


def _compare(left, right, op) -> bool | None:
    """None when an input is missing — "can't evaluate", not "false"."""
    if left is None or right is None:
        return None
    return op(float(left), float(right))


def _equals(value, expected) -> bool | None:
    return None if value is None else value == expected


# Each rule returns True (active), False (evaluated: inactive) or None (inputs missing → leave the
# signal as it is). Signals are only ever deactivated on a real evaluation, never on missing data.
SIGNAL_RULES: list[tuple[str, callable]] = [
    ("macd_bullish",      lambda t: _equals(_rationale_value(t, "macd_signal"), "bullish")),
    ("macd_bearish",      lambda t: _equals(_rationale_value(t, "macd_signal"), "bearish")),
    ("rsi_oversold",      lambda t: _compare(_rationale_value(t, "rsi_14"), 30, lambda a, b: a < b)),
    ("rsi_overbought",    lambda t: _compare(_rationale_value(t, "rsi_14"), 70, lambda a, b: a > b)),
    ("bb_breakout_upper", lambda t: _equals(_rationale_value(t, "bollinger_position"), "top")),
    ("bb_breakout_lower", lambda t: _equals(_rationale_value(t, "bollinger_position"), "bottom")),
    ("above_ma200",       lambda t: _compare(t.current_price, _rationale_value(t, "ma_200d"), lambda a, b: a > b)),
    ("below_ma200",       lambda t: _compare(t.current_price, _rationale_value(t, "ma_200d"), lambda a, b: a < b)),
    ("golden_cross",      lambda t: _compare(_rationale_value(t, "ma_50d"), _rationale_value(t, "ma_200d"), lambda a, b: a > b)),
    ("death_cross",       lambda t: _compare(_rationale_value(t, "ma_50d"), _rationale_value(t, "ma_200d"), lambda a, b: a < b)),
]

# Rules that read the live price (Trade.current_price, written by the price refresh). Skipped while
# market data is offline: the stored price stops updating, so it isn't "real evaluated data".
MARKET_RULES = {"above_ma200", "below_ma200"}


def _signal_value(trade: Trade, signal_type: str) -> float | None:
    """Extract the relevant numeric value for a signal type."""
    r = trade.rationale
    if signal_type in ("rsi_oversold", "rsi_overbought") and r and r.rsi_14:
        return float(r.rsi_14)
    if signal_type in ("above_ma200", "below_ma200") and r and r.ma_200d:
        return float(r.ma_200d)
    if signal_type in ("golden_cross", "death_cross") and r and r.ma_50d:
        return float(r.ma_50d)
    return None


async def run(db: AsyncSession, user_id: Optional[uuid.UUID] = None, market_offline: bool = False) -> dict:
    """Evaluate signal rules for all open trades (every user's, or one user's when user_id is
    given). Activate/deactivate signals. With market_offline, price-based rules are skipped."""
    stmt = (
        select(Trade)
        .where(Trade.status == "open")
        .options(selectinload(Trade.rationale), selectinload(Trade.signals))
    )
    if user_id is not None:
        stmt = stmt.where(Trade.user_id == user_id)
    result = await db.execute(stmt)
    trades = result.scalars().all()

    activated = 0
    deactivated = 0

    for trade in trades:
        existing: dict[str, TechnicalSignal] = {s.signal_type: s for s in trade.signals}

        for signal_type, condition in SIGNAL_RULES:
            if market_offline and signal_type in MARKET_RULES:
                continue
            try:
                outcome = condition(trade)
            except Exception:
                outcome = None
            if outcome is None:
                continue  # can't evaluate: never flip a signal on missing data
            should_be_active = bool(outcome)

            existing_signal = existing.get(signal_type)

            if should_be_active:
                if existing_signal is None:
                    # Create new active signal
                    sig = TechnicalSignal(
                        user_id=trade.user_id,
                        trade_id=trade.id,
                        signal_type=signal_type,
                        signal_value=_signal_value(trade, signal_type),
                        is_active=True,
                        notes=_make_note(trade, signal_type),
                    )
                    db.add(sig)
                    activated += 1
                elif not existing_signal.is_active:
                    # Re-activate
                    existing_signal.is_active = True
                    existing_signal.triggered_at = datetime.now(timezone.utc)
                    existing_signal.signal_value = _signal_value(trade, signal_type)
                    existing_signal.notes = _make_note(trade, signal_type)
                    activated += 1
            else:
                if existing_signal and existing_signal.is_active:
                    existing_signal.is_active = False
                    deactivated += 1

    if activated > 0 or deactivated > 0:
        await db.commit()

    return {"activated": activated, "deactivated": deactivated, "trades_evaluated": len(trades)}


def _make_note(trade: Trade, signal_type: str) -> str:
    r = trade.rationale
    notes = {
        "macd_bullish":      "MACD bullish crossover",
        "macd_bearish":      "MACD bearish crossover",
        "rsi_oversold":      f"RSI oversold ({float(r.rsi_14):.1f})" if r and r.rsi_14 else "RSI oversold",
        "rsi_overbought":    f"RSI overbought ({float(r.rsi_14):.1f})" if r and r.rsi_14 else "RSI overbought",
        "bb_breakout_upper": "Price at upper Bollinger Band",
        "bb_breakout_lower": "Price at lower Bollinger Band",
        "above_ma200":       f"Price above MA200 ({float(r.ma_200d):.2f})" if r and r.ma_200d else "Price above MA200",
        "below_ma200":       f"Price below MA200 ({float(r.ma_200d):.2f})" if r and r.ma_200d else "Price below MA200",
        "golden_cross":      f"Golden cross: MA50 ({float(r.ma_50d):.2f}) > MA200 ({float(r.ma_200d):.2f})" if r and r.ma_50d and r.ma_200d else "Golden cross",
        "death_cross":       f"Death cross: MA50 ({float(r.ma_50d):.2f}) < MA200 ({float(r.ma_200d):.2f})" if r and r.ma_50d and r.ma_200d else "Death cross",
    }
    return notes.get(signal_type, signal_type)
