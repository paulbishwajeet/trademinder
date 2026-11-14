# Feature: Account facts (account profile, part 1)

**Status:** Complete
**Branch:** feature/account-facts
**Created:** 2026-11-13

## Goal
Editable, per-brokerage-account facts (tax treatment, purpose, margin type, options tier, optional balances) that
later features (KB-powered trade guidance, playbook matching, portfolio import) will read. This part only stores and
edits them; nothing else in the app changes behavior.

## Scope
**In:** migration 019 (nullable columns + check constraints on `brokerage_accounts`), model, schemas (incl. derived
`account_tax_status` and `facts_complete`), service validation (422 + code), the existing accounts create/update/list
endpoints, tests, Settings → Accounts "Account facts" section and "Facts incomplete" marker, docs.
**Out:** goals and preferences (next prompt), any use of the facts elsewhere (signals, chain screener, margin page,
alerts, WHEEL), the KB/import/guidance/LLM, portfolio import, any extension change, per-broker margin math.

## Key Files / Modules Involved
- `backend/alembic/versions/019_account_facts.py` — the migration
- `backend/app/models/brokerage_account.py` — model columns + constraints
- `backend/app/schemas/account.py` — fact fields, derived fields, create/update requests
- `backend/app/services/accounts.py` — validation, `facts_updated_at` / `values_as_of` stamping
- `backend/app/services/account_facts.py` — vocabulary, derivations and combination rules
- `backend/tests/test_account_facts.py` — API, rules, timestamps, clearing, 404, DB checks
- `backend/tests/test_migration_account_facts.py` — 018 seed → 019 → 018
- `backend/app/main.py` — `AccountFactsError` → 422 handler
- `frontend/src/pages/SettingsAccountsPage.tsx` — Facts / Value columns, "Facts incomplete" marker
- `frontend/src/components/Accounts/AccountDialog.tsx` — Account facts section, `initialSection`, field errors
- `frontend/src/lib/accountFacts.ts` — labels, one-line hints, summary, money/staleness helpers
- `frontend/src/api/client.ts` — `ApiError.fields`; `frontend/src/types/index.ts` — fact types
- `docs/superpowers/specs/2026-11-13-account-facts-design.md`, `docs/superpowers/plans/2026-11-13-account-facts.md`

## Technical Approach
Columns on `brokerage_accounts`, all nullable. Enumerations as `String` columns with named `CHECK` constraints (the
repo's existing pattern; no Postgres enum types, so the downgrade is a plain drop). The service merges the stored
facts with the request, validates the merged result, and stamps `facts_updated_at` only when a fact value actually
changes and `values_as_of` only when a money value changes. Derived fields are model properties read by the response
schema. Errors use the `{detail, code}` body already used by the market-data endpoints.

## Decisions Made
| Decision | Chosen | Reason |
|---|---|---|
| Where facts live | Per brokerage account, not per user | An IRA and a taxable account at the same broker really do differ (given) |
| Unset values | Every fact nullable; null = "not set"; migration sets nothing | Guessing values for existing accounts would be wrong data (given) |
| Editing | Editable any time; `facts_updated_at` set only when a fact actually changes; no audit table | Facts change in real life; guidance uses the timestamp to detect staleness (given) |
| Broker | Keep the existing `broker` column | No second source of truth (given) |
| Options approval | Broker-neutral `options_tier` + optional `options_level_label` | Brokers number levels differently (given) |
| Money | `Numeric` in the DB, JSON strings in the API, `string \| null` in TS | Repo-wide money convention (given) |
| Balances source | Manual `net_liquidation_value` / `cash_balance` + `values_as_of` | READ FIRST found no stored source: the Margin page parses an uploaded file in the browser and keeps nothing; extension status/reconcile payloads carry positions only |
| Migration number | 019 | `alembic heads` = 018 on 2026-11-13, matching the master context |
| Enum storage | `String` + named `CHECK` constraints | Matches existing constraints on the table; clean downgrade; no Postgres enum type to migrate later |
| Money vs `facts_updated_at` | Money edits stamp only `values_as_of`, not `facts_updated_at` | Balances move daily; guidance staleness is about the gates, and balances carry their own as-of |
| "Changed" | A fact counts as changed only when the stored value differs (Decimal compared by value) | A form re-save with the same values must not mark guidance stale |
| Error body | `422 {detail, code, fields}` via an app-level `AccountFactsError` handler | Router stays thin; `fields` lets the UI put the message under the right inputs |
| Money range | `numeric(14,2)`; >2 decimals or >12 integer digits → 422 `invalid_value`; DB also has `≥ 0` checks | A coded error instead of a DB error; backstop at the DB |
| Migration test data | A 018 seed (linked IRA, archived account, second user, a trade) in a throwaway DB; the dev-DB copy is the manual checklist | Same pattern as `test_migration_multi_account.py`; CI-safe |
| Field error display | Highlight every field in `fields`; show the message once, under the last named field; any fact edit clears it | Rules name two fields; a duplicated message is noise |
| Options tier help | One-line hint for the selected choice, plus a "What each tier allows" disclosure listing all tiers | Meets "each choice gets a one-line explanation" without a very long dialog |
| UI primitives | Radix Dialog plus Tailwind form controls, like the existing dialog | `src/components/ui/` has only `command` and `popover`; no select/radio primitive exists |
| KB spellings | `account_tax_status` (`taxable`/`tax_advantaged`) derived; `account_purpose` stored with `trading`/`long_term` | The KB's situation pages match on exactly these keys |

## Open Questions / Blockers
- [ ] (Moved to master context §0 open items) `cash_balance` can't be negative (per the prompt), but a margin account with a debit has negative cash. Confirm whether a margin debit should be representable later (e.g. allow negative cash only on margin types).

## Progress Log
- 2026-11-13: Branch and worktree created off develop `65f1530`. READ FIRST done: head 018 → migration 019; no
  existing balance source, so manual balance fields. Spec and plan written. Backend done: migration 019, model,
  `account_facts.py` rules, schemas, service stamping, 422 handler; 40 new tests; full suite 556 passed, 6 known
  failures.
  Frontend done: types, `ApiError.fields`, `src/lib/accountFacts.ts`, the dialog's facts section, and the table's
  Facts/Value columns; build passes, changed files lint-clean. Manual checklist passed on a dev-DB copy (spec
  Results). Docs: master context §0, §3.6, §7, §8; decisions entry; README.

- 2026-11-13: Committed `11e5039` and merged to develop. Feature complete: account facts are editable per account,
  existing accounts show "Facts incomplete", impossible combinations return 422 with fields. Negative-cash
  question moved to the master context open items.

## Current State (Resume Here)
COMPLETE — merged to develop (2026-11-13). Not yet on `master`; migration 019 reaches the NAS with the next release
(Pull and redeploy runs `alembic upgrade head`).
