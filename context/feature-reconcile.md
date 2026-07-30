# Feature: E*TRADE Reconcile

**Branch:** `develop`
**Spec:** `docs/superpowers/specs/2026-07-16-on-demand-reconcile-button-design.md`, `docs/superpowers/specs/2026-07-17-immediate-stale-on-reconcile-design.md`

---

## Progress Log

| Date | Summary |
|------|---------|
| 2026-07-30 | Debugged and fixed 3 stacked bugs preventing reconcile from ever flagging closed positions (XSP legs never showed "Not in E*TRADE"): (1) 11 direct `fetch()` calls in `content.js` bypassed the `bgFetch` relay and were silently blocked by Chrome's Local Network Access policy — converted all to `bgFetch`. (2) Reconcile only captured whatever ~50 rows E*TRADE happened to render at click time (grid virtualizes against page scroll, no internal scroll container) — added `collectAllPositions()` to scroll the full page and accumulate all rows before snapshotting. (3) Backend's stale-detection guard (`positions.py`) required `last_etrade_seen` to already be non-null, so trades that closed before ever being successfully reconciled (true during the whole time bugs 1–2 were live) could never be backdated — extended eligibility to also trust `etrade_symbol IS NOT NULL` (proof of a real extension-added E*TRADE trade) while still protecting manual entries. All verified working end-to-end by user on live E*TRADE tab. |

---

## Current State

**All three bugs are fixed in the working tree on `develop` and confirmed working live by the user. Not yet committed.**

`git status` shows the following modified/created files, all uncommitted:
- `extension/content.js`
- `backend/app/routers/positions.py`
- `backend/tests/test_reconcile.py`
- `backend/uv.lock` (pre-existing unrelated modification from session start, not touched this session)

Backend test suite: `backend/tests/test_reconcile.py` — 12/12 passing. Full backend suite has 6 pre-existing failures in unrelated modules (`test_cc_signal.py`, `test_market_router_p2.py`, `test_schwab_client.py`) — confirmed present before this session's changes, not caused by this work.

**Immediate next step:** Ask the user whether to commit these changes (they haven't asked for a commit yet — do not commit without being asked, per standing repo convention). If committing, split logically: extension fetch/scroll fixes as one commit, backend stale-detection fix + test as another (matches this repo's granular commit style, e.g. `6c2e9c4`, `9138d1d`). No PR was discussed.

---

## Key Files

| File | Role |
|------|------|
| `extension/content.js` | `bgFetch` conversion (11 call sites); new `findScrollContainer()`, `makeScroller()`, `collectAllPositions()` helpers; `fireReconcile()` signature changed from taking DOM rows to taking pre-extracted `info` objects; reconcile button click handler now awaits `collectAllPositions()` instead of a single `querySelectorAll` |
| `backend/app/routers/positions.py` | `reconcile_positions()` — removed the `trade.ticker in snapshot_tickers` guard (obsolete now that the extension sends a complete snapshot); added `trade.etrade_symbol is not None` as a second eligibility path for backdating alongside `last_etrade_seen is not None` |
| `backend/tests/test_reconcile.py` | Renamed/inverted `test_reconcile_ticker_not_in_snapshot_not_backdated` → `test_reconcile_ticker_absent_from_snapshot_is_backdated` (opposite assertion, reflecting the new complete-snapshot assumption); added `test_reconcile_never_seen_but_extension_added_is_stale` |

---

## Decisions Made

- **Reconcile snapshot must be complete, not partial.** E*TRADE's grid has no internal scrollbar — it windows rows against the page's own scroll (placeholder rows fill not-yet-rendered slots). `findScrollContainer()` walks a row's ancestors for an internal `overflow:auto/scroll` element; when none is found (E*TRADE's actual case), `collectAllPositions()` falls back to scrolling `window`/`document.scrollingElement`. This was confirmed via a live DOM ancestor trace from the user (no ancestor had `scrollHeight > clientHeight`).
- **All backend-bound fetches in `content.js` must go through `bgFetch`.** The codebase already documented this requirement in a comment (`content.js:80`, "Chrome's Private Network Access policy blocks content scripts... Route all API calls through the background service worker") but 11 call sites didn't follow it. This is now enforced — verified zero raw `fetch(` calls remain (`grep -nF 'fetch(' content.js | grep -v bgFetch` returns empty).
- **Reverted the `6c2e9c4` ticker-presence guard.** That guard was added to protect against a *partial* viewport snapshot (an open-but-off-screen position falsely flagged stale). Now that `collectAllPositions()` guarantees a complete snapshot, the guard's premise no longer holds, and it was actively preventing detection of genuinely closed positions (a ticker fully closed will never appear in *any* snapshot, complete or not). The completeness guarantee now lives entirely on the extension side; the backend trusts it because reconcile has exactly one caller (the button handler).
- **`etrade_symbol IS NOT NULL` is the second stale-eligibility signal.** The original null-check on `last_etrade_seen` exists to protect manually-entered trades (not real E*TRADE positions) from ever being wrongly flagged. But a trade added via the extension's modal always has `etrade_symbol` set at creation time, which is proof-positive it's a real E*TRADE position — independent of whether reconcile ever successfully matched it before the position closed. This closes the gap where the XSP legs opened and closed entirely during the window the extension bugs were live, so `last_etrade_seen` was never once set.

---

## Open Questions

- **No LNA warm-up mechanism was added.** Diagnosis briefly suspected a Chrome Local Network Access permission gap for the `background.js` service worker, but this turned out to be a red herring — the popup's own `fetch()` (`popup.js:25`) already succeeds with a green status dot, confirming the service worker context is fine. The actual bug was the 11 direct content-script fetches. No LNA-specific code was added or is currently believed necessary; flag this if blocked calls resurface in a context that isn't one of the 11 fixed sites.
- **Historical trades with `last_etrade_seen = None` and `etrade_symbol = NULL`** (true manual entries) still can never be auto-flagged stale, by design. If a user manually enters a trade that *is* actually an E*TRADE position (skipping the extension modal), it will never be caught by reconcile. Not addressed this session — considered acceptable per original design intent.
- **Extension debug logging left in place.** `collectAllPositions()` still has several `console.debug('[TM] collectAllPositions: ...')` calls added during this debugging session. Consider stripping them once the fix has been stable for a while, or leave them (they're gated behind Chrome's Verbose console filter by default, so they're low-noise).
