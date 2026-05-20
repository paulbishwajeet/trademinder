# Technicals Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture 19 technical indicators (MACD, RSI, MA, Bollinger, etc.) from yfinance on-demand when adding a trade or commentary, persist them to the `rationale` table, and display the snapshot inline in the commentary thread.

**Architecture:** A new `GET /api/market/technicals/{ticker}` endpoint computes all indicators synchronously in a thread executor and returns them without persisting. The user edits the values in a `TechnicalsPanel` component, then the snapshot is saved alongside the trade (via `PUT /api/trades/{id}/rationale`) or embedded in the commentary POST body. The `rationale` table gains a nullable `commentary_id` FK so a trade's entry-time snapshot (`commentary_id IS NULL`) and per-commentary snapshots share the same table.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, yfinance, pandas, React 19, TypeScript, Tailwind CSS, vanilla JS (extension)

---

## File Map

**New files:**
- `backend/alembic/versions/005_commentary_rationale_link.py`
- `backend/app/services/technicals_fetcher.py`
- `backend/tests/test_technicals_fetcher.py`
- `backend/tests/test_trade_rationale.py`
- `backend/tests/test_commentary_rationale.py`
- `frontend/src/api/technicals.ts`
- `frontend/src/components/shared/TechnicalsPanel.tsx`

**Modified files:**
- `backend/app/models/rationale.py` — add `commentary_id` FK, `commentary` relationship, update `__table_args__`
- `backend/app/models/commentary.py` — add `rationale` relationship
- `backend/app/models/trade.py` — add `primaryjoin` to `rationale` relationship
- `backend/app/schemas/trade.py` — add `RationaleCreate`
- `backend/app/schemas/commentary.py` — add `rationale` field to create/response schemas
- `backend/app/routers/market.py` — add `GET /api/market/technicals/{ticker}`
- `backend/app/routers/trades.py` — add `PUT /{trade_id}/rationale`
- `backend/app/routers/commentary.py` — extend POST to accept rationale, GET to eager-load it
- `frontend/src/types/index.ts` — add `TechnicalsData`, update `Commentary`
- `frontend/src/api/commentary.ts` — update `add` to accept optional rationale
- `frontend/src/components/Trades/TradeForm.tsx` — add TechnicalsPanel section
- `frontend/src/components/Commentary/CommentaryForm.tsx` — add TechnicalsPanel section
- `frontend/src/components/Commentary/CommentaryThread.tsx` — add rationale chip + expand
- `extension/content.js` — add `renderTechnicalsForm`, `getTechnicalsValue`, fetch+save wiring
- `extension/content.css` — styles for technicals panel

---

## Task 1: Alembic migration — add `commentary_id` to `rationale`

**Files:**
- Create: `backend/alembic/versions/005_commentary_rationale_link.py`

- [ ] **Step 1: Create the migration file**

```bash
cd backend && alembic revision -m "add_commentary_id_to_rationale"
```

This generates a file in `alembic/versions/`. Rename it to `005_commentary_rationale_link.py` and replace its body with:

```python
"""add commentary_id to rationale

Revision ID: 005
Revises: 004
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rationale",
        sa.Column("commentary_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_rationale_commentary_id",
        "rationale", "commentary",
        ["commentary_id"], ["id"],
        ondelete="CASCADE",
    )
    # Drop old unique constraint on trade_id
    op.drop_constraint("idx_rationale_trade", "rationale", type_="unique")
    # Partial unique index: only one entry-time rationale per trade
    op.execute(
        "CREATE UNIQUE INDEX idx_rationale_trade_entry "
        "ON rationale (trade_id) WHERE commentary_id IS NULL"
    )
    op.create_index("idx_rationale_commentary", "rationale", ["commentary_id"])


def downgrade() -> None:
    op.drop_index("idx_rationale_commentary", "rationale")
    op.execute("DROP INDEX IF EXISTS idx_rationale_trade_entry")
    op.create_unique_constraint("idx_rationale_trade", "rationale", ["trade_id"])
    op.drop_constraint("fk_rationale_commentary_id", "rationale", type_="foreignkey")
    op.drop_column("rationale", "commentary_id")
```

> Note: The `down_revision` must match the actual revision ID of `004_strategy_categories.py`. Open that file and copy its `revision` value into `down_revision` here.

- [ ] **Step 2: Run the migration**

```bash
cd backend && alembic upgrade head
```

Expected: `Running upgrade ... -> 005, add commentary_id to rationale`

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/005_commentary_rationale_link.py
git commit -m "feat: migration — add commentary_id FK to rationale table"
```

---

## Task 2: Update SQLAlchemy models

**Files:**
- Modify: `backend/app/models/rationale.py`
- Modify: `backend/app/models/commentary.py`
- Modify: `backend/app/models/trade.py`

- [ ] **Step 1: Update `rationale.py`**

Replace the entire file:

```python
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Numeric, Date, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text
from app.database import Base

if TYPE_CHECKING:
    from app.models.trade import Trade
    from app.models.commentary import Commentary


class Rationale(Base):
    __tablename__ = "rationale"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trade_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trades.id", ondelete="CASCADE"), nullable=False)
    commentary_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("commentary.id", ondelete="CASCADE"), nullable=True)

    macd_signal: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    macd_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rsi_14: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    rsi_result: Mapped[Optional[str]] = mapped_column(String(15), nullable=True)
    ma_200d: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    ma_50d: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    price_vs_ma200: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    price_vs_ma50: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    bollinger_upper: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    bollinger_mid: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    bollinger_lower: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    bollinger_position: Mapped[Optional[str]] = mapped_column(String(15), nullable=True)
    day_color: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    price_action: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    sentiment: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    next_earnings_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    fetch_status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    fetch_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    trade: Mapped["Trade"] = relationship(
        back_populates="rationale",
        foreign_keys="[Rationale.trade_id]",
    )
    commentary: Mapped[Optional["Commentary"]] = relationship(
        back_populates="rationale",
        foreign_keys="[Rationale.commentary_id]",
    )

    __table_args__ = (
        Index(
            "idx_rationale_trade_entry",
            "trade_id",
            unique=True,
            postgresql_where=text("commentary_id IS NULL"),
        ),
        Index("idx_rationale_commentary", "commentary_id"),
    )
```

- [ ] **Step 2: Update `commentary.py`**

Add the `rationale` relationship. Replace the entire file:

```python
import uuid
from datetime import date, datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import Date, Text, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.sql import func, text
from app.database import Base

if TYPE_CHECKING:
    from app.models.trade import Trade
    from app.models.rationale import Rationale


class Commentary(Base):
    __tablename__ = "commentary"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trade_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("trades.id", ondelete="CASCADE"), nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    note: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    trade: Mapped["Trade"] = relationship(back_populates="commentary")
    rationale: Mapped[Optional["Rationale"]] = relationship(
        back_populates="commentary",
        foreign_keys="[Rationale.commentary_id]",
        cascade="all, delete-orphan",
        uselist=False,
    )

    __table_args__ = (
        Index("idx_commentary_trade", "trade_id"),
        Index("idx_commentary_date", text("entry_date DESC")),
    )
```

- [ ] **Step 3: Update `trade.py` — add `primaryjoin` to `rationale` relationship**

In `backend/app/models/trade.py`, replace the `rationale` relationship line:

```python
    # Old:
    rationale: Mapped[Optional["Rationale"]] = relationship(back_populates="trade", cascade="all, delete-orphan", uselist=False)

    # New:
    rationale: Mapped[Optional["Rationale"]] = relationship(
        "Rationale",
        primaryjoin="and_(Trade.id == foreign(Rationale.trade_id), Rationale.commentary_id == None)",
        back_populates="trade",
        cascade="all, delete-orphan",
        uselist=False,
        overlaps="commentary",
    )
```

- [ ] **Step 4: Verify models import cleanly**

```bash
cd backend && python -c "import app.models; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/rationale.py backend/app/models/commentary.py backend/app/models/trade.py
git commit -m "feat: update SQLAlchemy models — commentary_id FK on rationale, rationale rel on Commentary"
```

---

## Task 3: Update Pydantic schemas

**Files:**
- Modify: `backend/app/schemas/trade.py`
- Modify: `backend/app/schemas/commentary.py`

- [ ] **Step 1: Add `RationaleCreate` to `trade.py`**

In `backend/app/schemas/trade.py`, add after the imports and before `RationaleResponse`:

```python
class RationaleCreate(BaseModel):
    macd_signal: Optional[str] = None
    macd_notes: Optional[str] = None
    rsi_14: Optional[Decimal] = None
    rsi_result: Optional[str] = None
    ma_200d: Optional[Decimal] = None
    ma_50d: Optional[Decimal] = None
    price_vs_ma200: Optional[str] = None
    price_vs_ma50: Optional[str] = None
    bollinger_upper: Optional[Decimal] = None
    bollinger_mid: Optional[Decimal] = None
    bollinger_lower: Optional[Decimal] = None
    bollinger_position: Optional[str] = None
    day_color: Optional[str] = None
    price_action: Optional[str] = None
    sentiment: Optional[str] = None
    next_earnings_date: Optional[date] = None
    fetch_error: Optional[str] = None
    notes: Optional[str] = None
```

Also add `commentary_id: Optional[uuid.UUID] = None` to `RationaleResponse`:

```python
class RationaleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    trade_id: uuid.UUID
    commentary_id: Optional[uuid.UUID] = None   # ← add this line
    macd_signal: Optional[str] = None
    # ... rest unchanged
```

- [ ] **Step 2: Update `commentary.py` schemas**

Replace `backend/app/schemas/commentary.py` entirely:

```python
import uuid
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict
from app.schemas.trade import RationaleCreate, RationaleResponse


class CommentaryCreate(BaseModel):
    note: str
    tags: Optional[list[str]] = None
    rationale: Optional[RationaleCreate] = None


class CommentaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    trade_id: uuid.UUID
    entry_date: date
    note: str
    tags: Optional[list[str]] = None
    created_at: datetime
    rationale: Optional[RationaleResponse] = None
```

- [ ] **Step 3: Verify schemas import cleanly**

```bash
cd backend && python -c "from app.schemas.commentary import CommentaryCreate, CommentaryResponse; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/schemas/trade.py backend/app/schemas/commentary.py
git commit -m "feat: add RationaleCreate schema; add rationale field to CommentaryCreate/Response"
```

---

## Task 4: Technicals fetcher service (TDD)

**Files:**
- Create: `backend/tests/test_technicals_fetcher.py`
- Create: `backend/app/services/technicals_fetcher.py`

- [ ] **Step 1: Write the tests**

Create `backend/tests/test_technicals_fetcher.py`:

```python
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

from app.services.technicals_fetcher import (
    fetch_technicals,
    _compute_macd_weekly,
    _bollinger_position,
    _infer_sentiment,
)


def _daily(n: int = 200, start: float = 100.0, step: float = 0.25) -> pd.DataFrame:
    close = pd.Series([start + i * step for i in range(n)])
    return pd.DataFrame({"Close": close})


def _weekly(n: int = 60, start: float = 95.0, step: float = 0.5) -> pd.DataFrame:
    close = pd.Series([start + i * step for i in range(n)])
    return pd.DataFrame({"Close": close})


# --- unit tests for helpers ---

def test_bollinger_above_upper():
    assert _bollinger_position(125.0, 120.0, 100.0, 80.0) == "above_upper"

def test_bollinger_near_upper():
    assert _bollinger_position(116.0, 120.0, 100.0, 80.0) == "near_upper"

def test_bollinger_mid():
    assert _bollinger_position(100.0, 120.0, 100.0, 80.0) == "mid"

def test_bollinger_near_lower():
    assert _bollinger_position(84.0, 120.0, 100.0, 80.0) == "near_lower"

def test_bollinger_below_lower():
    assert _bollinger_position(75.0, 120.0, 100.0, 80.0) == "below_lower"

def test_bollinger_zero_band_returns_mid():
    assert _bollinger_position(100.0, 100.0, 100.0, 100.0) == "mid"


def test_infer_sentiment_bullish():
    assert _infer_sentiment("bullish", 110.0, 100.0, 50.0) == "bullish"

def test_infer_sentiment_bullish_overbought_rsi():
    # RSI > 70 → not bullish
    assert _infer_sentiment("bullish", 110.0, 100.0, 75.0) == "neutral"

def test_infer_sentiment_bearish():
    assert _infer_sentiment("bearish", 90.0, 100.0, 50.0) == "bearish"

def test_infer_sentiment_mixed_neutral():
    assert _infer_sentiment("bullish", 90.0, 100.0, 50.0) == "neutral"

def test_infer_sentiment_no_ma50():
    assert _infer_sentiment("bullish", 110.0, None, 50.0) == "neutral"


def test_macd_weekly_bullish():
    # Rising series → MACD line above signal
    close = pd.Series([100.0 + i for i in range(60)])
    result = _compute_macd_weekly(close)
    assert result["macd_signal"] == "bullish"
    assert result["macd_notes"] == "above 0 line"

def test_macd_weekly_bearish():
    # Falling series
    close = pd.Series([200.0 - i for i in range(60)])
    result = _compute_macd_weekly(close)
    assert result["macd_signal"] == "bearish"

def test_macd_weekly_insufficient_data():
    close = pd.Series([100.0] * 10)
    result = _compute_macd_weekly(close)
    assert result["macd_signal"] == "neutral"


# --- integration: fetch_technicals ---

def test_fetch_technicals_success():
    mock_calendar = {"Earnings Date": ["2026-08-15"]}

    with patch("app.services.technicals_fetcher.yf.download") as mock_dl, \
         patch("app.services.technicals_fetcher.yf.Ticker") as mock_ticker:
        mock_dl.side_effect = [_daily(200), _weekly(60)]
        mock_ticker.return_value.calendar = mock_calendar

        result = fetch_technicals("AAPL")

    assert result["fetch_status"] == "ok"
    assert result["fetch_error"] is None
    assert result["price_action"] is not None
    assert result["rsi_14"] is not None
    assert result["ma_200d"] is not None
    assert result["ma_50d"] is not None
    assert result["bollinger_upper"] is not None
    assert result["macd_signal"] in ("bullish", "bearish", "neutral")
    assert result["sentiment"] in ("bullish", "bearish", "neutral")
    assert result["next_earnings_date"] == "2026-08-15"
    assert result["day_color"] in ("green", "red")


def test_fetch_technicals_empty_daily_data():
    with patch("app.services.technicals_fetcher.yf.download") as mock_dl:
        mock_dl.return_value = pd.DataFrame()
        result = fetch_technicals("INVALID")

    assert result["fetch_status"] == "error"
    assert result["fetch_error"] is not None


def test_fetch_technicals_insufficient_daily_rows():
    with patch("app.services.technicals_fetcher.yf.download") as mock_dl:
        mock_dl.side_effect = [_daily(1), _weekly(60)]
        result = fetch_technicals("AAPL")

    assert result["fetch_status"] == "error"


def test_fetch_technicals_no_ma200_when_insufficient_history():
    with patch("app.services.technicals_fetcher.yf.download") as mock_dl, \
         patch("app.services.technicals_fetcher.yf.Ticker") as mock_ticker:
        mock_dl.side_effect = [_daily(60), _weekly(60)]
        mock_ticker.return_value.calendar = {}
        result = fetch_technicals("AAPL")

    assert result["fetch_status"] == "ok"
    assert result["ma_200d"] is None   # only 60 bars
    assert result["ma_50d"] is not None  # 60 >= 50


def test_fetch_technicals_exception_returns_error():
    with patch("app.services.technicals_fetcher.yf.download", side_effect=RuntimeError("timeout")):
        result = fetch_technicals("AAPL")
    assert result["fetch_status"] == "error"
    assert "timeout" in result["fetch_error"]
```

- [ ] **Step 2: Run tests — verify they all fail**

```bash
cd backend && python -m pytest tests/test_technicals_fetcher.py -v 2>&1 | head -20
```

Expected: `ImportError` or `ModuleNotFoundError` for `technicals_fetcher`.

- [ ] **Step 3: Implement `technicals_fetcher.py`**

Create `backend/app/services/technicals_fetcher.py`:

```python
# backend/app/services/technicals_fetcher.py
import yfinance as yf
import pandas as pd

from app.services.price_fetcher import _compute_rsi_14


def _compute_macd_weekly(close_w: pd.Series) -> dict[str, str]:
    if len(close_w) < 26:
        return {"macd_signal": "neutral", "macd_notes": "below 0 line"}
    exp1 = close_w.ewm(span=12, adjust=False).mean()
    exp2 = close_w.ewm(span=26, adjust=False).mean()
    macd_line = exp1 - exp2
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    last_macd = float(macd_line.iloc[-1])
    last_signal = float(signal_line.iloc[-1])
    if last_macd > last_signal:
        macd_signal = "bullish"
    elif last_macd < last_signal:
        macd_signal = "bearish"
    else:
        macd_signal = "neutral"
    macd_notes = "above 0 line" if last_macd > 0 else "below 0 line"
    return {"macd_signal": macd_signal, "macd_notes": macd_notes}


def _bollinger_position(price: float, upper: float, mid: float, lower: float) -> str:
    band_width = upper - lower
    if band_width == 0:
        return "mid"
    upper_zone = mid + (band_width * 0.25)
    lower_zone = mid - (band_width * 0.25)
    if price > upper:
        return "above_upper"
    if price > upper_zone:
        return "near_upper"
    if price < lower:
        return "below_lower"
    if price < lower_zone:
        return "near_lower"
    return "mid"


def _infer_sentiment(macd_signal: str, price: float, ma_50d: float | None, rsi_14: float | None) -> str:
    if ma_50d is None:
        return "neutral"
    if macd_signal == "bullish" and price > ma_50d and (rsi_14 is None or rsi_14 <= 70):
        return "bullish"
    if macd_signal == "bearish" and price < ma_50d:
        return "bearish"
    return "neutral"


def _get_next_earnings(ticker: str) -> str | None:
    try:
        cal = yf.Ticker(ticker).calendar
        if not cal:
            return None
        dates = cal.get("Earnings Date")
        if not dates:
            return None
        if isinstance(dates, list) and dates:
            return str(dates[0])[:10]
        return str(dates)[:10]
    except Exception:
        return None


def fetch_technicals(ticker: str) -> dict:
    try:
        df_d = yf.download(ticker, period="200d", interval="1d", progress=False, auto_adjust=True)
        if df_d is None or df_d.empty:
            return {"fetch_status": "error", "fetch_error": f"No daily data for {ticker}"}

        close_d = df_d["Close"]
        if isinstance(close_d, pd.DataFrame):
            close_d = close_d.iloc[:, 0]
        close_d = close_d.dropna()

        if len(close_d) < 2:
            return {"fetch_status": "error", "fetch_error": f"Insufficient daily history for {ticker}"}

        df_w = yf.download(ticker, period="2y", interval="1wk", progress=False, auto_adjust=True)
        close_w = pd.Series(dtype=float)
        if df_w is not None and not df_w.empty:
            close_w = df_w["Close"]
            if isinstance(close_w, pd.DataFrame):
                close_w = close_w.iloc[:, 0]
            close_w = close_w.dropna()

        price = round(float(close_d.iloc[-1]), 2)
        prev_price = round(float(close_d.iloc[-2]), 2)
        day_color = "green" if price >= prev_price else "red"

        rsi_14 = _compute_rsi_14(close_d)
        rsi_result = None
        if rsi_14 is not None:
            if rsi_14 < 30:
                rsi_result = "rsi_oversold"
            elif rsi_14 > 70:
                rsi_result = "rsi_overbought"

        ma_200d = round(float(close_d.rolling(200).mean().iloc[-1]), 2) if len(close_d) >= 200 else None
        ma_50d = round(float(close_d.rolling(50).mean().iloc[-1]), 2) if len(close_d) >= 50 else None

        price_vs_ma200 = ("above" if price > ma_200d else "below") if ma_200d is not None else None
        price_vs_ma50 = ("above" if price > ma_50d else "below") if ma_50d is not None else None

        rolling_mean = close_d.rolling(20).mean()
        rolling_std = close_d.rolling(20).std()
        b_mid = round(float(rolling_mean.iloc[-1]), 2) if len(close_d) >= 20 else None
        b_upper = round(float((rolling_mean + rolling_std * 2).iloc[-1]), 2) if len(close_d) >= 20 else None
        b_lower = round(float((rolling_mean - rolling_std * 2).iloc[-1]), 2) if len(close_d) >= 20 else None
        b_pos = _bollinger_position(price, b_upper, b_mid, b_lower) if (b_upper and b_mid and b_lower) else None

        macd = _compute_macd_weekly(close_w)
        sentiment = _infer_sentiment(macd["macd_signal"], price, ma_50d, rsi_14)
        next_earnings = _get_next_earnings(ticker)

        return {
            "macd_signal": macd["macd_signal"],
            "macd_notes": macd["macd_notes"],
            "rsi_14": rsi_14,
            "rsi_result": rsi_result,
            "ma_200d": ma_200d,
            "ma_50d": ma_50d,
            "price_vs_ma200": price_vs_ma200,
            "price_vs_ma50": price_vs_ma50,
            "bollinger_upper": b_upper,
            "bollinger_mid": b_mid,
            "bollinger_lower": b_lower,
            "bollinger_position": b_pos,
            "day_color": day_color,
            "price_action": str(price),
            "sentiment": sentiment,
            "next_earnings_date": next_earnings,
            "fetch_status": "ok",
            "fetch_error": None,
        }
    except Exception as exc:
        return {"fetch_status": "error", "fetch_error": str(exc)}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd backend && python -m pytest tests/test_technicals_fetcher.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/technicals_fetcher.py backend/tests/test_technicals_fetcher.py
git commit -m "feat: technicals fetcher service — MACD/RSI/MA/Bollinger/earnings from yfinance"
```

---

## Task 5: `GET /api/market/technicals/{ticker}` endpoint (TDD)

**Files:**
- Create: `backend/tests/test_market_technicals.py`
- Modify: `backend/app/routers/market.py`

- [ ] **Step 1: Write the test**

Create `backend/tests/test_market_technicals.py`:

```python
import pytest
from httpx import AsyncClient
from unittest.mock import patch

MOCK_TECHNICALS = {
    "macd_signal": "bullish",
    "macd_notes": "above 0 line",
    "rsi_14": 45.5,
    "rsi_result": None,
    "ma_200d": 150.0,
    "ma_50d": 155.0,
    "price_vs_ma200": "above",
    "price_vs_ma50": "above",
    "bollinger_upper": 165.0,
    "bollinger_mid": 157.0,
    "bollinger_lower": 149.0,
    "bollinger_position": "mid",
    "day_color": "green",
    "price_action": "158.50",
    "sentiment": "bullish",
    "next_earnings_date": "2026-08-15",
    "fetch_status": "ok",
    "fetch_error": None,
}


async def test_get_technicals_success(client: AsyncClient):
    with patch("app.routers.market.fetch_technicals", return_value=MOCK_TECHNICALS):
        response = await client.get("/api/market/technicals/AAPL")
    assert response.status_code == 200
    data = response.json()
    assert data["macd_signal"] == "bullish"
    assert data["fetch_status"] == "ok"
    assert data["price_action"] == "158.50"


async def test_get_technicals_fetch_error_returns_200_with_error_status(client: AsyncClient):
    error_result = {"fetch_status": "error", "fetch_error": "No data"}
    with patch("app.routers.market.fetch_technicals", return_value=error_result):
        response = await client.get("/api/market/technicals/INVALID")
    assert response.status_code == 200
    assert response.json()["fetch_status"] == "error"


async def test_get_technicals_ticker_uppercased(client: AsyncClient):
    with patch("app.routers.market.fetch_technicals", return_value=MOCK_TECHNICALS) as mock_fn:
        await client.get("/api/market/technicals/aapl")
    mock_fn.assert_called_once_with("AAPL")
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd backend && python -m pytest tests/test_market_technicals.py -v 2>&1 | head -15
```

Expected: `404 Not Found` (endpoint not yet wired).

- [ ] **Step 3: Add the endpoint to `market.py`**

In `backend/app/routers/market.py`, add the import and replace the stub `prefetch_indicators` with a real endpoint:

```python
# Add to imports at top of file:
from app.services.technicals_fetcher import fetch_technicals

# Add new endpoint (replace the prefetch_indicators stub):
@router.get("/technicals/{ticker}")
async def get_technicals(ticker: str):
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, fetch_technicals, ticker.upper())
    return result
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd backend && python -m pytest tests/test_market_technicals.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/market.py backend/tests/test_market_technicals.py
git commit -m "feat: GET /api/market/technicals/{ticker} — on-demand technicals fetch endpoint"
```

---

## Task 6: `PUT /api/trades/{trade_id}/rationale` endpoint (TDD)

**Files:**
- Create: `backend/tests/test_trade_rationale.py`
- Modify: `backend/app/routers/trades.py`

- [ ] **Step 1: Write the tests**

Create `backend/tests/test_trade_rationale.py`:

```python
import pytest
from httpx import AsyncClient
from datetime import date

TRADE_PAYLOAD = {
    "type": "Sell",
    "category": "WHEEL",
    "strategy": "Put",
    "ticker": "AAPL",
    "open_date": str(date.today()),
    "quantity": 1,
}

RATIONALE_PAYLOAD = {
    "rsi_14": "45.50",
    "macd_signal": "bullish",
    "macd_notes": "above 0 line",
    "ma_200d": "150.00",
    "ma_50d": "155.00",
    "price_vs_ma200": "above",
    "price_vs_ma50": "above",
    "bollinger_upper": "165.00",
    "bollinger_mid": "157.00",
    "bollinger_lower": "149.00",
    "bollinger_position": "mid",
    "day_color": "green",
    "price_action": "158.50",
    "sentiment": "bullish",
    "notes": "Strong momentum",
}


async def _create_trade(client: AsyncClient) -> str:
    resp = await client.post("/api/trades", json=TRADE_PAYLOAD)
    assert resp.status_code == 201
    return resp.json()["id"]


async def test_upsert_trade_rationale(client: AsyncClient):
    trade_id = await _create_trade(client)
    response = await client.put(f"/api/trades/{trade_id}/rationale", json=RATIONALE_PAYLOAD)
    assert response.status_code == 200
    data = response.json()
    assert float(data["rsi_14"]) == 45.50
    assert data["macd_signal"] == "bullish"
    assert data["fetch_status"] == "ok"
    assert data["commentary_id"] is None


async def test_upsert_trade_rationale_is_idempotent(client: AsyncClient):
    trade_id = await _create_trade(client)
    await client.put(f"/api/trades/{trade_id}/rationale", json=RATIONALE_PAYLOAD)
    # Second upsert updates the same row
    updated = {**RATIONALE_PAYLOAD, "macd_signal": "bearish"}
    response = await client.put(f"/api/trades/{trade_id}/rationale", json=updated)
    assert response.status_code == 200
    assert response.json()["macd_signal"] == "bearish"

    # Only one entry-time rationale row exists
    detail = await client.get(f"/api/trades/{trade_id}")
    assert detail.json()["rationale"]["macd_signal"] == "bearish"


async def test_upsert_rationale_trade_not_found(client: AsyncClient):
    response = await client.put(
        "/api/trades/00000000-0000-0000-0000-000000000000/rationale",
        json=RATIONALE_PAYLOAD,
    )
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd backend && python -m pytest tests/test_trade_rationale.py -v 2>&1 | head -15
```

Expected: `405 Method Not Allowed` (endpoint missing).

- [ ] **Step 3: Add the endpoint to `trades.py`**

In `backend/app/routers/trades.py`, add the import and new endpoint. Add to imports:

```python
from app.schemas.trade import TradeCreate, TradeUpdate, TradeListItem, TradeResponse, RationaleCreate, RationaleResponse
```

Add endpoint after `get_trade`:

```python
@router.put("/{trade_id}/rationale", response_model=RationaleResponse)
async def upsert_trade_rationale(
    trade_id: uuid.UUID,
    payload: RationaleCreate,
    db: AsyncSession = Depends(get_db),
):
    # Verify trade exists
    trade_stmt = select(Trade).where(Trade.id == trade_id)
    trade_result = await db.execute(trade_stmt)
    if trade_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Trade not found")

    # Find existing entry-time rationale (commentary_id IS NULL)
    stmt = select(Rationale).where(
        Rationale.trade_id == trade_id,
        Rationale.commentary_id.is_(None),
    )
    result = await db.execute(stmt)
    rationale = result.scalar_one_or_none()

    if rationale is None:
        rationale = Rationale(trade_id=trade_id, commentary_id=None)
        db.add(rationale)

    data = payload.model_dump(exclude_none=True)
    data["fetch_status"] = "ok"
    for field, value in data.items():
        setattr(rationale, field, value)

    await db.commit()
    await db.refresh(rationale)
    return rationale
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd backend && python -m pytest tests/test_trade_rationale.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/trades.py backend/tests/test_trade_rationale.py
git commit -m "feat: PUT /api/trades/{id}/rationale — upsert entry-time technicals snapshot"
```

---

## Task 7: Extend commentary POST + GET with rationale (TDD)

**Files:**
- Create: `backend/tests/test_commentary_rationale.py`
- Modify: `backend/app/routers/commentary.py`

- [ ] **Step 1: Write the tests**

Create `backend/tests/test_commentary_rationale.py`:

```python
import pytest
from httpx import AsyncClient
from datetime import date

TRADE_PAYLOAD = {
    "type": "Sell",
    "category": "WHEEL",
    "strategy": "Put",
    "ticker": "AAPL",
    "open_date": str(date.today()),
    "quantity": 1,
}

RATIONALE_SNIPPET = {
    "rsi_14": "35.20",
    "macd_signal": "bullish",
    "sentiment": "bullish",
}


async def _create_trade(client: AsyncClient) -> str:
    resp = await client.post("/api/trades", json=TRADE_PAYLOAD)
    return resp.json()["id"]


async def test_add_commentary_with_rationale(client: AsyncClient):
    trade_id = await _create_trade(client)
    response = await client.post(
        f"/api/trades/{trade_id}/commentary",
        json={"note": "RSI looks good", "rationale": RATIONALE_SNIPPET},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["note"] == "RSI looks good"
    assert data["rationale"] is not None
    assert float(data["rationale"]["rsi_14"]) == 35.20
    assert data["rationale"]["macd_signal"] == "bullish"
    assert data["rationale"]["commentary_id"] == data["id"]


async def test_add_commentary_without_rationale(client: AsyncClient):
    trade_id = await _create_trade(client)
    response = await client.post(
        f"/api/trades/{trade_id}/commentary",
        json={"note": "Just watching"},
    )
    assert response.status_code == 201
    assert response.json()["rationale"] is None


async def test_list_commentary_includes_rationale(client: AsyncClient):
    trade_id = await _create_trade(client)
    await client.post(
        f"/api/trades/{trade_id}/commentary",
        json={"note": "With technicals", "rationale": RATIONALE_SNIPPET},
    )
    await client.post(
        f"/api/trades/{trade_id}/commentary",
        json={"note": "Without technicals"},
    )
    response = await client.get(f"/api/trades/{trade_id}/commentary")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    with_rat = next(d for d in data if d["note"] == "With technicals")
    without_rat = next(d for d in data if d["note"] == "Without technicals")
    assert with_rat["rationale"] is not None
    assert without_rat["rationale"] is None


async def test_commentary_rationale_deleted_with_commentary(client: AsyncClient):
    """Deleting a comment must cascade-delete its rationale."""
    trade_id = await _create_trade(client)
    create_resp = await client.post(
        f"/api/trades/{trade_id}/commentary",
        json={"note": "To delete", "rationale": RATIONALE_SNIPPET},
    )
    comment_id = create_resp.json()["id"]
    del_resp = await client.delete(f"/api/commentary/{comment_id}")
    assert del_resp.status_code == 204

    list_resp = await client.get(f"/api/trades/{trade_id}/commentary")
    assert list_resp.json() == []
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd backend && python -m pytest tests/test_commentary_rationale.py -v 2>&1 | head -20
```

Expected: failures because `rationale` key is missing from response and POST ignores `rationale` field.

- [ ] **Step 3: Update `commentary.py` router**

Replace `backend/app/routers/commentary.py` `add_commentary` and `list_commentary` functions:

```python
# backend/app/routers/commentary.py
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from anthropic import AsyncAnthropic

from app.database import get_db
from app.models.commentary import Commentary
from app.models.rationale import Rationale
from app.schemas.commentary import CommentaryCreate, CommentaryResponse

router = APIRouter(tags=["commentary"])


@router.get("/api/trades/{trade_id}/commentary", response_model=list[CommentaryResponse])
async def list_commentary(trade_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Commentary)
        .where(Commentary.trade_id == trade_id)
        .options(selectinload(Commentary.rationale))
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
    await db.flush()  # get comment.id before creating rationale

    if payload.rationale is not None:
        rat_data = payload.rationale.model_dump(exclude_none=True)
        rat_data["fetch_status"] = "ok"
        rationale = Rationale(
            trade_id=trade_id,
            commentary_id=comment.id,
            **rat_data,
        )
        db.add(rationale)

    await db.commit()

    stmt = (
        select(Commentary)
        .where(Commentary.id == comment.id)
        .options(selectinload(Commentary.rationale))
    )
    result = await db.execute(stmt)
    return result.scalar_one()


@router.delete("/api/commentary/{comment_id}", status_code=204)
async def delete_commentary(comment_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = select(Commentary).where(Commentary.id == comment_id)
    result = await db.execute(stmt)
    comment = result.scalar_one_or_none()
    if comment is None:
        raise HTTPException(status_code=404, detail="Commentary entry not found")
    await db.delete(comment)
    await db.commit()
```

Keep the `commentary_summary` endpoint below unchanged (it's unaffected by this change).

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd backend && python -m pytest tests/test_commentary_rationale.py tests/test_commentary.py -v
```

Expected: all green (both new and existing commentary tests).

- [ ] **Step 5: Run the full backend suite**

```bash
cd backend && python -m pytest -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/commentary.py backend/tests/test_commentary_rationale.py
git commit -m "feat: commentary POST accepts rationale snapshot; GET eager-loads rationale"
```

---

## Task 8: Frontend — types + API layer

**Files:**
- Modify: `frontend/src/types/index.ts`
- Create: `frontend/src/api/technicals.ts`
- Modify: `frontend/src/api/commentary.ts`

- [ ] **Step 1: Update `types/index.ts`**

Add `TechnicalsData` interface and update `Commentary`:

```typescript
// Add after the Rationale interface:
export interface TechnicalsData {
  macd_signal: string | null
  macd_notes: string | null
  rsi_14: number | null
  rsi_result: string | null
  ma_200d: number | null
  ma_50d: number | null
  price_vs_ma200: string | null
  price_vs_ma50: string | null
  bollinger_upper: number | null
  bollinger_mid: number | null
  bollinger_lower: number | null
  bollinger_position: string | null
  day_color: string | null
  price_action: string | null
  sentiment: string | null
  next_earnings_date: string | null
  fetch_status: string
  fetch_error: string | null
  notes: string | null
}

// Update Commentary interface — add rationale field:
export interface Commentary {
  id: string
  trade_id: string
  entry_date: string
  note: string
  tags: string[] | null
  created_at: string
  rationale: Rationale | null   // ← add this
}
```

- [ ] **Step 2: Create `api/technicals.ts`**

```typescript
// frontend/src/api/technicals.ts
import { apiFetch } from './client'
import type { TechnicalsData } from '../types'

export const technicalsApi = {
  fetch: (ticker: string) =>
    apiFetch<TechnicalsData>(`/market/technicals/${ticker}`),

  saveTradeRationale: (tradeId: string, data: TechnicalsData) =>
    apiFetch<void>(`/trades/${tradeId}/rationale`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
}
```

- [ ] **Step 3: Update `api/commentary.ts`**

```typescript
// frontend/src/api/commentary.ts
import { apiFetch } from './client'
import type { Commentary, TechnicalsData } from '../types'

export const commentaryApi = {
  list: (tradeId: string) =>
    apiFetch<Commentary[]>(`/trades/${tradeId}/commentary`),

  add: (tradeId: string, payload: { note: string; tags?: string[]; rationale?: TechnicalsData | null }) =>
    apiFetch<Commentary>(`/trades/${tradeId}/commentary`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  delete: (commentId: string) =>
    apiFetch<void>(`/commentary/${commentId}`, { method: 'DELETE' }),
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/technicals.ts frontend/src/api/commentary.ts
git commit -m "feat: frontend types + API — TechnicalsData type, technicals API, commentary rationale"
```

---

## Task 9: `TechnicalsPanel` component

**Files:**
- Create: `frontend/src/components/shared/TechnicalsPanel.tsx`

- [ ] **Step 1: Create the component**

```tsx
// frontend/src/components/shared/TechnicalsPanel.tsx
import { useState } from 'react'
import { technicalsApi } from '../../api/technicals'
import type { TechnicalsData } from '../../types'

interface Props {
  ticker: string
  onChange: (data: TechnicalsData | null) => void
}

const SELECT_FIELDS: Record<string, string[]> = {
  macd_signal: ['bullish', 'bearish', 'neutral'],
  rsi_result: ['rsi_oversold', 'rsi_overbought'],
  price_vs_ma200: ['above', 'below'],
  price_vs_ma50: ['above', 'below'],
  bollinger_position: ['above_upper', 'near_upper', 'mid', 'near_lower', 'below_lower'],
  day_color: ['green', 'red'],
  sentiment: ['bullish', 'bearish', 'neutral'],
}

const FIELD_LABELS: Record<string, string> = {
  macd_signal: 'MACD Signal', macd_notes: 'MACD Notes', rsi_14: 'RSI-14',
  rsi_result: 'RSI Result', ma_200d: 'MA 200D', ma_50d: 'MA 50D',
  price_vs_ma200: 'Price vs MA200', price_vs_ma50: 'Price vs MA50',
  bollinger_upper: 'BB Upper', bollinger_mid: 'BB Mid', bollinger_lower: 'BB Lower',
  bollinger_position: 'BB Position', day_color: 'Day Color', price_action: 'Price',
  sentiment: 'Sentiment', next_earnings_date: 'Next Earnings', notes: 'Notes',
}

const FIELD_ORDER = [
  'price_action', 'day_color', 'rsi_14', 'rsi_result',
  'macd_signal', 'macd_notes', 'ma_200d', 'ma_50d',
  'price_vs_ma200', 'price_vs_ma50', 'bollinger_upper', 'bollinger_mid',
  'bollinger_lower', 'bollinger_position', 'sentiment', 'next_earnings_date', 'notes',
]

export function TechnicalsPanel({ ticker, onChange }: Props) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<TechnicalsData | null>(null)

  const handleFetch = async () => {
    if (!ticker.trim()) { setError('Enter a ticker first'); return }
    setLoading(true)
    setError(null)
    try {
      const result = await technicalsApi.fetch(ticker.trim().toUpperCase())
      if (result.fetch_status === 'error') {
        setError(result.fetch_error ?? 'Fetch failed')
        return
      }
      setData(result)
      setOpen(true)
      onChange(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Fetch failed')
    } finally {
      setLoading(false)
    }
  }

  const handleClear = () => {
    setData(null)
    setOpen(false)
    onChange(null)
  }

  const handleChange = (field: string, value: string) => {
    if (!data) return
    const updated = { ...data, [field]: value || null }
    setData(updated)
    onChange(updated)
  }

  return (
    <div className="border border-gray-200 rounded-lg p-3 bg-gray-50">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={handleFetch}
          disabled={loading}
          className="px-3 py-1.5 bg-indigo-600 text-white rounded text-xs hover:bg-indigo-700 disabled:opacity-50"
        >
          {loading ? 'Fetching…' : '📊 Fetch Technicals'}
        </button>
        {data && (
          <button type="button" onClick={handleClear} className="text-xs text-gray-400 hover:text-red-500">
            Clear
          </button>
        )}
        {data && (
          <button
            type="button"
            onClick={() => setOpen(o => !o)}
            className="text-xs text-indigo-600 hover:underline ml-auto"
          >
            {open ? 'Collapse ▲' : 'Expand ▼'}
          </button>
        )}
      </div>

      {error && <p className="text-red-500 text-xs mt-1">{error}</p>}

      {data && open && (
        <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2">
          {FIELD_ORDER.map(field => {
            const label = FIELD_LABELS[field] ?? field
            const value = (data as Record<string, unknown>)[field]
            const strValue = value != null ? String(value) : ''
            const isSelect = field in SELECT_FIELDS

            return (
              <div key={field} className={field === 'notes' ? 'col-span-2' : ''}>
                <label className="block text-xs text-gray-500">{label}</label>
                {field === 'notes' ? (
                  <textarea
                    rows={2}
                    value={strValue}
                    onChange={e => handleChange(field, e.target.value)}
                    className="mt-0.5 block w-full border border-gray-300 rounded px-2 py-1 text-xs"
                  />
                ) : isSelect ? (
                  <select
                    value={strValue}
                    onChange={e => handleChange(field, e.target.value)}
                    className="mt-0.5 block w-full border border-gray-300 rounded px-2 py-1 text-xs"
                  >
                    <option value="">—</option>
                    {SELECT_FIELDS[field].map(opt => (
                      <option key={opt} value={opt}>{opt}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={strValue}
                    onChange={e => handleChange(field, e.target.value)}
                    className="mt-0.5 block w-full border border-gray-300 rounded px-2 py-1 text-xs"
                  />
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/shared/TechnicalsPanel.tsx
git commit -m "feat: TechnicalsPanel component — fetch, edit, clear all 19 technicals fields"
```

---

## Task 10: Update `TradeForm` — add TechnicalsPanel

**Files:**
- Modify: `frontend/src/components/Trades/TradeForm.tsx`
- Modify: `frontend/src/pages/TradesPage.tsx` (or wherever `TradeForm.onSubmit` is called — find it with grep)

- [ ] **Step 1: Find where `TradeForm.onSubmit` is handled**

```bash
grep -rn "TradeForm\|onSubmit.*trade\|tradesApi.create" frontend/src/
```

Note the file and function that calls `tradesApi.create` — you will update that handler.

- [ ] **Step 2: Update `TradeForm.tsx`**

Add the `TechnicalsPanel` import and a `technicalsData` state. The form now calls `onSubmit` with the trade payload AND returns the technicals snapshot separately via a new `onTechnicalsChange` prop so the parent can fire the second request.

Replace the entire `TradeForm.tsx`:

```tsx
// frontend/src/components/Trades/TradeForm.tsx
import { useState, useEffect } from 'react'
import type { TradeCreate, TechnicalsData } from '../../types'
import { TechnicalsPanel } from '../shared/TechnicalsPanel'

interface Category { id: string; name: string; color: string }

interface Props {
  onSubmit: (payload: TradeCreate, technicals: TechnicalsData | null) => Promise<void>
  onCancel: () => void
}

const STRATEGIES = ['Stock', 'Put', 'Call', 'CoveredCall', 'PutCreditSpread', 'Leap']
const TYPES = ['Buy', 'Sell', 'Assigned']

export function TradeForm({ onSubmit, onCancel }: Props) {
  const today = new Date().toISOString().split('T')[0]
  const [form, setForm] = useState<TradeCreate>({
    type: 'Sell', category: 'WHEEL', strategy: 'Put',
    ticker: '', open_date: today, quantity: 1,
  })
  const [technicals, setTechnicals] = useState<TechnicalsData | null>(null)
  const [techOpen, setTechOpen] = useState(false)
  const [categories, setCategories] = useState<Category[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/categories').then(r => r.json()).then(setCategories).catch(() => {})
  }, [])

  const set = (field: keyof TradeCreate, value: unknown) =>
    setForm(prev => ({ ...prev, [field]: value }))

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      await onSubmit(form, technicals)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create trade')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && <div className="p-3 bg-red-50 text-red-700 rounded text-sm">{error}</div>}

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700">Ticker *</label>
          <input required value={form.ticker} onChange={e => set('ticker', e.target.value.toUpperCase())}
            className="mt-1 block w-full border border-gray-300 rounded px-3 py-2 text-sm uppercase" placeholder="AAPL" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Type *</label>
          <select value={form.type} onChange={e => set('type', e.target.value)} className="mt-1 block w-full border border-gray-300 rounded px-3 py-2 text-sm">
            {TYPES.map(t => <option key={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Strategy *</label>
          <select value={form.strategy} onChange={e => set('strategy', e.target.value)} className="mt-1 block w-full border border-gray-300 rounded px-3 py-2 text-sm">
            {STRATEGIES.map(s => <option key={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Category *</label>
          <select value={form.category} onChange={e => set('category', e.target.value)} className="mt-1 block w-full border border-gray-300 rounded px-3 py-2 text-sm">
            {categories.length === 0
              ? <option value="" disabled>Loading...</option>
              : categories.map(c => <option key={c.id} value={c.name}>{c.name}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Open Date *</label>
          <input type="date" required value={form.open_date} onChange={e => set('open_date', e.target.value)} className="mt-1 block w-full border border-gray-300 rounded px-3 py-2 text-sm" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Expiry Date</label>
          <input type="date" value={form.expiry_date ?? ''} onChange={e => set('expiry_date', e.target.value || null)} className="mt-1 block w-full border border-gray-300 rounded px-3 py-2 text-sm" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Strike Price</label>
          <input type="number" step="0.01" value={form.strike_price ?? ''} onChange={e => set('strike_price', e.target.value ? parseFloat(e.target.value) : null)} className="mt-1 block w-full border border-gray-300 rounded px-3 py-2 text-sm" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Quantity *</label>
          <input type="number" required min="1" value={form.quantity} onChange={e => set('quantity', parseInt(e.target.value))} className="mt-1 block w-full border border-gray-300 rounded px-3 py-2 text-sm" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Premium</label>
          <input type="number" step="0.01" value={form.premium ?? ''} onChange={e => set('premium', e.target.value ? parseFloat(e.target.value) : null)} className="mt-1 block w-full border border-gray-300 rounded px-3 py-2 text-sm" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Collateral</label>
          <input type="number" step="0.01" value={form.collateral ?? ''} onChange={e => set('collateral', e.target.value ? parseFloat(e.target.value) : null)} className="mt-1 block w-full border border-gray-300 rounded px-3 py-2 text-sm" />
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700">Exit Strategy</label>
        <textarea rows={2} value={form.exit_strategy ?? ''} onChange={e => set('exit_strategy', e.target.value || null)} className="mt-1 block w-full border border-gray-300 rounded px-3 py-2 text-sm" placeholder="Close at 50% profit or 21 DTE" />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700">Notes (rationale)</label>
        <textarea rows={2} value={form.rationale_notes ?? ''} onChange={e => set('rationale_notes', e.target.value || null)} className="mt-1 block w-full border border-gray-300 rounded px-3 py-2 text-sm" placeholder="IV rank elevated, earnings in 6 weeks…" />
      </div>

      <div>
        <button
          type="button"
          onClick={() => setTechOpen(o => !o)}
          className="text-sm text-indigo-600 hover:underline"
        >
          {techOpen ? '▲ Hide Technicals' : '▼ Attach Technicals (optional)'}
        </button>
        {techOpen && (
          <div className="mt-2">
            <TechnicalsPanel ticker={form.ticker} onChange={setTechnicals} />
          </div>
        )}
      </div>

      <div className="flex gap-3 pt-2">
        <button type="submit" disabled={loading} className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50">
          {loading ? 'Saving...' : 'Add Trade'}
        </button>
        <button type="button" onClick={onCancel} className="px-4 py-2 border border-gray-300 rounded text-sm hover:bg-gray-50">
          Cancel
        </button>
      </div>
    </form>
  )
}
```

- [ ] **Step 3: Update the parent that calls `TradeForm.onSubmit`**

Find the handler (from Step 1 grep). It will look like:

```tsx
// Before — called with just (payload: TradeCreate):
const handleCreate = async (payload: TradeCreate) => {
  const trade = await tradesApi.create(payload)
  // ...
}
```

Update it to also save technicals:

```tsx
// After:
import { technicalsApi } from '../api/technicals'

const handleCreate = async (payload: TradeCreate, technicals: TechnicalsData | null) => {
  const trade = await tradesApi.create(payload)
  if (technicals) {
    await technicalsApi.saveTradeRationale(trade.id, technicals)
  }
  // ... rest unchanged (close modal, refresh list, etc.)
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Trades/TradeForm.tsx frontend/src/
git commit -m "feat: TradeForm — collapsible TechnicalsPanel, saves snapshot after trade creation"
```

---

## Task 11: Update `CommentaryForm` and `CommentaryThread`

**Files:**
- Modify: `frontend/src/components/Commentary/CommentaryForm.tsx`
- Modify: `frontend/src/components/Commentary/CommentaryThread.tsx`

- [ ] **Step 1: Update `CommentaryForm.tsx`**

Replace entirely:

```tsx
// frontend/src/components/Commentary/CommentaryForm.tsx
import { useState } from 'react'
import type { TechnicalsData } from '../../types'
import { TechnicalsPanel } from '../shared/TechnicalsPanel'

interface Props {
  ticker: string
  onSubmit: (note: string, tags: string[], rationale: TechnicalsData | null) => Promise<void>
}

export function CommentaryForm({ ticker, onSubmit }: Props) {
  const [note, setNote] = useState('')
  const [tagsInput, setTagsInput] = useState('')
  const [technicals, setTechnicals] = useState<TechnicalsData | null>(null)
  const [techOpen, setTechOpen] = useState(false)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!note.trim()) return
    setLoading(true)
    const tags = tagsInput.split(',').map(t => t.trim()).filter(Boolean)
    await onSubmit(note.trim(), tags, technicals)
    setNote('')
    setTagsInput('')
    setTechnicals(null)
    setTechOpen(false)
    setLoading(false)
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-2">
      <textarea required rows={3} value={note} onChange={e => setNote(e.target.value)}
        className="block w-full border border-gray-300 rounded px-3 py-2 text-sm"
        placeholder="What happened or what did you decide?" />
      <input value={tagsInput} onChange={e => setTagsInput(e.target.value)}
        className="block w-full border border-gray-300 rounded px-3 py-2 text-sm"
        placeholder="Tags: rolled, exit-change, earnings (comma-separated)" />

      <div>
        <button type="button" onClick={() => setTechOpen(o => !o)}
          className="text-xs text-indigo-600 hover:underline">
          {techOpen ? '▲ Hide Technicals' : '▼ Attach Technicals (optional)'}
        </button>
        {techOpen && (
          <div className="mt-2">
            <TechnicalsPanel ticker={ticker} onChange={setTechnicals} />
          </div>
        )}
      </div>

      <button type="submit" disabled={loading}
        className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50">
        {loading ? 'Adding...' : 'Add Note'}
      </button>
    </form>
  )
}
```

- [ ] **Step 2: Update `CommentaryThread.tsx`**

`CommentaryThread` must now pass `ticker` to `CommentaryForm` and forward rationale in `commentaryApi.add`. It also renders a rationale chip per entry.

Replace entirely:

```tsx
// frontend/src/components/Commentary/CommentaryThread.tsx
import { useState } from 'react'
import type { Commentary, Rationale, TechnicalsData } from '../../types'
import { commentaryApi } from '../../api/commentary'
import { CommentaryForm } from './CommentaryForm'

interface Props {
  tradeId: string
  ticker: string
  entries: Commentary[]
  onRefresh: () => void
}

const RATIONALE_LABELS: Record<string, string> = {
  rsi_14: 'RSI', macd_signal: 'MACD', sentiment: 'Sentiment',
  bollinger_position: 'BB Pos', price_vs_ma50: 'vs MA50', price_vs_ma200: 'vs MA200',
  ma_50d: 'MA50', ma_200d: 'MA200', day_color: 'Day', price_action: 'Price',
  next_earnings_date: 'Earnings', notes: 'Notes',
}

function RationaleChip({ rationale }: { rationale: Rationale }) {
  const [expanded, setExpanded] = useState(false)
  const fields = Object.entries(RATIONALE_LABELS)
    .map(([k, label]) => ({ key: k, label, value: (rationale as Record<string, unknown>)[k] }))
    .filter(({ value }) => value != null && value !== '')

  return (
    <div className="mt-1">
      <button type="button" onClick={() => setExpanded(o => !o)}
        className="text-xs px-2 py-0.5 bg-indigo-50 text-indigo-600 rounded hover:bg-indigo-100">
        📊 Technicals {expanded ? '▲' : '▼'}
      </button>
      {expanded && (
        <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs bg-white border border-gray-100 rounded p-2">
          {fields.map(({ key, label, value }) => (
            <div key={key}>
              <span className="text-gray-400">{label}: </span>
              <span className="text-gray-700 font-medium">{String(value)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function CommentaryThread({ tradeId, ticker, entries, onRefresh }: Props) {
  const handleAdd = async (note: string, tags: string[], rationale: TechnicalsData | null) => {
    await commentaryApi.add(tradeId, {
      note,
      tags: tags.length > 0 ? tags : undefined,
      rationale: rationale ?? undefined,
    })
    onRefresh()
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this note?')) return
    await commentaryApi.delete(id)
    onRefresh()
  }

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-gray-700">Journal</h3>
      <CommentaryForm ticker={ticker} onSubmit={handleAdd} />
      <div className="space-y-3 mt-4">
        {entries.length === 0 && <p className="text-gray-400 text-sm">No notes yet.</p>}
        {entries.map(entry => (
          <div key={entry.id} className="bg-gray-50 rounded p-3 text-sm">
            <div className="flex justify-between items-start">
              <span className="text-gray-400 text-xs">{entry.entry_date}</span>
              <button onClick={() => handleDelete(entry.id)} className="text-red-400 hover:text-red-600 text-xs">×</button>
            </div>
            <p className="mt-1 text-gray-800">{entry.note}</p>
            {entry.tags && entry.tags.length > 0 && (
              <div className="flex gap-1 mt-1">
                {entry.tags.map(tag => (
                  <span key={tag} className="px-1.5 py-0.5 bg-blue-100 text-blue-600 rounded text-xs">{tag}</span>
                ))}
              </div>
            )}
            {entry.rationale && <RationaleChip rationale={entry.rationale} />}
          </div>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Find callers of `CommentaryThread` and add `ticker` prop**

```bash
grep -rn "CommentaryThread" frontend/src/
```

In each file found, pass the trade's ticker:

```tsx
// Before:
<CommentaryThread tradeId={trade.id} entries={comments} onRefresh={reload} />

// After:
<CommentaryThread tradeId={trade.id} ticker={trade.ticker} entries={comments} onRefresh={reload} />
```

- [ ] **Step 4: TypeScript compile check**

```bash
cd frontend && npm run build 2>&1 | grep -E "error TS|warning" | head -20
```

Fix any type errors before committing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Commentary/
git commit -m "feat: CommentaryForm/Thread — attach technicals to notes; rationale chip with expand"
```

---

## Task 12: Extension — `renderTechnicalsForm` helper + CSS

**Files:**
- Modify: `extension/content.js`
- Modify: `extension/content.css`

- [ ] **Step 1: Add CSS for the technicals panel**

In `extension/content.css`, append:

```css
/* Technicals panel */
.tm-tech-section { margin-top: 8px; }
.tm-tech-toggle { font-size: 11px; color: #4f46e5; background: none; border: none; cursor: pointer; padding: 0; }
.tm-tech-toggle:hover { text-decoration: underline; }
.tm-tech-panel { margin-top: 6px; border: 1px solid #e5e7eb; border-radius: 6px; padding: 8px; background: #f9fafb; }
.tm-tech-fetch-btn { font-size: 11px; padding: 3px 8px; background: #4f46e5; color: #fff; border: none; border-radius: 4px; cursor: pointer; }
.tm-tech-fetch-btn:disabled { opacity: 0.5; cursor: default; }
.tm-tech-clear-btn { font-size: 11px; color: #9ca3af; background: none; border: none; cursor: pointer; margin-left: 6px; }
.tm-tech-status { font-size: 11px; color: #ef4444; margin-top: 4px; }
.tm-tech-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 12px; margin-top: 8px; }
.tm-tech-field { display: flex; flex-direction: column; }
.tm-tech-field.full-width { grid-column: span 2; }
.tm-tech-field label { font-size: 10px; color: #6b7280; margin-bottom: 1px; }
.tm-tech-field input,
.tm-tech-field select,
.tm-tech-field textarea { font-size: 11px; padding: 2px 4px; border: 1px solid #d1d5db; border-radius: 3px; background: #fff; }
.tm-tech-field textarea { resize: vertical; }
/* Rationale chip in comment thread */
.tm-rationale-chip { font-size: 10px; color: #4f46e5; background: #eef2ff; border: none; border-radius: 3px; padding: 1px 5px; cursor: pointer; margin-top: 4px; }
.tm-rationale-detail { font-size: 10px; margin-top: 4px; background: #fff; border: 1px solid #e5e7eb; border-radius: 4px; padding: 6px; display: grid; grid-template-columns: 1fr 1fr; gap: 2px 8px; }
.tm-rationale-row span:first-child { color: #9ca3af; }
```

- [ ] **Step 2: Add `renderTechnicalsForm` helper to `content.js`**

Near the top of `content.js`, after the existing constant/cache declarations, add:

```javascript
// ── Technicals helpers ──────────────────────────────────────────────────────

const TECH_SELECT_FIELDS = {
  macd_signal: ['bullish', 'bearish', 'neutral'],
  rsi_result: ['rsi_oversold', 'rsi_overbought'],
  price_vs_ma200: ['above', 'below'],
  price_vs_ma50: ['above', 'below'],
  bollinger_position: ['above_upper', 'near_upper', 'mid', 'near_lower', 'below_lower'],
  day_color: ['green', 'red'],
  sentiment: ['bullish', 'bearish', 'neutral'],
};

const TECH_FIELD_ORDER = [
  ['price_action', 'Price'], ['day_color', 'Day Color'],
  ['rsi_14', 'RSI-14'], ['rsi_result', 'RSI Result'],
  ['macd_signal', 'MACD Signal'], ['macd_notes', 'MACD Notes'],
  ['ma_200d', 'MA 200D'], ['ma_50d', 'MA 50D'],
  ['price_vs_ma200', 'vs MA200'], ['price_vs_ma50', 'vs MA50'],
  ['bollinger_upper', 'BB Upper'], ['bollinger_mid', 'BB Mid'],
  ['bollinger_lower', 'BB Lower'], ['bollinger_position', 'BB Pos'],
  ['sentiment', 'Sentiment'], ['next_earnings_date', 'Earnings'],
  ['notes', 'Notes'],
];

/**
 * Injects a self-contained technicals fetch+edit panel into `container`.
 * Returns { getValue() } — call getValue() to get the current snapshot object or null.
 */
function renderTechnicalsForm(container, ticker) {
  container.innerHTML = `
    <div class="tm-tech-panel">
      <button type="button" class="tm-tech-fetch-btn">📊 Fetch Technicals</button>
      <button type="button" class="tm-tech-clear-btn tm-hidden">Clear</button>
      <div class="tm-tech-status"></div>
      <div class="tm-tech-fields tm-hidden">
        <div class="tm-tech-grid"></div>
      </div>
    </div>
  `;

  let techData = null;
  const fetchBtn = container.querySelector('.tm-tech-fetch-btn');
  const clearBtn = container.querySelector('.tm-tech-clear-btn');
  const statusEl = container.querySelector('.tm-tech-status');
  const fieldsEl = container.querySelector('.tm-tech-fields');
  const gridEl = container.querySelector('.tm-tech-grid');

  function renderFields(data) {
    gridEl.innerHTML = '';
    TECH_FIELD_ORDER.forEach(([key, label]) => {
      const isNotes = key === 'notes';
      const div = document.createElement('div');
      div.className = `tm-tech-field${isNotes ? ' full-width' : ''}`;
      const lbl = document.createElement('label');
      lbl.textContent = label;
      div.appendChild(lbl);

      if (key in TECH_SELECT_FIELDS) {
        const sel = document.createElement('select');
        sel.dataset.techField = key;
        const emptyOpt = document.createElement('option');
        emptyOpt.value = ''; emptyOpt.textContent = '—';
        sel.appendChild(emptyOpt);
        TECH_SELECT_FIELDS[key].forEach(opt => {
          const o = document.createElement('option');
          o.value = opt; o.textContent = opt;
          if (data[key] === opt) o.selected = true;
          sel.appendChild(o);
        });
        div.appendChild(sel);
      } else if (isNotes) {
        const ta = document.createElement('textarea');
        ta.dataset.techField = key;
        ta.rows = 2;
        ta.value = data[key] ?? '';
        div.appendChild(ta);
      } else {
        const inp = document.createElement('input');
        inp.dataset.techField = key;
        inp.value = data[key] != null ? String(data[key]) : '';
        div.appendChild(inp);
      }
      gridEl.appendChild(div);
    });
  }

  fetchBtn.addEventListener('click', async () => {
    fetchBtn.disabled = true;
    statusEl.textContent = 'Fetching…';
    try {
      const resp = await fetch(`${tmApiUrl}/api/market/technicals/${ticker.toUpperCase()}`, {
        signal: AbortSignal.timeout(20000),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      if (data.fetch_status === 'error') throw new Error(data.fetch_error ?? 'Fetch failed');
      techData = data;
      renderFields(data);
      fieldsEl.classList.remove('tm-hidden');
      clearBtn.classList.remove('tm-hidden');
      statusEl.textContent = '';
    } catch (e) {
      statusEl.textContent = `Error: ${e.message}`;
    } finally {
      fetchBtn.disabled = false;
    }
  });

  clearBtn.addEventListener('click', () => {
    techData = null;
    fieldsEl.classList.add('tm-hidden');
    clearBtn.classList.add('tm-hidden');
    statusEl.textContent = '';
    gridEl.innerHTML = '';
  });

  return {
    getValue() {
      if (!techData) return null;
      const snapshot = { ...techData };
      container.querySelectorAll('[data-tech-field]').forEach(el => {
        snapshot[el.dataset.techField] = el.value || null;
      });
      return snapshot;
    },
  };
}
```

- [ ] **Step 3: Commit**

```bash
git add extension/content.js extension/content.css
git commit -m "feat: extension — renderTechnicalsForm helper + CSS for technicals panel"
```

---

## Task 13: Extension — add-trade modal integration

**Files:**
- Modify: `extension/content.js`

- [ ] **Step 1: Find the add-trade modal HTML and submit handler**

```bash
grep -n "tm-modal-form\|rationale_notes\|tm-modal-submit\|Add Trade" extension/content.js | head -20
```

The modal HTML is built inside a function (around line 834). The submit handler is around line 928.

- [ ] **Step 2: Add technicals section to the modal HTML**

In the modal HTML string (the section that builds the `<form id="tm-modal-form">`), add a technicals section directly after the `rationale_notes` textarea group. Find:

```javascript
          <textarea name="rationale_notes" rows="2" placeholder="Why are you entering this trade?"></textarea>
```

Add after it:

```javascript
          <div class="tm-tech-section">
            <button type="button" class="tm-tech-toggle" id="tm-modal-tech-toggle">▼ Attach Technicals (optional)</button>
            <div id="tm-modal-tech-container" class="tm-hidden"></div>
          </div>
```

- [ ] **Step 3: Wire the toggle and `renderTechnicalsForm` after modal insertion**

After `document.body.appendChild(overlay)` (or wherever the modal is inserted into the DOM), add:

```javascript
  // Wire technicals toggle
  let techFormControl = null;
  const techToggle = overlay.querySelector('#tm-modal-tech-toggle');
  const techContainer = overlay.querySelector('#tm-modal-tech-container');
  techToggle.addEventListener('click', () => {
    const isOpen = !techContainer.classList.contains('tm-hidden');
    if (isOpen) {
      techContainer.classList.add('tm-hidden');
      techToggle.textContent = '▼ Attach Technicals (optional)';
    } else {
      if (!techFormControl) {
        techFormControl = renderTechnicalsForm(techContainer, ticker);
      }
      techContainer.classList.remove('tm-hidden');
      techToggle.textContent = '▲ Hide Technicals';
    }
  });
```

- [ ] **Step 4: Update the modal submit handler to POST technicals after trade creation**

In the form submit handler (around the `fetch('/api/trades', ...)` call), after a successful trade creation, add:

```javascript
    // After: const trade = await resp.json();
    const techSnapshot = techFormControl ? techFormControl.getValue() : null;
    if (techSnapshot) {
      try {
        await fetch(`${tmApiUrl}/api/trades/${trade.id}/rationale`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(techSnapshot),
          signal: AbortSignal.timeout(10000),
        });
      } catch (e) {
        console.debug('[TM] technicals save failed:', e.message);
        // Non-fatal — trade was already created
      }
    }
```

- [ ] **Step 5: Reload the extension and test**

Open the E*TRADE positions page, right-click a position → "Add to TradeMinder". Verify:
- "Attach Technicals" toggle appears
- Clicking it opens the panel
- Clicking "Fetch Technicals" calls the API and populates fields
- Submitting saves the trade and the technicals (check DB via `GET /api/trades/{id}`)

- [ ] **Step 6: Commit**

```bash
git add extension/content.js
git commit -m "feat: extension add-trade modal — technicals section with fetch + save"
```

---

## Task 14: Extension — commentary panel technicals + thread display

**Files:**
- Modify: `extension/content.js`

- [ ] **Step 1: Find the commentary add-note area**

```bash
grep -n "Add Note\|add.*note\|comment.*form\|tm-cp\|commentary.*submit" extension/content.js | head -20
```

Note the function that renders the commentary panel and the submit handler for adding a note.

- [ ] **Step 2: Add technicals toggle to the add-note section**

In the HTML that renders the "Add Note" area inside the commentary hover panel, add after the note textarea:

```javascript
    <div class="tm-tech-section">
      <button type="button" class="tm-tech-toggle" data-note-tech-toggle>▼ Attach Technicals</button>
      <div data-note-tech-container class="tm-hidden"></div>
    </div>
```

After that DOM section is inserted, wire it up (similar to Task 13 Step 3):

```javascript
  let noteTechControl = null;
  const noteTechToggle = panelEl.querySelector('[data-note-tech-toggle]');
  const noteTechContainer = panelEl.querySelector('[data-note-tech-container]');
  if (noteTechToggle) {
    noteTechToggle.addEventListener('click', () => {
      const isOpen = !noteTechContainer.classList.contains('tm-hidden');
      if (isOpen) {
        noteTechContainer.classList.add('tm-hidden');
        noteTechToggle.textContent = '▼ Attach Technicals';
      } else {
        if (!noteTechControl) {
          noteTechControl = renderTechnicalsForm(noteTechContainer, ticker);
        }
        noteTechContainer.classList.remove('tm-hidden');
        noteTechToggle.textContent = '▲ Hide Technicals';
      }
    });
  }
```

- [ ] **Step 3: Update the note submit handler to embed technicals**

In the commentary POST handler (where `fetch('/api/trades/{id}/commentary', ...)` is called), add the technicals payload:

```javascript
  const techSnapshot = noteTechControl ? noteTechControl.getValue() : null;
  const body = { note: noteText, tags: parsedTags };
  if (techSnapshot) body.rationale = techSnapshot;

  const resp = await fetch(`${tmApiUrl}/api/trades/${tradeId}/commentary`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(10000),
  });
```

- [ ] **Step 4: Update commentary thread rendering to show rationale chip**

In the function that renders each comment entry in the hover panel (find with `grep -n "entry_date\|comment.*note\|tm-cp-note" extension/content.js`), after rendering the note text, add:

```javascript
    // After note text is appended:
    if (comment.rationale) {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'tm-rationale-chip';
      chip.textContent = '📊 Technicals';
      let detailEl = null;
      chip.addEventListener('click', () => {
        if (detailEl) {
          detailEl.remove();
          detailEl = null;
          return;
        }
        detailEl = document.createElement('div');
        detailEl.className = 'tm-rationale-detail';
        const r = comment.rationale;
        const SHOW = [
          ['RSI', r.rsi_14], ['MACD', r.macd_signal], ['Sentiment', r.sentiment],
          ['BB Pos', r.bollinger_position], ['vs MA50', r.price_vs_ma50],
          ['Price', r.price_action], ['Earnings', r.next_earnings_date],
          ['Day', r.day_color], ['Notes', r.notes],
        ].filter(([, v]) => v != null && v !== '');
        SHOW.forEach(([label, value]) => {
          const row = document.createElement('div');
          row.className = 'tm-rationale-row';
          row.innerHTML = `<span>${escapeHtml(label)}: </span><span>${escapeHtml(String(value))}</span>`;
          detailEl.appendChild(row);
        });
        chip.insertAdjacentElement('afterend', detailEl);
      });
      entryEl.appendChild(chip);
    }
```

- [ ] **Step 5: Test end-to-end in the extension**

Open the hover panel for a trade, add a note with technicals attached. Verify the `📊 Technicals` chip appears on the saved note. Click it — verify the detail block toggles. Reload the panel — verify data persists (it comes from the API response).

- [ ] **Step 6: Commit**

```bash
git add extension/content.js
git commit -m "feat: extension commentary panel — attach technicals to notes; rationale chip in thread"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| 19 technical fields in `rationale` | All fields already existed; Tasks 2–3 extend schema |
| Fetch from yfinance on demand | Task 4 (service), Task 5 (endpoint) |
| Display + edit before save | Tasks 9, 10, 12 (TechnicalsPanel + extension form) |
| Save with trade (frontend) | Task 10 |
| Save with trade (extension) | Task 13 |
| Commentary linked to rationale | Tasks 2, 3, 7 |
| Save with commentary (frontend) | Task 11 |
| Save with commentary (extension) | Task 14 |
| Commentary thread shows rationale chip (collapsed) | Tasks 11, 14 |
| `sentiment` inferred from indicators | Task 4 (`_infer_sentiment`) |
| `fetch_status` / `fetch_error` fields | Task 4 |

**Placeholder scan:** None found.

**Type consistency:** `TechnicalsData` (frontend type) matches `RationaleCreate` (backend schema) field-for-field. `CommentaryResponse.rationale` matches `RationaleResponse`. `renderTechnicalsForm.getValue()` returns the same field names as `TechnicalsData`. Extension `body.rationale` keys match backend `RationaleCreate` fields.
