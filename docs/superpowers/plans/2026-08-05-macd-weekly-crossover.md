# Weekly MACD Crossover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect the most recent weekly MACD/signal crossover for a ticker (date, direction) and a numeric strength score reflecting how much of that crossover's peak momentum remains, then expose it both as new fields on `fetch_technicals` and as a standalone endpoint.

**Architecture:** A new private helper `_macd_weekly_crossover_state(close_w)` in `backend/app/services/technicals_fetcher.py` does the actual math (pure function, `pd.Series` in, `dict` out). `fetch_technicals()` calls it with the weekly close series it already fetches (no extra Schwab call). A new public function `fetch_macd_crossover(ticker)` calls it after an independent weekly-only Schwab fetch, for use by a new standalone endpoint. Both endpoints follow the existing thread-executor pattern in `backend/app/routers/market.py`.

**Tech Stack:** FastAPI, pandas (EWM-based MACD, already used elsewhere in this file), pytest + httpx `AsyncClient` for router tests, `unittest.mock.patch`/`MagicMock` for service-layer tests.

## Global Constraints

- 2-year weekly lookback (`period_type="year", period=2, frequency_type="weekly", frequency=1`) — matches the window `fetch_technicals` already uses for its weekly MACD signal. If no crossover exists in that window, all 5 new fields are `None` — this is accepted, not an error (per spec).
- Minimum 35 weekly bars required before attempting crossover detection (room for a stable 26-EMA + 9-EMA signal). Fewer bars → all 5 fields `None`.
- No DB/schema changes. No frontend changes. `RationaleCreate`/`RationaleResponse` are untouched.
- New fields: `macd_cross_date` (str `YYYY-MM-DD` or `None`), `macd_cross_direction` (`"bullish"`/`"bearish"`/`None`), `macd_weeks_since_cross` (int or `None`), `macd_strength_score` (float or `None`), `macd_trend` (`"expanding"`/`"holding_strong"`/`"squeezing"`/`"fading_near_flip"`/`None`).

---

### Task 1: `_macd_weekly_crossover_state` helper

**Files:**
- Modify: `backend/app/services/technicals_fetcher.py`
- Test: `backend/tests/test_technicals_fetcher.py`

**Interfaces:**
- Produces: `_macd_weekly_crossover_state(close_w: pd.Series) -> dict` with keys `macd_cross_date`, `macd_cross_direction`, `macd_weeks_since_cross`, `macd_strength_score`, `macd_trend` (all `None` if insufficient data or no crossover found).

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_technicals_fetcher.py` (near the other `_compute_macd_weekly` tests):

```python
from app.services.technicals_fetcher import _macd_weekly_crossover_state


def _make_weekly_close(values: list[float]) -> pd.Series:
    idx = pd.date_range(end=pd.Timestamp("2026-08-03", tz="UTC"), periods=len(values) + 1, freq="W")[-len(values):]
    return pd.Series(values, index=idx)


def test_macd_crossover_insufficient_data_returns_all_none():
    close = _make_weekly_close([100.0] * 10)
    result = _macd_weekly_crossover_state(close)
    assert result == {
        "macd_cross_date": None,
        "macd_cross_direction": None,
        "macd_weeks_since_cross": None,
        "macd_strength_score": None,
        "macd_trend": None,
    }


def test_macd_crossover_bullish_fading_near_flip():
    # 30 weeks falling, 25 weeks rising sharply (bullish crossover), 5 weeks pulling back (squeeze)
    down = [200.0 - i * 2.0 for i in range(30)]
    up = [down[-1] + i * 3.0 for i in range(1, 26)]
    flat = [up[-1] - i * 0.5 for i in range(1, 6)]
    close = _make_weekly_close(down + up + flat)

    result = _macd_weekly_crossover_state(close)

    assert result["macd_cross_date"] == "2026-01-25"
    assert result["macd_cross_direction"] == "bullish"
    assert result["macd_weeks_since_cross"] == 27
    assert result["macd_strength_score"] == 12.2
    assert result["macd_trend"] == "fading_near_flip"


def test_macd_crossover_bearish_fading_near_flip():
    # Mirror image of the bullish case: rising, then falling sharply (bearish crossover), then a small bounce
    up = [100.0 + i * 2.0 for i in range(30)]
    down = [up[-1] - i * 3.0 for i in range(1, 26)]
    bounce = [down[-1] + i * 0.5 for i in range(1, 6)]
    close = _make_weekly_close(up + down + bounce)

    result = _macd_weekly_crossover_state(close)

    assert result["macd_cross_date"] == "2026-01-25"
    assert result["macd_cross_direction"] == "bearish"
    assert result["macd_weeks_since_cross"] == 27
    assert result["macd_strength_score"] == 12.2
    assert result["macd_trend"] == "fading_near_flip"


def test_macd_crossover_squeezing():
    # Steady compounding growth (1% per week) - gap narrows to a mid-range score after the initial ramp
    close = _make_weekly_close([100.0 * (1.01 ** i) for i in range(60)])
    result = _macd_weekly_crossover_state(close)

    assert result["macd_cross_direction"] == "bullish"
    assert result["macd_strength_score"] == 42.8
    assert result["macd_trend"] == "squeezing"


def test_macd_crossover_holding_strong():
    close = _make_weekly_close([100.0 * (1.016 ** i) for i in range(60)])
    result = _macd_weekly_crossover_state(close)

    assert result["macd_strength_score"] == 75.5
    assert result["macd_trend"] == "holding_strong"


def test_macd_crossover_expanding_at_peak():
    # Strong compounding growth - the gap is still widening at the very last bar
    close = _make_weekly_close([100.0 * (1.02 ** i) for i in range(60)])
    result = _macd_weekly_crossover_state(close)

    assert result["macd_strength_score"] == 100.0
    assert result["macd_trend"] == "expanding"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_technicals_fetcher.py -k macd_crossover -v`
Expected: FAIL with `ImportError: cannot import name '_macd_weekly_crossover_state'`

- [ ] **Step 3: Implement the helper**

Add to `backend/app/services/technicals_fetcher.py`, above `fetch_technicals`:

```python
_NONE_CROSSOVER_FIELDS: dict = {
    "macd_cross_date": None,
    "macd_cross_direction": None,
    "macd_weeks_since_cross": None,
    "macd_strength_score": None,
    "macd_trend": None,
}


def _macd_weekly_crossover_state(close_w: pd.Series) -> dict:
    if len(close_w) < 35:
        return dict(_NONE_CROSSOVER_FIELDS)

    exp1 = close_w.ewm(span=12, adjust=False).mean()
    exp2 = close_w.ewm(span=26, adjust=False).mean()
    macd_line = exp1 - exp2
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    diff = macd_line - signal_line

    sign = diff.apply(lambda x: 1 if x > 0 else -1)
    crossovers = sign[sign != sign.shift(1)].iloc[1:]
    if crossovers.empty:
        return dict(_NONE_CROSSOVER_FIELDS)

    last_cross_date = crossovers.index[-1]
    direction = "bullish" if crossovers.iloc[-1] == 1 else "bearish"

    since = diff[diff.index >= last_cross_date]
    weeks_since = len(since) - 1

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
        "macd_cross_date": str(last_cross_date.date()),
        "macd_cross_direction": direction,
        "macd_weeks_since_cross": weeks_since,
        "macd_strength_score": score,
        "macd_trend": trend,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_technicals_fetcher.py -k macd_crossover -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/technicals_fetcher.py backend/tests/test_technicals_fetcher.py
git commit -m "feat(technicals): add weekly MACD crossover detection + strength score helper"
```

---

### Task 2: Wire crossover fields into `fetch_technicals`

**Files:**
- Modify: `backend/app/services/technicals_fetcher.py`
- Test: `backend/tests/test_technicals_fetcher.py`

**Interfaces:**
- Consumes: `_macd_weekly_crossover_state(close_w: pd.Series) -> dict` from Task 1.
- Produces: `fetch_technicals(ticker)`'s returned dict now also contains the 5 crossover fields on the `fetch_status == "ok"` path.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_technicals_fetcher.py`, in the `fetch_technicals` integration section:

```python
def test_fetch_technicals_includes_macd_crossover_fields():
    mock_client = _mock_client(_make_daily_df(200), _make_weekly_df(60))
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client), \
         patch("yfinance.Ticker") as mock_ticker:
        mock_ticker.return_value.calendar = {}
        result = fetch_technicals("AAPL")

    assert result["fetch_status"] == "ok"
    assert "macd_cross_date" in result
    assert "macd_cross_direction" in result
    assert "macd_weeks_since_cross" in result
    assert "macd_strength_score" in result
    assert "macd_trend" in result
```

Note: `_make_weekly_df(60)` is a monotonic step series (see existing helper at the top of this file), so the crossover fields will most likely be non-`None` here, but this test only asserts the keys are present — the exact values are already covered by Task 1's dedicated unit tests.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_technicals_fetcher.py::test_fetch_technicals_includes_macd_crossover_fields -v`
Expected: FAIL — `KeyError` / `assert "macd_cross_date" in result` fails because the keys don't exist yet

- [ ] **Step 3: Wire the helper into `fetch_technicals`**

In `backend/app/services/technicals_fetcher.py`, `fetch_technicals()` already has this line:

```python
        macd = _compute_macd_weekly(close_w)
```

Add immediately after it:

```python
        crossover = _macd_weekly_crossover_state(close_w)
```

Then in the `result = {...}` dict a few lines below, add the crossover fields (spread them in alongside the existing keys):

```python
        result = {
            "macd_signal": macd["macd_signal"],
            "macd_notes": macd["macd_notes"],
            **crossover,
            "rsi_14": rsi_14,
            ...
```

(Keep every existing key exactly as-is — this only adds `**crossover` into the dict literal.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_technicals_fetcher.py -v`
Expected: all tests pass (the new one plus all pre-existing ones in this file)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/technicals_fetcher.py backend/tests/test_technicals_fetcher.py
git commit -m "feat(technicals): merge MACD crossover fields into fetch_technicals response"
```

---

### Task 3: Standalone `fetch_macd_crossover(ticker)` function

**Files:**
- Modify: `backend/app/services/technicals_fetcher.py`
- Test: `backend/tests/test_technicals_fetcher.py`

**Interfaces:**
- Consumes: `_macd_weekly_crossover_state` (Task 1), `_NONE_CROSSOVER_FIELDS` (Task 1), `get_schwab_client`/`SchwabAPIError` from `app.services.schwab_client` (already imported in this file).
- Produces: `fetch_macd_crossover(ticker: str) -> dict` — returns the 5 crossover fields plus `fetch_status`/`fetch_error`. Raises `ValueError` if there is no weekly data at all for the ticker (caller/router turns this into a 404).

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_technicals_fetcher.py`:

```python
from app.services.technicals_fetcher import fetch_macd_crossover


def test_fetch_macd_crossover_success():
    mock_client = MagicMock()
    mock_client.get_price_history.return_value = _make_weekly_df(60)
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        result = fetch_macd_crossover("AAPL")

    assert result["fetch_status"] == "ok"
    assert result["fetch_error"] is None
    mock_client.get_price_history.assert_called_once_with("AAPL", "year", 2, "weekly", 1)


def test_fetch_macd_crossover_no_weekly_data_raises_value_error():
    mock_client = MagicMock()
    mock_client.get_price_history.return_value = pd.DataFrame()
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        with pytest.raises(ValueError):
            fetch_macd_crossover("INVALID")


def test_fetch_macd_crossover_schwab_error_returns_error_status():
    from app.services.schwab_client import SchwabAPIError
    mock_client = MagicMock()
    mock_client.get_price_history.side_effect = SchwabAPIError("network error")
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        result = fetch_macd_crossover("AAPL")

    assert result["fetch_status"] == "error"
    assert "network error" in result["fetch_error"]
    assert result["macd_cross_date"] is None


def test_fetch_macd_crossover_insufficient_history_returns_ok_with_none_fields():
    mock_client = MagicMock()
    mock_client.get_price_history.return_value = _make_weekly_df(10)
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        result = fetch_macd_crossover("AAPL")

    assert result["fetch_status"] == "ok"
    assert result["macd_cross_date"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_technicals_fetcher.py -k fetch_macd_crossover -v`
Expected: FAIL with `ImportError: cannot import name 'fetch_macd_crossover'`

- [ ] **Step 3: Implement `fetch_macd_crossover`**

Add to `backend/app/services/technicals_fetcher.py`, after `fetch_technicals`:

```python
def fetch_macd_crossover(ticker: str) -> dict:
    try:
        client = get_schwab_client()
        df_w = client.get_price_history(ticker, "year", 2, "weekly", 1)
    except SchwabAPIError as exc:
        return {**_NONE_CROSSOVER_FIELDS, "fetch_status": "error", "fetch_error": str(exc)}

    if df_w is None or df_w.empty:
        raise ValueError(f"No weekly data for {ticker}")

    close_w = df_w["Close"].dropna()
    result = _macd_weekly_crossover_state(close_w)
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
git commit -m "feat(technicals): add standalone fetch_macd_crossover service function"
```

---

### Task 4: `GET /api/market/macd-crossover/{ticker}` endpoint

**Files:**
- Modify: `backend/app/routers/market.py`
- Test: `backend/tests/test_market_technicals.py`

**Interfaces:**
- Consumes: `fetch_macd_crossover(ticker: str) -> dict` from Task 3, imported the same way `fetch_technicals` already is in `market.py`.
- Produces: `GET /api/market/macd-crossover/{ticker}` — 200 with the crossover dict on success (including `fetch_status: "error"` sub-cases), 404 if the ticker has no weekly data at all.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_market_technicals.py`:

```python
MOCK_CROSSOVER = {
    "macd_cross_date": "2026-04-27",
    "macd_cross_direction": "bullish",
    "macd_weeks_since_cross": 14,
    "macd_strength_score": 19.1,
    "macd_trend": "fading_near_flip",
    "fetch_status": "ok",
    "fetch_error": None,
}


async def test_get_macd_crossover_success(client: AsyncClient):
    with patch("app.routers.market.fetch_macd_crossover", return_value=MOCK_CROSSOVER):
        response = await client.get("/api/market/macd-crossover/AAPL")
    assert response.status_code == 200
    data = response.json()
    assert data["macd_cross_direction"] == "bullish"
    assert data["macd_strength_score"] == 19.1


async def test_get_macd_crossover_no_data_returns_404(client: AsyncClient):
    with patch("app.routers.market.fetch_macd_crossover", side_effect=ValueError("No weekly data for INVALID")):
        response = await client.get("/api/market/macd-crossover/INVALID")
    assert response.status_code == 404


async def test_get_macd_crossover_ticker_uppercased(client: AsyncClient):
    with patch("app.routers.market.fetch_macd_crossover", return_value=MOCK_CROSSOVER) as mock_fn:
        await client.get("/api/market/macd-crossover/aapl")
    mock_fn.assert_called_once_with("AAPL")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_market_technicals.py -k macd_crossover -v`
Expected: FAIL with 404 for all three (route doesn't exist yet) / import error if `fetch_macd_crossover` isn't patchable on `app.routers.market`

- [ ] **Step 3: Add the endpoint**

In `backend/app/routers/market.py`, update the import line:

```python
from app.services.technicals_fetcher import fetch_technicals, fetch_macd_crossover
```

Add the new endpoint after `get_technicals`:

```python
@router.get("/macd-crossover/{ticker}")
async def get_macd_crossover(ticker: str):
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, fetch_macd_crossover, ticker.upper())
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
git commit -m "feat(technicals): add GET /api/market/macd-crossover/{ticker} endpoint"
```

---

### Task 5: Manual smoke test against live Schwab data

**Files:** none (verification only)

- [ ] **Step 1: Start the backend dev server**

Run: `cd backend && source venv/bin/activate && uvicorn app.main:app --reload --port 8000` (or whatever command `context/_project.md` documents for local dev — check there if this differs)

- [ ] **Step 2: Hit both endpoints for AAPL**

Run: `curl -s http://localhost:8000/api/market/macd-crossover/AAPL | python3 -m json.tool`
Expected: 200 response with `macd_cross_date`, `macd_cross_direction`, `macd_weeks_since_cross`, `macd_strength_score`, `macd_trend`, `fetch_status: "ok"`. Sanity-check `macd_cross_direction` is `"bullish"` or `"bearish"` and `macd_strength_score` is between 0 and 100.

Run: `curl -s http://localhost:8000/api/market/technicals/AAPL | python3 -m json.tool`
Expected: 200 response containing both the original 19 fields (`rsi_14`, `ma_200d`, etc.) and the 5 new crossover fields, with matching values to the standalone endpoint's output for the same ticker.

- [ ] **Step 3: Check a 404 case**

Run: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/market/macd-crossover/ZZZZZINVALID`
Expected: `404` (or the ticker legitimately has no weekly history — either way, confirm it's not a 500)

- [ ] **Step 4: Stop the dev server**

No commit for this task — it's manual verification only.
