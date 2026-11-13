# Account goal and preferences (account profile, part 2): design

**Date:** 2026-11-13 · **Branch:** `feature/account-goals` · **Context:** `context/feature-account-goals.md`

## Goal

Each brokerage account gets an editable goal and risk preferences, next to the account facts from part 1. Later
guidance treats facts as **gates** (what's allowed) and these as **weights** (what's best among the allowed moves).
This part only stores, defaults and edits them. Nothing else in the app changes behavior.

## READ FIRST findings

- `alembic heads` on 2026-11-13 gives `019 (head)` (account facts, merged to develop as `92eafa1`). This migration
  is **020**.
- The part 1 patterns are reused as they are:
  - columns on `brokerage_accounts`, with null meaning "not set";
  - named `CHECK`s;
  - service validation on the merged stored + request values, with `422 {detail, code, fields}`;
  - a timestamp that moves only on a real change;
  - a derived completeness flag;
  - a dialog section, plus a table marker that opens the dialog at that section.

## Data model (migration 020)

Nullable columns on `brokerage_accounts`. The migration sets nothing on existing rows.

| Column | Type | Allowed (DB `CHECK`) |
|---|---|---|
| `objective` | `varchar(10)` | `income`, `growth`, `mixed` |
| `assignment_stance` | `varchar(12)` | `willing` (happy to own at the strike), `selective` (depends on the ticker), `unwilling` (avoid assignment) |
| `monthly_premium_target` | `numeric(12,2)` | ≥ 0 |
| `annual_yield_target_pct` | `numeric(5,2)` | 0–100 |
| `max_position_pct` | `numeric(5,2)` | > 0 and ≤ 100 |
| `max_speculative_position_pct` | `numeric(5,2)` | > 0 and ≤ 100 |
| `max_margin_used_pct` | `numeric(5,2)` | 0–100 |
| `min_cash_reserve_pct` | `numeric(5,2)` | 0–100 |
| `defensive_at_loss_pct` | `numeric(5,2)` | > 0 and ≤ 100 |
| `goals_updated_at` | `timestamptz` | set by the service |

Percent values are stored as percent: `10` means 10%. Cross-field rules live in the service, not the database,
because they depend on defaults that can change.

## House defaults

`backend/app/services/house_defaults.py` holds the named constants:

| Constant | Value |
|---|---|
| `MAX_POSITION_PCT` | 10 |
| `MAX_SPECULATIVE_POSITION_PCT` | 3 (the top of the KB's 1–3%) |
| `MAX_MARGIN_USED_PCT` | 30 |

The other fields have no default. A comment marks the module to be replaced by values from the imported KB.
Defaults are never written into an account row.

## Effective limits: stored, effective, source

The response includes `limits` with one object per defaulted limit:

```json
"limits": {
  "max_position_pct":             {"stored": null,   "effective": "10.00", "source": "default",  "default": "10.00"},
  "max_speculative_position_pct": {"stored": "2.00", "effective": "2.00",  "source": "account",  "default": "3.00"},
  "max_margin_used_pct":          {"stored": null,   "effective": "0.00",  "source": "cash_account", "default": "30.00"}
}
```

**How the effective value and `source` are worked out:**
1. **The account's own value:** when `stored` is set, the effective value is the stored value and the source is
   `account`.
2. **Cash accounts:** for `max_margin_used_pct` on a `cash` account with nothing stored, the effective value is
   `0` and the source is **`cash_account`**. A cash account can't borrow. This is the "say why" case: it isn't the
   house default, and the account didn't choose it.
3. **Speculative limit capped by the position limit:** for `max_speculative_position_pct` with nothing stored, when
   the house default (3) exceeds the effective `max_position_pct` (e.g. the account set its position limit to 2),
   the effective value is the position limit and the source is **`position_limit`**. A speculative ticker can't be
   allowed more than any ticker. Capping avoids forcing the user to set two fields just to tighten one.
4. **Otherwise:** the effective value is the house default and the source is `default`.

`source` is therefore `account | default | cash_account | position_limit`. The prompt named `account` or `default`;
the other two values say *why* when neither applies (decisions entry). `default` always carries the house default,
so the UI can label it, even while an override is set.

## Rules (422 `{detail, code, fields}`, checked on the merged stored + request values for facts and goals together)

| code | Rule | fields |
|---|---|---|
| `cash_account_margin` | `margin_type = cash` and stored `max_margin_used_pct > 0` | `max_margin_used_pct`, `margin_type` |
| `speculative_above_position` | stored `max_speculative_position_pct` > effective `max_position_pct` | `max_speculative_position_pct`, `max_position_pct` |
| `out_of_range` | a percent outside its range (see the table) | the field |
| `negative_value` | `monthly_premium_target` < 0 | the field |
| `invalid_value` | more than 2 decimals, or too many digits | the field |

**Notes on the rules:**
- **Both edit orders hold.** Facts and goals are merged and validated in one pass, so these cases fail with
  `cash_account_margin`:
  - setting a 25% margin limit on a cash account;
  - switching a margin account with a 25% limit to cash.

  The same holds for the speculative rule: raising the speculative limit, or lowering or clearing the position
  limit below it.
- **Allowed:**
  - a stored `max_margin_used_pct = 0` on a cash account (consistent);
  - an unset margin limit on a cash account;
  - every merely unusual combination, such as growth with a monthly premium target, or a cash reserve plus a margin
    limit over 100.
- **Limited margin** gets no special margin rule. The prompt names only `cash`; this is an open question in the
  context file.

## Timestamps

- `goals_updated_at` moves only when one of the nine goal/preference fields actually changes (Decimal compared by
  value), including a clear.
- Goal edits never touch `facts_updated_at`, and fact edits never touch `goals_updated_at`.

## API

There are no new endpoints. `GET/POST /api/accounts`, `PATCH /api/accounts/{id}` and create-and-link carry the
fields.

- **Requests:** every field is optional. On `PATCH`, an absent field is left alone, and an explicit `null` clears
  it, which makes a limit fall back to its default.
- **Responses:** add the nine stored fields, `limits`, `goals_complete` (`objective` and `assignment_stance` both
  set) and `goals_updated_at`.

## Frontend

The dialog gets a **Goal and preferences** section after Account facts.

- **Objective and assignment stance** are segmented choices (a radio group of buttons), each with a one-line plain
  explanation of the selected choice and a "Clear" link when set.
- **Targets** are optional inputs: monthly premium ($) and annual yield (%).
- **Limits:**
  - Each defaulted limit shows its effective value. When it comes from the house default it's labelled
    **default**, or **cash account** / **capped at position limit** for the other sources.
  - Typing overrides it, and **Use default** clears the override.
  - The defaults' numbers come from `limits.*.default`. For a new account, they come from any existing account,
    since the backend is the single source of the numbers.
- **Margin limit on cash accounts:** when the dialog's margin type is `cash`, the margin limit is hidden with a
  short note ("Cash accounts can't borrow, so margin use is 0."). The exception is a stored nonzero value: then the
  field stays visible with the error, so it can be cleared.
- **Other preferences:** minimum cash reserve (%) and defensive-at-loss (%) are optional inputs with no default.
- **Accounts table:** a **Goal not set** marker appears next to **Facts incomplete** when `goals_complete` is
  false. It opens the dialog at the goals section.
- **Errors:** validation errors from `fields` show under the inputs involved.

## Out of scope

Any use of these fields elsewhere; computing real position size or margin use; the KB, import, guidance or LLM
calls; per-user or portfolio-wide goals; goal history; portfolio import; extension changes.

## Tests (pytest)

- **Migration and constraints:** 020 on realistic 019 data leaves accounts unset and reverses cleanly; each check
  constraint holds.
- **Limits:** effective value and source for each limit, including clearing back to the default, `cash_account`,
  and `position_limit`.
- **Cash-margin rule:** both orders.
- **Speculative rule:** against an explicit and a defaulted position limit.
- **Timestamps and flags:** `goals_updated_at` versus `facts_updated_at` isolation in both directions, and
  `goals_complete`.
- **Validation and ownership:** ranges, and a 404 for another user's account.

## Manual verification checklist (run on a copy of the dev database)

1. An account with nothing set shows the defaults labelled **default**.
2. Override `max_position_pct`, then reset it.
3. A cash IRA hides the margin limit.
4. Switching a margin account with a 25% margin limit to cash is refused.
5. A speculative limit above the position limit is refused.
6. Editing a goal changes `goals_updated_at` but not `facts_updated_at`.
7. A second user can't see or edit these fields.

### Results (2026-11-13)

**Setup.** Run on `trademinder_agtest`, a copy of the dev database at 019 (one account with taxable / margin facts
already set), upgraded to 020 with Alembic. A scratch backend ran on :5441 and Vite on :5440. A second user and the
sessions were minted in the scratch database, and everything was torn down afterwards.

| # | Check | Result |
|---|---|---|
| — | Migration on the dev copy: 019 → 020; goals unset, facts untouched | ✅ |
| 1 | Nothing set → all three limits `source=default` (10 / 3 / 30); the dialog shows "10% default", "3% default" | ✅ |
| 2 | Override `max_position_pct` (7 → `account`), then reset (null → `default`, row null); in the UI, **Use default** appears when overridden and disappears after reset | ✅ |
| 3 | Cash IRA: margin limit `0.00` from `cash_account`; the dialog hides the field with "Cash accounts can't borrow, so margin use is 0." | ✅ |
| 4 | A margin account with a 25% limit switched to cash → 422 `cash_account_margin`. In the UI, an amber hint appears before saving, then the error, with both Margin type and Max margin used outlined | ✅ |
| 5 | A speculative limit above the position limit → 422 `speculative_above_position` (default 10 via the API; your 2 via the UI). Typing a position limit of 2 shows the speculative "2% capped at position limit" | ✅ |
| 6 | A goal edit moves `goals_updated_at` and leaves `facts_updated_at` unchanged; `goals_complete` becomes true | ✅ |
| 7 | The second user doesn't see the accounts, and `PATCH` → 404 | ✅ |
| — | **Goal not set** opens the dialog at the goals section with Income focused; after saving, the row shows "Income · Willing" | ✅ |

**Automated.** `test_account_goals.py` (45) and `test_migration_account_goals.py` (1) pass. The full suite gives
602 passed plus the 6 known pre-existing failures. `npm run build` (`tsc -b`) passes, and the changed files have no
lint findings.

**Fix found during the run:** the speculative error message showed "2.00%"; it's now formatted "2%".
