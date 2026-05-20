# Technicals Capture Feature — Design Spec

**Date:** 2026-05-19
**Status:** Approved

---

## Overview

Add on-demand technical indicator capture to TradeMinder so that every trade entry and every commentary note can carry a full snapshot of market technicals at the time of capture. Technicals are fetched from yfinance, displayed in an editable panel, and persisted to the existing `rationale` table.

---

## Fields Captured

| Field | Type | Source |
|---|---|---|
| `macd_signal` | `bullish` / `bearish` / `neutral` | Computed: MACD line vs signal line (weekly) |
| `macd_notes` | `above 0 line` / `below 0 line` | Computed from weekly MACD histogram |
| `rsi_14` | Decimal (5,2) | Computed: Wilder EMA RSI-14 from daily close |
| `rsi_result` | `rsi_oversold` / `rsi_overbought` / null | Derived: `< 30` → oversold, `> 70` → overbought |
| `ma_200d` | Decimal (10,2) | 200-day SMA from daily close |
| `ma_50d` | Decimal (10,2) | 50-day SMA from daily close |
| `price_vs_ma200` | `above` / `below` | Derived: current price vs MA200 |
| `price_vs_ma50` | `above` / `below` | Derived: current price vs MA50 |
| `bollinger_upper` | Decimal (10,2) | 20-day BB upper band (2σ) from daily |
| `bollinger_mid` | Decimal (10,2) | 20-day BB midline (20-day SMA) |
| `bollinger_lower` | Decimal (10,2) | 20-day BB lower band (2σ) from daily |
| `bollinger_position` | `above_upper` / `near_upper` / `mid` / `near_lower` / `below_lower` | Derived: price relative to bands |
| `day_color` | `green` / `red` | Today's close vs previous close |
| `price_action` | Decimal (string) | Current price at time of fetch |
| `sentiment` | `bullish` / `bearish` / `neutral` | Derived: MACD bullish + price above MA50 + RSI ≤ 70 → bullish; MACD bearish + price below MA50 → bearish; else neutral |
| `next_earnings_date` | Date | `yf.Ticker.calendar` next earnings date |
| `fetch_status` | `pending` / `ok` / `error` | Set to `ok` on success, `error` on failure |
| `fetch_error` | Text | Error message if fetch fails |
| `notes` | Text | User-entered free-text notes |

---

## Data Model

### `rationale` table changes

One Alembic migration:

1. Add column: `commentary_id UUID NULL REFERENCES commentary(id) ON DELETE CASCADE`
2. Drop existing `UniqueConstraint("trade_id", name="idx_rationale_trade")`
3. Add partial unique index: `UNIQUE (trade_id) WHERE commentary_id IS NULL` — preserves 1:1 guarantee for the trade's entry-time snapshot
4. Add index on `commentary_id`

### Row semantics

| `commentary_id` | `trade_id` | Meaning |
|---|---|---|
| NULL | set | Entry-time snapshot (trade rationale) |
| set | set | Per-commentary snapshot |

### `Commentary` model

Add `rationale` relationship (`uselist=False`, `cascade="all, delete-orphan"`, foreign key `rationale.commentary_id`).

`Trade.rationale` relationship stays unchanged — it resolves to the row where `commentary_id IS NULL` by virtue of the unique partial index and the existing `uselist=False` setup.

---

## Backend API

### New service: `backend/app/services/technicals_fetcher.py`

Single public function: `fetch_technicals(ticker: str) -> dict`

- Downloads 200 bars of **daily** history from yfinance for RSI-14, MA200, MA50, Bollinger Bands (20-day, 2σ), price action, day color
- Downloads 104 bars of **weekly** history for MACD (12-26-9 EMA)
- Calls `yf.Ticker(ticker).calendar` for next earnings date
- Derives `rsi_result`, `price_vs_ma200`, `price_vs_ma50`, `bollinger_position`, `macd_signal`, `macd_notes`, `sentiment` from computed values
- Returns a flat dict of all 19 fields plus `fetch_status` and `fetch_error`
- All computation is synchronous (runs in thread executor at the router level)

**Sentiment derivation heuristic:**
- `bullish`: MACD line > signal line AND price > MA50 AND RSI ≤ 70
- `bearish`: MACD line < signal line AND price < MA50
- `neutral`: anything else

### New endpoint: `GET /api/market/technicals/{ticker}`

- Runs `fetch_technicals` in a thread executor (same pattern as `/api/market/options/{ticker}`)
- Returns the flat dict — does **not** persist anything
- Returns 404 if ticker is not found / history is empty

### Extended endpoint: `PUT /api/trades/{trade_id}/rationale`

- Upserts the entry-time rationale row (`commentary_id = NULL`) for a trade
- Accepts all 19 rationale fields as an optional body (any subset)
- Used by the frontend after trade creation and from the trade edit form
- Sets `fetch_status = "ok"` on successful payload

### Extended endpoint: `POST /api/trades/{trade_id}/commentary`

- Request body gains an optional `rationale: RationaleCreate | null` sub-object
- If present, creates a `rationale` row with `commentary_id` set to the new comment's ID within the same DB transaction
- `CommentaryCreate` schema gains `rationale: Optional[RationaleCreate] = None`

### Extended endpoint: `GET /api/trades/{trade_id}/commentary`

- Eager-loads `rationale` for each comment via `selectinload`
- `CommentaryResponse` schema gains `rationale: Optional[RationaleResponse] = None`

---

## Frontend

### New component: `frontend/src/components/shared/TechnicalsPanel.tsx`

Props:
- `ticker: string`
- `initialData?: RationaleData | null`
- `onChange: (data: RationaleData | null) => void`

Behavior:
- Renders a "Fetch Technicals" button
- On click: calls `GET /api/market/technicals/{ticker}`, populates all fields
- All 19 fields rendered as controlled inputs (text inputs for numeric values; selects for `macd_signal`, `bollinger_position`, `day_color`, `sentiment`, `rsi_result`)
- User can edit any field before saving
- A "Clear" button resets to null (no snapshot attached)
- Shows a loading spinner during fetch and an error message on failure

### Trade form: `frontend/src/components/Trades/TradeForm.tsx`

- Adds a collapsible "Technicals" section below existing fields
- Contains `TechnicalsPanel`
- On trade save: creates trade first, then calls `PUT /api/trades/{trade_id}/rationale` with the panel's current value if non-null

### Commentary form: `frontend/src/components/Commentary/CommentaryForm.tsx`

- Adds an optional collapsible "Attach Technicals" section
- Contains `TechnicalsPanel`
- If user fetched technicals, the `rationale` sub-object is embedded in the `POST /api/trades/{trade_id}/commentary` body
- If not fetched (or cleared), `rationale` is omitted

### Commentary thread: `frontend/src/components/Commentary/CommentaryThread.tsx`

- Each comment with a non-null `rationale` shows a `📊 Technicals` chip below the note text
- Clicking the chip toggles an inline expanded panel showing all non-null rationale fields in a read-only 2-column grid
- No additional fetch on expand — data is already in the `CommentaryResponse`

---

## Chrome Extension

### Add-trade modal (`content.js`)

- A collapsible "Technicals" section is added below the `rationale_notes` textarea
- Contains a "Fetch Technicals" button; on click calls `GET /api/market/technicals/{ticker}` (ticker already known from the E*TRADE row)
- Response populates labeled `<input>` fields rendered inline, styled with existing `content.css` patterns
- All fields editable before submit
- On form submit: trade is created first, then a second request `PUT /api/trades/{trade_id}/rationale` sends the technicals payload
- A shared helper function `renderTechnicalsForm(container, ticker)` is extracted in `content.js` and reused across both modal and commentary panel

### Commentary panel (`content.js`)

- "Add Note" area gains an "Attach Technicals" toggle button
- Clicking expands the inline technicals form via `renderTechnicalsForm`
- Snapshot is sent embedded in the commentary POST body (same field as frontend)

### Commentary thread display (`content.js`)

- Each comment in the hover-reveal panel that has a non-null `rationale` gets a `📊` chip appended
- Clicking toggles an inline block showing non-null rationale fields
- Data comes from the already-loaded commentary response — no extra fetch

---

## Error Handling

- If `fetch_technicals` fails (network error, ticker not found, yfinance throttle), `fetch_status = "error"` and `fetch_error` is set. The user sees the error message in the panel and can retry or save without technicals.
- Saving without technicals is always allowed — the `rationale` sub-object is optional in all save paths.
- The trade's entry-time rationale row is always created (with `fetch_status = "pending"`) at trade creation time (existing behavior). The `PUT` endpoint upgrades it to `ok` once the user fetches and saves.

---

## Out of Scope

- Automatic background refresh of technicals (not scheduled; always on-demand)
- Editing a previously-saved rationale snapshot on a commentary (snapshots are immutable after save)
- Showing technicals history chart or trend across commentary entries
