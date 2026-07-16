# On-Demand Reconcile Button

**Date:** 2026-07-16  
**Status:** Approved

## Overview

Replace the automatic reconcile trigger (which fired on every DOM mutation) with an on-demand button injected adjacent to E*TRADE's native "Customize" button in the portfolio filters bar.

## Changes

### 1. Remove auto-reconcile

Remove the `fireReconcile(rows)` call from `processVisibleRows()` (`content.js` ~line 441). This is the only place the auto-trigger fires.

Remove the `lastReconcileKey` dedup guard from `fireReconcile()` (lines 865–867): the guard existed to prevent redundant auto-fires; it is unnecessary for an explicit user action. The `lastReconcileKey` variable and state can be deleted entirely.

### 2. Inject reconcile button into E*TRADE's filter bar

Add `insertReconcileButton()`, modeled after `insertFilterToolbar()`:

- Target: `.PortfoliosFilters---customize-view---Ln4bT`
- Inject a `<div>` sibling immediately **before** that element
- Button styled to match E*TRADE's `btn-block btn-link` pattern (text link style, no background)
- Guard with `document.getElementById('tm-reconcile-btn')` to prevent duplicate injection

Call `insertReconcileButton()` from `startObserver()`, alongside the existing `insertFilterToolbar()` call.

If the target element is not yet in the DOM when `startObserver` runs, retry with `setTimeout(insertReconcileButton, 500)` (same pattern as `startObserver` itself).

### 3. Button states

| State | Label |
|---|---|
| Idle | `🔄 Reconcile` |
| In-flight | `⏳ Reconciling…` (disabled) |
| Success — all matched | `✓ All matched` (2 s, then reset to idle) |
| Success — unmatched found | `⚠ N unmatched` (2 s, then reset to idle) |
| Error | `✗ Failed` (2 s, then reset to idle) |

### 4. Click handler

On click:
1. Set button to in-flight state.
2. Collect all visible rows via `document.querySelectorAll(ETRADE.positionRows)`.
3. Call `fireReconcile(rows)` (unchanged logic — POST to `/api/positions/reconcile`, update `reconcileCache`, apply pills).
4. On completion, update button label with result summary for 2 s, then reset.

`fireReconcile` returns the `data` response; the handler reads `data.unmatched_etrade.length` to determine the label.

## Files Changed

- `extension/content.js` only — no backend changes needed.

## Out of Scope

- No changes to the backend reconcile endpoint.
- No changes to how `applyReconcilePillToRow` works.
- No persistent display of last-reconcile results beyond the 2 s flash.
