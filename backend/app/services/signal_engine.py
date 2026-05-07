# backend/app/services/signal_engine.py
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.trade import Trade
from app.models.signal import TechnicalSignal


SIGNAL_RULES: list[tuple[str, callable]] = [
    ("macd_bullish",      lambda t: t.rationale and t.rationale.macd_signal == "bullish"),
    ("macd_bearish",      lambda t: t.rationale and t.rationale.macd_signal == "bearish"),
    ("rsi_oversold",      lambda t: t.rationale and t.rationale.rsi_14 is not None and float(t.rationale.rsi_14) < 30),
    ("rsi_overbought",    lambda t: t.rationale and t.rationale.rsi_14 is not None and float(t.rationale.rsi_14) > 70),
    ("bb_breakout_upper", lambda t: t.rationale and t.rationale.bollinger_position == "top"),
    ("bb_breakout_lower", lambda t: t.rationale and t.rationale.bollinger_position == "bottom"),
    ("above_ma200",       lambda t: t.rationale and t.rationale.ma_200d is not None and t.current_price is not None and float(t.current_price) > float(t.rationale.ma_200d)),
    ("below_ma200",       lambda t: t.rationale and t.rationale.ma_200d is not None and t.current_price is not None and float(t.current_price) < float(t.rationale.ma_200d)),
    ("golden_cross",      lambda t: t.rationale and t.rationale.ma_50d is not None and t.rationale.ma_200d is not None and float(t.rationale.ma_50d) > float(t.rationale.ma_200d)),
    ("death_cross",       lambda t: t.rationale and t.rationale.ma_50d is not None and t.rationale.ma_200d is not None and float(t.rationale.ma_50d) < float(t.rationale.ma_200d)),
]


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


async def run(db: AsyncSession) -> dict:
    """Evaluate signal rules for all open trades. Activate/deactivate signals."""
    stmt = (
        select(Trade)
        .where(Trade.status == "open")
        .options(selectinload(Trade.rationale), selectinload(Trade.signals))
    )
    result = await db.execute(stmt)
    trades = result.scalars().all()

    activated = 0
    deactivated = 0

    for trade in trades:
        existing: dict[str, TechnicalSignal] = {s.signal_type: s for s in trade.signals}

        for signal_type, condition in SIGNAL_RULES:
            should_be_active = False
            try:
                should_be_active = bool(condition(trade))
            except Exception:
                pass

            existing_signal = existing.get(signal_type)

            if should_be_active:
                if existing_signal is None:
                    # Create new active signal
                    sig = TechnicalSignal(
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
