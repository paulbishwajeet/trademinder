# Extension Account Awareness — Part 3 of 5 (Design)

**Date:** 2026-11-04 · **Branch:** `feature/extension-account-awareness` · **Depends on:** Parts 1 and 2

## Goal

Make the Chrome extension account-aware: a configurable TradeMinder server, detection of the E*TRADE account on
screen, a one-time server-side link from each E*TRADE dropdown entry to a TradeMinder account, overlay calls
scoped to that account (or spanning all accounts in E*TRADE's All view), and Reconcile limited to one linked
account. No login.

## Repo reality vs. the brief

1. **Parts 1 and 2 are not merged.** `develop` (local and origin) still ends at `4872ac1`. This branch is stacked
   on `feature/account-container-ui` (Part 2, `b7e094f`), which is stacked on Part 1. Rebase onto develop once
   both land.
2. **Work happens in a git worktree** (`.claude/worktrees/extension-account-awareness`). The user's dev backend
   runs `uvicorn --reload` from the main checkout against the live DB. Adding model columns there would break
   the running app until the live DB is migrated, so all development and verification runs from the worktree
   against a copy of the DB.
3. **There is no `extension/sidebar/`.** The extension has `content.js`, `background.js`, `content.css` and
   `popup/`. The only in-page chrome is the `#tm-toolbar` filter bar inserted above the grid and the Reconcile
   button next to E*TRADE's "Customize". The brief's "sidebar" is therefore built as a **TradeMinder account bar**
   at the start of `#tm-toolbar`, which holds the context indicator. The link card renders directly beneath the
   toolbar, above the grid. No `chrome.sidePanel`: it would need a new permission and a second messaging surface
   for what is one card.
4. **`/api/wheel/active-slots` already takes `account_id` and returns `account` per slot** (Part 1). The work there
   is the extension side only.
5. **The backend already resolves writes without `account_id` to the user's default account** (`resolve_account`).
   That rule stays for the SPA. The extension always sends an explicit `account_id`.

## E*TRADE DOM facts

Two sources:

- **A.** `docs/DOMSample.html`, a rendered capture from June 2026 that contains the account dropdown.
- **B.** `~/Downloads/etradePortfolioview.html` (2026-11-03), which is the unrendered page source only. It has no
  dropdown and no grid, so it can't confirm anything rendered. It shows the React bundle build
  `react_portfolios_positions/20260929.2753`.

- **C.** Fresh masked captures, rendered 2026-11-04 by the user:
  - `oneaccounthtml.html`, a single account;
  - `combiledaccounthtml.html`, the All brokerage accounts view.

  Both were masked with the snippet below. Every option value shows `XXXXX1020`, and no full account number appears
  anywhere: the remaining 7+ digit runs are option symbols, CSS colours and analytics ids. The captures were
  analysed and replayed in the fixture, then deleted from the scratchpad, and they aren't committed. Both still
  contain badges from the previous extension build, which was running at the time.

| Brief fact | A (June capture) | Fresh capture |
|---|---|---|
| `select#accountDropdown` inside `optgroup[label="E*TRADE from Morgan Stanley accounts"]` | Confirmed: it is the select's only optgroup, and the select carries class `AccountList---account-list-select---<hash>`. A separate `select#positionsView` (optgroups "Standard Views" and "Saved Custom Views") picks the column layout. It isn't an account and must be ignored. | Confirmed (both views): same select, same class hash `CqGVn`, single optgroup; `#positionsView` present. |
| Option `value` = full account number + `-` + label | Confirmed. 9-digit numbers in A, e.g. `NNNNN1020-Individual Brokerage -1020`. The label itself contains `-`, so the parser splits on the **first** hyphen only. | Confirmed: 9-character prefix (masked) + `-` + label in both views. |
| Label ends with `-` + last four | Confirmed: `Individual Brokerage -1020`, `Stock Plan (AVGO) -1020`. Note the space before the hyphen. | Confirmed. |
| All view: value starts with `all-`, label "All brokerage accounts" | Confirmed: `all-All brokerage accounts`. | Confirmed. |
| Selected option only visible through the live `.value` | Confirmed: no `selected` attribute anywhere in the select's HTML. | Confirmed: no `selected` attribute in either capture, so the HTML alone doesn't say which entry is selected. |
| Two accounts can share the last four | Confirmed: both options end in 1020, and their full numbers differ. | Confirmed (both entries end in 1020). |
| Rows carry no account info | Confirmed in A, which was captured in a single-account view: rows are `[role="row"][level="0"]`, with no account column and no group rows. | Confirmed in **both** views: identical 11 column headers, every row `level="0"`, no account column or group rows, and no account text in the grid. |
| Grid id `rdt_2`, not `rdt_3` | Confirmed: A has `id="rdt_2"` on `[role="grid"][aria-label="Portfolios"]`. | Confirmed: `rdt_2` in both views. The previous build's `#tm-toolbar` is absent from both captures, which proves the `#rdt_3` lookup never matched. |
| Hashed class suffixes | Confirmed. In A, every selector the extension uses (`Content---root---D2Ylg` and the rest) still matched in June. | Confirmed: every prefix the extension uses has the same hash as in June (e.g. `Content---root---D2Ylg`, `SymbolCellRenderer---content---mcwCT`). |

**Differences in the All view found in the fresh captures** (not in the brief):

| Finding | Consequence / fix |
|---|---|
| Rows have **no "Trade Actions" split button** (`a.split-button-button[href*="Symbol="]` is missing from every row). A single account has one per row. | `getRowInfo` read the full symbol only from that button, except as an option-only fallback. It now falls back to the symbol's quote link (`…snapshot.asp?symbol=AAOI--270115P00050000` / `?symbol=AAPL`) for every row type. |
| No **Customize** button (`PortfoliosFilters---customize-view---*`), and no "Edit Lots". The links bar (`PortfoliosFilters---links-container---*`) holds only "Reset Sort". | Reconcile was anchored to Customize, so in the All view it vanished; the previous build's button is missing from the All-view capture. It now anchors next to Customize when present, otherwise at the end of the links container, so the disabled button and its reason show in the All view. The 1 s watchdog re-inserts it after React re-renders the bar. |
| The same contract never appears twice among the rendered rows in either view. AVGO stock is a single 200-share row in both. Footers say "Viewing 175 of 175 positions" in both. | It's still unproven whether a position held in **two** accounts shows as two rows or one merged row: these captures contain no such position. Per-account chips work either way, because they come from the backend's matches, not from the rows. |

**DOM code rules that follow from this:**

- **Grid:** locate it as `[role="grid"][aria-label="Portfolios"]`, falling back to
  `[class*="PortfoliosTable---table---"]`, and never by `#rdt_N`.
- **Classes:** match E*TRADE classes with `[class*="Block---element---"]` prefixes.
- **Account:** read it only from `#accountDropdown`'s live `.value` and `selectedOptions[0].textContent`.
- **Values:** a value counts as a single account only if it matches `^\d{6,}-`. Anything else, apart from `all-`,
  is treated as "unknown", and the overlay stays scoped to nothing.
- **Re-reads:** a `#positionsView` change re-renders the grid but leaves the account the same. The observer's
  re-read sees the same context and keeps the caches.

### Capture procedure (masked)

To capture each view, select it in the dropdown, wait for the grid to render, and run this in DevTools:

```js
copy(document.documentElement.outerHTML.replace(/\b\d{6,}\b/g, m => 'X'.repeat(m.length - 4) + m.slice(-4)))
```

Then paste the result into a file. Full account numbers are masked before the HTML leaves the page.

## Decisions (given)

| Decision | Reason |
|---|---|
| Server address configured once in the popup; the extension acts as the single owner until Part 5 | Login comes later; the seam is `get_current_user` |
| Account on screen comes from the dropdown. The first time an entry is seen, a link card offers an existing account or "Create new" (E*TRADE, nickname = label without the last-four suffix, last four) | The user maps broker accounts to containers once |
| Links are stored server-side: one dropdown entry ↔ one account, and one account has at most one link | Survives reinstalls and works across computers |
| Link key is the SHA-256 of broker + full account number, computed in the service worker. The number is never sent or stored. The backend stores the fingerprint, last label and last-seen time | Last four isn't unique, and the full number is sensitive |
| Reconcile only for a single linked account; otherwise disabled with a hint | Reconcile backdate-closes missing trades, so the account must be certain |
| Overlays work in every view. Single linked account = that account's trades; All view = across accounts, with per-account chips | Scoping must never paint one account's status on another's rows |
| Add trade targets the linked account; asks for one in the All view; disabled when unlinked | Writes must land in a known account |

## Decisions (made here)

| Decision | Reason |
|---|---|
| Fingerprint = lowercase hex SHA-256 of the UTF-8 string `E*TRADE:<account number>`, via `crypto.subtle` in the service worker | Exactly the brief. The broker prefix keeps a future broker's numbers in a separate space |
| DB check constraint: `external_ref IS NULL OR external_ref ~ '^[0-9a-f]{64}$'` | The schema itself refuses anything that isn't a fingerprint, including a raw account number |
| Fingerprints travel only in POST bodies, never in URLs | Access logs record paths, not bodies |
| Migration 017 adds `external_label` (String 100) and `external_seen_at` (timestamptz), plus a partial unique index `(user_id, external_ref) WHERE external_ref IS NOT NULL` | The brief requires uniqueness per user; two users may legitimately see the same account (e.g. a joint account) |
| Endpoints: `POST /api/accounts/links/resolve`, `POST /api/accounts/links` (create + link), `POST /api/accounts/{id}/link`, `DELETE /api/accounts/{id}/link` | Static paths come before `/{account_id}`; `links` reads as the resource |
| Resolving a linked fingerprint refreshes `external_label` and `external_seen_at` | "Last label seen and when", without a separate heartbeat |
| Linking is idempotent: the same account + same fingerprint returns 200. A different fingerprint on the account, or the fingerprint on another account, returns 409 | Retry-safe; conflicts are explicit |
| Linking to an archived account is allowed (it just links). Resolve reports `is_archived`, and the extension treats an archived link like "Not linked" for writes, with the hint "Linked account is archived — restore it in TradeMinder" | Restoring brings the link back without relinking |
| `AccountResponse` drops `external_ref` (the fingerprint) and gains `link: {label, last_seen_at} \| null` | The SPA needs the label and date, never the hash |
| `PositionsStatusRequest.account_id` is optional. Each `PositionStatus` gains `account` (the primary match's account) and `matches: [{account, trade_id, category_name, category_color, alert_severity}]` | One shape for both modes. In single-account mode `matches` has at most one entry |
| All-view primary match = the most severe alert, then account `sort_order` | The row color shows the most urgent account; chips show all of them |
| `ReconcileRequest.account_id` is required: missing → 422, foreign/unknown/archived → 404 | Reconcile writes, so it needs an active, owned account |
| Reconcile, add trade and edit-session creation always send `account_id` from the extension | No silent default-account writes from the extension |
| Edit trade lookup (`GET /api/trades?etrade_symbol=`) passes `account_id` in a single-account view. In the All view, if several accounts match, a picker asks which trade to edit | The same symbol can exist in two accounts |
| Session picker (`/api/sessions/active`) is scoped to the trade's account: the linked account, or the one chosen in the All-view picker | A trade can only join a session in its own account (backend enforces `require_same_account`) |
| Account context is keyed `single:<fingerprint>` or `all`. Every cache (`processedRows`, `statusCache`, `reconcileCache`, `commentaryCountCache`, `etradeSymbolIndex`, the active-sessions and wheel-slot TTLs) is cleared on change. Every in-flight result is dropped if the context changed while it was pending | Stale statuses from one account must never paint another's rows |
| Unlinked single account: rows get no status at all (no badges, colors or pills), plus the link card | We can't know which trades those rows are |
| Server address: stored as `tmApiUrl`, default `http://127.0.0.1:5431`. The manifest keeps `http://localhost/*` and `http://127.0.0.1/*` and adds `optional_host_permissions: ["http://*/*", "https://*/*"]`. The popup calls `chrome.permissions.request({origins: [<origin>/*]})` on Save | Runtime grant for a user-chosen host, as the brief asks |
| Unreachable state: `bgFetch` failures (network, timeout, missing permission) set a "can't reach TradeMinder" state in the account bar with the configured address. Recovery: the next successful call clears it | One clear message instead of silent missing badges |
| Service worker logs never include the account number. The content script sends it in a single `ACCOUNT_FINGERPRINT` message, and the worker returns only the hash | The number never leaves the page process except into the worker's memory |
| Extension storage holds only `tmApiUrl` and `tmStages`. The resolve cache is in worker memory (`Map<fingerprint, result>`) for the browser session | Nothing account-identifying persists locally |

## Backend

- `models/brokerage_account.py`: `external_label`, `external_seen_at`, check constraint, partial unique index.
- `alembic/versions/017_account_external_link.py`.
- `services/account_links.py`: `resolve`, `link_existing`, `create_and_link`, `unlink`.
- `routers/accounts.py`: the four link endpoints.
- `schemas/account.py`: `AccountLinkRequest`, `AccountLinkResolveResponse`, `AccountCreateAndLink`, `AccountLinkInfo`.
- `routers/positions.py`: `status` with an optional account; `reconcile` with a required account; the default-account
  fallback removed.
- Tests: `tests/test_account_links.py` and `tests/test_positions_scoping.py`; existing reconcile tests updated to
  send `account_id`.

## Extension

- `background.js`:
  - `getApiUrl()` from storage;
  - `FETCH` accepts a `path` and prefixes the stored address, still accepting a full `url` for
    compatibility;
  - fetch failures are classified (`unreachable`, `no_permission`);
  - `ACCOUNT_FINGERPRINT` (SHA-256);
  - `RESOLVE_ACCOUNT` with a session cache;
  - the cache is invalidated after link and unlink.
- `content.js`:
  - prefix-based `ETRADE` selectors;
  - `readAccountContext()`;
  - an `accountContext` state machine (`unknown`, `all`, `single-unlinked`, `single-linked`,
    `single-archived`);
  - `onAccountChange()` clears the caches and re-runs `processVisibleRows`;
  - account bar and link card;
  - scoped calls;
  - per-account chips;
  - All-view account picker in Add trade;
  - Reconcile gating.
- `popup/`: the server address field with a permission request and a reachability dot.
- `manifest.json`: `optional_host_permissions`, `127.0.0.1` host permission.

## SPA

Settings → Accounts gains a "E*TRADE link" column showing the label, "seen <date>" and an Unlink action (with a
confirm dialog). `src/api/accounts.ts` gains `unlink`; `BrokerageAccount` gains `link`.

## Manual verification checklist

1. Link a single unlinked account to an **existing** TradeMinder account through the link card; badges then appear
   for that account's trades only.
2. Link another entry via **Create new**: the prefill is E*TRADE / nickname without " -1020" / 1020; the new
   account appears in the SPA sidebar.
3. Two entries sharing the last four (1020) get separate fingerprints and link to separate accounts.
4. Switching the dropdown re-scopes the badges; no colors or badges from the previous account remain.
5. The All view shows per-account chips for a ticker held in two accounts.
6. Reconcile is disabled in the All view ("Pick a single account in the dropdown") and for an unlinked account
   ("Link this account first").
7. Reconcile in account A never closes account B's trades (checked in the DB).
8. Reinstalling the extension keeps the links (they're server-side; the resolve after reinstall finds them).
9. A bad server address shows the "can't reach TradeMinder" state in the account bar and the popup.
10. No full account number appears in backend logs, DB rows (`brokerage_accounts`) or `chrome.storage`.
11. Backend suite passes apart from the known failures in `test_cc_signal.py`, `test_market_router_p2.py` and
    `test_schwab_client.py`; `tsc -b` adds no errors.

### Results (2026-11-04)

**Harness.** Chrome 156 ignores `--load-extension`, so the unpacked extension could not be loaded into a driven
browser. Instead:
- The real `content.js`, `content.css` and `background.js` ran in a page rebuilt from `docs/DOMSample.html`: the
  real grid, header and Customize markup, plus an `#accountDropdown` with fake 9-digit numbers sharing the last four
  1020. Switching the dropdown re-renders the rows with recycled ids, the way React does.
- A small `chrome.*` shim stood in for the extension APIs: runtime messaging, `storage.local` and `storage.session`,
  `permissions.contains`, and `contextMenus`.
- The backend ran from the worktree against a copy of the live DB (`trademinder_p3test`, migrated to 017), driven
  with Playwright.
- The copy was dropped afterwards. The live DB stayed at 016 and was never touched.

| # | Result |
|---|---|
| 1 | Pass (fixture). "Individual Brokerage -1020" showed the link card with no badges and Reconcile disabled ("Link this account first"). Linking it to the existing "E*TRADE" account brought up badges, pills, colors and the indicator, and enabled Reconcile. |
| 2 | Pass (fixture). "Stock Plan (AVGO) -1020" prefilled E*TRADE / "Stock Plan (AVGO)" / 1020 and defaulted to Create new, because the only account was already linked (shown disabled). The account was created and linked. |
| 3 | Pass. The DB holds two different fingerprints for the two -1020 entries, each on its own account. pytest covers the same case. |
| 4 | Pass (fixture). Switching from the linked account to an unlinked one stripped every badge, color and pill from the recycled row ids. A row id that showed AMD in E*TRADE kept no color in the new account. |
| 5 | Pass (fixture). After an AMD put was added to Stock Plan via right-click → Add (the modal fixed to that account; its session list didn't include the E*TRADE account's sessions), the All view showed two chips on the AMD row: "E*TRADE — SWING" and "Stock Plan (AVGO) ····1020 — WHEEL". |
| 6 | Pass (fixture). The All view showed "Pick a single account in the dropdown"; the unlinked account showed "Link this account first". In the All view, Add trade asks for the account, with the default preselected. |
| 7 | Pass. Reconciling Stock Plan marked its AMD trade seen and reported AVGO unmatched. The E*TRADE account's 131 open trades kept identical `last_etrade_seen` values (same md5 before and after). Switching the dropdown mid-Reconcile sent nothing: the log shows only the one POST. pytest covers both directions. |
| 8 | Pass (fixture). A page reload with empty extension storage, which stands in for a reinstall, resolved both entries as linked straight from the server. Unlink in Settings brought the link card back on the next load. |
| 9 | Pass (fixture). An unreachable address showed "Can't reach TradeMinder at http://127.0.0.1:5999". An address without access showed "No access to …" with the popup hint. Restoring the address recovered on the next call. |
| 10 | Pass. Neither fake number appears in the backend log or a full data dump of the copy. Extension storage held only `tmApiUrl`, `tmStages` and a session cache keyed by fingerprint. The DB check constraint refuses a raw number (pytest). |
| 11 | Pass. pytest: 400 passed, 6 known failures. `tsc -b`: only the 2 pre-existing unused-symbol errors. Settings → Accounts shows the link label, "seen <date>" and Unlink with a confirm dialog. |

**Not provable with the fixture; needs a run on the live E*TRADE page with the extension loaded:**
- the fresh DOM capture in both views;
- the real popup `chrome.permissions.request` prompt;
- the real service worker, including `storage.session` surviving worker suspension;
- an actual remove-and-reload of the extension.
