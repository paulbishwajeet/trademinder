# Immediate Stale Marking on Reconcile — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the reconcile button is clicked, any previously-seen backend trade absent from the E*TRADE snapshot is immediately marked stale rather than waiting up to 24 hours.

**Architecture:** In `reconcile_positions`, extend the existing post-match loop to also backdate `last_etrade_seen` to `now - timedelta(days=2)` for unmatched trades that have a non-null `last_etrade_seen`. This satisfies the existing stale threshold (`< now - 1 day`) used by both the reconcile response and `GET /api/trades?stale=true`. One file, one commit.

**Tech Stack:** Python, SQLAlchemy async, FastAPI, pytest-asyncio

## Global Constraints

- Only `backend/app/routers/positions.py` and `backend/tests/test_reconcile.py` are modified — no schema changes, no migrations.
- Backdating value is exactly `now - timedelta(days=2)`.
- Trades with `last_etrade_seen IS NULL` must NOT be backdated.
- Matched trades continue to receive `last_etrade_seen = now` (unchanged).
- All changes land in a single commit.

---

### Task 1: Backdate unmatched previously-seen trades at reconcile time

**Files:**
- Modify: `backend/app/routers/positions.py:204-208` (post-match commit block)
- Test: `backend/tests/test_reconcile.py`

**Interfaces:**
- Consumes: `matched_ids: set`, `all_open_trades: list[Trade]`, `now: datetime`, `timedelta`
- Produces: no new public interface — behavior change only

- [ ] **Step 1: Write the new failing test — unmatched previously-seen trade is immediately stale**

Add this test to `backend/tests/test_reconcile.py`:

```python
async def test_reconcile_unmatched_seen_trade_immediately_stale(
    client: AsyncClient, db_session: AsyncSession
):
    """Previously-seen trade absent from snapshot → immediately in stale_backend."""
    from sqlalchemy import select
    from app.models.trade import Trade

    create_resp = await client.post("/api/trades", json=STOCK_TRADE)
    trade_id = create_resp.json()["id"]

    # Simulate a recent prior reconcile (1 hour ago)
    result = await db_session.execute(select(Trade).where(Trade.id == trade_id))
    trade = result.scalar_one()
    trade.last_etrade_seen = datetime.now(timezone.utc) - timedelta(hours=1)
    await db_session.commit()

    # Reconcile without AAPL in snapshot
    resp = await client.post(RECONCILE_URL, json={
        "positions": [{"ticker": "TSLA", "full_symbol": None, "type": "Stock"}]
    })
    assert resp.status_code == 200
    data = resp.json()
    stale_ids = [item["id"] for item in data["stale_backend"]]
    assert trade_id in stale_ids
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend
python -m pytest tests/test_reconcile.py::test_reconcile_unmatched_seen_trade_immediately_stale -v
```

Expected: `FAILED` — the trade is not yet in `stale_backend` because `last_etrade_seen` is only 1 hour old.

- [ ] **Step 3: Update the existing test whose expectation changes**

`test_reconcile_recently_seen_not_stale` (line 94) tests the OLD behavior — that a recently-seen unmatched trade is NOT stale. After this change the trade will be immediately backdated and WILL appear as stale. Update the test body to assert the new behavior:

Replace the existing `test_reconcile_recently_seen_not_stale` function with:

```python
async def test_reconcile_recently_seen_unmatched_is_now_immediately_stale(
    client: AsyncClient, db_session: AsyncSession
):
    """Trade seen within the last hour IS now immediately stale when absent from snapshot."""
    from sqlalchemy import select
    from app.models.trade import Trade

    create_resp = await client.post("/api/trades", json=STOCK_TRADE)
    trade_id = create_resp.json()["id"]

    result = await db_session.execute(select(Trade).where(Trade.id == trade_id))
    trade = result.scalar_one()
    trade.last_etrade_seen = datetime.now(timezone.utc) - timedelta(hours=1)
    await db_session.commit()

    resp = await client.post(RECONCILE_URL, json={
        "positions": [{"ticker": "TSLA", "full_symbol": None, "type": "Stock"}]
    })
    assert resp.status_code == 200
    data = resp.json()
    stale_ids = [item["id"] for item in data["stale_backend"]]
    assert trade_id in stale_ids
```

- [ ] **Step 4: Implement the backdating in `reconcile_positions`**

In `backend/app/routers/positions.py`, replace the post-match commit block (lines 204-208):

**Before:**
```python
    now = datetime.now(timezone.utc)
    for trade in all_open_trades:
        if trade.id in matched_ids:
            trade.last_etrade_seen = now
    await db.commit()
```

**After:**
```python
    now = datetime.now(timezone.utc)
    for trade in all_open_trades:
        if trade.id in matched_ids:
            trade.last_etrade_seen = now
        elif trade.last_etrade_seen is not None:
            trade.last_etrade_seen = now - timedelta(days=2)
    await db.commit()
```

- [ ] **Step 5: Run the full reconcile test suite**

```bash
cd backend
python -m pytest tests/test_reconcile.py -v
```

Expected: all tests pass. Verify specifically:
- `test_reconcile_unmatched_seen_trade_immediately_stale` — PASS
- `test_reconcile_recently_seen_unmatched_is_now_immediately_stale` — PASS
- `test_reconcile_never_seen_not_stale` — PASS (null guard still works)
- `test_reconcile_stale_trade_in_stale_backend` — PASS (already-stale trade still appears)
- `test_reconcile_matched_trade_gets_last_etrade_seen` — PASS (matched trades unaffected)

- [ ] **Step 6: Run the full test suite to check for regressions**

```bash
cd backend
python -m pytest tests/ -q --tb=short
```

Expected: same pass/fail count as before this task (6 pre-existing failures, all unrelated to reconcile).

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/positions.py backend/tests/test_reconcile.py
git commit -m "feat(reconcile): immediately mark unmatched seen trades as stale"
```
