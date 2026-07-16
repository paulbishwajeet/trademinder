# On-Demand Reconcile Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the auto-firing reconcile with a manually triggered "Reconcile" button injected adjacent to E*TRADE's native "Customize" button.

**Architecture:** All changes are in `extension/content.js`. Remove the auto-trigger from `processVisibleRows`, make `fireReconcile` return result data, and add `insertReconcileButton` which injects a button before `.PortfoliosFilters---customize-view---Ln4bT` and wires it to `fireReconcile`.

**Tech Stack:** Vanilla JS, Chrome extension content script (no build step)

## Global Constraints

- No backend changes — endpoint and response shape are unchanged.
- No new files — all changes are in `extension/content.js`.
- Button must have `id="tm-reconcile-btn"` for duplicate-injection guard.
- Button styled to match E*TRADE's `btn-block btn-link` pattern (text link, no background fill).
- No automated test harness exists for extension JS — verification is manual in Chrome.

---

### Task 1: Remove auto-reconcile trigger and dedup state

**Files:**
- Modify: `extension/content.js:60` (delete `lastReconcileKey` variable)
- Modify: `extension/content.js:440-443` (delete auto-fire block in `processVisibleRows`)
- Modify: `extension/content.js:865-867` (delete dedup guard in `fireReconcile`)

**Interfaces:**
- Produces: `fireReconcile(rows)` is no longer called automatically; the `lastReconcileKey` variable is gone.

- [ ] **Step 1: Delete `lastReconcileKey` state variable**

In `content.js`, find and delete this line (~line 60):
```js
let lastReconcileKey = '';
```

- [ ] **Step 2: Delete the auto-fire block from `processVisibleRows`**

Find and delete these lines (~lines 440-443):
```js
    // Fire-and-forget: reconcile all visible positions against backend
    if (rows.length > 0) {
      fireReconcile(rows);
    }
```

- [ ] **Step 3: Delete the dedup guard from `fireReconcile`**

Find and delete these lines (~lines 865-867) inside `fireReconcile`:
```js
  const posKey = keys.slice().sort().join(',');
  if (posKey === lastReconcileKey) return;
  lastReconcileKey = posKey;
```

- [ ] **Step 4: Verify manually**

Load the extension in Chrome (`chrome://extensions` → Load unpacked → select `extension/`). Open E*TRADE Portfolios. Confirm no reconcile network request fires on page load or scroll (check DevTools Network tab, filter by `/reconcile`).

- [ ] **Step 5: Commit**

```bash
git add extension/content.js
git commit -m "refactor(extension): remove auto-reconcile trigger and dedup state"
```

---

### Task 2: Make `fireReconcile` return result data

**Files:**
- Modify: `extension/content.js` — `fireReconcile` function (~line 845)

**Interfaces:**
- Consumes: existing `reconcileCache`, `bgFetch`, `tmApiUrl`, `ETRADE`, `getRowInfo`, `applyReconcilePillToRow`
- Produces: `fireReconcile(rows)` now returns `Promise<{ unmatched_etrade: Array, stale_backend: Array } | null>` — `null` on error or empty positions.

- [ ] **Step 1: Add return values to `fireReconcile`**

Replace the current `fireReconcile` function body so it returns `data` on success and `null` on early-exit or error. The full updated function:

```js
async function fireReconcile(rows) {
  const positions = [];
  const keys = [];

  rows.forEach(row => {
    const info = getRowInfo(row);
    if (!info) return;
    const key = info.fullSymbol || info.ticker;
    keys.push(key);
    positions.push({
      ticker: info.ticker,
      full_symbol: info.fullSymbol || null,
      type: info.optionDetails?.type || (info.isOption ? 'Option' : 'Stock'),
      strike: info.optionDetails?.strike || null,
      expiry: info.optionDetails?.expiry || null,
    });
  });

  if (positions.length === 0) return null;

  try {
    const resp = await bgFetch(`${tmApiUrl}/api/positions/reconcile`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ positions }),
      signal: AbortSignal.timeout(5000),
    });
    if (!resp.ok) return null;
    const data = await resp.json();

    reconcileCache.clear();
    (data.unmatched_etrade || []).forEach(item => {
      reconcileCache.set((item.full_symbol || item.ticker).toUpperCase(), true);
    });

    document.querySelectorAll(ETRADE.positionRows).forEach(row => {
      const info = getRowInfo(row);
      if (info) applyReconcilePillToRow(row, info);
    });

    return data;
  } catch (err) {
    if (err.name !== 'AbortError') {
      console.debug('TradeMinder: reconcile failed', err.message);
    }
    return null;
  }
}
```

- [ ] **Step 2: Verify manually**

In DevTools console on E*TRADE, run:
```js
const rows = document.querySelectorAll('[role="row"][level="0"]:not(.Row---placeholderRow---2t5Gs)');
window.fireReconcile(rows).then(d => console.log('reconcile result', d));
```
Expected: network request fires, result object logged with `unmatched_etrade` and `stale_backend` arrays.

*(Note: `fireReconcile` is not on `window` by default in a content script — this step is a conceptual check. The real verification is in Task 3 via the button.)*

- [ ] **Step 3: Commit**

```bash
git add extension/content.js
git commit -m "refactor(extension): make fireReconcile return result data"
```

---

### Task 3: Inject reconcile button adjacent to E*TRADE Customize button

**Files:**
- Modify: `extension/content.js` — add `insertReconcileButton()`, call it from `startObserver()`

**Interfaces:**
- Consumes: `fireReconcile(rows)`, `ETRADE.positionRows`, `document.getElementById('tm-reconcile-btn')`
- Produces: A `<div id="tm-reconcile-btn-wrap">` injected as the previous sibling of `.PortfoliosFilters---customize-view---Ln4bT`, containing a button that triggers reconcile on click.

- [ ] **Step 1: Add `insertReconcileButton` function**

Add this function after `insertFilterToolbar` (around line 1441):

```js
function insertReconcileButton() {
  if (document.getElementById('tm-reconcile-btn')) return;

  const target = document.querySelector('.PortfoliosFilters---customize-view---Ln4bT');
  if (!target?.parentNode) {
    setTimeout(insertReconcileButton, 500);
    return;
  }

  const wrap = document.createElement('div');
  wrap.id = 'tm-reconcile-btn-wrap';
  wrap.style.cssText = 'display:inline-block;margin-right:8px;';

  const btn = document.createElement('button');
  btn.id = 'tm-reconcile-btn';
  btn.className = 'btn-block btn-link';
  btn.type = 'button';
  btn.textContent = '🔄 Reconcile';

  btn.addEventListener('click', async () => {
    btn.disabled = true;
    btn.textContent = '⏳ Reconciling…';

    const rows = document.querySelectorAll(ETRADE.positionRows);
    const data = await fireReconcile(rows);

    if (data === null) {
      btn.textContent = '✗ Failed';
    } else {
      const n = (data.unmatched_etrade || []).length;
      btn.textContent = n === 0 ? '✓ All matched' : `⚠ ${n} unmatched`;
    }

    setTimeout(() => {
      btn.disabled = false;
      btn.textContent = '🔄 Reconcile';
    }, 2000);
  });

  wrap.appendChild(btn);
  target.parentNode.insertBefore(wrap, target);
}
```

- [ ] **Step 2: Call `insertReconcileButton` from `startObserver`**

In `startObserver`, add the call right after `insertFilterToolbar()`:

```js
function startObserver() {
  const contentArea = document.querySelector(ETRADE.contentArea);
  if (!contentArea) {
    setTimeout(startObserver, 500);
    return;
  }

  insertFilterToolbar();
  insertReconcileButton();   // ← add this line

  processVisibleRows();
  // ... rest unchanged
```

- [ ] **Step 3: Verify manually — button appearance**

Reload extension. Open E*TRADE Portfolios. Confirm:
- A "🔄 Reconcile" button appears to the left of the "Customize" button in the portfolio filters bar.
- Button looks like a text link (matching E*TRADE's Customize button style — no background fill).
- No duplicate button appears on scroll or re-render.

- [ ] **Step 4: Verify manually — button behavior**

Click the "🔄 Reconcile" button. Confirm:
- Button immediately shows "⏳ Reconciling…" and is disabled.
- Network request fires to `POST /api/positions/reconcile`.
- After response, button shows either "✓ All matched" or "⚠ N unmatched" for ~2 seconds.
- Button resets to "🔄 Reconcile" and re-enables after 2 seconds.
- Any `+` unmatched pills on position rows update correctly.

- [ ] **Step 5: Verify — no reconcile auto-fires**

Scroll the positions grid up and down. Confirm no `/reconcile` requests appear in DevTools Network tab.

- [ ] **Step 6: Commit**

```bash
git add extension/content.js
git commit -m "feat(extension): add on-demand reconcile button next to Customize"
```
