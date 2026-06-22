# Spreads Strategy Dashboard — Design Spec
**Date:** 2026-06-04
**Feature:** Iron Condor (IC) and Put Broken Wing Butterfly (PBWB) strategy sessions
**Branch:** TBD (new branch off master)

---

## Goal

Extend the existing trade-sessions infrastructure (built for WHEEL) to support multi-leg spread strategies — Iron Condor and Put Broken Wing Butterfly. Traders manually link individual option legs to a session from the Chrome extension's Add Trade modal. The extension then shows an "IC" or "PBWB" pill on each linked row, with a color signal indicating whether the current underlying price is safe, approaching, or past a short strike. A new `/spreads` dashboard page in the frontend shows all spread sessions with leg details and the same price-relative indicator.

---

## Background

The `trade_sessions` table was built generically (strategy column is `String(30)`, status is `String(30)`, no DB-level enum constraints) so new strategies require no migration. The existing sessions API, WHEEL session-picker flow in the extension, and WheelDashboardPage all provide direct analogues for every component needed here.

---

## Scope

**In scope:**
- `IRON_CONDOR` and `PUT_B_W_FLY` as new strategy values
- `open` and `closed` as the two status values for spread sessions
- Session-picker in the extension Add Trade modal for IC/PBWB (same UX as WHEEL)
- IC/PBWB strategy pill on E*TRADE rows, with price-relative color signal
- `GET /api/market/quote/{ticker}` used for price signal (endpoint already exists)
- New `SpreadsDashboardPage` at `/spreads` with session cards showing legs + price indicator
- Session lookup generalized to cover all strategies per ticker (not WHEEL-only)

**Out of scope:**
- Automated leg detection from DOM (user manually links each leg)
- Cross-ticker session grouping (one session per ticker, per design decision)
- P&L calculation per session
- Automatic status transitions
- Any changes to the WHEEL dashboard or WHEEL session flow

---

## Architecture

### Backend (no migration required)

No schema or migration changes. Both `strategy` and `status` are unconstrained `String(30)` columns.

Changes are limited to **Pydantic schemas only:**

**`backend/app/schemas/session.py`:**
- `SessionCreate.strategy`: add `"IRON_CONDOR"` and `"PUT_B_W_FLY"` to the docstring/validator comment (no runtime enforcement needed; keep as plain `str` to stay flexible)
- `SessionCreate` default strategy: leave as `"WHEEL"` (no change)
- Status: `"open"` and `"closed"` are valid for IC/PBWB; no change needed to schema since status is a free-form string

No new endpoints. Existing endpoints used (with two targeted changes noted):
| Endpoint | Change | Usage |
|---|---|---|
| `POST /api/sessions` | none | Create new IC/PBWB session (first leg) |
| `GET /api/sessions/lookup?ticker=X` | Make `strategy` optional; add `legs` to response; fix closed-session filter | Fetch active session for ticker (extension) |
| `GET /api/sessions?ticker=X&strategy=IRON_CONDOR&status=open` | none | Populate session-picker dropdown in Add Trade modal |
| `PATCH /api/sessions/{id}` | none | Close a session |
| `GET /api/market/quote/{ticker}` | none | Fetch current price for price signal |

**Changes to the lookup endpoint (`backend/app/routers/sessions.py`):**

1. Make `strategy` optional — `strategy: Optional[str] = Query(None)`. Apply the `WHERE strategy = X` filter only when strategy is provided. The extension calls lookup without strategy to surface any active session for the ticker across all strategies.

2. Fix the terminal-status filter — current code excludes `status != "completed"` but `closed` (new IC/PBWB terminal status) would not be excluded. Change to `TradeSession.status.not_in(["completed", "closed"])`.

3. Add `legs` to `SessionLookupResponse` — each session summary in the response includes a `legs: list[SessionLegItem]` field. This gives the extension the strike data it needs for the price signal without a second round-trip. Requires a `selectinload(TradeSession.legs)` on the lookup query.

**Changes to `backend/app/schemas/session.py`:**
- `SessionLookupResponse.sessions`: change from `list[SessionSummary]` to `list[SessionWithLegs]` (which already includes `legs`), or add `legs` to `SessionSummary`. Simplest: use `SessionWithLegs` directly.

---

### Extension (`content.js`)

#### 1. Session fetch — generalize to all strategies

Current: `fetchWheelSessionsForTickers` calls `/api/sessions/lookup?ticker=X&strategy=WHEEL`.

Change: remove the `strategy=WHEEL` filter. The lookup endpoint returns the most relevant open session for the ticker regardless of strategy. Cache the result as before. This means one fetch per ticker surfaces WHEEL, IC, or PBWB sessions equally.

#### 2. Pill rendering

Extend the pill renderer to branch on `session.strategy`:

| strategy | Label | Safe color | Warning color | Danger color |
|---|---|---|---|---|
| `WHEEL` | `WHL: <status>` | blue `#DBEAFE` / `#1E40AF` | amber `#FEF3C7` / `#92400E` | (existing logic unchanged) |
| `IRON_CONDOR` | `IC ✓` / `IC ⚠` / `IC ✗` | purple `#EDE9FE` / `#5B21B6` | amber | red `#FEE2E2` / `#991B1B` |
| `PUT_B_W_FLY` | `PBWB ✓` / `PBWB ⚠` / `PBWB ✗` | teal `#CCFBF1` / `#0F766E` | amber | red |

#### 3. Price signal logic

After fetching sessions for visible tickers, fetch `GET /api/market/quote/{ticker}` for each ticker that has an IC or PBWB session. Cache price per ticker for the page session (same pattern as RSI cache).

Price signal computation (runs in extension JS, inputs from session metadata):

The session's linked trades provide the legs. The extension already sends `strike` and `type` when creating trades, and the session detail endpoint returns linked trades. On lookup, the session response must include the leg strikes — see Session Metadata section below.

**IC signal:**
- Extract short put strike (`max` of the two put strikes) and short call strike (`min` of the two call strikes) from session legs
- `safe`: `short_put_strike < price < short_call_strike`
- `warning`: price within 5% of either short strike (i.e., `price < short_put_strike * 1.05` or `price > short_call_strike * 0.95`)
- `danger`: `price ≤ short_put_strike` or `price ≥ short_call_strike`

**PBWB signal:**
- Extract short strikes (the strikes with negative/short qty)
- `safe`: price between the two outermost short strikes
- `warning`: within 5% of either boundary
- `danger`: outside either boundary

#### 4. Session metadata for strike data

The `/api/sessions/lookup` response must include enough strike data for the extension to compute the price signal without a second fetch. Add a `legs` array to the lookup response — each leg has `{ strike, type, qty }`. This requires the lookup endpoint to JOIN `trades` on `session_id` and return the linked trades' key fields.

**`backend/app/routers/sessions.py`** — extend the lookup response schema to include:
```
legs: list[{ strike: float | None, type: str | None, qty: int | None }]
```

This is a read-only addition, no schema migration.

#### 5. Add Trade modal — session picker for IC/PBWB

When user selects `IRON_CONDOR` or `PUT_B_W_FLY` as the trade category in the Add Trade modal:
- Show a "Session" dropdown below the category field
- Populate by calling `GET /api/sessions?ticker=<ticker>&strategy=<strategy>&status=open`
- Options: one entry per open session (show `strategy + opened_at date`), plus "New session" at top
- Selecting "New session": `POST /api/sessions` with `{ ticker, strategy, status: "open" }` before saving the trade
- Selecting an existing session: set `session_id` on the trade payload

No change to the existing WHEEL session-picker flow.

---

### Frontend — `SpreadsDashboardPage`

**Route:** `/spreads` (add to `App.tsx` alongside `/wheel`)

**Layout** (mirrors `WheelDashboardPage`):
- Page header: "Spreads Dashboard" with a "+ New Session" button
- Two sections: **Open Positions** and **Closed**
- Each section is a card grid

**Session card** (`SpreadSessionCard` component):
- Header: strategy badge (`IC` purple / `PBWB` teal), ticker, expiry of legs, opened date
- Price indicator bar: shows current price relative to the short strikes as a labeled range  
  - Green zone: between short strikes  
  - Amber zone: within 5% buffer on either side  
  - Red zone: outside short strikes  
  - Current price shown as a marker on the bar
- Legs table: one row per linked trade — strike, type (Put/Call), qty (long/short), entry price
- Footer: "Close Session" button → `PATCH /api/sessions/{id}` with `{ status: "closed" }`

**Data fetching:**
1. `GET /api/sessions?strategy=IRON_CONDOR&status=open` + `GET /api/sessions?strategy=PUT_B_W_FLY&status=open` — fetched in parallel on mount
2. For each session, `GET /api/sessions/{id}` on card expand to get legs detail
3. `GET /api/market/quote/{ticker}` per unique ticker — batched on mount, result used for price indicator

**New API wrapper:** `frontend/src/api/sessions.ts` already exists; add `getSpreadSessions(strategy, status)` call.

**New types** in `frontend/src/types/index.ts`: no new types needed if `Session` and `Trade` types are already defined; just use `strategy: string`.

---

## Key Files

| File | Change |
|---|---|
| `backend/app/schemas/session.py` | Add `legs` field to lookup response schema |
| `backend/app/routers/sessions.py` | Extend lookup to JOIN trades and return `legs` array |
| `frontend/src/pages/SpreadsDashboardPage.tsx` | New page |
| `frontend/src/components/Spreads/SpreadSessionCard.tsx` | New component |
| `frontend/src/api/sessions.ts` | Add `getSpreadSessions` helper |
| `frontend/src/App.tsx` | Add `/spreads` route |
| `extension/content.js` | Generalize session fetch; extend pill renderer; add price signal logic; extend Add Trade modal |

---

## Decisions

| Decision | Chosen | Reason |
|---|---|---|
| Session per ticker | One session per ticker (no cross-ticker grouping) | Keeps extension lookup simple — same per-ticker pattern as WHEEL |
| Status states | `open` / `closed` only | IC/PBWB have no meaningful intermediate states unlike WHEEL |
| No DB migration | Plain `String(30)` columns; new strategy/status values just work | Already designed this way in the WHEEL spec |
| Price signal in extension | Fetch `GET /api/market/quote/{ticker}` after session load; cache per page | Reuses existing endpoint; same caching pattern as RSI |
| Strike data via lookup `legs` | Extend lookup response with leg strikes | Avoids a second round-trip from the extension per session |
| Warning threshold | 5% of short strike price | Practical buffer for intraday moves without being too noisy |

---

## Open Questions / Future Scope

- [ ] Should the Spreads Dashboard also surface the P&L per session? (Requires cost basis data from linked trades — deferred)
- [ ] Filter toolbar in the extension: add "IC" and "PBWB" filter buttons alongside existing category filters
- [ ] Nav link to `/spreads` in the frontend sidebar
