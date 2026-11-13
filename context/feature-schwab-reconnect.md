# Feature: In-app Schwab reconnect, phase 1 ("paste the redirect URL")

**Status:** Complete — merged to `master`
**Branch:** feature/schwab-reconnect
**Created:** 2026-11-12

## Goal
Let the admin renew the Schwab refresh token from the production web app in under a minute: no Mac, no CLI, no
token-row copy to the NAS. The banner clears without a restart.

## Scope
**In:**
- a backend service: authorize URL with a signed state; validate the pasted redirect URL; exchange the code; write
  the token row under the provider's lock;
- two admin-only endpoints under `/api/market-data/reconnect/*`;
- a Reconnect button on the banner (every state), a Settings → Market data tab (admin only), and the reconnect
  dialog;
- pytest coverage; a manual checklist; docs and a runbook.

**Out:** changing Schwab's registered callback or adding a backend callback route (phase 2); automatic or scheduled
re-auth; storing Schwab credentials; headless login; notifications; Redis or queues; per-user Schwab connections;
changes to signal scoring, the wheel state machine or offline-mode behaviour.

## Key Files / Modules Involved
- **Spec:** `docs/superpowers/specs/2026-11-12-schwab-reconnect-design.md`
- **Plan:** `docs/superpowers/plans/2026-11-12-schwab-reconnect.md`
- `scripts/schwab_auth.py`: the CLI; reference for the authorize URL, exchange and row write.
- `backend/app/services/schwab_client.py`: the provider, its lock and offline state.
- `backend/app/services/auth.py`: `sign_state` / `read_state` (HMAC with `AUTH_STATE_SECRET`).
- `backend/app/routers/market_data.py`, `backend/app/schemas/market_data.py`: the two endpoints, shared status builder.
- `backend/app/services/schwab_oauth.py` (new, standalone): authorize URL, URL parsing, exchange, `store_tokens`.
- `backend/app/services/schwab_reconnect.py` (new): state, errors, `start` / `complete`.
- `backend/tests/test_schwab_reconnect.py` (new).
- `frontend/src/components/MarketData/ReconnectSchwabDialog.tsx` (new: the dialog + `ReconnectSchwabButton`).
- `frontend/src/pages/SettingsMarketDataPage.tsx` (new).
- `scripts/schwab_auth.py`: now uses `schwab_oauth`.
- `docs/deployment/schwab-reconnect.md` (new runbook).
- `frontend/src/components/MarketData/MarketDataBanner.tsx`, `frontend/src/context/MarketDataContext.tsx`,
  `frontend/src/api/marketData.ts`, `frontend/src/components/Layout/SettingsLayout.tsx`, `frontend/src/App.tsx`.

## Technical Approach
See the spec. In short:
- **Start:** returns the CLI's exact authorize URL plus `state`, a signed token bound to the admin with a 10-minute
  expiry.
- **Complete:** takes the pasted URL. It checks it in this order: the callback, then `code`, then `state`, then
  that the state is unused. It then exchanges the code exactly as the CLI does, and writes the row under the
  provider lock.
- **After the write:** the provider reloads the row and leaves offline mode at once, so the banner clears on the
  status refetch.

## Decisions Made
| Decision | Chosen | Reason |
|---|---|---|
| Flow | Paste the redirect URL: Start → Schwab login in a new tab → the dead callback page → paste → exchange | Given in the brief. Schwab allows a single callback URL and its console rejects a second one |
| Backend callback route | None in phase 1 | Given in the brief; possible phase 2 |
| State | HMAC-signed with `AUTH_STATE_SECRET`, bound to the admin's user id, 10-minute expiry, single use in process memory; no Redis or new table | Given in the brief. A single backend process makes memory enough |
| Expired code | Surfaces as "code expired, start again", never a generic 500; the dialog tells the admin to paste promptly | Given in the brief. Schwab codes are short-lived |
| Access | Admin role only, for every endpoint and UI element | Given in the brief. Pilot users never see it |
| Token write | Under the provider's own lock; the provider reloads the row immediately afterwards | Given in the brief, so the banner clears in seconds without a restart |
| Logging | Never log or return tokens, codes or the pasted URL. One success line (user id, new expiry) and one sanitized line per failure | Given in the brief |
| Migration | None | Given in the brief; the existing `schwab_tokens` row is enough |
| Share the OAuth code, don't duplicate it | New standalone `app/services/schwab_oauth.py` (stdlib + httpx + asyncpg, no `app.config`); the CLI imports it via `sys.path`; the provider's refresh write uses the same `store_tokens` | One copy of the URL, exchange and SQL. The CLI still runs standalone from `.env` (checked: `app.config` is never imported) |
| Redirect URI | Stays a constant (`https://127.0.0.1:8765/callback`), not a new env var | There's exactly one registered callback; a setting would invite drift |
| Immediate recovery | `SchwabClient.install_tokens()`: under `_lock`, store → reload the row (new marker) → come online → clear `last_error` | The banner clears on the status refetch; no one-minute wait |
| When the state is consumed | After the URL checks, before the exchange; not restored on a failed exchange | A re-paste after a typo'd URL still works; a used Schwab code can't be retried anyway |
| Pending states after a restart | Forgotten: "link isn't valid any more, start again" | The brief allows process memory; the admin restarts in seconds |
| Error mapping | `bad_url` / `authorization_denied` / `missing_code` / `missing_state` / `code_expired` → 400; `state_invalid` / `state_expired` / `not_configured` → 409; `schwab_unreachable` → 502; body `{detail, code}` | The brief's 400/409/502 split; `apiFetch` already reads `code` |
| Schwab 400/401/403 on exchange | Always `code_expired` ("start again, paste promptly") | Indistinguishable in practice (expired, reused or foreign code); one recovery path |
| No Pydantic length limit on `redirect_url` | Checked in the service (4096 → `bad_url`) | A 422 would echo the pasted URL back |
| Opening Schwab | A real `<a target=_blank>` link shown once start returns | `window.open` after an await is popup-blocked |
| Settings → Market data | A new admin-only tab and route (`/settings/market-data`, behind `RequireAdmin`) | Settings is a tabbed layout; the tab is hidden from non-admins |
| Log level of the success / failure lines | WARNING | The app has no logging config, so INFO never reaches the container log (found during manual verification) |
| One context hook | `useMarketDataStatus` replaced by `useMarketData()` (status + refresh + apply) | Avoids a second non-component export (a new react-refresh lint finding) |
| The dialog's flow state | A child mounted per open; start requested in an effect keyed on an attempt counter | Each open starts fresh, with no new set-state-in-effect lint finding |
| Real-Schwab end-to-end check | In production right after the release, not on the dev copy | It is the real use; a dev-copy authorization might invalidate the NAS's refresh token |

## Open Questions / Blockers
> Still-open items moved to `docs/TRADEMINDER_MASTER_CONTEXT.md` §0 open item 1 on 2026-11-12 (merge).
- [ ] Does Schwab echo `state` back on the callback? The CLI never sent one. Standard OAuth, and schwab-py relies
  on it, so it should; confirmed only by the first real reconnect (checklist 2f).
- [ ] Checklist 2f (real Schwab login → banner clears, quotes return) runs in production after release.

## Progress Log
- 2026-11-12: Branch `feature/schwab-reconnect` off `develop` (`2688107`) in worktree
  `.claude/worktrees/schwab-reconnect`. Read the CLI, the provider, state signing and the banner. Wrote the spec and
  plan. Backend done: `schwab_oauth.py` (shared, CLI uses it), `install_tokens`, `schwab_reconnect.py`, the two
  endpoints; the app imports, and the CLI builds a byte-identical URL.
- 2026-11-12: 33 new tests (`test_schwab_reconnect.py`); full suite 516 passed / the 6 known failures. Frontend:
  dialog, banner button, Settings → Market data; the build passes; ESLint shows only the 2 findings already on
  `develop`. Manual checklist on a DB copy: all ✅ except the real-Schwab login (2f) and a real CLI run (results in
  the spec); the copy was dropped. Docs: master context §0/5/8/10/11, README, the NAS doc, the runbook
  `docs/deployment/schwab-reconnect.md`, and `decisions.md`.

- 2026-11-12: The user tested on the main checkout and approved. Committed `0300319`; merged into `develop` and
  `master` and pushed. Still to do in production: Pull and redeploy on the NAS, then the real-Schwab reconnect
  (checklist 2f) before 2026-11-17.

## Current State (Resume Here)
COMPLETE — merged to `master` (feature `0300319`, 2026-11-12). Follow-up in production: redeploy the NAS and run
the first real Reconnect Schwab (checklist 2f; tracked in master context §0 open item 1).
