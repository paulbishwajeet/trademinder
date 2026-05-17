# Extension Context

**Branch:** `develop` (all recent work merged here from `commentary-extension`)
**Files:** `extension/content.js`, `extension/content.css`, `extension/manifest.json`, `extension/background.js`, `extension/popup/`

---

## What the Extension Does

Chrome MV3 content script that overlays TradeMinder data directly onto the E*TRADE positions page. It:
- Injects a badge into every position row showing DTE (for options), RSI pill, and commentary count
- Colors each row and adds a left border based on alert severity or category
- Provides a filter toolbar above the grid (by category + RSI fetch button)
- Lets users open a floating commentary panel per trade via a hover-reveal trigger
- Supports right-click → "Add to TradeMinder" modal via context menu (background.js)

---

## E*TRADE DOM — Critical Facts

**Grid structure:**
- Grid root: `#rdt_3`
- Content area (MutationObserver target): `.Content---root---D2Ylg`
- Position rows: `[role="row"][level="0"]:not(.Row---placeholderRow---2t5Gs)`
- Rows use `position:absolute; transform:translateY(Xpx)` — virtual scroll
- Row `overflow` is `visible` by default (columns can bleed outside row bounds)
- Columns are flex children with `min-width`/`width` only (no absolute positioning per column)

**Key column selectors:**
- `col="1"` = Actions column (65px wide, contains Alert + Note buttons inside `ActionsCellRenderer---root---sNuFp`)
- Column header text (after `&nbsp;` normalization): `"qty #"`, `"price paid $"` — resolved via `buildColumnMap()`
- Symbol cell: `.SymbolCellRenderer---content---mcwCT`, link: `a.SymbolCellRenderer---symbol---_S70m`
- Option detection: class `SymbolCellRenderer---option---qIlje` on the symbol root
- ITM detection: class `SymbolCellRenderer---in-the-money---AQRUo`

**E*TRADE click behavior:**
- E*TRADE uses **capture-phase** click listeners on rows to expand them
- `stopPropagation()` in a bubble-phase handler does NOT prevent row expansion
- Solution: the commentary pill (`.tm-commentary-btn`) has NO click handler; hover reveals a `position:fixed` button on `document.body` (`#tm-commentary-trigger`) which is never a DOM descendant of any row, so no capture listener ever fires on it

**React renderer wiping injected content:**
- E*TRADE's React can clear the Actions cell content on scroll/re-render
- Guard in `processVisibleRows`: `const badgeMissing = !row.querySelector('.tm-badge')` forces re-injection whenever the badge disappears

---

## Badge Injection — Current Approach

Badge (`div.tm-badge`) is injected **inside `[col="1"]`** (Actions cell):
```js
badge.style.cssText = 'display:inline-flex;align-items:center;white-space:nowrap;pointer-events:auto;';
const actionsCell = row.querySelector('[col="1"]');
if (actionsCell) {
  actionsCell.style.overflow = 'visible';  // lets badge extend past 65px without breaking layout
  actionsCell.appendChild(badge);
} else {
  // Fallback: absolute position on the row
  badge.style.cssText += 'position:absolute;left:339px;top:50%;transform:translateY(-50%);z-index:100;';
  row.style.overflow = 'visible';
  row.appendChild(badge);
}
```

**Why inside the Actions cell, not as a new column sibling:**
Earlier approach used `position:absolute; right:-195px` on the row — this visually worked but the badge wasn't actually in the Actions column. Trying to append as a flex sibling broke E*TRADE's column layout. The `overflow:visible` + `appendChild` approach puts the badge in the right DOM location without disturbing column widths.

**Current badge contents** (as of last commit `0f09a36`):
```js
badge.innerHTML = dte != null ? `<span class="tm-dte">${dte}d</span>` : '';
// Then: commentary btn appended via JS (see below)
// Then: RSI pill appended via applyRsiToRow()
```
The `tm-tag tm-urgent` status span was intentionally removed — the badge now shows only DTE + commentary count + RSI.

---

## Commentary Panel — Architecture

**Hover-reveal pattern (avoids E*TRADE capture listeners):**
1. `.tm-commentary-btn` (pill in the badge) has only `mouseenter`/`mouseleave` handlers
2. On `mouseenter`, `showCommentaryTrigger()` positions `#tm-commentary-trigger` (a `position:fixed` button on `document.body`) over the pill
3. User hovers onto trigger (150ms grace window prevents flicker), clicks it
4. `openCommentaryPanel()` opens `#tm-commentary-panel` floating panel

**State variables:**
```js
const commentaryCountCache = new Map();  // trade_id → count
let _panelClickOutside = null;           // cleanup ref
let _panelEsc = null;                    // cleanup ref
let _threadAbortCtrl = null;             // AbortController for in-flight fetch
let _hoverTrigger = null;                // the body-level trigger button
let _hoverHideTimer = null;              // setTimeout for hide delay
let _hoverTradeId = null;
let _hoverTicker = null;
let _hoverRow = null;
```

**Panel features:**
- Loads commentary thread from `GET /api/trades/:id/commentary`
- Shows entries with date, note text, tags, and delete button
- Add note form: textarea + tags input (comma-separated) + submit
- Submit: `POST /api/trades/:id/commentary` → re-renders thread → updates badge count
- In-flight cancellation: new `AbortController` on every `renderCommentaryThread` call, previous aborted
- `finally` block resets submit button after await, regardless of success/error
- Click-outside and Escape close the panel

---

## RSI

- Fetched on demand via "📊 Fetch RSI" button in toolbar
- Batch request: `POST /api/market/rsi` with `{ tickers: [...] }`
- **Response shape (updated):** `{ "AAPL": { "rsi": 52.3, "price": 213.40 }, "BADTICKER": null }` — each value is a `{rsi, price}` object or `null`, not a bare float. `fetchRsiForAll` extracts `val.rsi` with a type guard: `val && typeof val === 'object' ? val.rsi : null`
- Results stored in `rsiCache: Map<ticker, number|null>` (only RSI stored; price is used by MarginDashboardPage separately)
- Applied to badge as `.tm-rsi-pill` with class based on value:
  - `< 30` → `rsi-oversold` (green)
  - `30–40` → `rsi-near-oversold`
  - `40–60` → `rsi-neutral`
  - `60–70` → `rsi-near-overbought`
  - `> 70` → `rsi-overbought` (red)
  - fetch failed → `rsi-error`

---

## Backend API — Extension Endpoints

Base URL: `http://localhost:5431` (configurable via chrome.storage in popup)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/categories` | All categories (for filter toolbar) |
| POST | `/api/positions/status` | Batch status for visible rows |
| GET | `/api/trades/:id/commentary` | Load commentary thread + count |
| POST | `/api/trades/:id/commentary` | Add commentary note |
| DELETE | `/api/commentary/:id` | Delete a note |
| POST | `/api/market/rsi` | Batch RSI + price fetch — returns `{rsi, price}` per ticker |
| POST | `/api/trades` | Add new trade (from modal) |

---

## Known Deferred Issues

- **Actions column width overlap:** The 65px Actions cell is narrow; badge content can visually overlap with the Alert/Note buttons inside it. Deferred — removed the status span to reduce width, but haven't addressed the layout more deeply.
- **Commentary count cache staleness:** Count is fetched once per session per `trade_id` and only updated after a delete or add in the open panel. If notes are added from the web app, count won't update until page reload.

---

## Recent Commit History

```
573521e  docs: update context files with new port assignments (5430/5431/5432)
121e6f0  chore: reassign application ports (frontend 5430, backend 5431, postgres 5432)
495ac9e  fix: update extension fetchRsiForAll to read new {rsi, price} response shape
0f09a36  feat: remove status tag from badge, keep only DTE and RSI/commentary
1941a36  fix: inject TM badge inside Actions cell (col=1) after ActionsCellRenderer
```

---

## Loading the Extension

1. Open Chrome → `chrome://extensions`
2. Enable Developer Mode
3. "Load unpacked" → select `extension/` directory
4. Navigate to E*TRADE portfolio page
5. Requires local backend running on port 5431 (`docker-compose up` or `uvicorn` in `backend/`)
