# Immediate Stale Marking on Reconcile

**Date:** 2026-07-17  
**Status:** Approved

## Overview

When a user clicks the "🔄 Reconcile" button, any backend trade that is not matched against the current E*TRADE portfolio should immediately appear as stale on the trades page — rather than waiting up to 24 hours for the time-based threshold to expire.

## Change

### `backend/app/routers/positions.py` — `reconcile_positions`

After the match loop and in the same DB commit as matched-trade `last_etrade_seen` updates, backdate `last_etrade_seen` to `now - timedelta(days=2)` for trades that meet both conditions:

1. `t.id not in matched_ids` — not matched against any visible E*TRADE position
2. `t.last_etrade_seen is not None` — was previously seen in E*TRADE (guards against flagging trades that were added manually and never seen in E*TRADE at all)

Setting `now - 2 days` ensures the value satisfies the existing stale threshold of `last_etrade_seen < now - 1 day` used by both the reconcile response and the trades page `GET /api/trades?stale=true`.

The `stale_backend` list is computed after the commit, so it will include the newly backdated trades in the same reconcile response.

## No Schema Changes

The `last_etrade_seen` column already exists on `Trade`. No migration needed.

## Files Changed

- `backend/app/routers/positions.py` only

## Out of Scope

- No frontend changes — the trades page already uses `GET /api/trades?stale=true` which queries `last_etrade_seen < now - 1 day`
- No changes to the stale threshold value (stays at 1 day)
- No changes to the extension
