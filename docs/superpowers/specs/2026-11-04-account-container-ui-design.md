# Account Container UI — Part 2 of 5 (Design)

**Date:** 2026-11-04 · **Branch:** `feature/account-container-ui` · **Depends on:** Part 1 (`feature/multi-account-foundation`)

## Goal

Reorganize the SPA around brokerage accounts: a left sidebar, account-scoped pages, account management,
Research pages that span accounts, and a cross-account Dashboard. No login.

## Repo reality vs. the brief

1. **Part 1 is not merged.** `develop` (local and origin) stops at `4872ac1`; Part 1's commits exist only on
   the unpushed `feature/multi-account-foundation`. This branch is therefore **stacked on Part 1**, not cut from
   develop; it rebases onto develop once Part 1 lands. The live DB is already at revision 016, so develop's
   code cannot run against it anyway.
2. **shadcn is not installed** (no `components/ui`, no `cn` helper). Available: `@radix-ui/react-dialog`,
   `@radix-ui/react-slot`, `lucide-react`, Tailwind. Added one pinned dependency,
   `@radix-ui/react-collapsible@1.1.12`, for the account sections. Drag-to-reorder uses native HTML5 DnD, the
   same technique `GroupedTradeTable` already uses — no DnD library.
3. **Chain and Scanner create nothing today** (no trade/wheel/symbol create actions). "Creates target the
   current account / Research asks which account" therefore has no surface yet; both pages are rendered
   unchanged in both places and receive the account context so future create actions can use it.
4. **The extension has no links into SPA routes** (it only calls `/api/...`). Nothing to change there.
5. Margin keeps its CSV only in component state (no localStorage). Per-account isolation = the page is
   remounted per account (`key={accountId}`).
6. Internal links that must become account-aware: `/trades/:id` (TradeTable, GroupedTradeTable, WheelSlotCard,
   WheelDashboardPage, SpreadSessionCard), `/scanner?ticker=` (TradeTable, GroupedTradeTable, TradeDetail),
   `/chain?symbol=` (WheelDashboardPage SP Timing).

## Decisions (given)

| Decision | Reason |
|---|---|
| Left sidebar: Dashboard · ACCOUNTS (one collapsible section per active account, nickname + last four, gear) · RESEARCH (Screener, Chain, Scanner) · Settings | Every account one click away; scales to 6+ accounts |
| An account is a container, not a filter; account pages show exactly one account; Dashboard is the only cross-account view; Margin is always one account | Positions, cash and margin are per account |
| Account Screener = that account's member symbols + that account's notes; Chain/Scanner inside an account create into it without asking | The account is the context |
| Research Screener = all symbols with account badges + notes from every account labeled; creating from Research asks which account (default = user's default) | Research is account-agnostic |
| Accounts with any trade, wheel or spread are archived, never deleted; empty accounts can be deleted; Settings → Accounts shows archived ones with Restore/Delete | Preserve history |
| Pilot Dashboard: per-account cards, Needs-action list, today's alerts | Performance metrics and the action queue are later features |

## Decisions (made here)

| Decision | Reason |
|---|---|
| Branch stacked on Part 1 | Part 1 isn't merged; Part 2 cannot work without it |
| Delete guard = no trades, wheels, spreads, screener notes **or memberships** (Part 1 also allowed memberships, cleaning orphans) | Brief's rule; a membership is account data the user curated |
| Reorder accepts every active account id exactly once, may include archived ids; unknown/foreign id → 404, missing active / duplicate → 400; unlisted archived accounts keep their relative order after the listed ones | The sidebar only shows active accounts but archived ones must keep a stable order |
| `AccountResponse.can_delete` computed server-side | The UI shows Delete only when empty; the server is the source of truth |
| "Legs expiring within 7 days" = open trades in the account with `expiry_date` between today and today+7 (ET), inclusive | An expiring spread or stand-alone put needs the same attention as a wheel leg |
| "Net premium this month" = Σ signed `wheel_premium_logs.premium_amount` with `event_date` in the current US/Eastern calendar month | Brief; premium logs are already signed (buy-backs negative) |
| "Today's alerts" = not dismissed, not currently snoozed, `triggered_at` on today's US/Eastern date | Brief says "today's"; older unread alerts stay visible on the trade pages |
| Needs-action open-leg expiry = earliest expiry among the slot's legs whose trade is open | A slot has at most one active option leg; earliest is the safe answer if data is odd |
| Current account comes only from `/accounts/:accountId/...`; `AccountsProvider` caches the list (incl. archived) and exposes `refresh()` | Brief: URL is the only source; no global mutable selection |
| `/trades/:id` legacy URL resolves the trade's account then redirects | Trade ids are account-specific |
| Research Screener remove = remove from every account (confirm dialog); account Screener remove = membership only | Mirrors the container rule |
| Research note writes ask which account (default account preselected) | Notes are per account |
| Trades group order key = `trademinder_group_order:<accountId>`; first load in an account seeds from the legacy global key | Per-account order without losing today's order |
| Scanner reads `symbol` and falls back to `ticker`; new links use `symbol` | One parameter name across Chain and Scanner, old links keep working |
| New accounts default to the end of the order (max sort_order + 1) | Found during verification: defaulting to 0 slotted a new account between existing ones |
| New-trade category default: account default → WHEEL if the account uses it → first allowed | Keeps today's WHEEL default where it applies |
| Trade edit shows a category outside the account as a disabled "(not in this account)" option | Opening Edit must not silently change a trade's category |
| Trades page keeps its hardcoded group headers (empty groups for unused categories) | They are group headings, not a picker; the brief only restricts pickers |
| Research add sends `precomputed`/`category` with the first successful membership only | Category and fetched data belong to the symbol row, not to each account |

## Backend additions

- `POST /api/accounts/{id}/restore` — un-archive.
- `DELETE /api/accounts/{id}` — guard extended to memberships; 409 message points to archive.
- `PUT /api/accounts/order` `{account_ids: [...]}` → the reordered list.
- `AccountResponse.can_delete`.
- `GET /api/dashboard/summary` → `{accounts: [AccountCard], needs_action: [NeedsActionSlot], alerts: [DashboardAlert]}`;
  money as Decimal strings; all queries filter by the current user.

## Frontend structure

- `context/AccountsContext.tsx` — `AccountsProvider`, `useAccounts()`, `useCurrentAccount()` (URL-derived), `AccountLayout` (not-found state for foreign/archived ids).
- `lib/paths.ts` — route builders (`accountPath`, `researchPath`, `tradePath`).
- `components/Layout/Sidebar.tsx`, `components/Accounts/AccountDialog.tsx`, `pages/SettingsAccountsPage.tsx`, `pages/LegacyRedirects.tsx`.
- Routes: `/` · `/accounts/:accountId/{trades,trades/:tradeId,wheel,spreads,margin,screener,chain,scanner}` ·
  `/research/{screener,chain,scanner}` · `/settings` → `/settings/accounts` · legacy redirects.

## Manual verification checklist

1. App opens on `/` (cross-account Dashboard); sidebar shows Dashboard, the accounts, Research, Settings.
2. Create a second account via "+ Add account" (broker, nickname, last four = 4 digits, categories, default category).
3. In the new account add a trade and a wheel; neither appears in the first account's Trades/WHEEL; the first account's data doesn't appear in the new one.
4. Trade form in the new account only offers its categories and preselects its default category.
5. Reorder accounts by drag; reload; order persists.
6. Archive the new account (blocked with data? no — archive is allowed); it leaves the sidebar, shows in Settings → Accounts as archived; its URL shows not-found; Restore brings it back.
7. Create an empty third account, Delete it (confirm dialog); Delete is not offered for accounts with data; last active account cannot be archived/deleted.
8. Account Screener shows only member symbols; adding creates a membership; removing removes only the membership; notes are that account's only.
9. Research Screener shows all symbols with account badges, notes labeled by account; adding asks which account(s).
10. Old URLs `/trades`, `/wheel`, `/spreads`, `/margin` land on the default account; `/screener`, `/chain?symbol=X`, `/scanner?ticker=X` land on Research with the query kept; `/trades/<id>` lands on that trade's account page.
11. Dashboard card numbers match SQL for both accounts (open trades, active wheels, needs-action slots, legs expiring ≤7d, net premium this month).
12. `tsc -b` adds no errors; backend suite passes apart from the known failures.

### Results (2026-11-03, sandbox: copy of the live DB, SPA :5450 → API :5452, driven with Playwright)

| # | Result |
|---|---|
| 1 | Pass — opens on `/`, sidebar Dashboard / ACCOUNTS / RESEARCH / Settings |
| 2 | Pass — "Schwab IRA ····4321" (Schwab, HOLD+LEAP, default LEAP); non-digits stripped, 3 digits blocks Save, default list narrows to selected categories |
| 3 | Pass — ZIRA trade + wheel only in the IRA (DB); E*TRADE still 440 trades / 65 wheels, no ZIRA; IRA pages empty of E*TRADE data |
| 4 | Pass — category picker offered HOLD, LEAP with LEAP preselected; trade saved as LEAP |
| 5 | Pass — drag IRA above E*TRADE → sort_order persisted, order survives reload |
| 6 | Pass — archive removes from sidebar, Settings shows Archived + Restore (no Delete), URL shows not-found, Restore brings it back |
| 7 | Pass — Delete offered only on the empty account, confirm dialog, row gone; last-active guard covered by pytest |
| 8 | Pass — account Screener empty of other accounts' symbols; adding AAPL created a membership (one row, two accounts); IRA note visible only in the IRA; Remove dropped only the IRA membership |
| 9 | Pass — Research lists all 39 symbols with per-membership badges, notes from both accounts labeled, note "to" picker defaults to the default account, Add asks which accounts (default preselected) |
| 10 | Pass — `/trades`, `/wheel`, `/spreads`, `/margin` → default account; `/screener`, `/chain?symbol=NVDA&strategy=sell_put`, `/scanner?ticker=NVDA` → Research with query kept; `/trades/<id>` → that trade's account; bad account id and unknown path → not-found |
| 11 | Pass — API equals direct SQL for both accounts (E*TRADE 131 / 65 / 0 / 10 / 13.17; IRA 1 / 1 / 0 / 1 / 0) |
| 12 | Pass — tsc: only the 2 pre-existing unused-symbol errors; pytest 377 passed, 6 known failures |

Observed but out of scope: `GET /api/chain/{ticker}` returns a Schwab "400 Check Param Values" on the live backend too (pre-existing, not caused by this part).
