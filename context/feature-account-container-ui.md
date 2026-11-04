# Feature: Account Container UI (Part 2 of 5)

## Goal
Reorganize the SPA around brokerage accounts: left sidebar, account-scoped pages, account management,
Research pages spanning accounts, and a cross-account Dashboard. No login.

## Scope
In: accounts restore/reorder/delete guard, dashboard summary endpoint, routing, sidebar, account dialog,
Settings → Accounts, account-scoped Trades/WHEEL/Spreads/Margin/Screener/Chain/Scanner, Research pages,
Dashboard rebuild, legacy redirects.
Out: login/OAuth (Part 5), extension account detection / Reconcile (Part 3), Schwab banner (Part 4),
performance metrics, action queue, signal scoring, slot state machine, Chain scoring, server-side watchlist sort.

## Key Files
- Spec: `docs/superpowers/specs/2026-11-04-account-container-ui-design.md`
- Plan: `docs/superpowers/plans/2026-11-04-account-container-ui.md`
- Backend: `backend/app/services/accounts.py` (restore, reorder, can_delete, delete guard incl. memberships,
  new accounts appended), `routers/accounts.py`, `schemas/account.py`, new `services/dashboard.py`,
  `routers/dashboard.py`, `schemas/dashboard.py`, `tests/test_accounts_part2.py` (16 tests)
- Shell: `frontend/src/App.tsx`, `context/AccountsContext.tsx`, `lib/paths.ts`,
  `components/Layout/{Sidebar,AccountLayout,NotFound}.tsx`, `components/Accounts/AccountDialog.tsx`,
  `pages/SettingsAccountsPage.tsx`, `pages/LegacyRedirects.tsx`, `pages/DashboardPage.tsx`,
  `components/Dashboard/AlertFeed.tsx`
- API/types: `src/api/{accounts,categories,dashboard,trades,wheel,sessions,screener}.ts`, `src/types/index.ts`
- Account pages: Trades (+detail, TradeForm, GroupedTradeTable, TradeTable), WHEEL (+NewWheelModalV2,
  ResolveModal, LinkLegModalV2, WheelSlotCard), Spreads (+NewSpreadSessionModal, SpreadSessionCard), Scanner
- Screener: `ScreenerPage`, `AddSymbolForm`, `SymbolLookup`, `ScreenerTable`, `ScreenerCommentaryCell`,
  `ScreenerCommentaryThread`, new `AccountPicker.tsx`, `addToAccounts.ts`
- Dependency: `@radix-ui/react-collapsible@1.1.12` (frontend/package.json)
- Docs: this file, `context/_active.md`

## Technical Approach
See spec "Frontend structure". Current account comes only from the URL (`/accounts/:accountId/...`).

## Decisions Made
| Decision | Reason |
|---|---|
| Left sidebar with Dashboard / ACCOUNTS / RESEARCH / Settings | Every account one click away; scales to 6+ accounts |
| Account is a container, not a filter; Dashboard is the only cross-account view; Margin always one account | Positions, cash and margin are per account |
| Account Screener = member symbols + that account's notes; Chain/Scanner in an account create into it | The account is the context |
| Research Screener = all symbols, account badges, all notes labeled; creating asks which account | Research is account-agnostic |
| Accounts with trades/wheels/spreads are archived, never deleted; empty ones can be deleted | Preserve history |
| Pilot Dashboard = account cards, Needs-action list, today's alerts | Metrics and action queue are later features |
| Branch stacked on `feature/multi-account-foundation`, not develop | Part 1 is not merged into develop; Part 2 depends on it |
| See spec "Decisions (made here)" for metric definitions, reorder semantics, delete guard, redirects | Kept in one place |
| shadcn isn't installed; built with Radix Dialog + Collapsible, lucide icons, Tailwind; native HTML5 drag for reorder | Matches the repo's actual stack and GroupedTradeTable's existing DnD technique |
| Every account page remounts per account (keyed `<Outlet>`) | No state (e.g. a Margin CSV) can carry across accounts |
| New accounts are appended to the end of the order | Defaulting to 0 slotted them between existing accounts |
| Part 2 committed as a single feature commit (code + spec + plan + context) | Backend, UI and page changes only work together; no reason to split |

## Open Questions
1. Part 1 (`feature/multi-account-foundation`) is still unmerged and unpushed; this branch is stacked on it.
   Merge Part 1 into develop first, then rebase this branch.
2. Trades page shows empty group headers for categories the account doesn't use (unchanged behaviour) — hide them?
3. Chain returns a Schwab "400 Check Param Values" (pre-existing on the live backend; not caused by this part).
4. Chain and Scanner have no create actions yet, so "create into the current account / ask in Research" has no
   surface; the account context is available to them when one is added.
5. eslint `react-hooks/set-state-in-effect` flags the existing load-in-useEffect pattern in ScreenerPage and
   ScreenerCommentaryCell (pre-existing pattern, left as is).
6. Part 1's own next action (extension overlay + E*TRADE Reconcile smoke test against the migrated live DB) has
   still not been done; do it before the Part 1 PR.

## Progress Log
- 2026-11-03: Branch `feature/account-container-ui` created (stacked on Part 1). Spec + plan written.
- 2026-11-03: Backend: restore, reorder, can_delete, stricter delete guard, `GET /api/dashboard/summary`; 16 new
  tests incl. isolation. Suite 377 passed, 6 known failures.
- 2026-11-03: Frontend: AccountsProvider + URL-derived current account, routes, sidebar, account dialog, Settings →
  Accounts, Dashboard, legacy redirects; Trades/WHEEL/Spreads/Screener/Scanner adapted (three parallel subagents,
  WHEEL signal throttle/caching verified untouched by diff). tsc: no new errors.
- 2026-11-03: Manual checklist run in a sandbox (copy of live DB) with Playwright: all 12 items pass (results table
  in the spec). Fixed: new accounts were inserted at sort_order 0. Sandbox torn down.
- 2026-11-04: User approved; all Part 2 work committed as one commit on `feature/account-container-ui` (on top of
  Part 1's `1364bd5`). Not pushed.

## Current State
**Part 2 is implemented, verified and committed (not pushed).**

- Branch `feature/account-container-ui` = develop (`4872ac1`) + Part 1's 3 commits (`92447f1`, `c7c2893`,
  `1364bd5`, all unpushed, not in develop) + one Part 2 commit `feat(accounts): account container UI (Part 2 of 5)`.
  Working tree clean apart from pre-existing untracked `.claude/worktrees/` and `docs/learnings/` (not ours —
  leave them out of commits).
- Verification done: pytest 377 passed / 6 known failures (`test_cc_signal.py`, `test_market_router_p2.py`,
  `test_schwab_client.py`); `tsc -b` shows only the 2 pre-existing unused-symbol errors (`WheelSlotCard.tsx:27`,
  `WheelDashboardPage.tsx:3`); 12/12 manual checklist items pass (results table in the spec).
- Live DB is at revision 016; Part 2 needs no migration. The user's dev servers (`uvicorn --reload` on 5431,
  Vite on 5430) serve this code. The user had not yet clicked through the new UI on real data at session close.
- `@radix-ui/react-collapsible@1.1.12` is in package.json/lockfile and installed in `frontend/node_modules`;
  anyone on a fresh checkout needs `npm install` in `frontend/`.

**Single next action:** click through http://localhost:5430 on real data (sidebar, each account page, Settings →
Accounts, Dashboard); then land Part 1 — run its extension/Reconcile smoke test, push
`feature/multi-account-foundation` and PR it into develop — and after it merges, rebase this branch onto develop
and open its PR.
