# Account facts: implementation plan

Spec: `docs/superpowers/specs/2026-11-13-account-facts-design.md`. Order: migration → model → schemas → service →
router → tests → frontend → docs. No commits unless asked.

1. **Migration 019** `backend/alembic/versions/019_account_facts.py`
   - Add the 9 nullable columns.
   - Add the named checks: 4 enumerations plus 2 money ≥ 0.
   - The downgrade drops the constraints, then the columns.
2. **Model** `app/models/brokerage_account.py`
   - The columns and the same `CheckConstraint`s (the tests build the schema from metadata).
   - Properties `account_tax_status` and `facts_complete`, delegating to `app/services/account_facts.py`.
3. **Vocabulary and rules** `app/services/account_facts.py`
   - The tuples of allowed values, `FACT_FIELDS`, `MONEY_FIELDS` and `tax_status()`.
   - `validate(merged) -> None`, which raises `AccountFactsError(code, detail, fields)`.
4. **Schemas** `app/schemas/account.py`
   - `Literal` types for the enumerations.
   - The label stripped, with an empty string meaning null.
   - Money as `Decimal`.
   - The fields on `AccountResponse` (plus the derived ones), `AccountCreate` and `AccountUpdate`.
5. **Service** `app/services/accounts.py`
   - `_apply_facts(account, data, now)`: merge, validate, assign, then stamp `facts_updated_at` / `values_as_of`
     only on real changes.
   - Called from `create_account` and `update_account`.
6. **Router and app**
   - The router needs no change: the shapes flow through.
   - `app/main.py` gets an `AccountFactsError` handler returning `422 {detail, code, fields}`.
7. **Tests**
   - `tests/test_account_facts.py`: API, rules, timestamps, clearing, 404, DB checks.
   - `tests/test_migration_account_facts.py`: 018 seed → 019 → 018 on a throwaway database.
8. **Frontend**
   - `ApiError.fields`.
   - Types and the facts vocabulary with labels and explanations (`src/lib/accountFacts.ts`).
   - `AccountDialog`: the facts section, `initialSection`, and field errors.
   - `SettingsAccountsPage`: the Facts and Value columns and the incomplete marker.
   - Then `npm run build`.
9. **Manual checklist** on a copy of the dev database (scratch database plus a scratch backend and Vite).
10. **Docs**
    - The master context: §0 (019 and the head), §3.6, §8 accounts.
    - A `docs/decisions.md` entry.
    - The README, if it describes accounts.
    - The context checkpoint.
