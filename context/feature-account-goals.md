# Feature: Account goal and preferences (account profile, part 2)

**Status:** Complete
**Branch:** feature/account-goals
**Created:** 2026-11-13

## Goal
An editable goal and risk preferences per brokerage account, next to the account facts from part 1. Guidance will
later use facts as gates and these as weights. This part only stores, defaults and edits them; nothing else in the
app changes behavior.

## Scope
**In:** migration 020 (nullable columns + range/enum checks on `brokerage_accounts`), a house-defaults module,
model, schemas (stored/effective/source per defaulted limit, `goals_complete`, `goals_updated_at`), service
validation on the merged facts + goals, tests, a "Goal and preferences" dialog section, a "Goal not set" marker, docs.
**Out:** any use of the fields elsewhere; computing actual position size or margin use; the KB/import/guidance/LLM;
per-user or portfolio-wide goals; goal history; portfolio import; extension changes.

## Key Files / Modules Involved
- `backend/alembic/versions/020_account_goals.py` — the migration
- `backend/app/services/house_defaults.py` — house default limits (to be sourced from the KB later)
- `backend/app/services/account_goals.py` — vocabulary, effective-limit resolution, rules
- `backend/app/services/accounts.py` — merged facts + goals validation and timestamp stamping
- `backend/app/models/brokerage_account.py`, `backend/app/schemas/account.py`
- `backend/tests/test_account_goals.py`, `backend/tests/test_migration_account_goals.py`
- `frontend/src/components/Accounts/AccountDialog.tsx` — "Goal and preferences" section (Segmented, PctInput,
  LimitInput), `initialSection: 'goals'`
- `frontend/src/pages/SettingsAccountsPage.tsx` — "Profile" column with "Goal not set" marker
- `frontend/src/lib/accountGoals.ts` — labels, hints, source labels; `frontend/src/types/index.ts` — goal types

## Technical Approach
Same pattern as account facts (part 1): nullable columns with named CHECKs; the service merges stored values with
the request and validates the merged result; a timestamp moves only on a real change; a derived completeness flag.
Facts and goals are validated together in one pass, because the cash-margin rule spans both (`margin_type` is a
fact, `max_margin_used_pct` a goal).

## Decisions Made
| Decision | Chosen | Reason |
|---|---|---|
| Where goals live | Per brokerage account, editable any time, nullable = not set; migration sets nothing | Given; mirrors facts |
| Unset limit | Means "use the house default", never "no limit"; defaults are never written to the row | Given: changing a default later reaches every account that didn't override it |
| Staleness | `goals_updated_at`, set only when a goal/preference field actually changes | Given: guidance uses it alongside `facts_updated_at` |
| Units | Percent as Decimal percent (10 = 10%); money as Decimal; JSON strings; TS `string \| null` | Given; repo money convention |
| Limit `source` values | `account \| default \| cash_account \| position_limit` | The prompt asked the cash case to "say why"; capping the speculative default needs the same. Deviation from "account or default" → decisions entry |
| Cash margin limit | Unset on a cash account → effective 0, source `cash_account`; stored > 0 on cash → 422 `cash_account_margin`; stored 0 allowed | A cash account can't borrow; stored 0 is consistent |
| Speculative default vs a tighter position limit | Unset speculative limit is capped at the effective position limit (source `position_limit`); a *stored* speculative limit above the effective position limit → 422 `speculative_above_position` | Tightening one limit shouldn't force setting a second one (don't over-constrain), but an explicit contradiction is rejected |
| One validation pass | Facts and goals merged and validated together in the service | The cash-margin rule spans a fact and a goal; both edit orders must fail |
| `default` in each limit object | Each limit object also carries the house default | The UI labels and shows defaults without duplicating the constants in TypeScript |
| Ranges in DB | Enum and range `CHECK`s in the DB; cross-field rules only in the service | Cross-field rules depend on defaults that will move to the KB |
| Limit UI | Blank input = default; the header shows what blank resolves to (`default` / `cash account` / `capped at position limit`), computed live from the API's default numbers; "Use default" clears | Live feedback while typing without duplicating the constants |
| Cash margin field | Hidden on cash with a note, unless it holds a nonzero value (then shown with an amber hint and the server error) | Hiding a contradicting value would leave the user unable to fix it |
| Table | Column renamed "Profile": facts summary + goal summary, or the two markers side by side | Both markers live together, as the prompt asks |
| Limit scale | Effective and default values quantized to 2 decimals | Same JSON shape ("10.00") whether the value came from the row or a constant |
| Migration number | 020 | `alembic heads` = 019 on 2026-11-13 (account facts) |

## Open Questions / Blockers
- [ ] (Moved to master context §0 open items) Should `limited_margin` (no borrowing in practice) also force the margin limit to 0 like `cash`? The prompt names only cash; left unconstrained for now.

## Progress Log
- 2026-11-13: Branch and worktree created off develop `92eafa1` (account facts merged). Head 019 → migration 020.
  Spec and plan written. Backend done: migration 020, `house_defaults.py`, `account_goals.py` (resolution + rules),
  model, schemas, one facts + goals validation pass in the service; 46 new tests; suite 602 passed + 6 known.
  Frontend done: types, `src/lib/accountGoals.ts`, dialog "Goal and preferences" section (segmented choices,
  targets, limit inputs with default label / "Use default", cash note), "Goal not set" marker; build + lint clean.
  Manual checklist passed on a dev-DB copy (spec Results); fixed percent formatting in the speculative error.
  Docs: master context §0, §3.6, §8; decisions entry; README.

- 2026-11-13: Committed `1c9ec72` and merged to develop. Feature complete: editable goal and preferences per
  account, house defaults with stored/effective/source, cash-margin and speculative rules in every edit order,
  "Goal not set" marker. The `limited_margin` question moved to the master context open items.

## Current State (Resume Here)
COMPLETE — merged to develop (2026-11-13). Not yet on `master`; migration 020 reaches the NAS with the next release.
