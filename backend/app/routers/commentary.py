# backend/app/routers/commentary.py
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from anthropic import AsyncAnthropic

from app.database import get_db
from app.models.commentary import Commentary
from app.schemas.commentary import CommentaryCreate, CommentaryResponse

router = APIRouter(tags=["commentary"])


@router.get("/api/trades/{trade_id}/commentary", response_model=list[CommentaryResponse])
async def list_commentary(trade_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Commentary)
        .where(Commentary.trade_id == trade_id)
        .order_by(Commentary.created_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/api/trades/{trade_id}/commentary", response_model=CommentaryResponse, status_code=201)
async def add_commentary(trade_id: uuid.UUID, payload: CommentaryCreate, db: AsyncSession = Depends(get_db)):
    comment = Commentary(
        trade_id=trade_id,
        note=payload.note,
        tags=payload.tags,
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    return comment


@router.delete("/api/commentary/{comment_id}", status_code=204)
async def delete_commentary(comment_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = select(Commentary).where(Commentary.id == comment_id)
    result = await db.execute(stmt)
    comment = result.scalar_one_or_none()
    if comment is None:
        raise HTTPException(status_code=404, detail="Commentary entry not found")
    await db.delete(comment)
    await db.commit()


# Simple in-memory cache: trade_id -> (summary_text, inferred_actions, cached_at)
_summary_cache: dict[str, tuple[str, list[str], datetime]] = {}
_CACHE_TTL_HOURS = 6


@router.get("/api/trades/{trade_id}/commentary/summary")
async def commentary_summary(trade_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    from app.config import settings
    cache_key = str(trade_id)
    now = datetime.now(timezone.utc)

    # Return cached result if fresh
    if cache_key in _summary_cache:
        summary, actions, cached_at = _summary_cache[cache_key]
        age_hours = (now - cached_at).total_seconds() / 3600
        if age_hours < _CACHE_TTL_HOURS:
            return {"summary": summary, "inferred_actions": actions}

    # Load commentary
    stmt = (
        select(Commentary)
        .where(Commentary.trade_id == trade_id)
        .order_by(Commentary.created_at.asc())
    )
    result = await db.execute(stmt)
    comments = result.scalars().all()

    # Load trade + rationale
    from app.models.trade import Trade
    from sqlalchemy.orm import selectinload
    trade_stmt = (
        select(Trade)
        .where(Trade.id == trade_id)
        .options(selectinload(Trade.rationale))
    )
    trade_result = await db.execute(trade_stmt)
    trade = trade_result.scalar_one_or_none()
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found")

    if not settings.anthropic_api_key:
        return {"summary": "AI summary not configured (ANTHROPIC_API_KEY missing).", "inferred_actions": []}

    # Build prompt
    rationale_text = ""
    if trade.rationale:
        r = trade.rationale
        rationale_text = (
            f"RSI: {r.rsi_14}, MACD: {r.macd_signal}, Bollinger: {r.bollinger_position}, "
            f"Next earnings: {r.next_earnings_date}"
        )

    notes_text = "\n".join(
        f"{c.entry_date}: {c.note}"
        for c in comments
    ) or "(no notes)"

    dte_text = f", {(trade.expiry_date - datetime.now(timezone.utc).date()).days} DTE" if trade.expiry_date else ""
    prompt = f"""You are a trading assistant. Summarize this option position's commentary thread and infer 2-3 concrete actions.

Position: {trade.ticker} {trade.strategy} ${trade.strike_price}{dte_text}
Current P&L: ${trade.unrealized_pnl}
Technical snapshot: {rationale_text}

Commentary thread:
{notes_text}

Respond with JSON exactly like this:
{{"summary": "2-3 sentence summary of the situation and what the notes tell you", "inferred_actions": ["Action 1", "Action 2"]}}"""

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    import json
    try:
        parsed = json.loads(message.content[0].text)
        summary = parsed.get("summary", "")
        actions = parsed.get("inferred_actions", [])
    except (json.JSONDecodeError, IndexError, KeyError):
        summary = message.content[0].text
        actions = []

    _summary_cache[cache_key] = (summary, actions, now)
    return {"summary": summary, "inferred_actions": actions}
