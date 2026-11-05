# Feature: Extension Account Awareness (Part 3 of 5)

## Goal
Make the Chrome extension account-aware: configurable TradeMinder server, detect which E*TRADE account is on
screen, link each dropdown entry once (server-side) to a TradeMinder account, scope every overlay call to it (or
across accounts in the All view), and run Reconcile only for a single linked account. No login.

## Scope
In: migration 017 + link endpoints, positions/status + reconcile scoping, extension service worker / detection /
link card / scoped calls / Reconcile gating / popup server address, SPA Settings → Accounts link column, docs.
Out: sign-in/tokens (Part 5), non-E*TRADE overlays, auto-cycling the dropdown, auto state transitions from
Reconcile, Schwab/market data (Part 4), signal scoring, wheel state machine.

## Key Files
- Spec: `docs/superpowers/specs/2026-11-04-extension-account-awareness-design.md`
- Plan: `docs/superpowers/plans/2026-11-04-extension-account-awareness.md`
- Backend:
  - `alembic/versions/017_account_external_link.py` and `models/brokerage_account.py`: `external_label`,
    `external_seen_at`, a check that `external_ref` is a 64-hex fingerprint, and a partial unique index on
    `(user_id, external_ref)`.
  - New `services/account_links.py` (resolve, link_existing, create_and_link, unlink).
  - `services/accounts.py`: `create_account(commit=False)`; `_reload` renamed to `reload_account`.
  - `routers/accounts.py`: `POST /links/resolve`, `POST /links`, `POST /{id}/link`, `DELETE /{id}/link`.
  - `schemas/account.py`: `Fingerprint`; `ExternalLabel`, which rejects 6+ digit runs; `AccountLinkInfo`.
    `AccountResponse.link` replaces `external_ref`.
  - `routers/positions.py` and `schemas/positions.py`: status takes an optional `account_id` and returns
    `account` + `matches`. Reconcile requires `account_id`. Matching runs per account via `_match_trade`.
- Tests:
  - new `tests/test_account_links.py` and `tests/test_positions_scoping.py`;
  - `tests/test_reconcile.py` and `tests/test_isolation.py` now send `account_id`.
- Extension:
  - `background.js`: stored address, path-based `FETCH`, `errorKind`, SHA-256 fingerprint, `RESOLVE_ACCOUNT` and
    `LINK_ACCOUNT` with a `storage.session` cache.
  - `content.js`:
    - prefix selectors via `cls()`;
    - the ACCOUNT CONTEXT section (`readAccountDropdown`, `onAccountChange`, `resetOverlay`, `overlayScope`,
      `addTradeScope`, account bar, link card, toast, `chooseFrom`);
    - scoped fetches with generation guards;
    - chips;
    - Reconcile gating;
    - add/edit modals scoped by account;
    - delegated `change` listener plus a 1 s watchdog.
  - `content.css`: new account UI styles.
  - `manifest.json`: `optional_host_permissions`, `127.0.0.1`.
  - `popup/*`: server address, permission request, status text.
- SPA: `SettingsAccountsPage.tsx` (E*TRADE link column, Unlink dialog), `api/accounts.ts` (`unlink`),
  `types/index.ts` (`AccountLink`).
- Docs: `context/extension.md` (DOM facts), `docs/TradeMinder-Context.md`, `README.md` (extension section, DOM
  reference).

## Decisions Made
| Decision | Reason |
|---|---|
| Server address configured once in the popup; extension acts as the single owner until Part 5 | Login is Part 5; `get_current_user` is the seam |
| Account on screen read from `#accountDropdown`; first sighting shows a link card (existing account or Create new, prefilled) | User maps broker accounts to containers once |
| Links stored server-side; 1 dropdown entry ↔ 1 account, 1 account ≤ 1 link | Survives reinstall, works across computers |
| Link key = SHA-256(broker + full account number) in the service worker; full number never sent or stored | Last four isn't unique; full number is sensitive |
| Reconcile only for a single linked account | It backdate-closes missing trades — the account must be certain |
| Overlays in every view; single = that account, All = across accounts with per-account chips | No cross-account painting |
| Add trade → linked account; All view asks; unlinked disables | Writes need a known account |
| Branch stacked on Part 2 (`b7e094f`), worked in a git worktree | Parts 1–2 aren't in develop; the user's dev backend reloads from the main checkout against the live DB, so new model columns there would break it before migration |
| No `extension/sidebar/` exists → "sidebar" = an account bar at the start of `#tm-toolbar` + link card under it | Matches the existing in-page UI; no new sidePanel permission |
| See spec "Decisions (made here)" for endpoint shapes, fingerprint format, cache keying, permissions | Kept in one place |
| Live DB not migrated; verification ran on a dropped copy (`trademinder_p3test`) | Migrating the user's live DB needs their go-ahead |
| Verified with the real content/background scripts in a fixture page plus a `chrome.*` shim, not a loaded extension | Chrome 156 (branded) ignores `--load-extension`; no separate Chromium was downloaded |
| Reconcile aborts, without sending, if the dropdown changed while it was collecting rows | Sending B's snapshot as A would backdate-close A's trades |
| Unrecognised dropdown values and an unresolved/unlinked single account paint nothing | Better no badge than the wrong account's |
| No account dropdown on the page → treated like the All view (cross-account statuses, Reconcile off) | Users with one E*TRADE account may not get a dropdown |
| Resolve is fresh on the first sight of each entry per page load, then cached for the browser session | Unlinks in the SPA show up on the next reload without a worker restart |
| Link label rejected if it contains 6+ consecutive digits | Server-side guarantee that no full account number lands in `external_label` |

## Open Questions
1. **Merged vs separate rows in the All view** is still unknown. The fresh captures contain no position held in two
   accounts. Chips don't depend on it.
2. **The live backend still serves Part 2 code.** The live DB is at 017 (2026-11-04, after a backup), but the main
   checkout that runs `uvicorn --reload` is on `feature/account-container-ui`, so the link endpoints aren't live
   yet. The extension from this branch needs this branch's backend.
3. **Fingerprint strength.** An unsalted SHA-256 of a 9-digit account number can be brute-forced in seconds by
   anyone holding the DB, so the hash hides the number only from casual reads. The brief fixed SHA-256. If this
   matters, switch to PBKDF2 with many iterations: deterministic, still computed only in the worker, with no
   per-user secret. That needs a relink, or a re-hash during the next resolve.
4. **Pre-existing behaviour kept.** Positions with no matching trade still get the green "ok" border and no ⊘
   badge, because status always returns an entry (`trade_id` null). In the All view, the commentary pill and row
   color follow the primary match (most severe alert, then account order); the chips show the rest.
5. **Filter toolbar now appears.** Because the grid is found structurally, `#tm-toolbar` (category filters, Fetch
   RSI and now the account bar) gets inserted. Under `#rdt_3` it most likely never was, since the captures show
   `rdt_2`.
6. Parts 1 and 2 are unmerged; this branch is stacked on them.

## Progress Log
- 2026-11-04: Branch and worktree created (stacked on Part 2). Spec, plan and context written. The June capture
  confirms the brief's dropdown facts; `#positionsView` is a separate (layout) select.
- 2026-11-04:
  - Backend: migration 017, link endpoints, positions scoping, 24 new tests, old reconcile tests updated. Suite:
    400 passed, 6 known failures.
  - Extension: service worker, detection, link card, scoped calls, chips, Reconcile gating, popup.
  - SPA: link column and Unlink.
  - Docs updated.
- 2026-11-04: Fixture verification against a DB copy: all 11 checklist items pass (results in the spec). Sandbox
  torn down.
- 2026-11-04: Fresh masked captures (single account + All view) analysed. All of the brief's facts are confirmed.
  Two All-view differences were fixed: there's no Trade button, so the symbol comes from the quote link, and
  there's no Customize, so Reconcile anchors to the links container. The fixture was rebuilt from both captures
  and re-run: badges, chips, the right-click menu, Reconcile gating and the Edit account chooser all pass.
- 2026-11-04: With the user's approval, backed up the live DB to
  `backups/trademinder-pre-017-20261104-1233.dump` (pg_dump -Fc) and migrated it 016 → 017. 443 trades intact;
  the running Part 2 app is unaffected (the new columns are additive).
- 2026-11-04: Committed Part 3 as `00eb5cc` on `feature/extension-account-awareness`, removed the worktree and
  switched the main checkout to the branch. Live check after the dev servers reloaded:
  - `GET /api/accounts` returns `link` and no `external_ref`;
  - `POST /api/accounts/links/resolve` answers (probed with a dummy fingerprint; no write);
  - reconcile without `account_id` returns 422;
  - the SPA loads through Vite on 5430, including Settings → Accounts.

  The real E*TRADE run hasn't happened yet.
- 2026-11-04: The user tested on real E*TRADE. First-time linking and the reset on account switch work as
  intended. Feedback: the toolbar filter left gaps where non-matching rows were hidden, so the filter now dims
  them instead (`applyFilter` toggles `.tm-filtered-out`; `content.css`). The user confirmed it looks good; committed as
  `b26ec00`.

## Current State
**Part 3 is committed and running live; the user has partly verified it on the real E*TRADE page. Nothing is
pushed.**

- **Branch:**
  - `feature/extension-account-awareness`, checked out in the main checkout, is develop (`4872ac1`) plus:
    - Part 1: `92447f1`, `c7c2893`, `1364bd5`;
    - Part 2: `b7e094f`;
    - Part 3: `00eb5cc` (feature) and `b26ec00` (filter dims instead of hiding).

    None of it is pushed or in develop.
  - Uncommitted: this context update only.
  - Untracked `.claude/worktrees/` and `docs/learnings/` predate this work; leave them out of commits.
- **Live environment:**
  - The user's dev servers (`uvicorn --reload` on 5431, Vite on 5430) serve this branch against the live DB at
    revision 017.
  - Backup taken before 017: `backups/trademinder-pre-017-20261104-1233.dump` (restore with `pg_restore --clean`
    inside `trademinder-db-1`).
  - The user's Chrome has the extension from this branch loaded, and links are being created on the live DB.
- **Verified:**
  - pytest: 400 passed / 6 known failures. `tsc -b`: only the 2 pre-existing errors.
  - Fixture runs from the June capture and the fresh Nov captures: all checklist items pass.
  - Real E*TRADE page, by the user: first-time linking through the card, everything resetting correctly on an
    account switch, and the toolbar category filter (after the dimming fix).
- **Not yet verified on the real page:**
  - Reconcile in a single linked account, and that it touches only that account (check `last_etrade_seen` in the
    DB);
  - Reconcile disabled in the All view with its hint;
  - per-account chips in the All view (needs a position tracked in both accounts);
  - removing and re-adding the extension: the links should survive without the card;
  - a bad server address in the popup showing "Can't reach TradeMinder".
- **Open decisions:**
  - Fingerprint strength (Open Question 3): unsalted SHA-256 of a 9-digit number is brute-forceable from the DB.
    Optional switch to PBKDF2, which needs a relink or a re-hash on the next resolve.
  - Whether the All view shows a position held in two accounts as two rows or one merged row (Open Question 1;
    chips work either way).
  - Parts 1–3 need to land in develop.

**Single next action:** finish the remaining real-page checks above and record them in the spec's Results table
(add a "real page" column or note). Then push the branches and open PRs into develop in order: Part 1
(`feature/multi-account-foundation`), then Part 2 (`feature/account-container-ui`), then Part 3 (this branch),
each rebased onto develop after the previous one merges.
