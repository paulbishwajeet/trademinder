# Account facts (account profile, part 1): design

**Date:** 2026-11-13 · **Branch:** `feature/account-facts` · **Context:** `context/feature-account-facts.md`

## Goal

Editable, per-brokerage-account facts that later features (KB-powered trade guidance, playbook matching, portfolio
import) will read as **gates**, meaning what the account is allowed to do. This part only stores and edits them.
Nothing else in the app changes behavior.

## READ FIRST findings

- **Alembic head.** `alembic heads` on 2026-11-13 gives `018 (head)`, matching the master context. The migration
  is **019**.
- **Existing balance sources.** None store an account's value or cash:
  - **Margin page** (`MarginDashboardPage.tsx`): parses an uploaded E*TRADE positions file in the browser and
    computes "Total Equity Value" and "Liquid Buffer (SGOV + Cash)" for display. It stores nothing, and the result
    isn't per account.
  - **Extension payloads:** `POST /positions/status` and `/positions/reconcile` carry positions only (ticker,
    symbol, type, strike, expiry, ITM), with no balances.

  So the manual `net_liquidation_value` / `cash_balance` / `values_as_of` fields are added as the prompt specifies.
  A future portfolio import can write the same columns.

## Data model (migration 019)

Nullable columns on `brokerage_accounts`. Null means "not set", and the migration sets nothing for existing rows.

| Column | Type | Values |
|---|---|---|
| `tax_treatment` | `varchar(30)` | `taxable`, `traditional_ira`, `roth_ira`, `other_tax_advantaged` |
| `account_purpose` | `varchar(20)` | `trading`, `long_term` (the KB's spelling) |
| `margin_type` | `varchar(20)` | `cash`, `limited_margin`, `margin`, `portfolio_margin` |
| `options_tier` | `varchar(30)` | `none`, `covered`, `cash_secured_and_long`, `spreads`, `uncovered` |
| `options_level_label` | `varchar(40)` | free text, e.g. "Level 2" |
| `net_liquidation_value` | `numeric(14,2)` | ≥ 0 |
| `cash_balance` | `numeric(14,2)` | ≥ 0 |
| `values_as_of` | `timestamptz` | set by the service when either money value changes |
| `facts_updated_at` | `timestamptz` | set by the service when a fact changes |

- **Constraints.** Each enumeration has a named `CHECK` (`ck_brokerage_accounts_<column>`, `col IS NULL OR col IN
  (...)`). The two money columns also get a `≥ 0` check as a backstop to the service rule.
- **Why strings and checks:** that's the table's existing pattern, and it avoids Postgres enum types, so the
  downgrade is a plain drop of the constraints and columns.
- **Options tiers are cumulative and broker-neutral:**
  - `none`: no options;
  - `covered`: covered calls only;
  - `cash_secured_and_long`: adds cash-secured puts and buying calls/puts;
  - `spreads`: adds defined-risk spreads;
  - `uncovered`: adds naked or undefined-risk options.

  The broker's own name for the level goes in `options_level_label`.

## API

There are no new endpoints. `GET /api/accounts`, `POST /api/accounts`, `PATCH /api/accounts/{id}` and
`POST /api/accounts/links` (create-and-link, which reuses the create path) carry the fields.

- **Response (`AccountResponse`):** every column above, plus two read-only derived fields:
  - `account_tax_status`: `taxable` when `tax_treatment = taxable`; `tax_advantaged` for the three IRA/other values;
    null when unset. This is the KB's key and spelling.
  - `facts_complete`: true when `tax_treatment`, `account_purpose`, `margin_type` and `options_tier` are all set.
    The label and the money values are optional.
- **Money** serializes as JSON strings (`"12345.67"`), per the repo convention.
- **Create and update** accept every fact as optional. On `PATCH`, a field that is absent is left alone, and an
  explicit `null` clears it. Unknown enumeration values fail request validation (FastAPI 422).
- **Combination errors** are `422 {detail, code, fields}`. `fields` names the inputs to highlight.

| code | Rule (checked on the merged result: stored values plus the request) |
|---|---|
| `tax_advantaged_margin` | `tax_treatment` ∈ {traditional_ira, roth_ira, other_tax_advantaged} with `margin_type` ∈ {margin, portfolio_margin}. `limited_margin` is allowed |
| `uncovered_requires_margin` | `options_tier = uncovered` with `margin_type` ∈ {cash, limited_margin} |
| `negative_value` | `net_liquidation_value` or `cash_balance` < 0 |
| `invalid_value` | a money value with more than 2 decimals or more than 12 integer digits |

Merely unusual combinations, such as a long-term account with the uncovered tier or a taxable account with limited
margin, are allowed. A rule only fires when both of its fields are set.

## Timestamps

- `facts_updated_at` is set to now whenever the stored value of `tax_treatment`, `account_purpose`, `margin_type`,
  `options_tier` or `options_level_label` changes, including being set at create or cleared. It doesn't change when
  the submitted value equals the stored one, for edits to the nickname, sort order or categories, or for money
  edits.
- `values_as_of` is set to now when `net_liquidation_value` or `cash_balance` changes, and cleared when both become
  null.

Money values are kept off `facts_updated_at` on purpose. Balances move daily, but guidance staleness is about the
gates, and the balances carry their own `values_as_of`.

## Frontend

- **Account dialog** (create and edit, shared with the sidebar gear) gets an **Account facts** section:
  - **Choice fields:** a select for each of tax treatment, purpose, margin type and options tier, each with a "Not
    set" option and a one-line plain explanation of the selected choice. The Options tier select also lists what
    each tier allows, and the broker's level label input sits beside it.
  - **Money fields:** inputs for net liquidation value and cash, showing "as of <date>". The date is muted when it
    is older than 7 days.
  - **Errors:** validation errors from `fields` appear under the inputs involved.
- **Accounts table** gets a **Facts** column showing either a summary (e.g. "Roth IRA · Cash · Covered (Level 1)")
  or an amber **Facts incomplete** button. That button opens the edit dialog scrolled to the facts section. A
  **Value** column shows the net liquidation value and cash with their as-of date, muted when stale.
- **Types and client.** The types in `src/types` keep money as `string | null` and format it with explicit
  `parseFloat`. `ApiError` gains `fields`.
- **UI primitives.** `src/components/ui/` currently holds only `command` and `popover`, so the dialog keeps the
  existing Radix Dialog with Tailwind form styling, like the current account dialog.

## Out of scope

- Goals and preferences. This part adds nothing for them, but the "Account facts" section leaves room for a
  sibling section.
- Any use of the facts elsewhere.
- The KB, its import, guidance and LLM calls.
- Portfolio import, any extension change, and per-broker margin math.

## Tests (pytest)

- **Migration:** 019 on a copy of realistic data (seeded at 018) leaves existing accounts unset and downgrades
  cleanly to 018.
- **Constraints:** each enumeration's check constraint rejects a bad value at the database level.
- **Validation:** each rule, including partial updates that only become invalid after merging.
- **Responses:** the derived fields, and money serializing as strings.
- **Timestamps:** `facts_updated_at` changes only on a real fact change (not on a nickname or sort-order edit, and
  not on a re-save with the same values), and `values_as_of` behaves as described above.
- **Clearing and ownership:** an explicit `null` clears a field, and another user's account returns 404 on update.

## Manual verification checklist (run on a copy of the dev database)

1. Existing accounts show **Facts incomplete**.
2. Fill in a taxable margin account and a Roth IRA.
3. The IRA rejects margin, and a cash account rejects uncovered, with the message under the fields.
4. Edit a fact and see `facts_updated_at` change.
5. Edit only the nickname and see `facts_updated_at` unchanged.
6. A second user can't see or edit the first user's facts (404).

Results are recorded below when run.

### Results (2026-11-13)

**Setup.** Run on `trademinder_aftest`, a `pg_dump | pg_restore` copy of the dev database (at 018, one account),
upgraded to 019 with Alembic. A scratch backend ran on :5441 and Vite on :5440. A second user and the sessions
were minted in the scratch database, and everything was torn down afterwards.

| # | Check | Result |
|---|---|---|
| — | Migration on the dev copy: 018 → 019, existing account unset | ✅ |
| 1 | Existing accounts show **Facts incomplete** (API `facts_complete=false`, `facts_updated_at=null`; table marker) | ✅ |
| 2 | Taxable margin account filled in (`account_tax_status=taxable`); Roth IRA created with facts (`tax_advantaged`) | ✅ |
| 3 | IRA + margin → 422 `tax_advantaged_margin`; cash + uncovered → 422 `uncovered_requires_margin`. In the dialog, the message appears once under Margin type, both fields are outlined red, and it clears on edit | ✅ |
| 4 | Editing a fact moves `facts_updated_at` | ✅ |
| 5 | A nickname-only edit leaves `facts_updated_at` unchanged | ✅ |
| 6 | The second user doesn't see the accounts in their list, and `PATCH` → 404 | ✅ |
| — | **Facts incomplete** opens the dialog on the facts section, with Tax treatment focused | ✅ |
| — | Balances older than 7 days are muted in the table; "88,500.25" is accepted and shown as $88,500 with today's as-of | ✅ |

**Automated.** `test_account_facts.py` (39) and `test_migration_account_facts.py` (1) pass. The full suite gives
556 passed plus the 6 known pre-existing failures. `npm run build` (`tsc -b`) passes, and the changed files have no
lint findings.
