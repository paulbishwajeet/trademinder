# Extension Session Picker — Design Spec

**Date:** 2026-06-18
**Branch:** `feature/strategyupdate`
**Status:** Approved

## Problem

The Chrome extension's add-trade modal has a "Spread Session" dropdown that only shows IRON_CONDOR and PUT_B_W_FLY sessions. Users cannot attach a sold covered call (or sold put) to an existing WHEEL session from the extension — they must create the trade unlinked, then go to the Wheel dashboard to manually link it via the LinkLegModal. The edit-trade modal has no session dropdown at all.

## Solution

Generalise the session dropdown in both the add-trade and edit-trade modals to cover all session-based strategies (WHEEL, IRON_CONDOR, PUT_B_W_FLY). Filter the dropdown options based on the selected strategy so only contextually relevant sessions appear.

## Scope

### In scope
- Rename "Spread Session" label → "Session"
- Strategy-aware dropdown filtering (re-runs on strategy change)
- WHEEL sessions shown for Sell Call / Covered Call / Sell Put strategies
- Auto-set category dropdown when a session is selected
- Auto-transition WHEEL session status on save (shares_sitting → cc_open, called_away → put_open)
- "→ New Wheel Session" create-on-the-fly option
- Edit modal: add session dropdown, pre-filled with trade's current session_id, editable
- Edit modal: same auto-transition logic on save when session_id changes

### Out of scope
- Stock trades (session dropdown only appears for options — `info.isOption` guard unchanged)
- Backend API changes (all existing endpoints sufficient)
- New session creation for strategies other than WHEEL/IC/PBWB

## Detailed Design

### 1. Session Fetch

Both modals call the same endpoint:

```
GET /api/sessions?ticker={ticker}&status=open
```

This returns all open sessions for the ticker across all strategies. No client-side pre-filter by strategy — filtering happens at render time based on the selected trade strategy.

### 2. Strategy-Aware Filtering

The dropdown contents update dynamically when the strategy `<select>` changes:

| Trade strategy selected | Sessions shown | "New" options shown |
|---|---|---|
| Sell Call, Covered Call | WHEEL with status `shares_sitting` | → New Wheel Session |
| Sell Put | WHEEL with status `called_away` or `completed` + IC + PBWB | → New Wheel Session, → New IC, → New PBWB |
| Put Credit Spread, Call Credit Spread | IC + PBWB | → New IC, → New PBWB |
| Buy Put, Buy Call | IC + PBWB | → New IC, → New PBWB |
| Stock | (dropdown hidden) | — |

Implementation: a `rebuildSessionDropdown(sessions, selectedStrategy)` helper that rebuilds the `<option>` list. Called on initial render and on strategy `change` event.

### 3. Dropdown Option Labels

Format per strategy:

- **WHEEL:** `WHL · {ticker} · {status_label} · opened {opened_at}`
  - Status labels: `Shares Sitting`, `Called Away`, `CC Open`, `Put Open`, `Completed`
- **IRON_CONDOR:** `IC · {ticker} · opened {opened_at}`
- **PUT_B_W_FLY:** `PBWB · {ticker} · opened {opened_at}`

Static options at bottom (filtered by strategy):
- `→ New Wheel Session`
- `→ New Iron Condor Session`
- `→ New Put BWB Session`

Sentinel values: `__new_WHEEL__`, `__new_IC__`, `__new_PBWB__`

### 4. Auto-Set Category

When the user selects a session (existing or "new"), the category dropdown auto-updates:

| Session strategy | Category set to |
|---|---|
| WHEEL | `WHEEL` |
| IRON_CONDOR | `IRON_CONDOR` |
| PUT_B_W_FLY | `PUT_B_W_FLY` |

When "— None —" is re-selected, category is not changed (user may have set it intentionally).

Determining strategy from the selection:
- Existing session: look up from the fetched sessions array by ID
- `__new_WHEEL__` / `__new_IC__` / `__new_PBWB__`: strategy is in the sentinel value

### 5. Auto-Transition on Save

After the trade is created/updated and linked to a WHEEL session, the extension PATCHes the session status:

| Current session status | Trade strategy | New session status |
|---|---|---|
| `shares_sitting` | Sell Call / Covered Call | `cc_open` |
| `called_away` | Sell Put | `put_open` |
| `completed` | Sell Put | `put_open` |

This uses the existing `PATCH /api/sessions/{id}` endpoint with `{ status: "..." }`.

No transition for IC/PBWB sessions (they stay `open`).

### 6. New Wheel Session Creation

When `__new_WHEEL__` is selected, `POST /api/sessions` with:

```json
{
  "ticker": "<ticker>",
  "strategy": "WHEEL",
  "status": "<initial_status>",
  "opened_at": "<open_date>"
}
```

Where `initial_status` depends on the trade strategy:
- Sell Put → `put_open`
- Sell Call / Covered Call → `cc_open`

For IC/PBWB new sessions, existing logic is unchanged (status: `open`).

### 7. Edit Modal — Session Dropdown

The edit modal gains a session dropdown between Category and Strike:

- Fetches sessions for `trade.ticker` on modal open
- Pre-selects `trade.session_id` if present (matched against fetched sessions)
- If `trade.session_id` points to a session not in the fetched list (e.g., closed session), show it as a disabled option: `{label} (closed)` so the user sees what it was
- Clearing to "— None —" sends `session_id: null` in the PATCH payload
- Same strategy-aware filtering, "new" options, auto-category, and auto-transition as add modal
- `rebuildSessionDropdown` is shared between both modals

### 8. Files Changed

| File | Change |
|---|---|
| `extension/content.js` | `rebuildSessionDropdown()` helper; refactored `showAddTradeModal` session logic; new session dropdown in `showEditTradeModal`; auto-category wiring; auto-transition PATCH on save |

No backend changes. No CSS changes (dropdown uses existing `tm-field-row` styling).

## Testing Plan

1. **Add modal — Sell Call:** Open add-trade on a Call option for a ticker with a `shares_sitting` WHEEL session → dropdown shows the session → select it → save → verify trade has `session_id`, session status is `cc_open`
2. **Add modal — Sell Put:** Same for a Put option with a `called_away` WHEEL session → save → session transitions to `put_open`
3. **Add modal — strategy change:** Switch strategy dropdown between Sell Call and Put Credit Spread → verify dropdown contents update dynamically
4. **Add modal — New Wheel Session:** Select "→ New Wheel Session" → save → verify new session created with correct status, trade linked
5. **Add modal — auto-category:** Select a WHEEL session → verify category dropdown switches to WHEEL
6. **Edit modal — pre-fill:** Edit a trade already linked to a WHEEL session → dropdown shows that session selected
7. **Edit modal — change session:** Change session selection → save → verify trade's session_id updated
8. **Edit modal — clear session:** Change to "— None —" → save → verify session_id is null
9. **Spread sessions:** Verify IC/PBWB sessions still work as before in both modals
10. **No sessions:** Open modal for a ticker with no sessions → dropdown shows "— None —" + "new" options only
