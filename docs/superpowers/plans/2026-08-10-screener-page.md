# Screener Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `/screener` page — a persisted watchlist of tickers with a compact technical snapshot grid, expandable detail rows, on-demand/bulk fetch, a symbol-lookup-before-add flow, and a per-symbol editable commentary thread.

**Architecture:** New `screener` + `screener_commentary` Postgres tables (via Alembic migration). A `screener_fetcher.py` service composes the existing `fetch_technicals` (extended with MA20/MA100) with a live quote and an IV-percentile calc relocated out of `cc_signal.py` into `technicals_fetcher.py` for reuse. A new `screener.py` FastAPI router exposes list/preview/add/fetch/fetch-all(background job)/delete/patch/commentary-CRUD. The frontend adds a `ScreenerPage` with an expandable-row table (existing `WheelSlotCard` chevron pattern), an add form, a preview-before-add lookup panel, and a Radix-Dialog commentary thread (existing `CommentaryCell` pattern, extended with inline edit).

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, PostgreSQL (JSONB), pytest + pytest-asyncio + httpx `AsyncClient`, React 19, TypeScript, Tailwind, Radix UI Dialog.

## Global Constraints

- Backend routes live under `backend/app/routers/`, models under `backend/app/models/`, schemas under `backend/app/schemas/`, services under `backend/app/services/` — follow existing per-file-per-concern layout.
- Frontend: TypeScript strict mode, functional components with hooks, Tailwind utility classes only, no new CSS files, API calls go through typed wrappers in `frontend/src/api/`.
- All monetary/technical numeric fields use `Decimal` in Python. **Correction discovered during Task 7 implementation/review:** this repo's Pydantic schemas serialize `Decimal` to a JSON **string** (e.g. `"195.50"`), not a number — confirmed empirically (`Decimal('195.50')` → `{"x":"195.50"}` via `model_dump_json()`) and consistent with this repo's existing `test_wheel_crud.py` convention. The pre-existing `Rationale`/`TechnicalsData` TS interfaces are typed `number | null` for these fields, but nothing in the existing frontend does arithmetic on them (only `String(value)` display in `CommentaryThread.tsx`), so that inaccuracy is latent and harmless there. The Screener frontend DOES need arithmetic (MA color comparison, `.toFixed()` formatting) on these fields, so Tasks 10/11/14 below are written with `string | null` for every Decimal-backed field and explicit `parseFloat`/`Number()` conversion at the point of use — do not copy the `number | null` pattern from `Rationale`/`TechnicalsData`. Fields inside `volume_spikes` (a raw JSON list of plain Python `int`/`float`, not `Decimal`) remain JSON numbers as before.
- New DB objects: table `screener`, table `screener_commentary`, both created via a single new Alembic migration (`010`), matching the numbered-revision convention in `backend/alembic/versions/`.
- No new background-job infrastructure (no Celery/RQ) — sequential `asyncio.create_task` + in-memory dict, same weight class as the existing in-memory `_summary_cache` in `commentary.py`.
- Spec reference: `docs/superpowers/specs/2026-08-10-screener-page-design.md`.

---

## Task 1: Extend `fetch_technicals` with MA20/MA100

**Files:**
- Modify: `backend/app/services/technicals_fetcher.py:260-264` (the MA computation block inside `fetch_technicals`)
- Test: `backend/tests/test_technicals_fetcher.py` (new file)

**Interfaces:**
- Produces: `fetch_technicals(ticker)` result dict gains two new keys: `ma_20d: float | None`, `ma_100d: float | None`, `price_vs_ma20: str | None`, `price_vs_ma100: str | None` — same shape/rounding/null-handling as the existing `ma_50d`/`price_vs_ma50` pair.

- [ ] **Step 1: Write the failing unit test**

Create `backend/tests/test_technicals_fetcher.py`:

```python
import pandas as pd
from unittest.mock import MagicMock, patch

from app.services.technicals_fetcher import fetch_technicals


def _make_daily_df(n: int, start_price: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    closes = [start_price + i * 0.1 for i in range(n)]
    return pd.DataFrame({
        "Open": closes, "High": closes, "Low": closes, "Close": closes,
        "Volume": [1_000_000] * n,
    }, index=idx)


def test_fetch_technicals_includes_ma20_and_ma100():
    daily_df = _make_daily_df(250)
    weekly_df = _make_daily_df(120)

    mock_client = MagicMock()
    mock_client.get_price_history.side_effect = [daily_df, weekly_df]

    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        result = fetch_technicals("AAPL")

    assert result["fetch_status"] == "ok"
    assert result["ma_20d"] is not None
    assert result["ma_100d"] is not None
    assert result["price_vs_ma20"] in ("above", "below")
    assert result["price_vs_ma100"] in ("above", "below")


def test_fetch_technicals_ma20_ma100_null_on_short_history():
    daily_df = _make_daily_df(15)
    weekly_df = _make_daily_df(15)

    mock_client = MagicMock()
    mock_client.get_price_history.side_effect = [daily_df, weekly_df]

    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        result = fetch_technicals("AAPL")

    assert result["ma_20d"] is None
    assert result["ma_100d"] is None
    assert result["price_vs_ma20"] is None
    assert result["price_vs_ma100"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_technicals_fetcher.py -v`
Expected: FAIL — `KeyError: 'ma_20d'`

- [ ] **Step 3: Implement MA20/MA100**

In `backend/app/services/technicals_fetcher.py`, replace the block:

```python
        ma_200d = round(float(close_d.rolling(200).mean().iloc[-1]), 2) if len(close_d) >= 200 else None
        ma_50d = round(float(close_d.rolling(50).mean().iloc[-1]), 2) if len(close_d) >= 50 else None

        price_vs_ma200 = ("above" if price > ma_200d else "below") if ma_200d is not None else None
        price_vs_ma50 = ("above" if price > ma_50d else "below") if ma_50d is not None else None
```

with:

```python
        ma_200d = round(float(close_d.rolling(200).mean().iloc[-1]), 2) if len(close_d) >= 200 else None
        ma_100d = round(float(close_d.rolling(100).mean().iloc[-1]), 2) if len(close_d) >= 100 else None
        ma_50d = round(float(close_d.rolling(50).mean().iloc[-1]), 2) if len(close_d) >= 50 else None
        ma_20d = round(float(close_d.rolling(20).mean().iloc[-1]), 2) if len(close_d) >= 20 else None

        price_vs_ma200 = ("above" if price > ma_200d else "below") if ma_200d is not None else None
        price_vs_ma100 = ("above" if price > ma_100d else "below") if ma_100d is not None else None
        price_vs_ma50 = ("above" if price > ma_50d else "below") if ma_50d is not None else None
        price_vs_ma20 = ("above" if price > ma_20d else "below") if ma_20d is not None else None
```

Then in the `result = {...}` dict a few lines below, replace:

```python
            "ma_200d": ma_200d,
            "ma_50d": ma_50d,
            "price_vs_ma200": price_vs_ma200,
            "price_vs_ma50": price_vs_ma50,
```

with:

```python
            "ma_200d": ma_200d,
            "ma_100d": ma_100d,
            "ma_50d": ma_50d,
            "ma_20d": ma_20d,
            "price_vs_ma200": price_vs_ma200,
            "price_vs_ma100": price_vs_ma100,
            "price_vs_ma50": price_vs_ma50,
            "price_vs_ma20": price_vs_ma20,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_technicals_fetcher.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full existing technicals test suite to check for regressions**

Run: `cd backend && uv run pytest tests/test_market_technicals.py -v`
Expected: PASS — existing tests patch `fetch_technicals` itself (mocked return value), so this change is invisible to them; confirms no import/syntax break.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/technicals_fetcher.py backend/tests/test_technicals_fetcher.py
git commit -m "feat(technicals): add ma_20d and ma_100d to fetch_technicals"
```

---

## Task 2: Relocate IV percentile calc into `technicals_fetcher.py`

**Files:**
- Modify: `backend/app/services/cc_signal.py` (remove `_compute_iv_percentile_from_chain`, import the relocated version instead)
- Modify: `backend/app/services/technicals_fetcher.py` (add the relocated function)
- Test: `backend/tests/test_technicals_fetcher.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `technicals_fetcher.compute_iv_percentile_from_chain(daily_closes: pd.Series, chain: dict, ticker: str = "?", contract_type: str = "CALL") -> tuple[float | None, float | None]` — public (no leading underscore), used by both `cc_signal.py` and (in Task 6) `screener_fetcher.py`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_technicals_fetcher.py`:

```python
import numpy as np
from datetime import date, timedelta

from app.services.technicals_fetcher import compute_iv_percentile_from_chain


def _make_chain(dte_days: int, strike: float, iv_pct: float) -> dict:
    exp_date = date.today() + timedelta(days=dte_days)
    exp_key = f"{exp_date.isoformat()}:{dte_days}"
    return {
        "underlyingPrice": strike,
        "callExpDateMap": {
            exp_key: {
                str(strike): [{"volatility": iv_pct}],
            }
        },
    }


def test_compute_iv_percentile_from_chain_returns_none_on_short_history():
    closes = pd.Series(np.linspace(100, 110, 10))
    chain = _make_chain(37, 105.0, 30.0)
    pct, atm_iv = compute_iv_percentile_from_chain(closes, chain, "AAPL")
    assert pct is None
    assert atm_iv is None


def test_compute_iv_percentile_from_chain_success():
    rng = np.random.default_rng(42)
    closes = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 120))))
    chain = _make_chain(37, float(closes.iloc[-1]), 25.0)
    pct, atm_iv = compute_iv_percentile_from_chain(closes, chain, "AAPL")
    assert pct is not None
    assert 0 <= pct <= 100
    assert atm_iv == 0.25
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_technicals_fetcher.py -v -k iv_percentile`
Expected: FAIL — `ImportError: cannot import name 'compute_iv_percentile_from_chain'`

- [ ] **Step 3: Move the function**

In `backend/app/services/cc_signal.py`, delete the entire `_compute_iv_percentile_from_chain` function body (currently lines 283-329, from `def _compute_iv_percentile_from_chain(` through its closing `return round(pct, 1), atm_iv` / `except` block). Replace every call site `_compute_iv_percentile_from_chain(...)` (there are two, in `_compute_combined_fresh`) with `compute_iv_percentile_from_chain(...)`.

Add to the top imports of `cc_signal.py`:

```python
from app.services.technicals_fetcher import compute_iv_percentile_from_chain
```

(This is added alongside the existing `from app.services.price_fetcher import _compute_rsi_14` and `from app.services.schwab_client import get_schwab_client` import lines.)

In `backend/app/services/technicals_fetcher.py`, add near the top (after existing imports, add `import math`, `import numpy as np`, `from datetime import date, datetime` — `pandas` is already imported):

```python
import math
from datetime import date, datetime

import numpy as np
```

Then add the function (unchanged body, renamed, logger added):

```python
import logging

log = logging.getLogger(__name__)


def compute_iv_percentile_from_chain(
    daily_closes: pd.Series, chain: dict, ticker: str = "?", contract_type: str = "CALL"
) -> tuple[float | None, float | None]:
    try:
        log_returns = np.log(daily_closes / daily_closes.shift(1)).dropna()
        if len(log_returns) < 60:
            return None, None
        hv30 = log_returns.rolling(window=30).std() * math.sqrt(252)
        hv30 = hv30.dropna()
        if len(hv30) < 30:
            return None, None

        exp_map_key = "putExpDateMap" if contract_type == "PUT" else "callExpDateMap"
        call_exp_map = chain.get(exp_map_key, {})
        if not call_exp_map:
            return None, None

        spot = float(chain.get("underlyingPrice", 0))

        today = date.today()
        best_exp_key = None
        best_dist = float("inf")
        for exp_key in call_exp_map:
            exp_str = exp_key.split(":")[0]
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - today).days
            if dte < 14:
                continue
            dist = abs(dte - 37)
            if dist < best_dist:
                best_dist = dist
                best_exp_key = exp_key

        if best_exp_key is None:
            return None, None

        strikes = call_exp_map[best_exp_key]
        best_strike_key = min(strikes.keys(), key=lambda s: abs(float(s) - spot))
        atm_option = strikes[best_strike_key][0]
        raw_iv = float(atm_option.get("volatility", 0))
        if raw_iv <= 1.0:
            return None, None
        atm_iv = raw_iv / 100.0

        pct = float((hv30 < atm_iv).sum()) / len(hv30) * 100
        return round(pct, 1), atm_iv

    except Exception as exc:
        log.warning("IV percentile failed for %s: %s", ticker, exc)
        return None, None
```

Place these new imports/function above the existing `_compute_macd_weekly` function definition (i.e., near the top of the file, after the current `from app.services.price_fetcher import _compute_rsi_14` / `from app.services.schwab_client import ...` import lines).

- [ ] **Step 4: Run the new test to verify it passes**

Run: `cd backend && uv run pytest tests/test_technicals_fetcher.py -v -k iv_percentile`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the existing cc_signal test suite to confirm the relocation didn't break behavior**

Run: `cd backend && uv run pytest tests/ -k cc_signal -v`
Expected: PASS — same output, just re-exported from a different module. If there's no dedicated `test_cc_signal.py`, run the broader combined-signal tests: `uv run pytest tests/ -k "combined_signal or cc_signal or sp_signal" -v` and confirm PASS.

- [ ] **Step 6: Run full backend test suite for regressions**

Run: `cd backend && uv run pytest tests/ -v`
Expected: PASS — no import errors anywhere else referencing the old private name (verify with `grep -rn "_compute_iv_percentile_from_chain" backend/app` returning no results before committing).

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/cc_signal.py backend/app/services/technicals_fetcher.py backend/tests/test_technicals_fetcher.py
git commit -m "refactor(technicals): relocate IV percentile calc from cc_signal to technicals_fetcher for reuse"
```

---

## Task 3: `screener` and `screener_commentary` models + migration

**Files:**
- Create: `backend/app/models/screener.py`
- Create: `backend/app/models/screener_commentary.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/010_screener.py`
- Test: `backend/tests/test_screener_models.py` (new file)

**Interfaces:**
- Produces: SQLAlchemy models `Screener` (table `screener`) and `ScreenerCommentary` (table `screener_commentary`), importable as `from app.models.screener import Screener` / `from app.models.screener_commentary import ScreenerCommentary`. `Screener.commentary` is a `list[ScreenerCommentary]` relationship (cascade delete-orphan, ordered newest-first). `ScreenerCommentary.screener_id` FK → `screener.id` ON DELETE CASCADE.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_screener_models.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_screener_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.screener'`

- [ ] **Step 3: Create the `Screener` model**

Create `backend/app/models/screener.py`:

```python
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Numeric, Date, Text, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.database import Base

if TYPE_CHECKING:
    from app.models.screener_commentary import ScreenerCommentary


class Screener(Base):
    __tablename__ = "screener"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    sector: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    prev_close: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    change_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    iv_rank: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    iv_percentile: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    rsi_14: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    macd_weekly_signal: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    macd_daily_signal: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    ma_20d: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    ma_50d: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    ma_100d: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    ma_200d: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    bollinger_upper: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    bollinger_mid: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    bollinger_lower: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    bollinger_position: Mapped[Optional[str]] = mapped_column(String(15), nullable=True)
    next_earnings_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    volume_spikes: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    last_fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    fetch_status: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    fetch_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    commentary: Mapped[list["ScreenerCommentary"]] = relationship(
        back_populates="screener",
        cascade="all, delete-orphan",
        order_by="ScreenerCommentary.created_at.desc()",
    )

    __table_args__ = (
        Index("idx_screener_symbol", "symbol", unique=True),
    )
```

- [ ] **Step 4: Create the `ScreenerCommentary` model**

Create `backend/app/models/screener_commentary.py`:

```python
import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import Text, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.sql import func
from app.database import Base

if TYPE_CHECKING:
    from app.models.screener import Screener


class ScreenerCommentary(Base):
    __tablename__ = "screener_commentary"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    screener_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("screener.id", ondelete="CASCADE"), nullable=False
    )
    note: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    screener: Mapped["Screener"] = relationship(back_populates="commentary")

    __table_args__ = (
        Index("idx_screener_commentary_screener", "screener_id"),
    )
```

- [ ] **Step 5: Register both models in `backend/app/models/__init__.py`**

Replace the file contents with:

```python
from app.models.trade import Trade
from app.models.rationale import Rationale
from app.models.commentary import Commentary
from app.models.alert import Alert
from app.models.briefing import DailyBriefing
from app.models.category import Category
from app.models.signal import TechnicalSignal
from app.models.trade_session import TradeSession
from app.models.wheel_session import WheelSession
from app.models.wheel_slot import WheelSlot
from app.models.wheel_slot_leg import WheelSlotLeg
from app.models.wheel_premium_log import WheelPremiumLog
from app.models.schwab_token import SchwabToken
from app.models.screener import Screener
from app.models.screener_commentary import ScreenerCommentary

__all__ = [
    "Trade", "Rationale", "Commentary", "Alert", "DailyBriefing",
    "Category", "TechnicalSignal", "TradeSession",
    "WheelSession", "WheelSlot", "WheelSlotLeg", "WheelPremiumLog", "SchwabToken",
    "Screener", "ScreenerCommentary",
]
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_screener_models.py -v`
Expected: PASS (2 tests) — `conftest.py`'s `create_test_tables` fixture imports `app.models` (which now includes the new models) and calls `Base.metadata.create_all`, so the test DB gets the new tables automatically without needing the Alembic migration to run first.

- [ ] **Step 7: Create the Alembic migration**

Create `backend/alembic/versions/010_screener.py`:

```python
"""add screener and screener_commentary tables

Revision ID: 010
Revises: 009
Create Date: 2026-08-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'screener',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('symbol', sa.String(10), nullable=False),
        sa.Column('sector', sa.String(50), nullable=True),
        sa.Column('category', sa.String(50), nullable=True),
        sa.Column('price', sa.Numeric(10, 2), nullable=True),
        sa.Column('prev_close', sa.Numeric(10, 2), nullable=True),
        sa.Column('change_pct', sa.Numeric(6, 2), nullable=True),
        sa.Column('iv_rank', sa.Numeric(5, 2), nullable=True),
        sa.Column('iv_percentile', sa.Numeric(5, 2), nullable=True),
        sa.Column('rsi_14', sa.Numeric(5, 2), nullable=True),
        sa.Column('macd_weekly_signal', sa.String(10), nullable=True),
        sa.Column('macd_daily_signal', sa.String(10), nullable=True),
        sa.Column('ma_20d', sa.Numeric(10, 2), nullable=True),
        sa.Column('ma_50d', sa.Numeric(10, 2), nullable=True),
        sa.Column('ma_100d', sa.Numeric(10, 2), nullable=True),
        sa.Column('ma_200d', sa.Numeric(10, 2), nullable=True),
        sa.Column('bollinger_upper', sa.Numeric(10, 2), nullable=True),
        sa.Column('bollinger_mid', sa.Numeric(10, 2), nullable=True),
        sa.Column('bollinger_lower', sa.Numeric(10, 2), nullable=True),
        sa.Column('bollinger_position', sa.String(15), nullable=True),
        sa.Column('next_earnings_date', sa.Date(), nullable=True),
        sa.Column('volume_spikes', postgresql.JSONB, nullable=True),
        sa.Column('last_fetched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('fetch_status', sa.String(10), nullable=True),
        sa.Column('fetch_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('idx_screener_symbol', 'screener', ['symbol'], unique=True)

    op.create_table(
        'screener_commentary',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'screener_id', postgresql.UUID(as_uuid=True),
            sa.ForeignKey('screener.id', ondelete='CASCADE'), nullable=False,
        ),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('tags', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('idx_screener_commentary_screener', 'screener_commentary', ['screener_id'])


def downgrade() -> None:
    op.drop_index('idx_screener_commentary_screener', table_name='screener_commentary')
    op.drop_table('screener_commentary')
    op.drop_index('idx_screener_symbol', table_name='screener')
    op.drop_table('screener')
```

- [ ] **Step 8: Apply the migration to the local dev database and verify round-trip**

Run: `cd backend && uv run alembic upgrade head`
Expected: no errors; `alembic current` shows `010 (head)`.

Run: `cd backend && uv run alembic downgrade 009 && uv run alembic upgrade head`
Expected: no errors on either direction — confirms `downgrade()` is correct.

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/screener.py backend/app/models/screener_commentary.py backend/app/models/__init__.py backend/alembic/versions/010_screener.py backend/tests/test_screener_models.py
git commit -m "feat(screener): add screener and screener_commentary tables"
```

---

## Task 4: Pydantic schemas

**Files:**
- Create: `backend/app/schemas/screener.py`

**Interfaces:**
- Consumes: nothing (pure schema definitions).
- Produces: `ScreenerFetchedFields` (base class holding every field `fetch_screener_row` computes — used by Task 6), `ScreenerPreviewResponse(ScreenerFetchedFields)` (adds `symbol`, `already_tracked`), `ScreenerRowCreate` (`symbol`, `category`, `precomputed: ScreenerFetchedFields | None`), `ScreenerRowPatch` (`sector`, `category`), `ScreenerRowResponse(ScreenerFetchedFields)` (adds `id`, `symbol`, `category`, `last_fetched_at`, `created_at`), `ScreenerCommentaryCreate`, `ScreenerCommentaryUpdate`, `ScreenerCommentaryResponse`, `ScreenerJobError`, `ScreenerJobStatus`. `list(ScreenerFetchedFields.model_fields.keys())` is the canonical list of fetched-data column names, used by the router in Task 7 to avoid re-listing them.

- [ ] **Step 1: Create the schema file**

Create `backend/app/schemas/screener.py`:

```python
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict


class ScreenerFetchedFields(BaseModel):
    """Every field `fetch_screener_row` computes. Shared by the preview response,
    the `precomputed` commit payload, and (via inheritance) the persisted row response."""
    sector: Optional[str] = None
    price: Optional[Decimal] = None
    prev_close: Optional[Decimal] = None
    change_pct: Optional[Decimal] = None
    iv_rank: Optional[Decimal] = None
    iv_percentile: Optional[Decimal] = None
    rsi_14: Optional[Decimal] = None
    macd_weekly_signal: Optional[str] = None
    macd_daily_signal: Optional[str] = None
    ma_20d: Optional[Decimal] = None
    ma_50d: Optional[Decimal] = None
    ma_100d: Optional[Decimal] = None
    ma_200d: Optional[Decimal] = None
    bollinger_upper: Optional[Decimal] = None
    bollinger_mid: Optional[Decimal] = None
    bollinger_lower: Optional[Decimal] = None
    bollinger_position: Optional[str] = None
    next_earnings_date: Optional[date] = None
    volume_spikes: Optional[list[dict]] = None
    fetch_status: Optional[str] = None
    fetch_error: Optional[str] = None


class ScreenerPreviewResponse(ScreenerFetchedFields):
    symbol: str
    already_tracked: bool


class ScreenerRowCreate(BaseModel):
    symbol: str
    category: Optional[str] = None
    precomputed: Optional[ScreenerFetchedFields] = None


class ScreenerRowPatch(BaseModel):
    sector: Optional[str] = None
    category: Optional[str] = None


class ScreenerRowResponse(ScreenerFetchedFields):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    symbol: str
    category: Optional[str] = None
    last_fetched_at: Optional[datetime] = None
    created_at: datetime


class ScreenerCommentaryCreate(BaseModel):
    note: str
    tags: Optional[list[str]] = None


class ScreenerCommentaryUpdate(BaseModel):
    note: str
    tags: Optional[list[str]] = None


class ScreenerCommentaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    screener_id: uuid.UUID
    note: str
    tags: Optional[list[str]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class ScreenerJobError(BaseModel):
    symbol: str
    error: str


class ScreenerJobStatus(BaseModel):
    job_id: str
    status: str
    total: int
    completed: int
    errors: list[ScreenerJobError] = []
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `cd backend && uv run python -c "from app.schemas.screener import ScreenerRowResponse, ScreenerFetchedFields; print(list(ScreenerFetchedFields.model_fields.keys()))"`
Expected: prints the 20-field list starting with `['sector', 'price', 'prev_close', ...]`, no errors.

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/screener.py
git commit -m "feat(screener): add Pydantic schemas"
```

---

## Task 5: `SchwabClient.get_instrument_fundamentals`

**Files:**
- Modify: `backend/app/services/schwab_client.py` (add method to `SchwabClient` class, after `get_option_chain`)
- Test: `backend/tests/test_schwab_client_fundamentals.py` (new file)

**Interfaces:**
- Produces: `SchwabClient.get_instrument_fundamentals(ticker: str) -> dict` — returns the raw `fundamental` sub-object from Schwab's `/marketdata/v1/instruments?projection=fundamental` response, or `{}` if the symbol isn't found. Never raises for a missing symbol; still raises `SchwabAPIError` for a non-200 HTTP response (via the existing `_get` helper).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_schwab_client_fundamentals.py`:

```python
from unittest.mock import MagicMock, patch

from app.services.schwab_client import SchwabClient


def _make_client() -> SchwabClient:
    client = SchwabClient.__new__(SchwabClient)  # bypass __init__ (no token setup needed for this test)
    return client


def test_get_instrument_fundamentals_returns_fundamental_dict():
    client = _make_client()
    mock_response = {
        "instruments": [
            {"symbol": "AAPL", "fundamental": {"symbol": "AAPL", "peRatio": 30.5}}
        ]
    }
    with patch.object(client, "_get", return_value=mock_response) as mock_get:
        result = client.get_instrument_fundamentals("aapl")
    mock_get.assert_called_once_with(
        "/marketdata/v1/instruments", {"symbol": "AAPL", "projection": "fundamental"}
    )
    assert result == {"symbol": "AAPL", "peRatio": 30.5}


def test_get_instrument_fundamentals_returns_empty_dict_when_not_found():
    client = _make_client()
    with patch.object(client, "_get", return_value={"instruments": []}):
        result = client.get_instrument_fundamentals("ZZZZ")
    assert result == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_schwab_client_fundamentals.py -v`
Expected: FAIL — `AttributeError: 'SchwabClient' object has no attribute 'get_instrument_fundamentals'`

- [ ] **Step 3: Implement the method**

In `backend/app/services/schwab_client.py`, add after `get_option_chain` (before the module-level `_client` singleton code):

```python
    def get_instrument_fundamentals(self, ticker: str) -> dict:
        """Returns the raw `fundamental` object from Schwab's instruments endpoint,
        or {} if the symbol has no fundamental data on file."""
        data = self._get("/marketdata/v1/instruments", {
            "symbol": ticker.upper(),
            "projection": "fundamental",
        })
        instruments = data.get("instruments", [])
        if not instruments:
            return {}
        return instruments[0].get("fundamental", {})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_schwab_client_fundamentals.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/schwab_client.py backend/tests/test_schwab_client_fundamentals.py
git commit -m "feat(schwab): add get_instrument_fundamentals for sector lookup"
```

---

## Task 6: `screener_fetcher.fetch_screener_row`

**Files:**
- Create: `backend/app/services/screener_fetcher.py`
- Test: `backend/tests/test_screener_fetcher.py` (new file)

**Interfaces:**
- Consumes: `fetch_technicals(ticker, return_closes=True)` (Task 1), `compute_iv_percentile_from_chain` (Task 2), `SchwabClient.get_instrument_fundamentals` (Task 5), `get_schwab_client()`, `SchwabAPIError`.
- Produces: `fetch_screener_row(ticker: str, existing_sector: str | None = None) -> dict` — a dict whose keys are exactly `list(ScreenerFetchedFields.model_fields.keys())` from Task 4 (`sector, price, prev_close, change_pct, iv_rank, iv_percentile, rsi_14, macd_weekly_signal, macd_daily_signal, ma_20d, ma_50d, ma_100d, ma_200d, bollinger_upper, bollinger_mid, bollinger_lower, bollinger_position, next_earnings_date, volume_spikes, fetch_status, fetch_error`). On any failure, returns `{"fetch_status": "error", "fetch_error": <str>}` only (a partial dict — callers must use `.get(key)` when merging, never assume every key is present on error).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_screener_fetcher.py`:

```python
import pandas as pd
from unittest.mock import MagicMock, patch

from app.services.screener_fetcher import fetch_screener_row
from app.services.schwab_client import SchwabAPIError

MOCK_TECHNICALS = {
    "fetch_status": "ok",
    "rsi_14": 55.2,
    "macd_signal": "bullish",
    "macd_daily_cross_direction": "bullish",
    "ma_20d": 190.0, "ma_50d": 185.0, "ma_100d": 180.0, "ma_200d": 170.0,
    "bollinger_upper": 200.0, "bollinger_mid": 190.0, "bollinger_lower": 180.0,
    "bollinger_position": "mid",
    "next_earnings_date": "2026-09-01",
    "volume_spikes": [],
}


def test_fetch_screener_row_success():
    close_d = pd.Series([190.0] * 100)
    mock_client = MagicMock()
    mock_client.get_quotes.return_value = {"AAPL": {"lastPrice": 195.5, "closePrice": 190.0}}
    mock_client.get_option_chain.return_value = {"underlyingPrice": 195.5, "callExpDateMap": {}}
    mock_client.get_instrument_fundamentals.return_value = {"sector": "Technology"}

    with patch("app.services.screener_fetcher.fetch_technicals", return_value=(MOCK_TECHNICALS, close_d)), \
         patch("app.services.screener_fetcher.get_schwab_client", return_value=mock_client), \
         patch("app.services.screener_fetcher.compute_iv_percentile_from_chain", return_value=(45.0, 0.25)):
        result = fetch_screener_row("AAPL")

    assert result["fetch_status"] == "ok"
    assert result["price"] == 195.5
    assert result["prev_close"] == 190.0
    assert result["change_pct"] == round((195.5 - 190.0) / 190.0 * 100, 2)
    assert result["iv_percentile"] == 45.0
    assert result["rsi_14"] == 55.2
    assert result["macd_weekly_signal"] == "bullish"
    assert result["macd_daily_signal"] == "bullish"
    assert result["ma_20d"] == 190.0
    assert result["sector"] == "Technology"


def test_fetch_screener_row_propagates_technicals_error():
    with patch(
        "app.services.screener_fetcher.fetch_technicals",
        return_value=({"fetch_status": "error", "fetch_error": "No daily data for ZZZZ"}, pd.Series(dtype=float)),
    ):
        result = fetch_screener_row("ZZZZ")

    assert result == {"fetch_status": "error", "fetch_error": "No daily data for ZZZZ"}


def test_fetch_screener_row_handles_schwab_api_error():
    with patch("app.services.screener_fetcher.fetch_technicals", side_effect=SchwabAPIError("rate limited")):
        result = fetch_screener_row("AAPL")

    assert result["fetch_status"] == "error"
    assert "rate limited" in result["fetch_error"]


def test_fetch_screener_row_sector_lookup_failure_falls_back_to_existing():
    close_d = pd.Series([190.0] * 100)
    mock_client = MagicMock()
    mock_client.get_quotes.return_value = {"AAPL": {"lastPrice": 195.5, "closePrice": 190.0}}
    mock_client.get_option_chain.return_value = {"underlyingPrice": 195.5, "callExpDateMap": {}}
    mock_client.get_instrument_fundamentals.side_effect = Exception("no fundamentals endpoint")

    with patch("app.services.screener_fetcher.fetch_technicals", return_value=(MOCK_TECHNICALS, close_d)), \
         patch("app.services.screener_fetcher.get_schwab_client", return_value=mock_client), \
         patch("app.services.screener_fetcher.compute_iv_percentile_from_chain", return_value=(None, None)):
        result = fetch_screener_row("AAPL", existing_sector="Manually Set Sector")

    assert result["fetch_status"] == "ok"
    assert result["sector"] == "Manually Set Sector"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_screener_fetcher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.screener_fetcher'`

- [ ] **Step 3: Implement the fetcher**

Create `backend/app/services/screener_fetcher.py`:

```python
# backend/app/services/screener_fetcher.py
import logging

from app.services.schwab_client import get_schwab_client, SchwabAPIError
from app.services.technicals_fetcher import fetch_technicals, compute_iv_percentile_from_chain

log = logging.getLogger(__name__)


def fetch_screener_row(ticker: str, existing_sector: str | None = None) -> dict:
    """Fetch a full screener snapshot for one ticker: quote, technicals, IV
    percentile, and best-effort sector. Never raises — on any failure returns
    {"fetch_status": "error", "fetch_error": <str>} (a partial dict; other
    keys are absent, not None, so callers must use .get())."""
    try:
        technicals, close_d = fetch_technicals(ticker, return_closes=True)
        if technicals.get("fetch_status") != "ok":
            return {"fetch_status": "error", "fetch_error": technicals.get("fetch_error")}

        client = get_schwab_client()

        quotes = client.get_quotes([ticker])
        quote = quotes.get(ticker, {})
        price = quote.get("lastPrice") or quote.get("mark")
        prev_close = quote.get("closePrice")
        if price is None:
            return {"fetch_status": "error", "fetch_error": f"No quote for {ticker}"}
        price = float(price)
        change_pct = (
            round((price - float(prev_close)) / float(prev_close) * 100, 2)
            if prev_close else None
        )

        chain = client.get_option_chain(ticker, contract_type="CALL", strike_count=30)
        iv_percentile, _atm_iv = compute_iv_percentile_from_chain(close_d, chain, ticker)

        sector = existing_sector
        try:
            fundamental = client.get_instrument_fundamentals(ticker)
            fetched_sector = fundamental.get("sector")
            if fetched_sector:
                sector = fetched_sector
        except Exception:
            log.warning("Sector lookup failed for %s", ticker, exc_info=True)

        return {
            "sector": sector,
            "price": round(price, 2),
            "prev_close": round(float(prev_close), 2) if prev_close else None,
            "change_pct": change_pct,
            "iv_rank": None,
            "iv_percentile": iv_percentile,
            "rsi_14": technicals.get("rsi_14"),
            "macd_weekly_signal": technicals.get("macd_signal"),
            "macd_daily_signal": technicals.get("macd_daily_cross_direction") or "neutral",
            "ma_20d": technicals.get("ma_20d"),
            "ma_50d": technicals.get("ma_50d"),
            "ma_100d": technicals.get("ma_100d"),
            "ma_200d": technicals.get("ma_200d"),
            "bollinger_upper": technicals.get("bollinger_upper"),
            "bollinger_mid": technicals.get("bollinger_mid"),
            "bollinger_lower": technicals.get("bollinger_lower"),
            "bollinger_position": technicals.get("bollinger_position"),
            "next_earnings_date": technicals.get("next_earnings_date"),
            "volume_spikes": technicals.get("volume_spikes"),
            "fetch_status": "ok",
            "fetch_error": None,
        }
    except SchwabAPIError as exc:
        return {"fetch_status": "error", "fetch_error": str(exc)}
    except Exception as exc:
        log.exception("fetch_screener_row failed for %s", ticker)
        return {"fetch_status": "error", "fetch_error": str(exc)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_screener_fetcher.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/screener_fetcher.py backend/tests/test_screener_fetcher.py
git commit -m "feat(screener): add fetch_screener_row service"
```

---

## Task 7: `screener.py` router — list, preview, add, fetch-one, delete, patch

**Files:**
- Create: `backend/app/routers/screener.py`
- Modify: `backend/app/main.py` (register router)
- Test: `backend/tests/test_screener_router.py` (new file)

**Interfaces:**
- Consumes: `Screener`, `ScreenerCommentary` models (Task 3); all schemas from Task 4; `fetch_screener_row` (Task 6).
- Produces: `router = APIRouter(prefix="/api/screener", tags=["screener"])` with `GET ""`, `GET "/preview/{ticker}"`, `POST ""`, `POST "/{symbol}/fetch"`, `DELETE "/{symbol}"`, `PATCH "/{symbol}"`. Also defines module-level `_SCREENER_FIELDS = list(ScreenerFetchedFields.model_fields.keys())` and helper `async def _get_row_or_404(symbol: str, db: AsyncSession) -> Screener`, both reused by Task 8 (fetch-all job) and Task 9 (commentary endpoints) in the same file.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_screener_router.py`:

```python
import pytest
from httpx import AsyncClient
from unittest.mock import patch

MOCK_FETCH_OK = {
    "sector": "Technology", "price": 195.5, "prev_close": 190.0, "change_pct": 2.89,
    "iv_rank": None, "iv_percentile": 45.0, "rsi_14": 55.2,
    "macd_weekly_signal": "bullish", "macd_daily_signal": "bullish",
    "ma_20d": 190.0, "ma_50d": 185.0, "ma_100d": 180.0, "ma_200d": 170.0,
    "bollinger_upper": 200.0, "bollinger_mid": 190.0, "bollinger_lower": 180.0,
    "bollinger_position": "mid", "next_earnings_date": "2026-09-01", "volume_spikes": [],
    "fetch_status": "ok", "fetch_error": None,
}

MOCK_FETCH_ERROR = {"fetch_status": "error", "fetch_error": "No daily data for ZZZZ"}


async def test_add_symbol_direct_mode_fetches_and_persists(client: AsyncClient):
    with patch("app.routers.screener.fetch_screener_row", return_value=MOCK_FETCH_OK) as mock_fn:
        response = await client.post("/api/screener", json={"symbol": "aapl", "category": "Watchlist"})
    assert response.status_code == 201
    data = response.json()
    assert data["symbol"] == "AAPL"
    assert data["category"] == "Watchlist"
    assert data["price"] == 195.5
    assert data["fetch_status"] == "ok"
    mock_fn.assert_called_once_with("AAPL")


async def test_add_symbol_duplicate_returns_409(client: AsyncClient):
    with patch("app.routers.screener.fetch_screener_row", return_value=MOCK_FETCH_OK):
        await client.post("/api/screener", json={"symbol": "AAPL"})
        response = await client.post("/api/screener", json={"symbol": "AAPL"})
    assert response.status_code == 409


async def test_add_symbol_with_precomputed_skips_fetch(client: AsyncClient):
    with patch("app.routers.screener.fetch_screener_row") as mock_fn:
        response = await client.post("/api/screener", json={"symbol": "MSFT", "precomputed": MOCK_FETCH_OK})
    assert response.status_code == 201
    assert response.json()["price"] == 195.5
    mock_fn.assert_not_called()


async def test_preview_returns_data_without_persisting(client: AsyncClient):
    with patch("app.routers.screener.fetch_screener_row", return_value=MOCK_FETCH_OK) as mock_fn:
        response = await client.get("/api/screener/preview/tsla")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "TSLA"
    assert data["already_tracked"] is False
    mock_fn.assert_called_once_with("TSLA")

    list_response = await client.get("/api/screener")
    assert list_response.json() == []


async def test_preview_flags_already_tracked(client: AsyncClient):
    with patch("app.routers.screener.fetch_screener_row", return_value=MOCK_FETCH_OK):
        await client.post("/api/screener", json={"symbol": "AAPL"})
        response = await client.get("/api/screener/preview/aapl")
    assert response.json()["already_tracked"] is True


async def test_list_screener_rows(client: AsyncClient):
    with patch("app.routers.screener.fetch_screener_row", return_value=MOCK_FETCH_OK):
        await client.post("/api/screener", json={"symbol": "AAPL"})
        await client.post("/api/screener", json={"symbol": "MSFT"})
    response = await client.get("/api/screener")
    symbols = [r["symbol"] for r in response.json()]
    assert symbols == ["AAPL", "MSFT"]


async def test_fetch_one_updates_existing_row(client: AsyncClient):
    with patch("app.routers.screener.fetch_screener_row", return_value=MOCK_FETCH_OK):
        await client.post("/api/screener", json={"symbol": "AAPL"})
    updated = {**MOCK_FETCH_OK, "price": 200.0}
    with patch("app.routers.screener.fetch_screener_row", return_value=updated):
        response = await client.post("/api/screener/AAPL/fetch")
    assert response.status_code == 200
    assert response.json()["price"] == 200.0


async def test_fetch_one_404_when_not_tracked(client: AsyncClient):
    response = await client.post("/api/screener/ZZZZ/fetch")
    assert response.status_code == 404


async def test_delete_screener_symbol(client: AsyncClient):
    with patch("app.routers.screener.fetch_screener_row", return_value=MOCK_FETCH_OK):
        await client.post("/api/screener", json={"symbol": "AAPL"})
    response = await client.delete("/api/screener/aapl")
    assert response.status_code == 204
    list_response = await client.get("/api/screener")
    assert list_response.json() == []


async def test_delete_404_when_not_tracked(client: AsyncClient):
    response = await client.delete("/api/screener/ZZZZ")
    assert response.status_code == 404


async def test_patch_sector_and_category(client: AsyncClient):
    with patch("app.routers.screener.fetch_screener_row", return_value=MOCK_FETCH_OK):
        await client.post("/api/screener", json={"symbol": "AAPL"})
    response = await client.patch("/api/screener/AAPL", json={"sector": "Consumer Electronics", "category": "Wheel Candidate"})
    assert response.status_code == 200
    data = response.json()
    assert data["sector"] == "Consumer Electronics"
    assert data["category"] == "Wheel Candidate"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_screener_router.py -v`
Expected: FAIL — `404 Not Found` for all routes (router not registered / doesn't exist) or `ModuleNotFoundError`.

- [ ] **Step 3: Implement the router (list/preview/add/fetch-one/delete/patch only — fetch-all job comes in Task 8, commentary comes in Task 9)**

Create `backend/app/routers/screener.py`:

```python
# backend/app/routers/screener.py
import asyncio
import uuid
from datetime import datetime, timezone
from functools import partial

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.screener import Screener
from app.schemas.screener import (
    ScreenerFetchedFields,
    ScreenerRowCreate,
    ScreenerRowResponse,
    ScreenerRowPatch,
    ScreenerPreviewResponse,
)
from app.services.screener_fetcher import fetch_screener_row

router = APIRouter(prefix="/api/screener", tags=["screener"])

_SCREENER_FIELDS = list(ScreenerFetchedFields.model_fields.keys())


async def _get_row_or_404(symbol: str, db: AsyncSession) -> Screener:
    stmt = select(Screener).where(Screener.symbol == symbol.upper())
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{symbol.upper()} is not tracked")
    return row


@router.get("", response_model=list[ScreenerRowResponse])
async def list_screener(db: AsyncSession = Depends(get_db)):
    stmt = select(Screener).order_by(Screener.symbol)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/preview/{ticker}", response_model=ScreenerPreviewResponse)
async def preview_screener(ticker: str, db: AsyncSession = Depends(get_db)):
    symbol = ticker.upper()
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, fetch_screener_row, symbol)
    existing = await db.execute(select(Screener.id).where(Screener.symbol == symbol))
    already_tracked = existing.scalar_one_or_none() is not None
    return {**data, "symbol": symbol, "already_tracked": already_tracked}


@router.post("", response_model=ScreenerRowResponse, status_code=201)
async def add_screener_symbol(payload: ScreenerRowCreate, db: AsyncSession = Depends(get_db)):
    symbol = payload.symbol.upper()
    existing = await db.execute(select(Screener).where(Screener.symbol == symbol))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"{symbol} is already tracked")

    if payload.precomputed is not None:
        data = payload.precomputed.model_dump()
    else:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, fetch_screener_row, symbol)

    row = Screener(
        symbol=symbol,
        category=payload.category,
        last_fetched_at=datetime.now(timezone.utc),
        **{k: data.get(k) for k in _SCREENER_FIELDS},
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.post("/{symbol}/fetch", response_model=ScreenerRowResponse)
async def fetch_screener_symbol(symbol: str, db: AsyncSession = Depends(get_db)):
    row = await _get_row_or_404(symbol, db)
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, partial(fetch_screener_row, row.symbol, row.sector))
    for k in _SCREENER_FIELDS:
        setattr(row, k, data.get(k))
    row.last_fetched_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{symbol}", status_code=204)
async def delete_screener_symbol(symbol: str, db: AsyncSession = Depends(get_db)):
    row = await _get_row_or_404(symbol, db)
    await db.delete(row)
    await db.commit()


@router.patch("/{symbol}", response_model=ScreenerRowResponse)
async def patch_screener_symbol(symbol: str, payload: ScreenerRowPatch, db: AsyncSession = Depends(get_db)):
    row = await _get_row_or_404(symbol, db)
    if payload.sector is not None:
        row.sector = payload.sector
    if payload.category is not None:
        row.category = payload.category
    await db.commit()
    await db.refresh(row)
    return row
```

- [ ] **Step 4: Register the router in `main.py`**

In `backend/app/main.py`, change:

```python
from app.routers import trades, commentary, alerts, market, briefing, categories, positions, signals, sessions, wheel
```

to:

```python
from app.routers import trades, commentary, alerts, market, briefing, categories, positions, signals, sessions, wheel, screener
```

and add after `app.include_router(wheel.router)`:

```python
app.include_router(screener.router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_screener_router.py -v`
Expected: PASS (11 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/screener.py backend/app/main.py backend/tests/test_screener_router.py
git commit -m "feat(screener): add list/preview/add/fetch/delete/patch endpoints"
```

---

## Task 8: Fetch-all background job

**Files:**
- Modify: `backend/app/routers/screener.py` (append job machinery)
- Test: `backend/tests/test_screener_router.py` (append)

**Interfaces:**
- Consumes: `_SCREENER_FIELDS`, `Screener` model, `fetch_screener_row` (all from Task 7/6).
- Produces: `POST /api/screener/fetch-all` (202, returns `ScreenerJobStatus`), `GET /api/screener/jobs/{job_id}` (returns `ScreenerJobStatus`, 404 if unknown). Module-level `_jobs: dict[str, dict]` (in-memory, mirrors `commentary.py`'s `_summary_cache` pattern — no persistence across restarts, acceptable for a manually-triggered short-lived job).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_screener_router.py`:

```python
import asyncio


async def test_fetch_all_runs_job_and_updates_rows(client: AsyncClient):
    with patch("app.routers.screener.fetch_screener_row", return_value=MOCK_FETCH_OK):
        await client.post("/api/screener", json={"symbol": "AAPL"})
        await client.post("/api/screener", json={"symbol": "MSFT"})

    updated = {**MOCK_FETCH_OK, "price": 999.0}
    with patch("app.routers.screener.fetch_screener_row", return_value=updated):
        response = await client.post("/api/screener/fetch-all")
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        assert response.json()["total"] == 2

        for _ in range(50):
            status_response = await client.get(f"/api/screener/jobs/{job_id}")
            status = status_response.json()
            if status["status"] == "done":
                break
            await asyncio.sleep(0.1)
        assert status["status"] == "done"
        assert status["completed"] == 2

    list_response = await client.get("/api/screener")
    prices = {r["symbol"]: r["price"] for r in list_response.json()}
    assert prices == {"AAPL": 999.0, "MSFT": 999.0}


async def test_fetch_all_records_per_symbol_errors(client: AsyncClient):
    with patch("app.routers.screener.fetch_screener_row", return_value=MOCK_FETCH_OK):
        await client.post("/api/screener", json={"symbol": "AAPL"})

    with patch("app.routers.screener.fetch_screener_row", return_value=MOCK_FETCH_ERROR):
        response = await client.post("/api/screener/fetch-all")
        job_id = response.json()["job_id"]

        for _ in range(50):
            status_response = await client.get(f"/api/screener/jobs/{job_id}")
            status = status_response.json()
            if status["status"] == "done":
                break
            await asyncio.sleep(0.1)
        assert status["status"] == "done"
        assert status["errors"] == [{"symbol": "AAPL", "error": "No daily data for ZZZZ"}]


async def test_get_job_status_404_for_unknown_job(client: AsyncClient):
    response = await client.get("/api/screener/jobs/does-not-exist")
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_screener_router.py -v -k fetch_all`
Expected: FAIL — `404 Not Found` (routes don't exist yet)

- [ ] **Step 3: Implement the job machinery**

Append to `backend/app/routers/screener.py` (after the existing `patch_screener_symbol` endpoint, before end of file):

```python
from app.database import AsyncSessionLocal
from app.schemas.screener import ScreenerJobStatus

_jobs: dict[str, dict] = {}


async def _run_fetch_all_job(job_id: str, symbols: list[str]) -> None:
    loop = asyncio.get_running_loop()
    for symbol in symbols:
        async with AsyncSessionLocal() as session:
            stmt = select(Screener).where(Screener.symbol == symbol)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is not None:
                data = await loop.run_in_executor(None, partial(fetch_screener_row, symbol, row.sector))
                if data.get("fetch_status") == "error":
                    _jobs[job_id]["errors"].append({"symbol": symbol, "error": data.get("fetch_error")})
                for k in _SCREENER_FIELDS:
                    setattr(row, k, data.get(k))
                row.last_fetched_at = datetime.now(timezone.utc)
                await session.commit()
        _jobs[job_id]["completed"] += 1
    _jobs[job_id]["status"] = "done"


@router.post("/fetch-all", response_model=ScreenerJobStatus, status_code=202)
async def fetch_all_screener(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Screener.symbol))
    symbols = [row[0] for row in result.all()]
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "running", "total": len(symbols), "completed": 0, "errors": []}
    asyncio.create_task(_run_fetch_all_job(job_id, symbols))
    return {"job_id": job_id, **_jobs[job_id]}


@router.get("/jobs/{job_id}", response_model=ScreenerJobStatus)
async def get_screener_job(job_id: str):
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job")
    return {"job_id": job_id, **job}
```

Move the `from app.database import AsyncSessionLocal` and `from app.schemas.screener import ScreenerJobStatus` lines up to the top import block (with the other imports) instead of inline — final import block at the top of the file should read:

```python
import asyncio
import uuid
from datetime import datetime, timezone
from functools import partial

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db, AsyncSessionLocal
from app.models.screener import Screener
from app.schemas.screener import (
    ScreenerFetchedFields,
    ScreenerRowCreate,
    ScreenerRowResponse,
    ScreenerRowPatch,
    ScreenerPreviewResponse,
    ScreenerJobStatus,
)
from app.services.screener_fetcher import fetch_screener_row
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_screener_router.py -v -k fetch_all`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full screener router test file for regressions**

Run: `cd backend && uv run pytest tests/test_screener_router.py -v`
Expected: PASS (all 14 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/screener.py backend/tests/test_screener_router.py
git commit -m "feat(screener): add sequential fetch-all background job with progress polling"
```

---

## Task 9: Commentary CRUD endpoints

**Files:**
- Modify: `backend/app/routers/screener.py` (append commentary endpoints)
- Test: `backend/tests/test_screener_commentary_router.py` (new file)

**Interfaces:**
- Consumes: `ScreenerCommentary` model (Task 3), `_get_row_or_404` (Task 7).
- Produces: `GET /api/screener/{symbol}/commentary`, `POST /api/screener/{symbol}/commentary`, `PUT /api/screener/commentary/{comment_id}`, `DELETE /api/screener/commentary/{comment_id}`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_screener_commentary_router.py`:

```python
import pytest
from httpx import AsyncClient
from unittest.mock import patch

MOCK_FETCH_OK = {
    "sector": None, "price": 100.0, "prev_close": 99.0, "change_pct": 1.01,
    "iv_rank": None, "iv_percentile": None, "rsi_14": None,
    "macd_weekly_signal": None, "macd_daily_signal": None,
    "ma_20d": None, "ma_50d": None, "ma_100d": None, "ma_200d": None,
    "bollinger_upper": None, "bollinger_mid": None, "bollinger_lower": None,
    "bollinger_position": None, "next_earnings_date": None, "volume_spikes": [],
    "fetch_status": "ok", "fetch_error": None,
}


async def _add_symbol(client: AsyncClient, symbol: str = "AAPL") -> None:
    with patch("app.routers.screener.fetch_screener_row", return_value=MOCK_FETCH_OK):
        await client.post("/api/screener", json={"symbol": symbol})


async def test_add_and_list_commentary(client: AsyncClient):
    await _add_symbol(client)
    response = await client.post("/api/screener/AAPL/commentary", json={"note": "Watching for a breakout", "tags": ["breakout"]})
    assert response.status_code == 201
    data = response.json()
    assert data["note"] == "Watching for a breakout"
    assert data["updated_at"] is None

    list_response = await client.get("/api/screener/AAPL/commentary")
    assert len(list_response.json()) == 1


async def test_add_commentary_404_when_symbol_not_tracked(client: AsyncClient):
    response = await client.post("/api/screener/ZZZZ/commentary", json={"note": "note"})
    assert response.status_code == 404


async def test_update_commentary_sets_updated_at(client: AsyncClient):
    await _add_symbol(client)
    add_response = await client.post("/api/screener/AAPL/commentary", json={"note": "original"})
    comment_id = add_response.json()["id"]

    response = await client.put(f"/api/screener/commentary/{comment_id}", json={"note": "edited note"})
    assert response.status_code == 200
    data = response.json()
    assert data["note"] == "edited note"
    assert data["updated_at"] is not None


async def test_update_commentary_404_when_missing(client: AsyncClient):
    import uuid
    response = await client.put(f"/api/screener/commentary/{uuid.uuid4()}", json={"note": "x"})
    assert response.status_code == 404


async def test_delete_commentary(client: AsyncClient):
    await _add_symbol(client)
    add_response = await client.post("/api/screener/AAPL/commentary", json={"note": "delete me"})
    comment_id = add_response.json()["id"]

    response = await client.delete(f"/api/screener/commentary/{comment_id}")
    assert response.status_code == 204

    list_response = await client.get("/api/screener/AAPL/commentary")
    assert list_response.json() == []


async def test_delete_commentary_404_when_missing(client: AsyncClient):
    import uuid
    response = await client.delete(f"/api/screener/commentary/{uuid.uuid4()}")
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_screener_commentary_router.py -v`
Expected: FAIL — `404 Not Found` (routes don't exist)

- [ ] **Step 3: Implement the commentary endpoints**

Add to the top imports of `backend/app/routers/screener.py`:

```python
from app.models.screener_commentary import ScreenerCommentary
```

and add `ScreenerCommentaryCreate, ScreenerCommentaryUpdate, ScreenerCommentaryResponse` to the existing `from app.schemas.screener import (...)` block.

Append to the end of `backend/app/routers/screener.py`:

```python
@router.get("/{symbol}/commentary", response_model=list[ScreenerCommentaryResponse])
async def list_screener_commentary(symbol: str, db: AsyncSession = Depends(get_db)):
    row = await _get_row_or_404(symbol, db)
    stmt = (
        select(ScreenerCommentary)
        .where(ScreenerCommentary.screener_id == row.id)
        .order_by(ScreenerCommentary.created_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/{symbol}/commentary", response_model=ScreenerCommentaryResponse, status_code=201)
async def add_screener_commentary(symbol: str, payload: ScreenerCommentaryCreate, db: AsyncSession = Depends(get_db)):
    row = await _get_row_or_404(symbol, db)
    entry = ScreenerCommentary(screener_id=row.id, note=payload.note, tags=payload.tags)
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.put("/commentary/{comment_id}", response_model=ScreenerCommentaryResponse)
async def update_screener_commentary(comment_id: uuid.UUID, payload: ScreenerCommentaryUpdate, db: AsyncSession = Depends(get_db)):
    stmt = select(ScreenerCommentary).where(ScreenerCommentary.id == comment_id)
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Commentary entry not found")
    entry.note = payload.note
    entry.tags = payload.tags
    entry.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.delete("/commentary/{comment_id}", status_code=204)
async def delete_screener_commentary(comment_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt = select(ScreenerCommentary).where(ScreenerCommentary.id == comment_id)
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Commentary entry not found")
    await db.delete(entry)
    await db.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_screener_commentary_router.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the complete backend test suite for regressions**

Run: `cd backend && uv run pytest tests/ -v`
Expected: PASS — all tests across the whole suite, including everything from Tasks 1-9.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/screener.py backend/tests/test_screener_commentary_router.py
git commit -m "feat(screener): add commentary CRUD endpoints"
```

---

## Task 10: Frontend types + API client

**Files:**
- Modify: `frontend/src/types/index.ts` (append types)
- Create: `frontend/src/api/screener.ts`

**Interfaces:**
- Produces: TS types `VolumeSpike`, `ScreenerFetchedFields`, `ScreenerRow`, `ScreenerPreview`, `ScreenerCommentary`, `ScreenerJobStatus`. `screenerApi` object with `list`, `preview`, `add`, `fetchOne`, `fetchAll`, `getJobStatus`, `remove`, `patch`, `commentary.{list,add,update,remove}` — consumed by every component in Tasks 11-14.

- [ ] **Step 1: Append types to `frontend/src/types/index.ts`**

Add at the end of the file:

```typescript
export interface VolumeSpike {
  date: string
  volume: number
  avg_volume: number
  ratio: number
}

// Decimal-backed fields are serialized as JSON strings by this repo's Pydantic
// schemas (e.g. "195.50", not 195.5) — parseFloat() at the point of use, don't
// treat these as numbers. volume_spikes entries are plain JSON ints/floats
// (not Decimal), so VolumeSpike stays numeric.
export interface ScreenerFetchedFields {
  sector: string | null
  price: string | null
  prev_close: string | null
  change_pct: string | null
  iv_rank: string | null
  iv_percentile: string | null
  rsi_14: string | null
  macd_weekly_signal: string | null
  macd_daily_signal: string | null
  ma_20d: string | null
  ma_50d: string | null
  ma_100d: string | null
  ma_200d: string | null
  bollinger_upper: string | null
  bollinger_mid: string | null
  bollinger_lower: string | null
  bollinger_position: string | null
  next_earnings_date: string | null
  volume_spikes: VolumeSpike[] | null
  fetch_status: string | null
  fetch_error: string | null
}

export interface ScreenerRow extends ScreenerFetchedFields {
  id: string
  symbol: string
  category: string | null
  last_fetched_at: string | null
  created_at: string
}

export interface ScreenerPreview extends ScreenerFetchedFields {
  symbol: string
  already_tracked: boolean
}

export interface ScreenerCommentary {
  id: string
  screener_id: string
  note: string
  tags: string[] | null
  created_at: string
  updated_at: string | null
}

export interface ScreenerJobError {
  symbol: string
  error: string
}

export interface ScreenerJobStatus {
  job_id: string
  status: 'running' | 'done'
  total: number
  completed: number
  errors: ScreenerJobError[]
}
```

- [ ] **Step 2: Create `frontend/src/api/screener.ts`**

```typescript
// frontend/src/api/screener.ts
import { apiFetch } from './client'
import type { ScreenerRow, ScreenerPreview, ScreenerCommentary, ScreenerJobStatus, ScreenerFetchedFields } from '../types'

export const screenerApi = {
  list: () => apiFetch<ScreenerRow[]>('/screener'),

  preview: (ticker: string) => apiFetch<ScreenerPreview>(`/screener/preview/${ticker}`),

  add: (payload: { symbol: string; category?: string; precomputed?: ScreenerFetchedFields }) =>
    apiFetch<ScreenerRow>('/screener', { method: 'POST', body: JSON.stringify(payload) }),

  fetchOne: (symbol: string) =>
    apiFetch<ScreenerRow>(`/screener/${symbol}/fetch`, { method: 'POST' }),

  fetchAll: () =>
    apiFetch<ScreenerJobStatus>('/screener/fetch-all', { method: 'POST' }),

  getJobStatus: (jobId: string) =>
    apiFetch<ScreenerJobStatus>(`/screener/jobs/${jobId}`),

  remove: (symbol: string) =>
    apiFetch<void>(`/screener/${symbol}`, { method: 'DELETE' }),

  patch: (symbol: string, payload: { sector?: string; category?: string }) =>
    apiFetch<ScreenerRow>(`/screener/${symbol}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  commentary: {
    list: (symbol: string) => apiFetch<ScreenerCommentary[]>(`/screener/${symbol}/commentary`),

    add: (symbol: string, payload: { note: string; tags?: string[] }) =>
      apiFetch<ScreenerCommentary>(`/screener/${symbol}/commentary`, {
        method: 'POST',
        body: JSON.stringify(payload),
      }),

    update: (commentId: string, payload: { note: string; tags?: string[] }) =>
      apiFetch<ScreenerCommentary>(`/screener/commentary/${commentId}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      }),

    remove: (commentId: string) =>
      apiFetch<void>(`/screener/commentary/${commentId}`, { method: 'DELETE' }),
  },
}
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/screener.ts
git commit -m "feat(screener): add frontend types and API client"
```

---

## Task 11: `timeAgo` helper + `ScreenerTable` + `ScreenerDetailRow`

**Files:**
- Create: `frontend/src/components/Screener/timeAgo.ts`
- Create: `frontend/src/components/Screener/ScreenerDetailRow.tsx`
- Create: `frontend/src/components/Screener/ScreenerTable.tsx`

**Interfaces:**
- Consumes: `ScreenerRow` type (Task 10), `screenerApi.fetchOne` (Task 10), `ScreenerCommentaryCell` (Task 13 — imported here but not implemented until Task 13; this task will not type-check standalone, see Step 4 note).
- Produces: `timeAgo(iso: string | null): string`. `ScreenerTable` props `{ rows: ScreenerRow[]; onRefreshRow: (row: ScreenerRow) => void; onRemove: (symbol: string) => void }`. `ScreenerDetailRow` props `{ row: ScreenerRow; colSpan: number }`.

- [ ] **Step 1: Create the time-ago helper**

Create `frontend/src/components/Screener/timeAgo.ts`:

```typescript
export function timeAgo(iso: string | null): string {
  if (!iso) return 'never'
  const then = new Date(iso).getTime()
  const diffMs = Date.now() - then
  const minutes = Math.floor(diffMs / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min${minutes === 1 ? '' : 's'} ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`
  const days = Math.floor(hours / 24)
  return `${days} day${days === 1 ? '' : 's'} ago`
}
```

- [ ] **Step 2: Create `ScreenerDetailRow.tsx`**

Create `frontend/src/components/Screener/ScreenerDetailRow.tsx`:

```tsx
import type { ScreenerRow } from '../../types'

export function ScreenerDetailRow({ row, colSpan }: { row: ScreenerRow; colSpan: number }) {
  return (
    <tr className="bg-gray-50 border-t border-gray-100">
      <td colSpan={colSpan} className="px-6 py-3">
        <div className="grid grid-cols-4 gap-x-6 gap-y-2 text-xs">
          <div><span className="text-gray-400">Bollinger Upper: </span><span className="font-medium">{row.bollinger_upper ?? '—'}</span></div>
          <div><span className="text-gray-400">Bollinger Mid: </span><span className="font-medium">{row.bollinger_mid ?? '—'}</span></div>
          <div><span className="text-gray-400">Bollinger Lower: </span><span className="font-medium">{row.bollinger_lower ?? '—'}</span></div>
          <div><span className="text-gray-400">MACD Daily: </span><span className="font-medium">{row.macd_daily_signal ?? '—'}</span></div>
          <div><span className="text-gray-400">Next Earnings: </span><span className="font-medium">{row.next_earnings_date ?? '—'}</span></div>
          <div><span className="text-gray-400">Sector: </span><span className="font-medium">{row.sector ?? '—'}</span></div>
          <div><span className="text-gray-400">Category: </span><span className="font-medium">{row.category ?? '—'}</span></div>
          <div><span className="text-gray-400">Fetch Status: </span><span className="font-medium">{row.fetch_status ?? '—'}{row.fetch_error ? ` (${row.fetch_error})` : ''}</span></div>
        </div>
        {row.volume_spikes && row.volume_spikes.length > 0 && (
          <div className="mt-3">
            <div className="text-gray-400 text-xs mb-1">Volume Spikes</div>
            <table className="text-xs">
              <thead>
                <tr className="text-gray-400">
                  <th className="pr-4 text-left font-normal">Date</th>
                  <th className="pr-4 text-left font-normal">Volume</th>
                  <th className="pr-4 text-left font-normal">Avg</th>
                  <th className="text-left font-normal">Ratio</th>
                </tr>
              </thead>
              <tbody>
                {row.volume_spikes.map(spike => (
                  <tr key={spike.date}>
                    <td className="pr-4">{spike.date}</td>
                    <td className="pr-4">{spike.volume.toLocaleString()}</td>
                    <td className="pr-4">{spike.avg_volume.toLocaleString()}</td>
                    <td>{spike.ratio}x</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </td>
    </tr>
  )
}
```

- [ ] **Step 3: Create `ScreenerTable.tsx`**

Create `frontend/src/components/Screener/ScreenerTable.tsx`:

```tsx
import { useState } from 'react'
import type { ScreenerRow } from '../../types'
import { screenerApi } from '../../api/screener'
import { ScreenerDetailRow } from './ScreenerDetailRow'
import { ScreenerCommentaryCell } from './ScreenerCommentaryCell'
import { timeAgo } from './timeAgo'

interface Props {
  rows: ScreenerRow[]
  onRefreshRow: (row: ScreenerRow) => void
  onRemove: (symbol: string) => void
}

const MACD_COLORS: Record<string, string> = {
  bullish: 'bg-green-100 text-green-700',
  bearish: 'bg-red-100 text-red-700',
  neutral: 'bg-gray-100 text-gray-600',
}

const BB_LABELS: Record<string, string> = {
  above_upper: 'Above',
  near_upper: 'Top',
  mid: 'Mid',
  near_lower: 'Bottom',
  below_lower: 'Below',
}

const COLUMNS = ['Symbol', 'Price', 'Change%', 'IV Pctl', 'RSI(d)', 'MACD(w)', '20ma', '50ma', '100ma', '200ma', 'BB', 'Fetched', 'Commentary', '']

// Decimal fields arrive as strings (see types/index.ts note) — parse before math/formatting.
function toNum(v: string | null): number | null {
  if (v == null) return null
  const n = parseFloat(v)
  return Number.isNaN(n) ? null : n
}

function MaCell({ price, ma }: { price: string | null; ma: string | null }) {
  const maNum = toNum(ma)
  if (maNum == null) return <td className="px-3 py-2 text-gray-300">—</td>
  const priceNum = toNum(price)
  const below = priceNum != null && priceNum < maNum
  return (
    <td className={`px-3 py-2 font-medium ${below ? 'text-red-600' : 'text-green-600'}`}>
      {maNum.toFixed(2)}
    </td>
  )
}

function ScreenerRowView({ row, onRefreshRow, onRemove }: { row: ScreenerRow; onRefreshRow: (row: ScreenerRow) => void; onRemove: (symbol: string) => void }) {
  const [expanded, setExpanded] = useState(false)
  const [fetching, setFetching] = useState(false)

  const handleFetch = async () => {
    setFetching(true)
    try {
      const updated = await screenerApi.fetchOne(row.symbol)
      onRefreshRow(updated)
    } finally {
      setFetching(false)
    }
  }

  return (
    <>
      <tr className="border-t border-gray-100 hover:bg-gray-50">
        <td className="px-3 py-2">
          <button onClick={() => setExpanded(e => !e)} className="flex items-center gap-1 font-medium text-gray-800">
            <span style={{ transform: expanded ? 'rotate(0deg)' : 'rotate(-90deg)', display: 'inline-block', transition: 'transform 0.15s' }}>&#9660;</span>
            {row.symbol}
          </button>
        </td>
        <td className="px-3 py-2">{toNum(row.price) != null ? `$${toNum(row.price)!.toFixed(2)}` : '—'}</td>
        <td className={`px-3 py-2 font-medium ${(toNum(row.change_pct) ?? 0) < 0 ? 'text-red-600' : 'text-green-600'}`}>
          {toNum(row.change_pct) != null ? `${toNum(row.change_pct)!.toFixed(2)}%` : '—'}
        </td>
        <td className="px-3 py-2">{toNum(row.iv_percentile) != null ? `${toNum(row.iv_percentile)!.toFixed(0)}%` : '—'}</td>
        <td className="px-3 py-2">{toNum(row.rsi_14) != null ? toNum(row.rsi_14)!.toFixed(1) : '—'}</td>
        <td className="px-3 py-2">
          <span className={`px-2 py-0.5 rounded text-xs font-medium ${MACD_COLORS[row.macd_weekly_signal ?? 'neutral']}`}>
            {row.macd_weekly_signal ?? '—'}
          </span>
        </td>
        <MaCell price={row.price} ma={row.ma_20d} />
        <MaCell price={row.price} ma={row.ma_50d} />
        <MaCell price={row.price} ma={row.ma_100d} />
        <MaCell price={row.price} ma={row.ma_200d} />
        <td className="px-3 py-2 text-gray-600">{row.bollinger_position ? BB_LABELS[row.bollinger_position] ?? row.bollinger_position : '—'}</td>
        <td className="px-3 py-2 text-gray-400 text-xs">{timeAgo(row.last_fetched_at)}</td>
        <td className="px-3 py-2"><ScreenerCommentaryCell symbol={row.symbol} /></td>
        <td className="px-3 py-2 text-right space-x-2 whitespace-nowrap">
          <button onClick={handleFetch} disabled={fetching} className="text-xs text-blue-600 hover:underline disabled:text-gray-400">
            {fetching ? 'Fetching…' : 'Fetch'}
          </button>
          <button onClick={() => onRemove(row.symbol)} className="text-xs text-red-500 hover:underline">Remove</button>
        </td>
      </tr>
      {expanded && <ScreenerDetailRow row={row} colSpan={COLUMNS.length} />}
    </>
  )
}

export function ScreenerTable({ rows, onRefreshRow, onRemove }: Props) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead className="bg-gray-50">
          <tr>
            {COLUMNS.map(c => (
              <th key={c} className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={COLUMNS.length} className="px-3 py-6 text-center text-gray-400">No symbols tracked yet.</td></tr>
          )}
          {rows.map(row => (
            <ScreenerRowView key={row.id} row={row} onRefreshRow={onRefreshRow} onRemove={onRemove} />
          ))}
        </tbody>
      </table>
    </div>
  )
}
```

- [ ] **Step 4: Note on type-checking at this point**

`ScreenerTable.tsx` imports `./ScreenerCommentaryCell`, which doesn't exist until Task 13. Do **not** run `tsc --noEmit` yet — it will fail on that missing import. This is expected; Task 13 resolves it. Skip straight to commit.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Screener/timeAgo.ts frontend/src/components/Screener/ScreenerDetailRow.tsx frontend/src/components/Screener/ScreenerTable.tsx
git commit -m "feat(screener): add ScreenerTable and expandable detail row"
```

---

## Task 12: `AddSymbolForm`

**Files:**
- Create: `frontend/src/components/Screener/AddSymbolForm.tsx`

**Interfaces:**
- Consumes: `screenerApi.add` (Task 10), `ApiError` (`frontend/src/api/client.ts`).
- Produces: `AddSymbolForm` component, props `{ onAdded: (row: ScreenerRow) => void }` — consumed by `ScreenerPage` (Task 15).

- [ ] **Step 1: Create the component**

Create `frontend/src/components/Screener/AddSymbolForm.tsx`:

```tsx
import { useState, type FormEvent } from 'react'
import { screenerApi } from '../../api/screener'
import { ApiError } from '../../api/client'
import type { ScreenerRow } from '../../types'

interface Props {
  onAdded: (row: ScreenerRow) => void
}

export function AddSymbolForm({ onAdded }: Props) {
  const [symbol, setSymbol] = useState('')
  const [category, setCategory] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!symbol.trim()) return
    setLoading(true)
    setError(null)
    try {
      const row = await screenerApi.add({
        symbol: symbol.trim().toUpperCase(),
        category: category.trim() || undefined,
      })
      onAdded(row)
      setSymbol('')
      setCategory('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to add symbol')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex items-end gap-2 mb-4">
      <div>
        <label className="block text-xs text-gray-500 mb-1">Symbol</label>
        <input
          value={symbol}
          onChange={e => setSymbol(e.target.value)}
          placeholder="AAPL"
          className="border border-gray-300 rounded px-2 py-1 text-sm w-28"
        />
      </div>
      <div>
        <label className="block text-xs text-gray-500 mb-1">Category</label>
        <input
          value={category}
          onChange={e => setCategory(e.target.value)}
          placeholder="Watchlist"
          className="border border-gray-300 rounded px-2 py-1 text-sm w-40"
        />
      </div>
      <button
        type="submit"
        disabled={loading || !symbol.trim()}
        className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:bg-gray-300"
      >
        {loading ? 'Adding…' : 'Add Symbol'}
      </button>
      {error && <span className="text-red-500 text-xs">{error}</span>}
    </form>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/Screener/AddSymbolForm.tsx
git commit -m "feat(screener): add AddSymbolForm"
```

---

## Task 13: `ScreenerCommentaryCell` + `ScreenerCommentaryThread` (with edit)

**Files:**
- Create: `frontend/src/components/Screener/ScreenerCommentaryThread.tsx`
- Create: `frontend/src/components/Screener/ScreenerCommentaryCell.tsx`

**Interfaces:**
- Consumes: `screenerApi.commentary.*` (Task 10), `ScreenerCommentary` type (Task 10).
- Produces: `ScreenerCommentaryCell` component, props `{ symbol: string }` — this resolves the import `ScreenerTable.tsx` (Task 11) already has.

- [ ] **Step 1: Create `ScreenerCommentaryThread.tsx`**

Create `frontend/src/components/Screener/ScreenerCommentaryThread.tsx`:

```tsx
import { useState } from 'react'
import type { ScreenerCommentary } from '../../types'
import { screenerApi } from '../../api/screener'

interface Props {
  symbol: string
  entries: ScreenerCommentary[]
  onRefresh: () => void
}

function CommentaryEntry({ entry, onRefresh }: { entry: ScreenerCommentary; onRefresh: () => void }) {
  const [editing, setEditing] = useState(false)
  const [note, setNote] = useState(entry.note)
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    if (!note.trim()) return
    setSaving(true)
    try {
      await screenerApi.commentary.update(entry.id, { note: note.trim(), tags: entry.tags ?? undefined })
      setEditing(false)
      onRefresh()
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!confirm('Delete this note?')) return
    await screenerApi.commentary.remove(entry.id)
    onRefresh()
  }

  return (
    <div className="bg-gray-50 rounded p-3 text-sm">
      <div className="flex justify-between items-start">
        <span className="text-gray-400 text-xs">
          {entry.created_at.slice(0, 10)}{entry.updated_at ? ' (edited)' : ''}
        </span>
        <div className="space-x-2">
          {!editing && (
            <button onClick={() => setEditing(true)} className="text-blue-500 hover:text-blue-700 text-xs">Edit</button>
          )}
          <button onClick={handleDelete} className="text-red-400 hover:text-red-600 text-xs">×</button>
        </div>
      </div>
      {editing ? (
        <div className="mt-1 space-y-2">
          <textarea
            value={note}
            onChange={e => setNote(e.target.value)}
            rows={3}
            className="w-full border border-gray-300 rounded px-2 py-1 text-sm"
          />
          <div className="space-x-2">
            <button
              onClick={handleSave}
              disabled={saving}
              className="text-xs px-2 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:bg-gray-300"
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button
              onClick={() => { setEditing(false); setNote(entry.note) }}
              className="text-xs px-2 py-1 text-gray-500 hover:text-gray-700"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <p className="mt-1 text-gray-800 whitespace-pre-wrap">{entry.note}</p>
      )}
      {entry.tags && entry.tags.length > 0 && (
        <div className="flex gap-1 mt-1">
          {entry.tags.map(tag => (
            <span key={tag} className="px-1.5 py-0.5 bg-blue-100 text-blue-600 rounded text-xs">{tag}</span>
          ))}
        </div>
      )}
    </div>
  )
}

export function ScreenerCommentaryThread({ symbol, entries, onRefresh }: Props) {
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const handleAdd = async () => {
    if (!note.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      await screenerApi.commentary.add(symbol, { note: note.trim() })
      setNote('')
      onRefresh()
    } catch {
      setError('Failed to add note. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-gray-700">Commentary</h3>
      {error && <p className="text-red-500 text-xs">{error}</p>}
      <div className="space-y-2">
        <textarea
          value={note}
          onChange={e => setNote(e.target.value)}
          rows={2}
          placeholder="Add a note…"
          className="w-full border border-gray-300 rounded px-2 py-1 text-sm"
        />
        <button
          onClick={handleAdd}
          disabled={submitting || !note.trim()}
          className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:bg-gray-300"
        >
          {submitting ? 'Adding…' : 'Add Note'}
        </button>
      </div>
      <div className="space-y-3 mt-4">
        {entries.length === 0 && <p className="text-gray-400 text-sm">No notes yet.</p>}
        {entries.map(entry => (
          <CommentaryEntry key={entry.id} entry={entry} onRefresh={onRefresh} />
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Create `ScreenerCommentaryCell.tsx`**

Create `frontend/src/components/Screener/ScreenerCommentaryCell.tsx`:

```tsx
import { useCallback, useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import type { ScreenerCommentary } from '../../types'
import { screenerApi } from '../../api/screener'
import { ScreenerCommentaryThread } from './ScreenerCommentaryThread'

interface Props {
  symbol: string
}

export function ScreenerCommentaryCell({ symbol }: Props) {
  const [open, setOpen] = useState(false)
  const [entries, setEntries] = useState<ScreenerCommentary[]>([])
  const [loading, setLoading] = useState(true)

  const fetchEntries = useCallback(async () => {
    setLoading(true)
    try {
      const data = await screenerApi.commentary.list(symbol)
      setEntries(data)
    } finally {
      setLoading(false)
    }
  }, [symbol])

  useEffect(() => {
    fetchEntries()
  }, [fetchEntries])

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button className="flex items-center gap-1 text-gray-500 hover:text-blue-600">
          <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
            />
          </svg>
          <span className="text-xs font-medium">{loading ? '…' : entries.length}</span>
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40 z-40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-[560px] max-h-[80vh] bg-white rounded-lg shadow-xl flex flex-col">
          <div className="flex items-center justify-between px-5 py-4 border-b">
            <Dialog.Title className="text-sm font-semibold text-gray-800">Commentary — {symbol}</Dialog.Title>
            <Dialog.Description className="sr-only">Commentary entries for {symbol}</Dialog.Description>
            <Dialog.Close className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</Dialog.Close>
          </div>
          <div className="overflow-y-auto flex-1 px-5 py-4">
            <ScreenerCommentaryThread symbol={symbol} entries={entries} onRefresh={fetchEntries} />
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
```

- [ ] **Step 3: Type-check now that ScreenerTable's import resolves**

Run: `cd frontend && npx tsc --noEmit`
Expected: errors only about `ScreenerPage`/`SymbolLookup` not existing yet if anything references them (nothing does yet) — should pass cleanly for everything created so far. If `AddSymbolForm.tsx` and `ScreenerTable.tsx` are unused-but-valid files, `tsc --noEmit` still succeeds (unused *files* aren't flagged, only unused *locals* within a file).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Screener/ScreenerCommentaryThread.tsx frontend/src/components/Screener/ScreenerCommentaryCell.tsx
git commit -m "feat(screener): add commentary thread with inline edit support"
```

---

## Task 14: `SymbolLookup` (preview-before-add)

**Files:**
- Create: `frontend/src/components/Screener/SymbolLookup.tsx`

**Interfaces:**
- Consumes: `screenerApi.preview`, `screenerApi.add` (Task 10), `ScreenerPreview` type (Task 10).
- Produces: `SymbolLookup` component, props `{ onAdded: (row: ScreenerRow) => void }` — consumed by `ScreenerPage` (Task 15).

- [ ] **Step 1: Create the component**

Create `frontend/src/components/Screener/SymbolLookup.tsx`:

```tsx
import { useState } from 'react'
import { screenerApi } from '../../api/screener'
import { ApiError } from '../../api/client'
import type { ScreenerPreview, ScreenerRow } from '../../types'

interface Props {
  onAdded: (row: ScreenerRow) => void
}

export function SymbolLookup({ onAdded }: Props) {
  const [ticker, setTicker] = useState('')
  const [loading, setLoading] = useState(false)
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<ScreenerPreview | null>(null)

  const handleFetch = async () => {
    if (!ticker.trim()) return
    setLoading(true)
    setError(null)
    setPreview(null)
    try {
      const data = await screenerApi.preview(ticker.trim().toUpperCase())
      setPreview(data)
      if (data.fetch_status === 'error') {
        setError(data.fetch_error ?? 'Fetch failed')
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Lookup failed')
    } finally {
      setLoading(false)
    }
  }

  const handleAdd = async () => {
    if (!preview) return
    setAdding(true)
    setError(null)
    try {
      const row = await screenerApi.add({
        symbol: preview.symbol,
        precomputed: {
          sector: preview.sector,
          price: preview.price,
          prev_close: preview.prev_close,
          change_pct: preview.change_pct,
          iv_rank: preview.iv_rank,
          iv_percentile: preview.iv_percentile,
          rsi_14: preview.rsi_14,
          macd_weekly_signal: preview.macd_weekly_signal,
          macd_daily_signal: preview.macd_daily_signal,
          ma_20d: preview.ma_20d,
          ma_50d: preview.ma_50d,
          ma_100d: preview.ma_100d,
          ma_200d: preview.ma_200d,
          bollinger_upper: preview.bollinger_upper,
          bollinger_mid: preview.bollinger_mid,
          bollinger_lower: preview.bollinger_lower,
          bollinger_position: preview.bollinger_position,
          next_earnings_date: preview.next_earnings_date,
          volume_spikes: preview.volume_spikes,
          fetch_status: preview.fetch_status,
          fetch_error: preview.fetch_error,
        },
      })
      onAdded(row)
      setPreview(null)
      setTicker('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to add symbol')
    } finally {
      setAdding(false)
    }
  }

  return (
    <div className="mb-6 p-3 border border-gray-200 rounded bg-white">
      <div className="text-xs font-semibold text-gray-600 mb-2">Quick Lookup</div>
      <div className="flex items-end gap-2">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Symbol</label>
          <input
            value={ticker}
            onChange={e => setTicker(e.target.value)}
            placeholder="TSLA"
            className="border border-gray-300 rounded px-2 py-1 text-sm w-28"
          />
        </div>
        <button
          onClick={handleFetch}
          disabled={loading || !ticker.trim()}
          className="px-3 py-1.5 bg-gray-700 text-white text-sm rounded hover:bg-gray-800 disabled:bg-gray-300"
        >
          {loading ? 'Fetching…' : 'Fetch'}
        </button>
      </div>
      {error && <p className="text-red-500 text-xs mt-2">{error}</p>}
      {preview && preview.fetch_status !== 'error' && (
        <div className="mt-3 text-xs grid grid-cols-4 gap-x-4 gap-y-1 border-t border-gray-100 pt-2">
          <div><span className="text-gray-400">Price: </span>{preview.price ?? '—'}</div>
          <div><span className="text-gray-400">Change%: </span>{preview.change_pct ?? '—'}</div>
          <div><span className="text-gray-400">IV Pctl: </span>{preview.iv_percentile ?? '—'}</div>
          <div><span className="text-gray-400">RSI(d): </span>{preview.rsi_14 ?? '—'}</div>
          <div><span className="text-gray-400">MACD(w): </span>{preview.macd_weekly_signal ?? '—'}</div>
          <div><span className="text-gray-400">20ma: </span>{preview.ma_20d ?? '—'}</div>
          <div><span className="text-gray-400">50ma: </span>{preview.ma_50d ?? '—'}</div>
          <div><span className="text-gray-400">100ma: </span>{preview.ma_100d ?? '—'}</div>
          <div><span className="text-gray-400">200ma: </span>{preview.ma_200d ?? '—'}</div>
          <div><span className="text-gray-400">BB: </span>{preview.bollinger_position ?? '—'}</div>
          <div className="col-span-4 mt-2">
            {preview.already_tracked ? (
              <span className="text-gray-400 italic">Already tracked in the screener.</span>
            ) : (
              <button
                onClick={handleAdd}
                disabled={adding}
                className="px-3 py-1.5 bg-blue-600 text-white text-xs rounded hover:bg-blue-700 disabled:bg-gray-300"
              >
                {adding ? 'Adding…' : 'Add to Screener'}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Screener/SymbolLookup.tsx
git commit -m "feat(screener): add SymbolLookup preview-before-add flow"
```

---

## Task 15: `ScreenerPage` + route/nav wiring

**Files:**
- Create: `frontend/src/pages/ScreenerPage.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `screenerApi` (Task 10), `AddSymbolForm` (Task 12), `SymbolLookup` (Task 14), `ScreenerTable` (Task 11).
- Produces: page mounted at route `/screener`, nav item added.

- [ ] **Step 1: Create `ScreenerPage.tsx`**

Create `frontend/src/pages/ScreenerPage.tsx`:

```tsx
import { useCallback, useEffect, useRef, useState } from 'react'
import { screenerApi } from '../api/screener'
import type { ScreenerRow } from '../types'
import { AddSymbolForm } from '../components/Screener/AddSymbolForm'
import { SymbolLookup } from '../components/Screener/SymbolLookup'
import { ScreenerTable } from '../components/Screener/ScreenerTable'

export function ScreenerPage() {
  const [rows, setRows] = useState<ScreenerRow[]>([])
  const [loading, setLoading] = useState(true)
  const [fetchingAll, setFetchingAll] = useState(false)
  const [jobProgress, setJobProgress] = useState<{ completed: number; total: number } | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const loadRows = useCallback(async () => {
    setLoading(true)
    try {
      const data = await screenerApi.list()
      setRows(data)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadRows()
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [loadRows])

  const handleAdded = (row: ScreenerRow) => {
    setRows(prev =>
      [...prev.filter(r => r.symbol !== row.symbol), row].sort((a, b) => a.symbol.localeCompare(b.symbol))
    )
  }

  const handleRefreshRow = (row: ScreenerRow) => {
    setRows(prev => prev.map(r => (r.symbol === row.symbol ? row : r)))
  }

  const handleRemove = async (symbol: string) => {
    if (!confirm(`Remove ${symbol} from the screener?`)) return
    await screenerApi.remove(symbol)
    setRows(prev => prev.filter(r => r.symbol !== symbol))
  }

  const handleFetchAll = async () => {
    setFetchingAll(true)
    const job = await screenerApi.fetchAll()
    setJobProgress({ completed: job.completed, total: job.total })
    pollRef.current = setInterval(async () => {
      const status = await screenerApi.getJobStatus(job.job_id)
      setJobProgress({ completed: status.completed, total: status.total })
      if (status.status === 'done') {
        if (pollRef.current) clearInterval(pollRef.current)
        setFetchingAll(false)
        setJobProgress(null)
        loadRows()
      }
    }, 2000)
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-lg font-semibold text-gray-800">Screener</h1>
        <button
          onClick={handleFetchAll}
          disabled={fetchingAll || rows.length === 0}
          className="px-3 py-1.5 bg-gray-700 text-white text-sm rounded hover:bg-gray-800 disabled:bg-gray-300"
        >
          {fetchingAll ? `Fetching ${jobProgress?.completed ?? 0}/${jobProgress?.total ?? 0}…` : 'Fetch All'}
        </button>
      </div>
      <SymbolLookup onAdded={handleAdded} />
      <AddSymbolForm onAdded={handleAdded} />
      {loading ? (
        <p className="text-gray-400 text-sm">Loading…</p>
      ) : (
        <ScreenerTable rows={rows} onRefreshRow={handleRefreshRow} onRemove={handleRemove} />
      )}
    </div>
  )
}
```

- [ ] **Step 2: Wire the route and nav item in `App.tsx`**

In `frontend/src/App.tsx`, add the import:

```tsx
import { ScreenerPage } from './pages/ScreenerPage'
```

Add the nav item after the Scanner nav item:

```tsx
          <NavItem to="/scanner" label="Scanner" />
          <NavItem to="/screener" label="Screener" />
```

Add the route after the scanner route:

```tsx
            <Route path="/scanner" element={<ScannerPage />} />
            <Route path="/screener" element={<ScreenerPage />} />
```

- [ ] **Step 3: Type-check the whole frontend**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Manual verification via dev server**

Run: `cd backend && docker compose up -d` (ensure Postgres + backend are running with migration `010` applied — run `docker compose exec backend uv run alembic upgrade head` if needed), then `cd frontend && npm run dev`.

In the browser:
1. Navigate to `/screener` — page loads with an empty grid ("No symbols tracked yet.").
2. Use **Quick Lookup**: type a real ticker (e.g. `AAPL`), click **Fetch** — preview card renders with price/RSI/MACD/MA/BB values within a few seconds. Click **Add to Screener** — row appears in the grid immediately (no second fetch delay).
3. Preview the same already-added symbol again — confirm "Already tracked in the screener." replaces the Add button.
4. Use **Add Symbol** form with a different ticker + category — confirm it appears in the grid after the synchronous fetch completes.
5. Click a row's chevron to expand — confirm Bollinger/MACD-daily/earnings/volume-spike detail renders.
6. Click **Fetch All** — confirm the button shows progress (`Fetching N/M…`) and the grid refreshes with updated `last_fetched_at` ("just now") when done.
7. Click the commentary icon on a row — dialog opens; add a note, edit it (confirm "(edited)" appears), delete it.
8. Click **Remove** on a row — confirms and removes it from the grid.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ScreenerPage.tsx frontend/src/App.tsx
git commit -m "feat(screener): add ScreenerPage and wire /screener route"
```

---

## Self-Review Notes

- **Spec coverage:** all 6 numbered goals in the spec map to tasks — grid+columns (Task 11), persisted-table-backed load (Task 7 `GET /api/screener` + Task 15 page load), add via form and via lookup-preview (Tasks 12/14), on-demand single/bulk fetch (Tasks 7/8/11/15), expandable detail (Task 11's `ScreenerDetailRow`), commentary CRUD with edit (Tasks 3/9/13).
- **Type consistency verified:** `ScreenerFetchedFields.model_fields.keys()` (Task 4) is the single source of truth for `_SCREENER_FIELDS` in the router (Task 7/8) — no hand-duplicated field lists to drift. Frontend `ScreenerFetchedFields` (Task 10) field names match the backend schema field-for-field (checked against the `SymbolLookup.handleAdd` payload in Task 14, which enumerates every field). `fetch_screener_row`'s returned dict keys (Task 6) match `ScreenerFetchedFields` exactly (verified in Task 6's own test assertions).
- **No placeholders:** every step has runnable code, not descriptions of code.
