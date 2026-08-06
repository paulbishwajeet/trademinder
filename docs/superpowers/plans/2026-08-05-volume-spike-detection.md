# Volume Spike Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect days in the last 10 trading days where daily volume was at least 2x its trailing 20-day average, and expose the list of spike days on `fetch_technicals` and via a standalone endpoint.

**Architecture:** A new pure function `_detect_volume_spikes(volume: pd.Series, ...) -> list[dict]` in `backend/app/services/technicals_fetcher.py` scans the volume series and returns matching days. `fetch_technicals` calls it with the `Volume` column of the daily price history it already fetches (currently only `Close` is kept — this adds keeping `Volume` too). A new public function `fetch_volume_spikes(ticker)` calls it after an independent daily-only Schwab fetch, for a new standalone endpoint.

**Tech Stack:** Same as the MACD/RSI crossover work — FastAPI, pandas, pytest + httpx `AsyncClient`, `unittest.mock`.

## Global Constraints

- Constants, not query parameters: `lookback_days = 10`, `baseline_days = 20`, `threshold_multiple = 2.0`.
- Daily interval only — no weekly volume spike detection.
- No frontend changes.
- No extra Schwab call added to `fetch_technicals` — reuses the daily `df_d` it already fetches, just keeps the `Volume` column alongside `Close`.
- `_detect_volume_spikes` returns `[]` (never `None`) when there are no spikes or insufficient history — "no spikes" is a normal result, not an error.
- Validated against live AAPL data during brainstorming: one spike found, 2026-07-31, volume 132,489,137 vs a trailing 20-day baseline average of 50,812,793 (ratio 2.61).

---

### Task 1: `_detect_volume_spikes` helper

**Files:**
- Modify: `backend/app/services/technicals_fetcher.py`
- Modify: `backend/tests/test_technicals_fetcher.py`

**Interfaces:**
- Produces: `_detect_volume_spikes(volume: pd.Series, lookback_days: int = 10, baseline_days: int = 20, threshold: float = 2.0) -> list[dict]`. Each spike dict has keys `date` (str `YYYY-MM-DD`), `volume` (int), `avg_volume` (int), `ratio` (float, rounded to 2dp). Returns `[]` if no day in the lookback window meets the threshold, or if there isn't a full `baseline_days`-day trailing window for any day in the lookback window.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_technicals_fetcher.py`, near the other crossover-state tests:

```python
# --- unit tests for _detect_volume_spikes ---

from app.services.technicals_fetcher import _detect_volume_spikes


def _make_volume_series(values: list[int]) -> pd.Series:
    idx = pd.date_range(end=pd.Timestamp("2026-08-03", tz="UTC"), periods=len(values) + 1, freq="B")[-len(values):]
    return pd.Series(values, index=idx)


def test_volume_spikes_none_in_flat_series():
    volume = _make_volume_series([1_000_000] * 30)
    assert _detect_volume_spikes(volume) == []


def test_volume_spikes_insufficient_history_returns_empty():
    volume = _make_volume_series([1_000_000] * 15)
    assert _detect_volume_spikes(volume) == []


def test_volume_spikes_single_spike():
    values = [1_000_000] * 30
    values[29] = 3_000_000
    volume = _make_volume_series(values)

    result = _detect_volume_spikes(volume)

    assert result == [{"date": "2026-08-03", "volume": 3000000, "avg_volume": 1000000, "ratio": 3.0}]


def test_volume_spikes_multiple_spikes():
    values = [1_000_000] * 30
    values[25] = 2_500_000
    values[29] = 3_000_000
    volume = _make_volume_series(values)

    result = _detect_volume_spikes(volume)

    assert result == [
        {"date": "2026-07-28", "volume": 2500000, "avg_volume": 1000000, "ratio": 2.5},
        {"date": "2026-08-03", "volume": 3000000, "avg_volume": 1075000, "ratio": 2.79},
    ]


def test_volume_spikes_boundary_at_threshold_included():
    values = [1_000_000] * 21
    values[20] = 2_000_000
    volume = _make_volume_series(values)

    result = _detect_volume_spikes(volume)

    assert result == [{"date": "2026-08-03", "volume": 2000000, "avg_volume": 1000000, "ratio": 2.0}]


def test_volume_spikes_below_threshold_excluded():
    values = [1_000_000] * 21
    values[20] = 1_900_000
    volume = _make_volume_series(values)

    assert _detect_volume_spikes(volume) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_technicals_fetcher.py -k volume_spikes -v`
Expected: FAIL with `ImportError: cannot import name '_detect_volume_spikes'`

- [ ] **Step 3: Implement the helper**

Add to `backend/app/services/technicals_fetcher.py`, after `_rsi_crossover_state` (before `_bollinger_position`):

```python
def _detect_volume_spikes(
    volume: pd.Series,
    lookback_days: int = 10,
    baseline_days: int = 20,
    threshold: float = 2.0,
) -> list[dict]:
    spikes = []
    n = len(volume)
    for i in range(max(0, n - lookback_days), n):
        baseline = volume.iloc[max(0, i - baseline_days):i]
        if len(baseline) < baseline_days:
            continue
        avg = float(baseline.mean())
        if avg <= 0:
            continue
        today = float(volume.iloc[i])
        ratio = round(today / avg, 2)
        if ratio >= threshold:
            spikes.append({
                "date": str(volume.index[i].date()),
                "volume": int(today),
                "avg_volume": int(avg),
                "ratio": ratio,
            })
    return spikes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_technicals_fetcher.py -k volume_spikes -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/technicals_fetcher.py backend/tests/test_technicals_fetcher.py
git commit -m "feat(technicals): add unusual volume spike detection helper"
```

---

### Task 2: Merge `volume_spikes` into `fetch_technicals`

**Files:**
- Modify: `backend/app/services/technicals_fetcher.py`
- Modify: `backend/tests/test_technicals_fetcher.py`

**Interfaces:**
- Consumes: `_detect_volume_spikes(volume: pd.Series) -> list[dict]` from Task 1.
- Produces: `fetch_technicals(ticker)`'s response gains a new field `volume_spikes: list[dict]` (the only non-scalar field in this response — a list of spike dicts, possibly empty).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_technicals_fetcher.py`, near `test_fetch_technicals_includes_rsi_crossover_fields`:

```python
def test_fetch_technicals_includes_volume_spikes_field():
    mock_client = _mock_client(_make_daily_df(200), _make_weekly_df(60))
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client), \
         patch("yfinance.Ticker") as mock_ticker:
        mock_ticker.return_value.calendar = {}
        result = fetch_technicals("AAPL")

    assert result["fetch_status"] == "ok"
    assert "volume_spikes" in result
    assert isinstance(result["volume_spikes"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_technicals_fetcher.py::test_fetch_technicals_includes_volume_spikes_field -v`
Expected: FAIL — `assert "volume_spikes" in result` fails, the key doesn't exist yet

- [ ] **Step 3: Wire the helper into `fetch_technicals`**

In `backend/app/services/technicals_fetcher.py`, `fetch_technicals()` currently has:

```python
        close_d = df_d["Close"].dropna()
        if len(close_d) < 2:
            err = {"fetch_status": "error", "fetch_error": f"Insufficient daily history for {ticker}"}
            return (err, pd.Series(dtype=float)) if return_closes else err
```

Add a `volume_d` line right after:

```python
        close_d = df_d["Close"].dropna()
        if len(close_d) < 2:
            err = {"fetch_status": "error", "fetch_error": f"Insufficient daily history for {ticker}"}
            return (err, pd.Series(dtype=float)) if return_closes else err

        volume_d = df_d["Volume"].dropna()
```

Then, where the crossover states are computed:

```python
        macd = _compute_macd_weekly(close_w)
        weekly_crossover = _macd_crossover_state(close_w)
        daily_crossover = _macd_crossover_state(close_d)
        rsi_crossover = _rsi_crossover_state(close_d)
        sentiment = _infer_sentiment(macd["macd_signal"], price, ma_50d, rsi_14)
        next_earnings = _get_next_earnings(ticker)
```

Replace with:

```python
        macd = _compute_macd_weekly(close_w)
        weekly_crossover = _macd_crossover_state(close_w)
        daily_crossover = _macd_crossover_state(close_d)
        rsi_crossover = _rsi_crossover_state(close_d)
        volume_spikes = _detect_volume_spikes(volume_d)
        sentiment = _infer_sentiment(macd["macd_signal"], price, ma_50d, rsi_14)
        next_earnings = _get_next_earnings(ticker)
```

Finally, in the `result = {...}` dict, add `"volume_spikes": volume_spikes,` — put it right after `"rsi_trend": rsi_crossover["trend"],`:

```python
            "rsi_trend": rsi_crossover["trend"],
            "volume_spikes": volume_spikes,
            "ma_200d": ma_200d,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_technicals_fetcher.py -v`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/technicals_fetcher.py backend/tests/test_technicals_fetcher.py
git commit -m "feat(technicals): merge volume_spikes field into fetch_technicals response"
```

---

### Task 3: Standalone `fetch_volume_spikes(ticker)` function

**Files:**
- Modify: `backend/app/services/technicals_fetcher.py`
- Modify: `backend/tests/test_technicals_fetcher.py`

**Interfaces:**
- Consumes: `_detect_volume_spikes` from Task 1.
- Produces: `fetch_volume_spikes(ticker: str) -> dict` — `{"spikes": list[dict], "lookback_days": 10, "baseline_days": 20, "threshold_multiple": 2.0, "fetch_status": ..., "fetch_error": ...}`. Raises `ValueError` if there's no daily data at all for the ticker.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_technicals_fetcher.py`:

```python
# --- fetch_volume_spikes (standalone) ---

from app.services.technicals_fetcher import fetch_volume_spikes


def test_fetch_volume_spikes_success():
    mock_client = MagicMock()
    mock_client.get_price_history.return_value = _make_daily_df(200)
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        result = fetch_volume_spikes("AAPL")

    assert result["fetch_status"] == "ok"
    assert result["fetch_error"] is None
    assert result["spikes"] == []
    assert result["lookback_days"] == 10
    assert result["baseline_days"] == 20
    assert result["threshold_multiple"] == 2.0
    mock_client.get_price_history.assert_called_once_with("AAPL", "year", 1, "daily", 1)


def test_fetch_volume_spikes_no_data_raises_value_error():
    mock_client = MagicMock()
    mock_client.get_price_history.return_value = pd.DataFrame()
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        with pytest.raises(ValueError):
            fetch_volume_spikes("INVALID")


def test_fetch_volume_spikes_schwab_error_returns_error_status():
    from app.services.schwab_client import SchwabAPIError
    mock_client = MagicMock()
    mock_client.get_price_history.side_effect = SchwabAPIError("network error")
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        result = fetch_volume_spikes("AAPL")

    assert result["fetch_status"] == "error"
    assert "network error" in result["fetch_error"]
    assert result["spikes"] == []
```

Note: `test_fetch_volume_spikes_success` uses `_make_daily_df(200)`, whose `Volume` column is constant (`[1_000_000] * n`, see the existing helper at the top of this file) — so no spike will be found (ratio always 1.0), which is why the test asserts `result["spikes"] == []` rather than a populated list. This still exercises the full success path (status, error, and the three constant fields).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_technicals_fetcher.py -k fetch_volume_spikes -v`
Expected: FAIL with `ImportError: cannot import name 'fetch_volume_spikes'`

- [ ] **Step 3: Implement `fetch_volume_spikes`**

Add to `backend/app/services/technicals_fetcher.py`, after `fetch_rsi_signal`:

```python
def fetch_volume_spikes(ticker: str) -> dict:
    try:
        client = get_schwab_client()
        df_d = client.get_price_history(ticker, "year", 1, "daily", 1)
    except SchwabAPIError as exc:
        return {
            "spikes": [],
            "lookback_days": 10,
            "baseline_days": 20,
            "threshold_multiple": 2.0,
            "fetch_status": "error",
            "fetch_error": str(exc),
        }

    if df_d is None or df_d.empty:
        raise ValueError(f"No daily data for {ticker}")

    volume_d = df_d["Volume"].dropna()
    return {
        "spikes": _detect_volume_spikes(volume_d),
        "lookback_days": 10,
        "baseline_days": 20,
        "threshold_multiple": 2.0,
        "fetch_status": "ok",
        "fetch_error": None,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_technicals_fetcher.py -v`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/technicals_fetcher.py backend/tests/test_technicals_fetcher.py
git commit -m "feat(technicals): add standalone fetch_volume_spikes service function"
```

---

### Task 4: `GET /api/market/volume-spikes/{ticker}` endpoint

**Files:**
- Modify: `backend/app/routers/market.py`
- Modify: `backend/tests/test_market_technicals.py`

**Interfaces:**
- Consumes: `fetch_volume_spikes(ticker: str) -> dict` from Task 3.
- Produces: `GET /api/market/volume-spikes/{ticker}` — 200 with the spikes dict, 404 if no daily data at all.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_market_technicals.py`:

```python
MOCK_VOLUME_SPIKES = {
    "spikes": [
        {"date": "2026-07-31", "volume": 132489137, "avg_volume": 50812793, "ratio": 2.61},
    ],
    "lookback_days": 10,
    "baseline_days": 20,
    "threshold_multiple": 2.0,
    "fetch_status": "ok",
    "fetch_error": None,
}


async def test_get_volume_spikes_success(client: AsyncClient):
    with patch("app.routers.market.fetch_volume_spikes", return_value=MOCK_VOLUME_SPIKES):
        response = await client.get("/api/market/volume-spikes/AAPL")
    assert response.status_code == 200
    data = response.json()
    assert len(data["spikes"]) == 1
    assert data["spikes"][0]["ratio"] == 2.61


async def test_get_volume_spikes_no_data_returns_404(client: AsyncClient):
    with patch("app.routers.market.fetch_volume_spikes", side_effect=ValueError("No daily data for INVALID")):
        response = await client.get("/api/market/volume-spikes/INVALID")
    assert response.status_code == 404


async def test_get_volume_spikes_ticker_uppercased(client: AsyncClient):
    with patch("app.routers.market.fetch_volume_spikes", return_value=MOCK_VOLUME_SPIKES) as mock_fn:
        await client.get("/api/market/volume-spikes/aapl")
    mock_fn.assert_called_once_with("AAPL")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_market_technicals.py -k volume_spikes -v`
Expected: FAIL — the route and the patchable name don't exist yet

- [ ] **Step 3: Add the endpoint**

In `backend/app/routers/market.py`, update the import line:

```python
from app.services.technicals_fetcher import fetch_technicals, fetch_macd_crossover, fetch_rsi_signal, fetch_volume_spikes
```

Add the new endpoint after `get_rsi_crossover`:

```python
@router.get("/volume-spikes/{ticker}")
async def get_volume_spikes(ticker: str):
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, fetch_volume_spikes, ticker.upper())
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
git commit -m "feat(technicals): add GET /api/market/volume-spikes/{ticker} endpoint"
```

---

### Task 5: Manual smoke test against live Schwab data

**Files:** none (verification only)

- [ ] **Step 1: Confirm the dev server is running (it auto-reloads on file changes)**

Run: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5431/docs`
Expected: `200`. If not running: `cd backend && source venv/bin/activate && uvicorn app.main:app --reload --port 5431`

- [ ] **Step 2: Hit both endpoints for AAPL**

Run: `curl -s http://localhost:5431/api/market/volume-spikes/AAPL | python3 -m json.tool`
Expected: 200 with `spikes` (should include the 2026-07-31 entry we validated during brainstorming, if that date is still within the last 10 trading days as of when this is run — otherwise it will have rolled out of the lookback window and `spikes` may be `[]` or contain a different day), `lookback_days: 10`, `baseline_days: 20`, `threshold_multiple: 2.0`, `fetch_status: "ok"`.

Run: `curl -s http://localhost:5431/api/market/technicals/AAPL | python3 -m json.tool`
Expected: 200 containing all prior fields plus `volume_spikes`, whose contents (dates/volumes/ratios) should match the standalone endpoint's `spikes` array for the same ticker.

- [ ] **Step 3: Check a 404 case**

Run: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5431/api/market/volume-spikes/ZZZZZINVALID`
Expected: `404`

No commit for this task — manual verification only.
