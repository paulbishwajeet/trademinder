# Daily-Interval MACD Crossover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing weekly-only MACD crossover detection (from the unmerged `feature/macd-weekly-crossover` branch) to also cover the daily interval, on both `fetch_technicals` and the standalone `fetch_macd_crossover` endpoint.

**Architecture:** Generalize `_macd_weekly_crossover_state` into an interval-agnostic `_macd_crossover_state(close: pd.Series) -> dict` with generic field names (`cross_date`, `cross_direction`, `periods_since_cross`, `strength_score`, `trend`). `fetch_technicals` calls it twice (on `close_d` and `close_w`, both already fetched) and merges both results with `macd_weekly_*`/`macd_daily_*` prefixes into its flat response. `fetch_macd_crossover` now fetches both weekly and daily history and returns a nested `{"weekly": {...}, "daily": {...}}` shape.

**Tech Stack:** Same as the prior branch — FastAPI, pandas EWM-based MACD, pytest + httpx `AsyncClient`, `unittest.mock`.

## Global Constraints

- No new intervals beyond daily and weekly.
- No frontend changes.
- No extra Schwab call added to `fetch_technicals` — daily crossover reuses the `close_d` series (1yr) it already fetches.
- The 35-bar minimum and strength-score math are unchanged and periodicity-agnostic — confirmed against live daily Schwab data during brainstorming (AAPL: last daily crossover 2026-07-31, bearish, 2 days ago, score 100.0, "expanding").
- This plan renames fields added in the prior branch (`macd_cross_date` → `macd_weekly_cross_date`, etc.) — safe since that branch is unmerged and unshipped.

---

### Task 1: Generalize `_macd_crossover_state`

**Files:**
- Modify: `backend/app/services/technicals_fetcher.py`
- Modify: `backend/tests/test_technicals_fetcher.py`

**Interfaces:**
- Produces: `_macd_crossover_state(close: pd.Series) -> dict` with keys `cross_date`, `cross_direction`, `periods_since_cross`, `strength_score`, `trend` (renamed from `_macd_weekly_crossover_state`'s `macd_cross_date`/`macd_cross_direction`/`macd_weeks_since_cross`/`macd_strength_score`/`macd_trend`).

- [ ] **Step 1: Update the existing unit tests to the new name/keys (this makes them fail first, since the function still has the old name)**

In `backend/tests/test_technicals_fetcher.py`, replace the whole `_macd_weekly_crossover_state` test block (lines 94–172, from the `# --- unit tests for _macd_weekly_crossover_state ---` comment through the end of `test_macd_crossover_expanding_at_peak`) with:

```python
# --- unit tests for _macd_crossover_state ---

from app.services.technicals_fetcher import _macd_crossover_state


def _make_weekly_close(values: list[float]) -> pd.Series:
    idx = pd.date_range(end=pd.Timestamp("2026-08-03", tz="UTC"), periods=len(values) + 1, freq="W")[-len(values):]
    return pd.Series(values, index=idx)


def test_macd_crossover_insufficient_data_returns_all_none():
    close = _make_weekly_close([100.0] * 10)
    result = _macd_crossover_state(close)
    assert result == {
        "cross_date": None,
        "cross_direction": None,
        "periods_since_cross": None,
        "strength_score": None,
        "trend": None,
    }


def test_macd_crossover_bullish_fading_near_flip():
    # 30 weeks falling, 25 weeks rising sharply (bullish crossover), 5 weeks pulling back (squeeze)
    down = [200.0 - i * 2.0 for i in range(30)]
    up = [down[-1] + i * 3.0 for i in range(1, 26)]
    flat = [up[-1] - i * 0.5 for i in range(1, 6)]
    close = _make_weekly_close(down + up + flat)

    result = _macd_crossover_state(close)

    assert result["cross_date"] == "2026-01-25"
    assert result["cross_direction"] == "bullish"
    assert result["periods_since_cross"] == 27
    assert result["strength_score"] == 12.2
    assert result["trend"] == "fading_near_flip"


def test_macd_crossover_bearish_fading_near_flip():
    # Mirror image of the bullish case: rising, then falling sharply (bearish crossover), then a small bounce
    up = [100.0 + i * 2.0 for i in range(30)]
    down = [up[-1] - i * 3.0 for i in range(1, 26)]
    bounce = [down[-1] + i * 0.5 for i in range(1, 6)]
    close = _make_weekly_close(up + down + bounce)

    result = _macd_crossover_state(close)

    assert result["cross_date"] == "2026-01-25"
    assert result["cross_direction"] == "bearish"
    assert result["periods_since_cross"] == 27
    assert result["strength_score"] == 12.2
    assert result["trend"] == "fading_near_flip"


def test_macd_crossover_squeezing():
    # Steady compounding growth (1% per week) - gap narrows to a mid-range score after the initial ramp
    close = _make_weekly_close([100.0 * (1.01 ** i) for i in range(60)])
    result = _macd_crossover_state(close)

    assert result["cross_direction"] == "bullish"
    assert result["strength_score"] == 42.8
    assert result["trend"] == "squeezing"


def test_macd_crossover_holding_strong():
    close = _make_weekly_close([100.0 * (1.016 ** i) for i in range(60)])
    result = _macd_crossover_state(close)

    assert result["strength_score"] == 75.5
    assert result["trend"] == "holding_strong"


def test_macd_crossover_expanding_at_peak():
    # Strong compounding growth - the gap is still widening at the very last bar
    close = _make_weekly_close([100.0 * (1.02 ** i) for i in range(60)])
    result = _macd_crossover_state(close)

    assert result["strength_score"] == 100.0
    assert result["trend"] == "expanding"
```

(This is the same test logic as before — only the imported name and the dict keys under test have changed. The synthetic price series and expected numeric values are unchanged from the prior branch since the underlying math is identical.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_technicals_fetcher.py -k macd_crossover -v`
Expected: FAIL with `ImportError: cannot import name '_macd_crossover_state'`

- [ ] **Step 3: Rename the function and its field keys**

In `backend/app/services/technicals_fetcher.py`, replace:

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

with:

```python
_NONE_CROSSOVER_FIELDS: dict = {
    "cross_date": None,
    "cross_direction": None,
    "periods_since_cross": None,
    "strength_score": None,
    "trend": None,
}


def _macd_crossover_state(close: pd.Series) -> dict:
    if len(close) < 35:
        return dict(_NONE_CROSSOVER_FIELDS)

    exp1 = close.ewm(span=12, adjust=False).mean()
    exp2 = close.ewm(span=26, adjust=False).mean()
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
        "cross_date": str(last_cross_date.date()),
        "cross_direction": direction,
        "periods_since_cross": periods_since,
        "strength_score": score,
        "trend": trend,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_technicals_fetcher.py -k macd_crossover -v`
Expected: 6 passed

Note: `fetch_technicals` and `fetch_macd_crossover` in this same file still call the old `_macd_weekly_crossover_state` name and reference the old field keys — they will now be broken. This is expected and fixed in Tasks 2 and 3. Don't run the full test file yet; just the `-k macd_crossover` subset.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/technicals_fetcher.py backend/tests/test_technicals_fetcher.py
git commit -m "refactor(technicals): generalize _macd_weekly_crossover_state to interval-agnostic _macd_crossover_state"
```

---

### Task 2: Dual weekly + daily crossover in `fetch_technicals`

**Files:**
- Modify: `backend/app/services/technicals_fetcher.py`
- Modify: `backend/tests/test_technicals_fetcher.py`

**Interfaces:**
- Consumes: `_macd_crossover_state(close: pd.Series) -> dict` from Task 1.
- Produces: `fetch_technicals(ticker)`'s response now has `macd_weekly_cross_date`, `macd_weekly_cross_direction`, `macd_weekly_periods_since_cross`, `macd_weekly_strength_score`, `macd_weekly_trend`, and the `macd_daily_*` equivalents (10 fields total, replacing the prior branch's 5 unprefixed `macd_cross_*` fields).

- [ ] **Step 1: Update the failing test**

In `backend/tests/test_technicals_fetcher.py`, replace `test_fetch_technicals_includes_macd_crossover_fields`:

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

with:

```python
def test_fetch_technicals_includes_macd_crossover_fields():
    mock_client = _mock_client(_make_daily_df(200), _make_weekly_df(60))
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client), \
         patch("yfinance.Ticker") as mock_ticker:
        mock_ticker.return_value.calendar = {}
        result = fetch_technicals("AAPL")

    assert result["fetch_status"] == "ok"
    for prefix in ("weekly", "daily"):
        assert f"macd_{prefix}_cross_date" in result
        assert f"macd_{prefix}_cross_direction" in result
        assert f"macd_{prefix}_periods_since_cross" in result
        assert f"macd_{prefix}_strength_score" in result
        assert f"macd_{prefix}_trend" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_technicals_fetcher.py::test_fetch_technicals_includes_macd_crossover_fields -v`
Expected: FAIL — the prefixed keys don't exist yet (and this test module currently fails to even import `fetch_technicals` correctly at runtime since `_macd_weekly_crossover_state` no longer exists — see next step)

- [ ] **Step 3: Update `fetch_technicals` to compute and merge both intervals**

In `backend/app/services/technicals_fetcher.py`, replace:

```python
        macd = _compute_macd_weekly(close_w)
        crossover = _macd_weekly_crossover_state(close_w)
        sentiment = _infer_sentiment(macd["macd_signal"], price, ma_50d, rsi_14)
        next_earnings = _get_next_earnings(ticker)

        result = {
            "macd_signal": macd["macd_signal"],
            "macd_notes": macd["macd_notes"],
            **crossover,
            "rsi_14": rsi_14,
```

with:

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_technicals_fetcher.py -v`
Expected: all tests pass except `test_fetch_macd_crossover_*` (those are fixed in Task 3 — they still call the old `_macd_weekly_crossover_state` internally via `fetch_macd_crossover`, which hasn't been updated yet)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/technicals_fetcher.py backend/tests/test_technicals_fetcher.py
git commit -m "feat(technicals): add daily-interval MACD crossover fields to fetch_technicals"
```

---

### Task 3: Nested weekly/daily shape for `fetch_macd_crossover`

**Files:**
- Modify: `backend/app/services/technicals_fetcher.py`
- Modify: `backend/tests/test_technicals_fetcher.py`

**Interfaces:**
- Consumes: `_macd_crossover_state` (Task 1), `_NONE_CROSSOVER_FIELDS` (Task 1, now with generic keys).
- Produces: `fetch_macd_crossover(ticker: str) -> dict` returns `{"weekly": {...5 fields...}, "daily": {...5 fields...}, "fetch_status": ..., "fetch_error": ...}`. Raises `ValueError` if either weekly or daily history is completely empty.

- [ ] **Step 1: Update the failing tests**

In `backend/tests/test_technicals_fetcher.py`, replace the whole `# --- fetch_macd_crossover (standalone) ---` section (from that comment to the end of the file) with:

```python
# --- fetch_macd_crossover (standalone) ---

from app.services.technicals_fetcher import fetch_macd_crossover


def test_fetch_macd_crossover_success():
    mock_client = MagicMock()
    mock_client.get_price_history.side_effect = [_make_weekly_df(60), _make_daily_df(200)]
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        result = fetch_macd_crossover("AAPL")

    assert result["fetch_status"] == "ok"
    assert result["fetch_error"] is None
    assert set(result["weekly"].keys()) == {"cross_date", "cross_direction", "periods_since_cross", "strength_score", "trend"}
    assert set(result["daily"].keys()) == {"cross_date", "cross_direction", "periods_since_cross", "strength_score", "trend"}
    mock_client.get_price_history.assert_any_call("AAPL", "year", 2, "weekly", 1)
    mock_client.get_price_history.assert_any_call("AAPL", "year", 1, "daily", 1)


def test_fetch_macd_crossover_no_weekly_data_raises_value_error():
    mock_client = MagicMock()
    mock_client.get_price_history.side_effect = [pd.DataFrame(), _make_daily_df(200)]
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        with pytest.raises(ValueError):
            fetch_macd_crossover("INVALID")


def test_fetch_macd_crossover_no_daily_data_raises_value_error():
    mock_client = MagicMock()
    mock_client.get_price_history.side_effect = [_make_weekly_df(60), pd.DataFrame()]
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
    assert result["weekly"]["cross_date"] is None
    assert result["daily"]["cross_date"] is None


def test_fetch_macd_crossover_insufficient_history_returns_ok_with_none_fields():
    mock_client = MagicMock()
    mock_client.get_price_history.side_effect = [_make_weekly_df(10), _make_daily_df(10)]
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        result = fetch_macd_crossover("AAPL")

    assert result["fetch_status"] == "ok"
    assert result["weekly"]["cross_date"] is None
    assert result["daily"]["cross_date"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_technicals_fetcher.py -k fetch_macd_crossover -v`
Expected: FAIL — `test_fetch_macd_crossover_success` and the "insufficient history" test fail because `result["weekly"]` doesn't exist (current implementation returns a flat dict); the `no_daily_data` test is new and fails because the current implementation never fetches daily data at all

- [ ] **Step 3: Rewrite `fetch_macd_crossover`**

In `backend/app/services/technicals_fetcher.py`, replace:

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

with:

```python
def fetch_macd_crossover(ticker: str) -> dict:
    try:
        client = get_schwab_client()
        df_w = client.get_price_history(ticker, "year", 2, "weekly", 1)
        df_d = client.get_price_history(ticker, "year", 1, "daily", 1)
    except SchwabAPIError as exc:
        return {
            "weekly": dict(_NONE_CROSSOVER_FIELDS),
            "daily": dict(_NONE_CROSSOVER_FIELDS),
            "fetch_status": "error",
            "fetch_error": str(exc),
        }

    if df_w is None or df_w.empty or df_d is None or df_d.empty:
        raise ValueError(f"No price history for {ticker}")

    close_w = df_w["Close"].dropna()
    close_d = df_d["Close"].dropna()

    return {
        "weekly": _macd_crossover_state(close_w),
        "daily": _macd_crossover_state(close_d),
        "fetch_status": "ok",
        "fetch_error": None,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_technicals_fetcher.py -v`
Expected: all tests pass (31 total: the 30 from before this plan, plus the new `test_fetch_macd_crossover_no_daily_data_raises_value_error`)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/technicals_fetcher.py backend/tests/test_technicals_fetcher.py
git commit -m "feat(technicals): return nested weekly/daily shape from fetch_macd_crossover"
```

---

### Task 4: Update router tests for the new nested shape

**Files:**
- Modify: `backend/tests/test_market_technicals.py`

**Interfaces:**
- Consumes: `fetch_macd_crossover(ticker) -> dict` (Task 3's new nested shape). No router code changes — `GET /api/market/macd-crossover/{ticker}` in `backend/app/routers/market.py` already just returns whatever `fetch_macd_crossover` produces.

- [ ] **Step 1: Update the mock and assertions**

In `backend/tests/test_market_technicals.py`, replace:

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
```

with:

```python
MOCK_CROSSOVER = {
    "weekly": {
        "cross_date": "2026-04-27",
        "cross_direction": "bullish",
        "periods_since_cross": 14,
        "strength_score": 19.1,
        "trend": "fading_near_flip",
    },
    "daily": {
        "cross_date": "2026-07-31",
        "cross_direction": "bearish",
        "periods_since_cross": 2,
        "strength_score": 100.0,
        "trend": "expanding",
    },
    "fetch_status": "ok",
    "fetch_error": None,
}


async def test_get_macd_crossover_success(client: AsyncClient):
    with patch("app.routers.market.fetch_macd_crossover", return_value=MOCK_CROSSOVER):
        response = await client.get("/api/market/macd-crossover/AAPL")
    assert response.status_code == 200
    data = response.json()
    assert data["weekly"]["cross_direction"] == "bullish"
    assert data["weekly"]["strength_score"] == 19.1
    assert data["daily"]["cross_direction"] == "bearish"
    assert data["daily"]["strength_score"] == 100.0
```

(`test_get_macd_crossover_no_data_returns_404` and `test_get_macd_crossover_ticker_uppercased` are unaffected — they either patch `fetch_macd_crossover` to raise `ValueError` directly, or just check the mock was called with the uppercased ticker, neither of which depends on the response shape.)

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_market_technicals.py -v`
Expected: all 6 tests pass

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_market_technicals.py
git commit -m "test(technicals): update macd-crossover router tests for nested weekly/daily shape"
```

---

### Task 5: Manual smoke test against live Schwab data

**Files:** none (verification only)

- [ ] **Step 1: Start the backend dev server (skip if already running)**

Run: `cd backend && source venv/bin/activate && uvicorn app.main:app --reload --port 5431`

- [ ] **Step 2: Hit both endpoints for AAPL**

Run: `curl -s http://localhost:5431/api/market/macd-crossover/AAPL | python3 -m json.tool`
Expected: 200 response with top-level `weekly` and `daily` objects, each containing `cross_date`, `cross_direction`, `periods_since_cross`, `strength_score`, `trend`; `fetch_status: "ok"`.

Run: `curl -s http://localhost:5431/api/market/technicals/AAPL | python3 -m json.tool`
Expected: 200 response containing the original 19 fields plus 10 new `macd_weekly_*`/`macd_daily_*` fields, with values matching the standalone endpoint's `weekly`/`daily` sub-objects for the same ticker (once the weekly bar hasn't rolled since the last check, the weekly values should match what we saw in the previous branch's smoke test: `2026-04-27` bullish).

- [ ] **Step 3: Check a 404 case**

Run: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5431/api/market/macd-crossover/ZZZZZINVALID`
Expected: `404`

No commit for this task — manual verification only.
