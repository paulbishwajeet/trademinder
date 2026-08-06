# RSI/RSI-MA Crossover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect the most recent crossover between the daily RSI-14 line and a 14-period moving average of RSI itself, with a peak-based strength score (same shape as the existing MACD crossover work), plus the exact current RSI-14 value — exposed on `fetch_technicals` and via a new standalone endpoint.

**Architecture:** A new, fully self-contained function `_rsi_crossover_state(close: pd.Series) -> dict` in `backend/app/services/technicals_fetcher.py` computes the full RSI-14 series (not just the latest value), a 14-period SMA of that series, and detects the last sign flip between them — independently implemented, not sharing code with `_macd_crossover_state`. `fetch_technicals` calls it with the `close_d` series it already fetches. A new public function `fetch_rsi_signal(ticker)` calls it after an independent daily-only Schwab fetch, for a new standalone endpoint.

**Tech Stack:** Same as the MACD crossover work — FastAPI, pandas (Wilder's-smoothing RSI, same math as the existing single-value `_compute_rsi_14` in `price_fetcher.py`, but returning the full series), pytest + httpx `AsyncClient`, `unittest.mock`.

## Global Constraints

- **Do not refactor `_macd_crossover_state`.** `_rsi_crossover_state` is a fully independent function — some duplication of the sign-flip/peak/strength-score/trend logic is accepted, per explicit direction during brainstorming.
- Daily interval only — no weekly RSI crossover.
- No frontend changes.
- No extra Schwab call added to `fetch_technicals` — RSI crossover reuses the `close_d` series it already fetches.
- `rsi_14`/`rsi_result` (the existing single-value fields in `fetch_technicals`, computed via `_compute_rsi_14`) are unchanged — the new fields are additive and use a `rsi_` prefix that doesn't collide with them (`rsi_ma_14`, `rsi_cross_date`, `rsi_cross_direction`, `rsi_periods_since_cross`, `rsi_strength_score`, `rsi_trend`).
- Validated against live AAPL data during brainstorming: RSI-14 = 44.68 (matches the existing `_compute_rsi_14` output exactly), RSI-MA-14 = 60.73, last crossover 2026-07-30 bearish, 3 days ago, strength score 72.6 ("holding_strong").

---

### Task 1: `_rsi_crossover_state` helper

**Files:**
- Modify: `backend/app/services/technicals_fetcher.py`
- Modify: `backend/tests/test_technicals_fetcher.py`

**Interfaces:**
- Produces: `_rsi_crossover_state(close: pd.Series) -> dict` with keys `rsi_14`, `rsi_ma_14`, `cross_date`, `cross_direction`, `periods_since_cross`, `strength_score`, `trend`. `rsi_14`/`rsi_ma_14` are `None` if fewer than 15 bars are available; the 5 crossover fields are `None` whenever there are fewer than 35 valid RSI-vs-RSI-MA diff bars, even if `rsi_14`/`rsi_ma_14` themselves are available.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_technicals_fetcher.py` (near the other crossover tests):

```python
# --- unit tests for _rsi_crossover_state ---

from app.services.technicals_fetcher import _rsi_crossover_state


def _make_daily_close(values: list[float]) -> pd.Series:
    idx = pd.date_range(end=pd.Timestamp("2026-08-03", tz="UTC"), periods=len(values) + 1, freq="B")[-len(values):]
    return pd.Series(values, index=idx)


def test_rsi_crossover_insufficient_for_rsi_returns_all_none():
    close = _make_daily_close([100.0] * 10)
    result = _rsi_crossover_state(close)
    assert result == {
        "rsi_14": None,
        "rsi_ma_14": None,
        "cross_date": None,
        "cross_direction": None,
        "periods_since_cross": None,
        "strength_score": None,
        "trend": None,
    }


def test_rsi_crossover_enough_for_rsi_not_for_crossover():
    import math
    close = _make_daily_close([100.0 + 5 * math.sin(i / 2) for i in range(40)])
    result = _rsi_crossover_state(close)

    assert result["rsi_14"] == 61.6
    assert result["rsi_ma_14"] == 57.23
    assert result["cross_date"] is None
    assert result["cross_direction"] is None
    assert result["strength_score"] is None
    assert result["trend"] is None


def test_rsi_crossover_bearish_fading_near_flip():
    import math
    close = _make_daily_close([100.0 + 10 * math.sin(i / 6) * math.exp(-i / 300) + i * 0.02 for i in range(145)])
    result = _rsi_crossover_state(close)

    assert result["rsi_14"] == 28.17
    assert result["rsi_ma_14"] == 28.24
    assert result["cross_date"] == "2026-07-08"
    assert result["cross_direction"] == "bearish"
    assert result["periods_since_cross"] == 18
    assert result["strength_score"] == 0.3
    assert result["trend"] == "fading_near_flip"


def test_rsi_crossover_bearish_squeezing():
    import math
    close = _make_daily_close([100.0 + 10 * math.sin(i / 6) * math.exp(-i / 300) + i * 0.02 for i in range(140)])
    result = _rsi_crossover_state(close)

    assert result["cross_direction"] == "bearish"
    assert result["periods_since_cross"] == 13
    assert result["strength_score"] == 64.8
    assert result["trend"] == "squeezing"


def test_rsi_crossover_bullish_holding_strong():
    import math
    close = _make_daily_close([100.0 + 10 * math.sin(i / 6) * math.exp(-i / 300) + i * 0.02 for i in range(155)])
    result = _rsi_crossover_state(close)

    assert result["cross_direction"] == "bullish"
    assert result["periods_since_cross"] == 9
    assert result["strength_score"] == 94.4
    assert result["trend"] == "holding_strong"


def test_rsi_crossover_bullish_expanding():
    import math
    close = _make_daily_close([100.0 + 10 * math.sin(i / 6) * math.exp(-i / 300) + i * 0.02 for i in range(150)])
    result = _rsi_crossover_state(close)

    assert result["cross_direction"] == "bullish"
    assert result["periods_since_cross"] == 4
    assert result["strength_score"] == 100.0
    assert result["trend"] == "expanding"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_technicals_fetcher.py -k rsi_crossover -v`
Expected: FAIL with `ImportError: cannot import name '_rsi_crossover_state'`

- [ ] **Step 3: Implement the helper**

Add to `backend/app/services/technicals_fetcher.py`, above `_bollinger_position` (after `_macd_crossover_state`):

```python
_NONE_RSI_CROSSOVER_FIELDS: dict = {
    "rsi_14": None,
    "rsi_ma_14": None,
    "cross_date": None,
    "cross_direction": None,
    "periods_since_cross": None,
    "strength_score": None,
    "trend": None,
}


def _rsi_crossover_state(close: pd.Series) -> dict:
    if len(close) < 15:
        return dict(_NONE_RSI_CROSSOVER_FIELDS)

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = (100 - (100 / (1 + rs))).fillna(100)

    rsi_14 = round(float(rsi.iloc[-1]), 2)
    rsi_ma = rsi.rolling(14).mean()
    rsi_ma_14 = round(float(rsi_ma.iloc[-1]), 2) if not pd.isna(rsi_ma.iloc[-1]) else None

    diff = (rsi - rsi_ma).dropna()
    if len(diff) < 35:
        return {**_NONE_RSI_CROSSOVER_FIELDS, "rsi_14": rsi_14, "rsi_ma_14": rsi_ma_14}

    sign = diff.apply(lambda x: 1 if x > 0 else -1)
    crossovers = sign[sign != sign.shift(1)].iloc[1:]
    if crossovers.empty:
        return {**_NONE_RSI_CROSSOVER_FIELDS, "rsi_14": rsi_14, "rsi_ma_14": rsi_ma_14}

    last_cross_date = crossovers.index[-1]
    direction = "bullish" if crossovers.iloc[-1] == 1 else "bearish"

    since = diff[diff.index >= last_cross_date]
    periods_since = len(since) - 1

    if direction == "bullish":
        peak_val = float(since.max())
        peak_date = since.idxmax()
    else:
        peak_val = float(since.min())
        peak_date = since.idxmin()

    current = float(since.iloc[-1])
    score = round((current / peak_val) * 100, 1) if peak_val != 0 else 0.0

    if peak_date == since.index[-1]:
        trend = "expanding"
    elif score >= 70:
        trend = "holding_strong"
    elif score >= 30:
        trend = "squeezing"
    else:
        trend = "fading_near_flip"

    return {
        "rsi_14": rsi_14,
        "rsi_ma_14": rsi_ma_14,
        "cross_date": str(last_cross_date.date()),
        "cross_direction": direction,
        "periods_since_cross": periods_since,
        "strength_score": score,
        "trend": trend,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_technicals_fetcher.py -k rsi_crossover -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/technicals_fetcher.py backend/tests/test_technicals_fetcher.py
git commit -m "feat(technicals): add RSI/RSI-MA crossover detection + strength score helper"
```

---

### Task 2: Merge RSI crossover fields into `fetch_technicals`

**Files:**
- Modify: `backend/app/services/technicals_fetcher.py`
- Modify: `backend/tests/test_technicals_fetcher.py`

**Interfaces:**
- Consumes: `_rsi_crossover_state(close: pd.Series) -> dict` from Task 1.
- Produces: `fetch_technicals(ticker)`'s response gains `rsi_ma_14`, `rsi_cross_date`, `rsi_cross_direction`, `rsi_periods_since_cross`, `rsi_strength_score`, `rsi_trend`. The existing `rsi_14`/`rsi_result` fields (from `_compute_rsi_14`) are untouched — `_rsi_crossover_state`'s own `rsi_14` value is not merged in, to avoid a redundant/confusing second source for the same number.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_technicals_fetcher.py`, near `test_fetch_technicals_includes_macd_crossover_fields`:

```python
def test_fetch_technicals_includes_rsi_crossover_fields():
    mock_client = _mock_client(_make_daily_df(200), _make_weekly_df(60))
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client), \
         patch("yfinance.Ticker") as mock_ticker:
        mock_ticker.return_value.calendar = {}
        result = fetch_technicals("AAPL")

    assert result["fetch_status"] == "ok"
    assert result["rsi_14"] is not None
    assert "rsi_ma_14" in result
    assert "rsi_cross_date" in result
    assert "rsi_cross_direction" in result
    assert "rsi_periods_since_cross" in result
    assert "rsi_strength_score" in result
    assert "rsi_trend" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_technicals_fetcher.py::test_fetch_technicals_includes_rsi_crossover_fields -v`
Expected: FAIL — `assert "rsi_ma_14" in result` fails, the key doesn't exist yet

- [ ] **Step 3: Wire the helper into `fetch_technicals`**

In `backend/app/services/technicals_fetcher.py`, `fetch_technicals()` currently has:

```python
        macd = _compute_macd_weekly(close_w)
        weekly_crossover = _macd_crossover_state(close_w)
        daily_crossover = _macd_crossover_state(close_d)
        sentiment = _infer_sentiment(macd["macd_signal"], price, ma_50d, rsi_14)
        next_earnings = _get_next_earnings(ticker)

        result = {
            "macd_signal": macd["macd_signal"],
            "macd_notes": macd["macd_notes"],
            **{f"macd_weekly_{k}": v for k, v in weekly_crossover.items()},
            **{f"macd_daily_{k}": v for k, v in daily_crossover.items()},
            "rsi_14": rsi_14,
            "rsi_result": rsi_result,
```

Replace with:

```python
        macd = _compute_macd_weekly(close_w)
        weekly_crossover = _macd_crossover_state(close_w)
        daily_crossover = _macd_crossover_state(close_d)
        rsi_crossover = _rsi_crossover_state(close_d)
        sentiment = _infer_sentiment(macd["macd_signal"], price, ma_50d, rsi_14)
        next_earnings = _get_next_earnings(ticker)

        result = {
            "macd_signal": macd["macd_signal"],
            "macd_notes": macd["macd_notes"],
            **{f"macd_weekly_{k}": v for k, v in weekly_crossover.items()},
            **{f"macd_daily_{k}": v for k, v in daily_crossover.items()},
            "rsi_14": rsi_14,
            "rsi_result": rsi_result,
            "rsi_ma_14": rsi_crossover["rsi_ma_14"],
            "rsi_cross_date": rsi_crossover["cross_date"],
            "rsi_cross_direction": rsi_crossover["cross_direction"],
            "rsi_periods_since_cross": rsi_crossover["periods_since_cross"],
            "rsi_strength_score": rsi_crossover["strength_score"],
            "rsi_trend": rsi_crossover["trend"],
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_technicals_fetcher.py -v`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/technicals_fetcher.py backend/tests/test_technicals_fetcher.py
git commit -m "feat(technicals): merge RSI crossover fields into fetch_technicals response"
```

---

### Task 3: Standalone `fetch_rsi_signal(ticker)` function

**Files:**
- Modify: `backend/app/services/technicals_fetcher.py`
- Modify: `backend/tests/test_technicals_fetcher.py`

**Interfaces:**
- Consumes: `_rsi_crossover_state`, `_NONE_RSI_CROSSOVER_FIELDS` (Task 1).
- Produces: `fetch_rsi_signal(ticker: str) -> dict` — flat response with `rsi_14`, `rsi_ma_14`, `cross_date`, `cross_direction`, `periods_since_cross`, `strength_score`, `trend`, `fetch_status`, `fetch_error`. Raises `ValueError` if there's no daily data at all for the ticker.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_technicals_fetcher.py`:

```python
# --- fetch_rsi_signal (standalone) ---

from app.services.technicals_fetcher import fetch_rsi_signal


def test_fetch_rsi_signal_success():
    mock_client = MagicMock()
    mock_client.get_price_history.return_value = _make_daily_df(200)
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        result = fetch_rsi_signal("AAPL")

    assert result["fetch_status"] == "ok"
    assert result["fetch_error"] is None
    assert result["rsi_14"] is not None
    mock_client.get_price_history.assert_called_once_with("AAPL", "year", 1, "daily", 1)


def test_fetch_rsi_signal_no_data_raises_value_error():
    mock_client = MagicMock()
    mock_client.get_price_history.return_value = pd.DataFrame()
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        with pytest.raises(ValueError):
            fetch_rsi_signal("INVALID")


def test_fetch_rsi_signal_schwab_error_returns_error_status():
    from app.services.schwab_client import SchwabAPIError
    mock_client = MagicMock()
    mock_client.get_price_history.side_effect = SchwabAPIError("network error")
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        result = fetch_rsi_signal("AAPL")

    assert result["fetch_status"] == "error"
    assert "network error" in result["fetch_error"]
    assert result["rsi_14"] is None


def test_fetch_rsi_signal_insufficient_history_returns_ok_with_none_crossover():
    mock_client = MagicMock()
    mock_client.get_price_history.return_value = _make_daily_df(10)
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        result = fetch_rsi_signal("AAPL")

    assert result["fetch_status"] == "ok"
    assert result["rsi_14"] is None
    assert result["cross_date"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_technicals_fetcher.py -k fetch_rsi_signal -v`
Expected: FAIL with `ImportError: cannot import name 'fetch_rsi_signal'`

- [ ] **Step 3: Implement `fetch_rsi_signal`**

Add to `backend/app/services/technicals_fetcher.py`, after `fetch_macd_crossover`:

```python
def fetch_rsi_signal(ticker: str) -> dict:
    try:
        client = get_schwab_client()
        df_d = client.get_price_history(ticker, "year", 1, "daily", 1)
    except SchwabAPIError as exc:
        return {**_NONE_RSI_CROSSOVER_FIELDS, "fetch_status": "error", "fetch_error": str(exc)}

    if df_d is None or df_d.empty:
        raise ValueError(f"No daily data for {ticker}")

    close_d = df_d["Close"].dropna()
    result = _rsi_crossover_state(close_d)
    result["fetch_status"] = "ok"
    result["fetch_error"] = None
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_technicals_fetcher.py -v`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/technicals_fetcher.py backend/tests/test_technicals_fetcher.py
git commit -m "feat(technicals): add standalone fetch_rsi_signal service function"
```

---

### Task 4: `GET /api/market/rsi-crossover/{ticker}` endpoint

**Files:**
- Modify: `backend/app/routers/market.py`
- Modify: `backend/tests/test_market_technicals.py`

**Interfaces:**
- Consumes: `fetch_rsi_signal(ticker: str) -> dict` from Task 3.
- Produces: `GET /api/market/rsi-crossover/{ticker}` — 200 with the flat RSI crossover dict, 404 if no daily data at all.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_market_technicals.py`:

```python
MOCK_RSI_SIGNAL = {
    "rsi_14": 44.68,
    "rsi_ma_14": 60.73,
    "cross_date": "2026-07-30",
    "cross_direction": "bearish",
    "periods_since_cross": 3,
    "strength_score": 72.6,
    "trend": "holding_strong",
    "fetch_status": "ok",
    "fetch_error": None,
}


async def test_get_rsi_crossover_success(client: AsyncClient):
    with patch("app.routers.market.fetch_rsi_signal", return_value=MOCK_RSI_SIGNAL):
        response = await client.get("/api/market/rsi-crossover/AAPL")
    assert response.status_code == 200
    data = response.json()
    assert data["rsi_14"] == 44.68
    assert data["cross_direction"] == "bearish"
    assert data["strength_score"] == 72.6


async def test_get_rsi_crossover_no_data_returns_404(client: AsyncClient):
    with patch("app.routers.market.fetch_rsi_signal", side_effect=ValueError("No daily data for INVALID")):
        response = await client.get("/api/market/rsi-crossover/INVALID")
    assert response.status_code == 404


async def test_get_rsi_crossover_ticker_uppercased(client: AsyncClient):
    with patch("app.routers.market.fetch_rsi_signal", return_value=MOCK_RSI_SIGNAL) as mock_fn:
        await client.get("/api/market/rsi-crossover/aapl")
    mock_fn.assert_called_once_with("AAPL")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_market_technicals.py -k rsi_crossover -v`
Expected: FAIL — 404/`AttributeError` since the route and the patchable name don't exist yet

- [ ] **Step 3: Add the endpoint**

In `backend/app/routers/market.py`, update the import line:

```python
from app.services.technicals_fetcher import fetch_technicals, fetch_macd_crossover, fetch_rsi_signal
```

Add the new endpoint after `get_macd_crossover`:

```python
@router.get("/rsi-crossover/{ticker}")
async def get_rsi_crossover(ticker: str):
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, fetch_rsi_signal, ticker.upper())
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_market_technicals.py -v`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/market.py backend/tests/test_market_technicals.py
git commit -m "feat(technicals): add GET /api/market/rsi-crossover/{ticker} endpoint"
```

---

### Task 5: Manual smoke test against live Schwab data

**Files:** none (verification only)

- [ ] **Step 1: Confirm the dev server is running (it auto-reloads on file changes)**

Run: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5431/docs`
Expected: `200`. If not running: `cd backend && source venv/bin/activate && uvicorn app.main:app --reload --port 5431`

- [ ] **Step 2: Hit both endpoints for AAPL**

Run: `curl -s http://localhost:5431/api/market/rsi-crossover/AAPL | python3 -m json.tool`
Expected: 200 with `rsi_14`, `rsi_ma_14`, `cross_date`, `cross_direction`, `periods_since_cross`, `strength_score`, `trend`, `fetch_status: "ok"`.

Run: `curl -s http://localhost:5431/api/market/technicals/AAPL | python3 -m json.tool`
Expected: 200 containing the existing `rsi_14`/`rsi_result` plus the 6 new `rsi_ma_14`/`rsi_cross_*`/`rsi_periods_since_cross`/`rsi_strength_score`/`rsi_trend` fields, matching the standalone endpoint's values for the same ticker (`rsi_14` in both responses should match exactly).

- [ ] **Step 3: Check a 404 case**

Run: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5431/api/market/rsi-crossover/ZZZZZINVALID`
Expected: `404`

No commit for this task — manual verification only.
