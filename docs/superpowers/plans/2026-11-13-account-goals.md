# Account goal and preferences: implementation plan

Spec: `docs/superpowers/specs/2026-11-13-account-goals-design.md`. Order: migration → model → schemas → service →
router → tests → frontend → docs. No commits unless asked.

1. **Migration 020** `backend/alembic/versions/020_account_goals.py`
   - Add the 10 nullable columns, the 2 enum checks and the 7 range checks.
   - The downgrade drops the checks, then the columns.
2. **House defaults** `app/services/house_defaults.py`: three named constants, with a KB note.
3. **Vocabulary, resolution and rules** `app/services/account_goals.py`
   - `GOAL_FIELDS`, the ranges, `effective_limits(values) -> dict`.
   - `validate(merged)`, which raises `AccountFactsError` (the same 422 handler).
4. **Model**
   - The columns plus matching `CheckConstraint`s.
   - Properties `limits` and `goals_complete`.
5. **Schemas**
   - `AccountGoalsInput`, mixed into create and update.
   - `LimitInfo`; the fields plus `limits`, `goals_complete` and `goals_updated_at` on `AccountResponse`.
6. **Service** `accounts.py`
   - Generalise `_apply_facts` into a profile apply that merges facts and goals, validates facts then goals, and
     stamps `facts_updated_at` / `values_as_of` / `goals_updated_at` independently.
7. **Router:** no change.
8. **Tests**
   - `tests/test_account_goals.py`.
   - `tests/test_migration_account_goals.py`: a 019 seed → 020 → 019 on a throwaway database.
9. **Frontend**
   - Types and `src/lib/accountGoals.ts` (labels, hints, source labels).
   - The dialog's "Goal and preferences" section (segmented choices, targets, limit inputs with default/reset,
     cash note).
   - `initialSection: 'goals'`.
   - The table's "Goal not set" marker.
   - Then `npm run build`.
10. **Manual checklist** on a copy of the dev database.
11. **Docs**
    - The master context: §0, §3.6, §8.
    - A `decisions.md` entry.
    - The README.
    - The context checkpoint.
