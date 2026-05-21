# Feature: Technicals Capture

**Branch:** `master`
**Spec:** `docs/superpowers/specs/2026-05-19-technicals-capture-design.md`
**Plan:** `docs/superpowers/plans/2026-05-19-technicals-capture.md`

---

## Progress Log

| Date | Summary |
|------|---------|
| 2026-05-19 | Full feature implemented end-to-end: yfinance fetcher service, technicals API endpoint, rationale upsert endpoint, DB migration 005, commentary endpoint extensions, frontend TechnicalsPanel + TradeForm + CommentaryForm + CommentaryThread, extension `renderTechnicalsForm()` helper, technicals in add-trade modal, technicals in commentary panel. |
| 2026-05-19 | Post-feature bug fixes: add-trade modal widened to 520px (horizontal scroll), commentary panel repositioned relative to row (was fixed to window right edge), submit button pinned above scrolling technicals, `etrade_symbol` extraction fixed for stock rows, commentary badge cross-contamination fixed via strategy-type validation. |
| 2026-05-20 | Four more extension bug fixes: (1) panel now opens near badge pill position (pill rect used for horizontal anchor, not row right edge); (2) note textarea/tags extracted to `.tm-cp-form-static` (fixed height) — technicals in separate `.tm-cp-form-tech` (scrollable); (3) entry-time rationale fetched via `GET /api/trades/{id}` and shown as oldest thread item with purple left border; (4) price paid rounded to 2dp before populating the add-trade modal input. Panel widened to 400px, max-height to 600px. |

---

## Current State

**All feature code is merged to `master`. The feature is fully functional locally but has NOT been deployed to production (QNAP) yet.**

Migration 005 (`005_commentary_rationale_link.py`) adds `commentary_id` FK to the `rationale` table, drops the old unique constraint on `(trade_id)`, and replaces it with a partial unique index `UNIQUE (trade_id) WHERE commentary_id IS NULL`. This migration must be applied before any technicals endpoints will work on the production DB.

The Chrome extension's commentary panel now shows entry-time rationale (📊 chip) as the first thread item when `fetch_status = 'ok'`. Commentary notes can optionally carry their own technicals snapshot. The add-trade modal has a collapsible Technicals section that fires a second `PUT /api/trades/{id}/rationale` call after trade creation.

**Single next action:** On the QNAP, run `git pull && docker compose -f docker-compose.prod.yml build && docker compose -f docker-compose.prod.yml up -d`, then exec into the backend container and run `alembic upgrade head` to apply migration 005. Reload the Chrome extension and verify `📊 Fetch Technicals` returns data for a live ticker.

---

## Key Files

| File | Role |
|------|------|
| `backend/app/services/technicals_fetcher.py` | **New.** Single public function `fetch_technicals(ticker)` — downloads 200 daily + 104 weekly bars from yfinance, computes all 19 fields, derives sentiment/signal/position labels |
| `backend/app/routers/market.py` | Extended: `GET /api/market/technicals/{ticker}` runs fetcher in thread executor, returns flat dict, 404 on empty history |
| `backend/app/routers/trades.py` | Extended: `PUT /api/trades/{id}/rationale` upserts entry-time rationale row (`commentary_id IS NULL`) |
| `backend/app/routers/commentary.py` | Extended: POST accepts `rationale: RationaleCreate \| null` sub-object, creates rationale row in same transaction; GET eager-loads `rationale` via `selectinload` |
| `backend/app/schemas/trade.py` | Extended: `RationaleCreate`, `RationaleResponse` (19 fields + `fetch_status`, `fetch_error`, `notes`, `commentary_id`); `TradeResponse` gains `rationale: Optional[RationaleResponse]` |
| `backend/alembic/versions/005_commentary_rationale_link.py` | **New.** Adds `commentary_id UUID NULL REFERENCES commentary(id) ON DELETE CASCADE` to `rationale`; drops old unique constraint; adds partial unique index + index on `commentary_id` |
| `backend/tests/test_trade_rationale.py` | **New.** Tests for PUT /api/trades/{id}/rationale (create + upsert) |
| `backend/tests/test_market_technicals.py` | **New.** Tests for GET /api/market/technicals/{ticker} (mock yfinance) |
| `backend/tests/test_commentary_rationale.py` | **New.** Tests for POST commentary with embedded rationale; GET returns rationale |
| `frontend/src/types/index.ts` | Extended: `TechnicalsData` type (19 fields); `Commentary` type gains `rationale?: TechnicalsData \| null` |
| `frontend/src/api/technicals.ts` | **New.** `technicalsApi.fetch(ticker)` and `technicalsApi.saveTradeRationale(tradeId, data)` |
| `frontend/src/api/commentary.ts` | Extended: `add()` payload gains `rationale?: TechnicalsData \| null` |
| `frontend/src/components/shared/TechnicalsPanel.tsx` | **New.** Controlled panel: Fetch button, 19 editable fields (selects for enum fields, number inputs for decimals), Clear button, loading/error states |
| `frontend/src/components/Trades/TradeForm.tsx` | Extended: collapsible Technicals section; `onSubmit` receives `(payload, technicals \| null)` |
| `frontend/src/pages/TradesPage.tsx` | Extended: `handleCreate` saves technicals via `PUT /rationale` after trade creation (non-blocking) |
| `frontend/src/components/Commentary/CommentaryForm.tsx` | Extended: collapsible "Attach Technicals" section; embeds snapshot in POST body if present |
| `frontend/src/components/Commentary/CommentaryThread.tsx` | Extended: each entry with `rationale` shows a `📊 Technicals` chip; click toggles inline read-only grid |
| `extension/content.js` | Extended: `renderTechnicalsForm(container, ticker)` helper returns `{ getValue() }`; technicals section in add-trade modal; technicals toggle in commentary panel; rationale chip in thread; entry-time rationale shown as first thread item; `_hoverPill` stored for panel positioning; form split into `.tm-cp-form-static` + `.tm-cp-form-tech` |
| `extension/content.css` | Extended: `.tm-tech-*` styles for the technicals panel in both modal and commentary panel; `.tm-rationale-chip`, `.tm-rationale-detail`; `.tm-cp-form-static`, `.tm-cp-form-tech`; `.tm-cp-entry-snapshot` (purple left border) |

---

## Decisions Made

- **Single `rationale` table, context determined by `commentary_id` nullability** — `commentary_id IS NULL` = entry-time snapshot; `commentary_id SET` = per-commentary snapshot. A partial unique index enforces the 1:1 guarantee for entry-time rows without breaking per-commentary rows.
- **Technicals endpoint is read-only (no auto-persist)** — `GET /api/market/technicals/{ticker}` always returns a fresh fetch and never writes to DB. The user decides whether to save by completing the form submission.
- **Synchronous fetcher, thread executor at router level** — `fetch_technicals` is blocking (yfinance is sync); the FastAPI router wraps it in `asyncio.get_event_loop().run_in_executor(None, ...)`, matching the existing options endpoint pattern.
- **Sentiment derived, not user-editable** — bullish = MACD line > signal AND price > MA50 AND RSI ≤ 70; bearish = MACD line < signal AND price < MA50; else neutral. User sees computed value as a pre-filled editable field.
- **Entry-time rationale only shown in thread when `fetch_status = 'ok'`** — pending/error rationale rows exist (created at trade creation) but are not shown in the thread to avoid noise.
- **Extension panel uses pill rect for horizontal anchor** — `_hoverPill` (the `.tm-commentary-btn` element) rect drives `panel.style.left`; vertical anchor still uses the full row rect (needed to determine open direction).
- **`renderTechnicalsForm` returns `{ getValue() }`** — the form is a self-contained DOM tree; callers hold the control object and call `getValue()` at submit time. Panel state (`panel._techControl`) is reset on trade switch to avoid stale data.
- **Price paid rounded to 2dp at modal population time** — `Math.round(pricePaid * 100) / 100` applied in `showAddTradeModal`. E*TRADE reports prices with 4+ decimal places; the modal's `step="0.01"` validation then passes cleanly.

---

## Open Questions

- **Migration 005 not yet applied to QNAP production DB** — technicals endpoints will return 500 until the migration runs. The `rationale` table exists but lacks the `commentary_id` column.
- **yfinance throttling in production** — yfinance can rate-limit or return stale data for high-frequency requests. No retry logic is implemented; `fetch_status = 'error'` surfaces the error message to the user who can retry manually.
- **Entry-time rationale creation date** — the thread displays `trade.open_date` as the entry snapshot date. If the technicals were actually fetched days after the trade was opened, the date is misleading. No `fetched_at` timestamp is stored on the rationale row.
- **Bollinger + MACD on low-history tickers** — `fetch_technicals` requires ≥ 200 daily bars for MA200 and ≥ 104 weekly bars for MACD. Newer tickers or tickers with sparse history may return `null` for some fields without a user-facing explanation.
