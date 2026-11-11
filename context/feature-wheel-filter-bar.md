# Feature: WHEEL page symbol filter (filter bar v1)

## Goal
Add a sticky filter bar to the account-scoped WHEEL page. v1 has a single filter, Symbol: a combobox whose
options are the account's wheel tickers. The bar is a generic chip container, so status, DTE window, signal grade
and earnings-in-window filters can be added later as more chips.

## Scope
**In:**
- the filter bar;
- the Symbol combobox (Command + Popover, prefix match, GOOG/GOOGL aliases);
- `?symbol=` URL state;
- per-section filtered counts and muted zero-match lines;
- the "N other slots need action" safety notice;
- exiting the filter with ×, Clear, Escape or Back;
- click a row ticker to filter; "/" focuses the input;
- the account switch keeps `symbol`.

**Out:** backend, migrations and endpoints; server-side filtering; any change to data fetching, the 4-concurrent
throttle, the signal caches or the fetch order; inline contracts editing, Notes popover behaviour, signal badge
expansion; the extension's toolbar filters, which dim by deliberate decision; this page hides non-matching rows
instead.

## Key Files
- `frontend/src/pages/WheelDashboardPage.tsx`: filter state from search params; filtered section lists, counts and
  empty lines; ticker click; Escape and "/" keys.
- New `frontend/src/components/shared/FilterBar.tsx`: a generic sticky bar with chips, the input slot, Clear and a
  notice slot.
- New `frontend/src/components/shared/SymbolCombobox.tsx`: the Symbol input.
- New `frontend/src/components/ui/command.tsx` and `popover.tsx`: shadcn-style primitives over `cmdk` and
  `@radix-ui/react-popover`.
- New `frontend/src/lib/utils.ts` (`cn`) and `frontend/src/lib/tickers.ts` (alias map, matching).
- `frontend/src/components/Layout/Sidebar.tsx`: the account switch carries `symbol` on the WHEEL page.
- `frontend/src/components/Commentary/CommentaryPopover.tsx`: only a `data-escape-layer` marker on the open
  panel, with no change in behaviour.

## Technical Approach
- **Filtering happens at render time only.**
  - `sessions`, `load()`, `loadSignals()` and the `[sessions]` effect are untouched.
  - The page derives `needsAction`, `awaitingCC`, `awaitingSP`, `activeCC`, `activeSP` and `emptyWheels` exactly
    as before, then filters each list for rendering.
  - Signal state stays keyed by ticker, so nothing refetches and in-flight requests aren't cancelled.
- **URL state comes from `useSearchParams`.**
  - Setting or changing the symbol pushes a history entry, so Back exits the filter.
  - The value is uppercased.
  - No localStorage, so revisiting the page starts unfiltered.
- **Alias matching** uses `matchSymbols(symbol)`, which returns `{symbol, alias}`, so a row matches if its ticker
  is in that set.
- **Account switching:** the page already remounts per account (`<Outlet key={account.id}>`). The sidebar's
  account button keeps `symbol` when the current page is WHEEL.

## Decisions Made
| Decision | Reason |
|---|---|
| Add `cmdk` + `@radix-ui/react-popover` and write shadcn-style `ui/command.tsx` / `ui/popover.tsx` by hand | shadcn isn't set up in this repo (no `components/ui`, no `cn`); shadcn's Command / Popover are thin wrappers over exactly these two packages |
| Our own prefix filtering (`shouldFilter={false}`) | cmdk's default fuzzy match isn't the prefix match asked for |
| Frontend copy of the `GOOG`↔`GOOGL` alias map in `lib/tickers.ts` | The map exists only in `backend/app/routers/wheel.py` and `extension/content.js`; there's no shared module across the three |
| Sections that are empty even without a filter stay hidden; only sections emptied by the filter show the muted line | The filtered page keeps the unfiltered page's shape |
| The NEW — NEEDS SLOT section is filtered too | "Every section shows only matching rows" |
| Escape stands down while a modal, the contracts editor or a Notes panel is open, or focus is in another text field | Brief: not while a popover, edit control or dialog is open; the Notes panel (custom portal) is detected via a `data-escape-layer` marker |
| A symbol in the URL that matches no wheel in this account shows one empty state with Clear | Covers deep links and the account switch |
| The page's key listener runs in the **capture** phase; any open overlay carries `data-escape-layer` (the Notes panel, and the shared `PopoverContent`, i.e. the symbol list) and the listener stands down while one exists | Found in testing: the Notes panel's own Escape handler unmounted the panel (and its marker) before a bubbling listener ran, so one Escape both closed Notes and cleared the filter |
| Escape inside the symbol input: 1st closes the list, next clears typed text, only then clears the filter | Escape never throws away more than the innermost thing |
| Setting and clearing the symbol both push a history entry | Back always returns to the previous view; no special cases |
| The account switch carries `symbol` only from the WHEEL page | Other pages' `symbol` params (Chain) mean something else |
| `Command label="Filter by symbol"` rather than `aria-label` on the input | cmdk points the input's `aria-labelledby` at its own label, which overrode `aria-label` (found in testing: the input had no accessible name) |
| Popover parts wrapped as function components, not `const` re-exports | Satisfies the repo's react-refresh lint rule |

## Open Questions
1. A section's **Fetch** button and its "Fetched …" label still cover the section's full ticker list while a
   filter is on, because the brief said to leave fetching alone. Fetching only the visible tickers would be faster
   when filtered; that's a later choice.
2. The safety notice counts slots with `needs_action` only. New wheels without a slot (the NEW — NEEDS SLOT
   section) aren't counted.
3. The production bundle grew from 493 KB to 593 KB (170 KB gzipped), mostly Radix Popover's floating-ui. That's
   fine for a LAN app; code-splitting is an option if it matters later.
4. The WHEEL page's first load fetches signals for every ticker (~65 tickers × 5 endpoints, 4 at a time) and keeps
   the network busy for well over a minute. That's existing behaviour, not something the filter changed, but it's
   worth knowing.

## Progress Log
- 2026-11-11: Branch and worktree off `develop` `471dd1e`; surveyed the page, sidebar, popover and routing; context
  file created.
- 2026-11-11: Implemented. Added `cmdk@^1.1.1` and `@radix-ui/react-popover@^1.3.1`. npm also hoisted
  `@radix-ui/react-slot` 1.2.4 → 1.5.0; I pinned it back to 1.2.4, so the lockfile diff only adds packages. `npm run build` (`tsc -b`)
  passes; ESLint shows no new findings (the remaining ones are pre-existing on `develop`).
- 2026-11-11: Verified in Playwright against a copy of the local DB (`trademinder_wftest`, own backend :5441 and
  Vite :5440; dropped afterwards). The copy had a needs-action TSLA slot and a second account "Test IRA" with AAPL
  and GOOG wheels. Two bugs found and fixed: Escape with Notes open also cleared the filter, and the input had no
  accessible name.

| Check | Result |
|---|---|
| "/" focuses the input; typing "b" → "be" prefix-matches; Enter commits BE | ✅ `?symbol=BE`; chip "Symbol: BE" |
| Ticker in several sections (BE) | ✅ AWAITING CC 1 of 20, ACTIVE SOLD PUTS 1 of 6; the other sections show their muted line ("No BE slots awaiting a sold put", …) |
| Filtering makes no API calls | ✅ 0 requests while filtering |
| Ticker with no wheel ("xyz") | ✅ "No wheel for XYZ in this account"; Enter doesn't commit |
| GOOG vs GOOGL | ✅ typing "goog" offers GOOGL; `?symbol=GOOG` and `?symbol=googl` both show the 2 GOOGL rows; GOOGL in an account with a GOOG wheel shows it |
| Needs-action notice | ✅ BE / GOOGL filters show "1 other slot needs action · Show all"; TSLA (the needing slot itself) shows no notice |
| Exits | ✅ chip ×, Clear, Show all, Escape from the page, Escape in the bar (after the list closes), Back |
| Escape guards | ✅ Notes open → closes Notes only; contracts editor → nothing; typed text → clears text only; "/" with Notes open → nothing |
| Click a row's ticker | ✅ filters to it; Back exits |
| Sticky bar | ✅ stays at the top after scrolling 1,527 px |
| Account switch with a filter | ✅ AAPL → Test IRA's AAPL row; NVDA → "No wheel for NVDA in this account." + Clear filter; from Trades the symbol isn't carried |
| No localStorage | ✅ no keys written |

## Current State
**Implemented and verified on `feature/wheel-filter-bar` in the worktree `.claude/worktrees/wheel-filter-bar`; not
committed.** The main checkout (the user's dev servers) is still on `develop` and doesn't have this yet.

**Single next action:** the user tries it. Either commit and switch the main checkout to the branch (then run
`npm install` in `frontend/` for the two new packages), or look at it first in the worktree.
