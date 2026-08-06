# Spec: Ticker-Level Stock Cost Basis for Wheel Dashboard (Correction)

**Date:** 2026-07-30
**Feature:** WHEEL Strategy Dashboard v2 (context/feature-wheel-dashboard.md)
**Supersedes (partially):** docs/superpowers/specs/2026-07-30-cost-basis-gain-loss-design.md
**Status:** Approved, ready for implementation plan

## Problem

The previously merged `% G/L` column and covered-call underwater warning (commits `581d83c`..`b40b3ae` on `develop`) derived stock cost basis from a `wheel_slot_leg` with `leg_role='stock'` linked to the slot. In production data, this link almost never exists: across the entire database only 2 slots have a linked stock leg (one of which is `closed`), while 22 tickers have real, open stock positions.

Investigation showed these stock positions **do** exist as ordinary rows in `trades`: `category='WHEEL'`, `strategy='Stock'`, `status='open'`, with real `premium` (cost basis) and `current_price`. They represent one blended position per ticker (e.g. PLTR: quantity 1100, one averaged cost basis) shared across every wheel slot for that ticker — they were just never linked into `wheel_slot_legs`.

As a result, the `% G/L` column was empty and the CC warning never triggered for nearly every real row, even though the underlying cost-basis data was available all along.

## Goal

Redirect the cost-basis lookup from the slot/leg level to the **session/ticker level**, matching directly against `trades`, so the column and warning work for real data without requiring any leg-linking workflow change.

## Non-Goals

- No change to the column's visual behavior, placement, or the CC-warning behavior — those already match the original spec and are unchanged.
- No new price-fetching (still relies on `Trade.current_price`, kept fresh by the existing scheduler job).
- No data model or migration changes — this reads existing `trades` rows, no new tables/columns on `trades`.
- No backfill or change to `wheel_slot_legs` — the leg-based stock link is not being deprecated as a concept, just no longer used as the data source for this feature.
- `trade_current_price` on `WheelSlotLegItem` (added in the prior iteration) is not removed — it's harmless and may still be useful elsewhere — but the dashboard's gain/loss logic stops depending on it.

## Data Source

For a given `WheelSession.ticker`, the cost basis and current price come from the matching row(s) in `trades` where `category = 'WHEEL' AND strategy = 'Stock' AND status = 'open'`:

1. **Exact ticker match first:** look for `trades.ticker == session.ticker`.
2. **Alias fallback:** only if no exact match exists, look for `trades.ticker == alias(session.ticker)` using the existing `GOOG`/`GOOGL` alias pair (mirroring `extension/content.js`'s `TICKER_ALIASES` map — reimplement the same two-entry map in Python since the extension's map isn't importable from the backend).
3. **Multiple matches:** if more than one open Stock trade matches (none currently in the data, but not structurally prevented), take the one with the latest `open_date`.
4. **No match:** `stock_cost_basis` / `stock_current_price` are both `null` — the dashboard renders `—` for that session's slots, same as today's "no data" case.

`stock_cost_basis` comes from `trades.premium`; `stock_current_price` comes from `trades.current_price`.

## Backend Changes

**`backend/app/schemas/wheel.py`**
- Add `stock_cost_basis: Optional[Decimal] = None` and `stock_current_price: Optional[Decimal] = None` to `WheelSessionDetail`.

**`backend/app/routers/wheel.py`**
- Add a small helper, e.g. `_find_stock_position(db, ticker) -> tuple[Decimal | None, Decimal | None]`, implementing the matching rule above (exact ticker → alias fallback → latest `open_date` on ties) via a query against `Trade`.
- Call this helper from the endpoints that build `WheelSessionDetail` (`get_wheel_session`, and any list/detail path the dashboard uses to fetch full session data — currently the dashboard calls `wheelApi.get(id)` per session, which hits `GET /api/wheel/{session_id}` → `_build_session_detail`). Populate the two new fields on the returned `WheelSessionDetail`.
- Define the ticker alias map as a small module-level constant, e.g. `TICKER_ALIASES = {"GOOG": "GOOGL", "GOOGL": "GOOG"}`, matching `extension/content.js:45` exactly.

## Frontend Changes

**`frontend/src/types/index.ts`**
- Add `stock_cost_basis: number | null` and `stock_current_price: number | null` to the `WheelSessionDetail` interface.

**`frontend/src/pages/WheelDashboardPage.tsx`**
- Extend `FlatSlot` to carry `stockCostBasis: number | null` and `stockCurrentPrice: number | null`, populated in `flattenSlots` from the parent session's new fields (not from any leg).
- Delete `stockLegCostBasis` (the leg-based helper from the prior iteration) entirely — it's superseded and no code should keep using it.
- `renderGainLossCell` and the `+ CC` button-warning logic both switch from calling `stockLegCostBasis(slot)` to reading `f.stockCostBasis` / `f.stockCurrentPrice` directly off the `FlatSlot` (both functions currently take `slot: WheelSlotDetail` — they need to take the `FlatSlot` instead, or take the two values directly as parameters; either is fine as long as call sites are updated consistently).
- Rendering rules are unchanged from the original spec: green/red `%` with `+`/`-` prefix or `—` when either value is missing or cost basis is `0`; `+ CC` button tinted red with a tooltip only when `slot.status === 'awaiting_cc'` and `currentPrice < costBasis`; button remains fully clickable.

## Testing

- Backend: add a test asserting `WheelSessionDetail` exposes `stock_cost_basis`/`stock_current_price` populated from a matching open `category=WHEEL, strategy=Stock` trade; a test for the alias fallback (session ticker `GOOG`, only a `GOOGL` open Stock trade exists, expect that trade's values); a test for "no match" (both fields `null`).
- Frontend: `tsc --noEmit` clean. Manual verification (per the existing pattern from the prior iteration) against the real dev database: confirm a ticker with a real open Stock trade (e.g. AMD, cost $469.96 vs current $487.52 → should show `+3.7%` and a blue `+ CC` button) renders correctly, and that the GOOG/GOOGL alias fallback works using the two real existing GOOG/GOOGL trades if a suitable test case can be constructed without mutating production data (prefer a disposable scratch ticker pair over touching real GOOG/GOOGL data, same discipline as the prior verification pass).

## Open Questions

None — all resolved during brainstorming.
