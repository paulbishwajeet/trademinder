# Feature: NEW — NEEDS SLOT section — collapse, delete, edit

**Status:** Complete — merged to `master`

## Goal
On the WHEEL page's "NEW — NEEDS SLOT" section (wheels that have no slot yet):
1. collapse it by default;
2. delete an individual entry;
3. edit an entry's shares, ticker and opened date.

Until now the only action was "+ Add Slot".

## Scope
**In:**
- backend `DELETE /api/wheel/{id}`, allowed only for a wheel with no slots;
- `PATCH /api/wheel/{id}` gains `ticker` and `opened_at`; changing the ticker is refused once the wheel has slots;
- backend tests;
- frontend collapse toggle, a delete button with confirm, an edit dialog.

**Out:** deleting or editing wheels that have slots (they live in the other sections and carry leg and premium
history); migrations (none needed).

## Key Files
- `backend/app/routers/wheel.py`: `delete_wheel_session`; `update_wheel_session` (ticker / opened_at, slot guard).
- `backend/app/schemas/wheel.py`: `WheelSessionUpdate` gains `ticker` (normalised) and `opened_at`.
- `backend/tests/test_wheel_crud.py`: new tests.
- `frontend/src/api/wheel.ts`: `deleteSession`, `WheelSessionUpdate` fields.
- `frontend/src/components/Wheel/EditWheelModal.tsx` (new).
- `frontend/src/pages/WheelDashboardPage.tsx`: the section's collapse, row actions.

## Technical Approach
- **Backend:**
  - `DELETE /api/wheel/{id}` loads the wheel (owned by the user, else 404) with its slots. It returns 409 "Remove
    this wheel's slots before deleting it" if any exist, else deletes it (204).
  - `PATCH` loads the slots too and returns 409 "Can't change the ticker of a wheel that has slots" when the ticker
    *changes* on a wheel with slots. Resending the same ticker is fine.
  - `WheelSessionUpdate.ticker` is stripped and uppercased, and must match `[A-Z0-9.\-/]{1,10}` (the column is
    varchar(10)). `total_shares` must be >= 0.
- **Frontend:**
  - The section header is a button with a chevron and `aria-expanded`. The state is `boolean | null`, where null
    means not clicked yet.
  - Open = the click choice, else (symbol filter on and it matches a new wheel). So it's collapsed by default, a
    matching filter opens it, and a click always wins.
  - Rows get ✎ (`EditWheelModal`: ticker, shares, start date, pre-filled; the same ticker rule is checked
    client-side because a 422 only surfaces as "Request failed") and × (confirm → `deleteSession` → reload).
  - The edit dialog counts as an overlay for the page's Escape / "/" shortcuts.

## Decisions Made
| Decision | Reason |
|---|---|
| Real delete, only for wheels with no slots (409 otherwise) | User's choice. A slotless wheel has no legs, premium logs or commentary, so nothing is lost; wheels with slots keep their history |
| Edit = shares, ticker, opened date in a dialog | User's choice; fixes a typo'd ticker without delete + re-add |
| Stacked on `feature/wheel-filter-bar` (not yet merged) | It changes the same section the filter-bar work changed |
| Changing the ticker is refused (409) only when it actually changes on a wheel with slots; shares and date stay editable for any wheel | Slots' legs are linked to trades in the original ticker |
| Collapse state isn't remembered (no localStorage); a matching symbol filter opens the section until the header is clicked | "Collapsed by default"; and the filter bar's rule that a filter must never hide a match |
| Delete confirmation via the browser's `confirm()` | Same as the existing slot delete |

## Open Questions
> Still-open items were carried to `docs/TRADEMINDER_MASTER_CONTEXT.md` §0 Open items and §6 in the 2026-11-12 audit.

1. Merge order: this branch is stacked on `feature/wheel-filter-bar`. Merging it into `develop` brings the filter
   bar along; merge the filter bar first (or both together) when releasing.
2. Edit and delete exist only on NEW — NEEDS SLOT rows. Wheels with slots still have no edit (shares / date) in the
   UI, though the endpoint allows it.

## Progress Log
- 2026-11-11: Branch `feature/wheel-new-wheel-actions` off `feature/wheel-filter-bar` (`2281724`) in worktree
  `.claude/worktrees/new-wheel-actions`; user chose real delete and a full edit dialog.

- 2026-11-11: Implemented backend (DELETE, PATCH ticker / opened_at + guards) with 7 new tests (full suite 483 passed
  / the 6 known failures) and the frontend (collapse, ✎ dialog, × delete). Build passes; ESLint has no new findings.
  Verified in Playwright on a DB copy (dropped afterwards):

| Check | Result |
|---|---|
| Default | ✅ collapsed, header "NEW — NEEDS SLOT 6", no rows |
| Click / click again | ✅ opens (6 rows with + Add Slot, ✎, ×) / closes |
| `?symbol=SOFI` | ✅ opens with only SOFI; a click still closes it. `?symbol=NVDA` → stays collapsed, "0 of 6" |
| Edit | ✅ pre-filled; "BRK B" refused in the dialog (no request); RCAT → RCATZ / 300 / 2026-07-10 saved (PATCH 200), row updated, section stays open |
| Delete | ✅ confirm text "Delete the AMD wheel? It has no slots, so nothing else is removed."; Cancel keeps the row; OK deletes (DELETE 204) |
| Escape with the edit dialog open and a filter on | ✅ dialog and filter both stay |
- 2026-11-12: Committed `ed1a9b8`; merged with the filter bar into `develop` and `master` and pushed (both feature
  branches pushed too).
- 2026-11-12: Merge commits: `develop` `07a3a99` (filter bar `f4178ec`, then this feature), `master` `19c7008`
  (merged inside the `trademinder-release` worktree, which is now up to date; extension unchanged, so the Trading
  Chrome profile needs no reload). The main checkout switched back to `develop`.
- 2026-11-12: Context audit: marked Complete; code verified on `master`.

## Current State (Resume Here)
COMPLETE — merged to `master` (`develop` 07a3a99 → `master` 19c7008 (2026-11-12)). Released with the filter bar. Nothing pending here.
