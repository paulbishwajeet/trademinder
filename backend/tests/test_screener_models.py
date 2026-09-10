import pytest
from sqlalchemy import select

from app.models.screener import Screener
from app.models.screener_commentary import ScreenerCommentary


async def test_create_screener_row_and_commentary(db_session):
    row = Screener(symbol="AAPL", category="Watchlist")
    db_session.add(row)
    await db_session.flush()

    note = ScreenerCommentary(screener_id=row.id, note="Watching for a pullback")
    db_session.add(note)
    await db_session.commit()

    result = await db_session.execute(select(Screener).where(Screener.symbol == "AAPL"))
    fetched = result.scalar_one()
    assert fetched.category == "Watchlist"
    assert fetched.fetch_status is None
    assert fetched.last_fetched_at is None


async def test_deleting_screener_row_cascades_commentary(db_session):
    row = Screener(symbol="MSFT")
    db_session.add(row)
    await db_session.flush()
    db_session.add(ScreenerCommentary(screener_id=row.id, note="note one"))
    await db_session.commit()

    await db_session.delete(row)
    await db_session.commit()

    result = await db_session.execute(select(ScreenerCommentary))
    assert result.scalars().all() == []
