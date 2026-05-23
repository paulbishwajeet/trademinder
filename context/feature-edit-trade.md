# Feature: Edit Trade

**Branch:** `frontend-edittrade`
**Spec:** `docs/superpowers/specs/2026-05-22-edit-trade-design.md`
**Plan:** `docs/superpowers/plans/2026-05-22-edit-trade.md`

---

## Progress Log

| Date | Summary |
|------|---------|
| 2026-05-22 | Full feature designed and implemented. Backend: `closed_date` added to `TradeUpdate` schema + new pytest test. Frontend: `TradeUpdate` type, widened `tradesApi.update()`, full edit mode on `TradeDetailPage` — all field form controls, status/closed_date conditional reveal, Save/Cancel, error banner, unknown-value dropdown fallback. Also added `.playwright-mcp/` to `.gitignore`. |

---

## Current State

**Implementation is complete on branch `frontend-edittrade`. All 14 backend tests pass, frontend tsc is clean. The branch has NOT been merged or pushed — the session ended before the merge/push option was chosen.**

The `TradeDetailPage` now has an "Edit" button in the top-right. Clicking it flips the page into a full form: all static fields (type, strategy, category, strike, expiry, qty, premium, collateral, signal_action) become inputs; exit_strategy and rationale notes become textareas; status becomes a select with a conditional closed_date date input that appears only when status is set to "closed". Ticker and open_date are locked. Save calls `PATCH /api/trades/{id}` and returns to read mode; Cancel discards without a network call.

**Single next action:** Pick a merge option — either `git checkout master && git merge frontend-edittrade` (local merge) or `git push -u origin frontend-edittrade && gh pr create` (PR).

---

## Key Files

| File | Role |
|------|------|
| `docs/superpowers/specs/2026-05-22-edit-trade-design.md` | **New.** Approved design spec |
| `docs/superpowers/plans/2026-05-22-edit-trade.md` | **New.** Implementation plan (all tasks complete) |
| `backend/app/schemas/trade.py` | Extended: `closed_date: Optional[date] = None` added to `TradeUpdate` |
| `backend/tests/test_trades.py` | Extended: `test_patch_trade_sets_closed_date` — PATCHes status+closed_date, asserts both persist |
| `frontend/src/types/index.ts` | Extended: `TradeUpdate` interface added after `TradeCreate` |
| `frontend/src/api/trades.ts` | Extended: `tradesApi.update()` parameter widened from narrow Pick to `TradeUpdate` |
| `frontend/src/pages/TradeDetailPage.tsx` | **Rewritten.** Full edit mode (~290 lines vs. original 95) |
| `.gitignore` | Extended: `.playwright-mcp/` added |

---

## Decisions Made

- **`ticker` and `open_date` are locked** — identity fields; correction requires delete + re-enter.
- **Full-page edit mode, not inline or modal** — single Edit button in header toggles all fields at once.
- **Close date prompted, not automatic** — when status → "closed", a `closed_date` input appears defaulting to today; cleared to null when status changes away from "closed".
- **`closed_date` flows through existing PATCH handler's generic `setattr` loop** — adding it to `TradeUpdate` was the only backend change needed.
- **Disabled fallback `<option>` for unknown dropdown values** — strategy and type selects show `{value} (unknown)` as a disabled option when the DB value isn't in the static constants list. Protects against legacy values like "Sell Call" silently snapping to the first dropdown option and being overwritten on next save.
- **Empty quantity sends `undefined`, not `0`** — `Number('')` evaluates to 0; the handler uses a conditional to send `undefined` instead, preventing a silent write of 0 to the backend.
- **Categories fetch uses bare `fetch('/api/categories')`** — consistent with the existing `TradeForm.tsx` pattern; fetch runs once on first Edit click and is cached in component state.

---

## Open Questions

- **Branch not yet merged** — `frontend-edittrade` needs to be merged to `master` (or a PR created) before the feature reaches production. All tests pass and tsc is clean; it's ready.
- **`.playwright-mcp/` folder exists locally** — it's now gitignored but the folder itself still lives at project root. Safe to `rm -rf .playwright-mcp` to clean it up.
- **Extension auto-close not implemented** — closing a trade on E*TRADE still requires manually updating status in the frontend. Deferred to a future revision where the extension detects position close and calls the API automatically.
