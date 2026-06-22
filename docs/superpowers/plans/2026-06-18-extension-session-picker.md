# Extension Session Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalise the Chrome extension's session dropdown in both add-trade and edit-trade modals to support WHEEL, IRON_CONDOR, and PUT_B_W_FLY sessions with strategy-aware filtering, auto-category, and auto-transition.

**Architecture:** Single-file change to `extension/content.js`. A shared `rebuildSessionDropdown()` helper builds `<option>` elements from the already-cached `allActiveSessions` array filtered by ticker and trade strategy. Both modals wire a `change` listener on the strategy `<select>` to dynamically rebuild the session dropdown, and a `change` listener on the session `<select>` to auto-set category. On save, if a WHEEL session was selected, a PATCH transitions the session status.

**Tech Stack:** Vanilla JS (Chrome MV3 content script), existing REST API endpoints

## Global Constraints

- No backend changes — all existing endpoints are sufficient
- `allActiveSessions` is already fetched via `GET /api/sessions/active` with 60s TTL — reuse it, don't add a new API call
- The `fetchAllActiveSessions(true)` force-refresh must be called before populating the dropdown to ensure fresh data
- Session creation uses `POST /api/sessions` (existing)
- Session status transition uses `PATCH /api/sessions/{id}` (existing)
- Trade PATCH uses `PATCH /api/trades/{id}` with `session_id` field (existing, `exclude_none=True` — can set but not clear to null)
- Label format: `WHL · TICKER · Status Label · opened YYYY-MM-DD` for WHEEL, `IC · TICKER · opened YYYY-MM-DD` for IC, `PBWB · TICKER · opened YYYY-MM-DD` for PBWB

---

### Task 1: Add `rebuildSessionDropdown` helper and refactor add-trade modal

**Files:**
- Modify: `extension/content.js:1468-1728` (add-trade modal)
- Modify: `extension/content.js:1569-1596` (spread session population block — replaced)

**Interfaces:**
- Consumes: `allActiveSessions` (global array, populated by `fetchAllActiveSessions`)
- Consumes: `sessionsApi` endpoints: `POST /api/sessions`, `PATCH /api/sessions/{id}`
- Produces: `rebuildSessionDropdown(selectEl, sessions, strategy)` — standalone helper used by Task 2
- Produces: `getSessionStrategyFromValue(value, sessions)` — returns strategy string for a selected option value (UUID or sentinel)

**Context for implementer:**

The file is `extension/content.js` — a ~1900-line vanilla JS Chrome content script. Key state:
- `allActiveSessions` (line 39): array of session objects from `GET /api/sessions/active`. Each has: `id`, `ticker`, `strategy`, `status`, `opened_at`, `legs[]`. Refreshed every 60s via `fetchAllActiveSessions()` (line 1280).
- The add-trade modal `showAddTradeModal(info)` starts at line 1468. `info` has: `ticker`, `isOption`, `type` ("Put"/"Call"), `fullSymbol`, `strike`, `expiry`, `quantity`, `pricePaid`.
- The current "Spread Session" dropdown (lines 1520-1526 in HTML, lines 1569-1596 population) fetches from `/api/sessions?ticker=X&status=open` which defaults to `strategy=WHEEL` on the backend — meaning it never actually finds IC/PBWB sessions. This is being replaced entirely.

- [ ] **Step 1: Add `rebuildSessionDropdown` helper function**

Insert this function before `showAddTradeModal` (around line 1465), after the existing `buildCategoryOptions` helper:

```javascript
const WHEEL_STATUS_LABELS = {
  put_open: 'Put Open',
  shares_sitting: 'Shares Sitting',
  cc_open: 'CC Open',
  called_away: 'Called Away',
  completed: 'Completed',
};

function rebuildSessionDropdown(selectEl, sessions, strategy) {
  const isCC = strategy === 'Sell Call' || strategy === 'Covered Call';
  const isPut = strategy === 'Sell Put';

  const filtered = sessions.filter(s => {
    if (s.strategy === 'WHEEL') {
      if (isCC) return s.status === 'shares_sitting';
      if (isPut) return s.status === 'called_away';
      return false;
    }
    if (s.strategy === 'IRON_CONDOR' || s.strategy === 'PUT_B_W_FLY') {
      return !isCC;
    }
    return false;
  });

  const options = filtered.map(s => {
    let label;
    if (s.strategy === 'WHEEL') {
      const statusLabel = WHEEL_STATUS_LABELS[s.status] || s.status;
      label = `WHL · ${s.ticker} · ${statusLabel} · opened ${s.opened_at}`;
    } else {
      const tag = s.strategy === 'IRON_CONDOR' ? 'IC' : 'PBWB';
      label = `${tag} · ${s.ticker} · opened ${s.opened_at}`;
    }
    return `<option value="${s.id}">${label}</option>`;
  });

  const newOptions = [];
  if (isCC || isPut) {
    newOptions.push('<option value="__new_WHEEL__">→ New Wheel Session</option>');
  }
  if (!isCC) {
    newOptions.push('<option value="__new_IC__">→ New Iron Condor Session</option>');
    newOptions.push('<option value="__new_PBWB__">→ New Put BWB Session</option>');
  }

  selectEl.innerHTML =
    '<option value="">— None —</option>' +
    options.join('') +
    newOptions.join('');
}

function getSessionStrategyFromValue(value, sessions) {
  if (value === '__new_WHEEL__') return 'WHEEL';
  if (value === '__new_IC__') return 'IRON_CONDOR';
  if (value === '__new_PBWB__') return 'PUT_B_W_FLY';
  const match = sessions.find(s => String(s.id) === value);
  return match ? match.strategy : null;
}
```

- [ ] **Step 2: Update the add-trade modal HTML — rename label and remove old loading state**

In `showAddTradeModal`, change the session dropdown HTML (lines 1520-1526) from:

```javascript
        ${info.isOption ? `
        <div class="tm-field-row tm-field-full" id="tm-session-row">
          <label>Spread Session <span style="font-weight:normal;color:#6B7280">(optional)</span></label>
          <select name="session_id" id="tm-session-select">
            <option value="">Loading…</option>
          </select>
        </div>` : ''}
```

to:

```javascript
        ${info.isOption ? `
        <div class="tm-field-row tm-field-full" id="tm-session-row">
          <label>Session <span style="font-weight:normal;color:#6B7280">(optional)</span></label>
          <select name="session_id" id="tm-session-select">
            <option value="">— None —</option>
          </select>
        </div>` : ''}
```

- [ ] **Step 3: Replace the old session population block with new logic**

Replace the entire block at lines 1569-1596 (the `if (info.isOption)` block that fetches from `/api/sessions?ticker=...`) with:

```javascript
  if (info.isOption) {
    const sessionSelect = overlay.querySelector('#tm-session-select');
    const strategySelect = overlay.querySelector('[name="strategy"]');
    const categorySelect = overlay.querySelector('[name="category"]');
    const ticker = (info.ticker || '').toUpperCase();

    await fetchAllActiveSessions(true);
    const tickerSessions = allActiveSessions.filter(
      s => s.ticker.toUpperCase() === ticker,
    );

    rebuildSessionDropdown(sessionSelect, tickerSessions, strategySelect.value);

    strategySelect.addEventListener('change', () => {
      rebuildSessionDropdown(sessionSelect, tickerSessions, strategySelect.value);
    });

    sessionSelect.addEventListener('change', () => {
      const strat = getSessionStrategyFromValue(sessionSelect.value, tickerSessions);
      if (strat) {
        const catMap = { WHEEL: 'WHEEL', IRON_CONDOR: 'IRON_CONDOR', PUT_B_W_FLY: 'PUT_B_W_FLY' };
        const catName = catMap[strat];
        if (catName) {
          const catOption = categorySelect.querySelector(`option[value="${catName}"]`);
          if (catOption) categorySelect.value = catName;
        }
      }
    });
  }
```

- [ ] **Step 4: Update the add-trade submit handler — session creation and auto-transition**

Replace the session resolution block in the submit handler (lines 1651-1676) with:

```javascript
    let resolvedSessionId = null;
    let resolvedSessionStrategy = null;
    const rawSession = info.isOption ? (fd.get('session_id') || '') : '';
    if (rawSession && !rawSession.startsWith('__new_')) {
      resolvedSessionId = rawSession;
      resolvedSessionStrategy = getSessionStrategyFromValue(rawSession, tickerSessions);
    } else if (rawSession.startsWith('__new_')) {
      if (rawSession === '__new_WHEEL__') {
        const wheelStatus = (fd.get('strategy') === 'Sell Put') ? 'put_open' : 'cc_open';
        const sessionResp = await fetch(`${tmApiUrl}/api/sessions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ticker: payload.ticker,
            strategy: 'WHEEL',
            status: wheelStatus,
            opened_at: payload.open_date,
          }),
          signal: AbortSignal.timeout(8000),
        });
        if (!sessionResp.ok) {
          const err = await sessionResp.json().catch(() => ({}));
          throw new Error(err.detail || 'Failed to create session');
        }
        const newSession = await sessionResp.json();
        resolvedSessionId = newSession.id;
        resolvedSessionStrategy = 'WHEEL';
      } else {
        const strategy = rawSession === '__new_IC__' ? 'IRON_CONDOR' : 'PUT_B_W_FLY';
        const sessionResp = await fetch(`${tmApiUrl}/api/sessions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ticker: payload.ticker,
            strategy,
            status: 'open',
            opened_at: payload.open_date,
          }),
          signal: AbortSignal.timeout(8000),
        });
        if (!sessionResp.ok) {
          const err = await sessionResp.json().catch(() => ({}));
          throw new Error(err.detail || 'Failed to create session');
        }
        const newSession = await sessionResp.json();
        resolvedSessionId = newSession.id;
        resolvedSessionStrategy = strategy;
      }
    }
    if (resolvedSessionId) payload.session_id = resolvedSessionId;
```

Note: `tickerSessions` needs to be accessible from the submit handler. Move the `const tickerSessions` declaration to the function scope (before the `overlay.innerHTML` assignment) so it's available in both the population block and the submit handler. Declare it as `let tickerSessions = [];` at the top of `showAddTradeModal`, then assign in the `if (info.isOption)` block.

- [ ] **Step 5: Add WHEEL auto-transition after trade creation**

In the submit handler, after the trade is successfully created (after `const trade = await resp.json();` at line 1691), add the auto-transition logic before the technicals save:

```javascript
      // Auto-transition WHEEL session status when a leg is attached
      if (resolvedSessionId && resolvedSessionStrategy === 'WHEEL') {
        const tradeStrategy = fd.get('strategy');
        const selectedSession = tickerSessions.find(s => String(s.id) === resolvedSessionId);
        let newStatus = null;
        if ((tradeStrategy === 'Sell Call' || tradeStrategy === 'Covered Call')
            && selectedSession?.status === 'shares_sitting') {
          newStatus = 'cc_open';
        } else if (tradeStrategy === 'Sell Put' && selectedSession?.status === 'called_away') {
          newStatus = 'put_open';
        }
        if (newStatus) {
          try {
            await fetch(`${tmApiUrl}/api/sessions/${resolvedSessionId}`, {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ status: newStatus }),
              signal: AbortSignal.timeout(5000),
            });
          } catch (e) {
            console.debug('[TM] session auto-transition failed:', e.message);
          }
        }
      }
```

- [ ] **Step 6: Commit**

```bash
git add extension/content.js
git commit -m "feat: generalise extension session picker — WHEEL/IC/PBWB with strategy-aware filtering"
```

---

### Task 2: Add session dropdown to edit-trade modal

**Files:**
- Modify: `extension/content.js:1733-1903` (edit-trade modal)

**Interfaces:**
- Consumes: `rebuildSessionDropdown(selectEl, sessions, strategy)` from Task 1
- Consumes: `getSessionStrategyFromValue(value, sessions)` from Task 1
- Consumes: `allActiveSessions` global, `fetchAllActiveSessions(force)` function
- Consumes: `trade.session_id` from `GET /api/trades/{id}` response

**Context for implementer:**

The edit-trade modal `showEditTradeModal(info)` starts at line 1733. It:
1. Looks up the trade by `etrade_symbol` or ticker (lines 1736-1754)
2. Fetches full trade detail via `GET /api/trades/{id}` (lines 1756-1764) — response includes `session_id` (UUID or null)
3. Renders form pre-filled from trade data (lines 1773-1839)
4. Submit handler PATCHes `PUT /api/trades/{id}` (lines 1849-1902) — `TradeUpdate` schema accepts `session_id`

The edit modal currently has NO session dropdown. We're adding one between the Category and Strike fields, using the same `rebuildSessionDropdown` helper from Task 1.

The PATCH endpoint uses `model_dump(exclude_none=True)`, so we can SET `session_id` but not CLEAR it to null. The dropdown will show "— None —" but selecting it simply omits `session_id` from the payload (no change).

- [ ] **Step 1: Add session dropdown HTML to edit modal form**

In the `overlay.innerHTML` template inside `showEditTradeModal`, after the Category field block (after line 1809 — the closing `</div>` of the category `tm-field-row`) and before the Strike field (line 1810), insert:

```javascript
        <div class="tm-field-row tm-field-full" id="tm-session-row">
          <label>Session <span style="font-weight:normal;color:#6B7280">(optional)</span></label>
          <select name="session_id" id="tm-session-select">
            <option value="">— None —</option>
          </select>
        </div>
```

- [ ] **Step 2: Populate session dropdown after modal is appended to DOM**

After `document.body.appendChild(overlay);` (line 1842), add session population logic:

```javascript
  // Populate session picker
  let tickerSessions = [];
  {
    const sessionSelect = overlay.querySelector('#tm-session-select');
    const strategySelect = overlay.querySelector('[name="strategy"]');
    const categorySelect = overlay.querySelector('[name="category"]');
    const ticker = (trade.ticker || '').toUpperCase();

    await fetchAllActiveSessions(true);
    tickerSessions = allActiveSessions.filter(
      s => s.ticker.toUpperCase() === ticker,
    );

    rebuildSessionDropdown(sessionSelect, tickerSessions, strategySelect.value);

    // Pre-select current session if trade is linked
    if (trade.session_id) {
      const currentId = String(trade.session_id);
      const exists = sessionSelect.querySelector(`option[value="${currentId}"]`);
      if (exists) {
        sessionSelect.value = currentId;
      } else {
        // Session exists but filtered out (different status) — add as disabled option
        const s = allActiveSessions.find(s => String(s.id) === currentId);
        if (s) {
          const tag = s.strategy === 'WHEEL' ? 'WHL'
            : s.strategy === 'IRON_CONDOR' ? 'IC' : 'PBWB';
          const lbl = s.strategy === 'WHEEL'
            ? `${tag} · ${s.ticker} · ${WHEEL_STATUS_LABELS[s.status] || s.status} · opened ${s.opened_at}`
            : `${tag} · ${s.ticker} · opened ${s.opened_at}`;
          const opt = document.createElement('option');
          opt.value = currentId;
          opt.textContent = lbl;
          sessionSelect.insertBefore(opt, sessionSelect.options[1]);
          sessionSelect.value = currentId;
        }
      }
    }

    strategySelect.addEventListener('change', () => {
      const prevValue = sessionSelect.value;
      rebuildSessionDropdown(sessionSelect, tickerSessions, strategySelect.value);
      // Restore selection if it's still in the rebuilt list
      const stillExists = sessionSelect.querySelector(`option[value="${prevValue}"]`);
      if (stillExists) sessionSelect.value = prevValue;
    });

    sessionSelect.addEventListener('change', () => {
      const strat = getSessionStrategyFromValue(sessionSelect.value, tickerSessions);
      if (strat) {
        const catMap = { WHEEL: 'WHEEL', IRON_CONDOR: 'IRON_CONDOR', PUT_B_W_FLY: 'PUT_B_W_FLY' };
        const catName = catMap[strat];
        if (catName) {
          const catOption = categorySelect.querySelector(`option[value="${catName}"]`);
          if (catOption) categorySelect.value = catName;
        }
      }
    });
  }
```

- [ ] **Step 3: Update edit-trade submit handler to include session_id and auto-transition**

In the submit handler (around line 1861), after the `payload` object is built, add session handling before the `try { const resp = await fetch(...)` block:

```javascript
    // Resolve session_id: create new if sentinel, use existing if UUID, omit if unchanged
    const rawSession = fd.get('session_id') || '';
    let resolvedSessionId = null;
    let resolvedSessionStrategy = null;
    const sessionChanged = rawSession !== String(trade.session_id || '');

    if (sessionChanged && rawSession && !rawSession.startsWith('__new_')) {
      resolvedSessionId = rawSession;
      resolvedSessionStrategy = getSessionStrategyFromValue(rawSession, tickerSessions);
      payload.session_id = resolvedSessionId;
    } else if (rawSession.startsWith('__new_')) {
      if (rawSession === '__new_WHEEL__') {
        const wheelStatus = (fd.get('strategy') === 'Sell Put') ? 'put_open' : 'cc_open';
        const sessionResp = await fetch(`${tmApiUrl}/api/sessions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ticker: payload.ticker || trade.ticker.toUpperCase(),
            strategy: 'WHEEL',
            status: wheelStatus,
            opened_at: trade.open_date,
          }),
          signal: AbortSignal.timeout(8000),
        });
        if (!sessionResp.ok) {
          const err = await sessionResp.json().catch(() => ({}));
          throw new Error(err.detail || 'Failed to create session');
        }
        const newSession = await sessionResp.json();
        resolvedSessionId = newSession.id;
        resolvedSessionStrategy = 'WHEEL';
        payload.session_id = resolvedSessionId;
      } else {
        const strategy = rawSession === '__new_IC__' ? 'IRON_CONDOR' : 'PUT_B_W_FLY';
        const sessionResp = await fetch(`${tmApiUrl}/api/sessions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ticker: payload.ticker || trade.ticker.toUpperCase(),
            strategy,
            status: 'open',
            opened_at: trade.open_date,
          }),
          signal: AbortSignal.timeout(8000),
        });
        if (!sessionResp.ok) {
          const err = await sessionResp.json().catch(() => ({}));
          throw new Error(err.detail || 'Failed to create session');
        }
        const newSession = await sessionResp.json();
        resolvedSessionId = newSession.id;
        resolvedSessionStrategy = strategy;
        payload.session_id = resolvedSessionId;
      }
    }
```

Then, after the successful PATCH response (after `if (!resp.ok)` check), add auto-transition:

```javascript
      // Auto-transition WHEEL session status when a leg is attached
      if (resolvedSessionId && resolvedSessionStrategy === 'WHEEL') {
        const tradeStrategy = fd.get('strategy');
        const selectedSession = tickerSessions.find(s => String(s.id) === resolvedSessionId);
        let newStatus = null;
        if ((tradeStrategy === 'Sell Call' || tradeStrategy === 'Covered Call')
            && selectedSession?.status === 'shares_sitting') {
          newStatus = 'cc_open';
        } else if (tradeStrategy === 'Sell Put' && selectedSession?.status === 'called_away') {
          newStatus = 'put_open';
        }
        if (newStatus) {
          try {
            await fetch(`${tmApiUrl}/api/sessions/${resolvedSessionId}`, {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ status: newStatus }),
              signal: AbortSignal.timeout(5000),
            });
          } catch (e) {
            console.debug('[TM] session auto-transition failed:', e.message);
          }
        }
      }
```

Also add `await fetchAllActiveSessions(true);` after cache invalidation (before `processVisibleRows()`) to refresh session data:

```javascript
      await fetchAllActiveSessions(true);
      processVisibleRows();
```

- [ ] **Step 4: Commit**

```bash
git add extension/content.js
git commit -m "feat: add session dropdown to extension edit-trade modal with auto-transition"
```

---

### Manual Testing Checklist

Both tasks are in a Chrome extension with no automated test harness. Test manually:

1. **Add modal — Sell Call with WHEEL session:** Right-click a Call option for a ticker with a `shares_sitting` WHEEL session → "Add to TradeMinder" → verify dropdown shows `WHL · TICKER · Shares Sitting · opened ...` → select it → save → verify trade has `session_id`, session status changed to `cc_open` on the Wheel dashboard
2. **Add modal — Sell Put with WHEEL session:** Same for a Put option with a `called_away` WHEEL session → save → session transitions to `put_open`
3. **Add modal — strategy change:** With modal open, switch strategy from "Sell Call" to "Sell Put" → verify dropdown rebuilds (WHEEL sessions shown change from `shares_sitting` to `called_away`)
4. **Add modal — New Wheel Session:** Select "→ New Wheel Session" for a Sell Call → save → verify new session created with status `cc_open`, trade linked
5. **Add modal — auto-category:** Select a WHEEL session → verify category dropdown switches to `WHEEL`
6. **Add modal — IC/PBWB still work:** Select "Sell Put" strategy → verify IC and PBWB sessions appear alongside WHEEL → select one → save → trade linked, no status transition
7. **Edit modal — pre-fill:** Edit a trade already linked to a WHEEL session → verify dropdown shows that session pre-selected
8. **Edit modal — change session:** Change session to a different one → save → verify trade's `session_id` updated
9. **Edit modal — auto-transition:** Edit a Sell Call, change session to a `shares_sitting` WHEEL → save → session transitions to `cc_open`
10. **No sessions:** Open modal for a ticker with no sessions → dropdown shows "— None —" + "new" options only
