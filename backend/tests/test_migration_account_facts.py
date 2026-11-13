"""Migration 019 (account facts) on realistic 018 data: existing accounts stay unset, nothing else
changes, the check constraints hold, and the downgrade back to 018 is clean. Runs alembic against a
throwaway database."""
import os
import subprocess
import sys
from pathlib import Path

import asyncpg
import pytest

ADMIN_DSN = "postgresql://trademinder:password@localhost:5432/postgres"
DB_NAME = "trademinder_migration_019_test"
DSN = f"postgresql://trademinder:password@localhost:5432/{DB_NAME}"
BACKEND_DIR = Path(__file__).resolve().parents[1]

FACT_COLUMNS = {
    "tax_treatment", "account_purpose", "margin_type", "options_tier", "options_level_label",
    "net_liquidation_value", "cash_balance", "values_as_of", "facts_updated_at",
}
CONSTRAINTS = {
    "ck_brokerage_accounts_tax_treatment", "ck_brokerage_accounts_account_purpose",
    "ck_brokerage_accounts_margin_type", "ck_brokerage_accounts_options_tier",
    "ck_brokerage_accounts_net_liquidation_value_non_negative", "ck_brokerage_accounts_cash_balance_non_negative",
}

# On top of what 015/016 seed (the owner and a default E*TRADE account): a linked IRA, an archived
# account, a second user with an account, and a trade in the IRA.
SEED_SQL = """
INSERT INTO brokerage_accounts (id, user_id, broker, nickname, last_four, external_ref, external_label,
                                external_seen_at, sort_order, is_default, is_archived)
  SELECT '00000000-0000-0000-0000-0000000000a2', id, 'E*TRADE', 'IRA', '4321', repeat('ab', 32), 'IRA -4321',
         '2026-11-10', 1, false, false FROM users;
INSERT INTO brokerage_accounts (id, user_id, broker, nickname, sort_order, is_default, is_archived)
  SELECT '00000000-0000-0000-0000-0000000000a3', id, 'Schwab', 'Old', 2, false, true FROM users;
INSERT INTO users (id, email, display_name, status) VALUES
  ('00000000-0000-0000-0000-0000000000b1', 'pilot@example.com', 'Pilot', 'active');
INSERT INTO brokerage_accounts (id, user_id, broker, nickname, is_default) VALUES
  ('00000000-0000-0000-0000-0000000000a4', '00000000-0000-0000-0000-0000000000b1', 'Fidelity', 'Pilot', true);
INSERT INTO trades (id, user_id, account_id, type, category, strategy, ticker, open_date, quantity, premium, status)
  SELECT gen_random_uuid(), user_id, id, 'Sell', 'WHEEL', 'Put', 'NVDA', '2026-10-01', 1, 3.10, 'open'
  FROM brokerage_accounts WHERE id = '00000000-0000-0000-0000-0000000000a2';
"""

SNAPSHOT_SQL = """
SELECT id, user_id, broker, nickname, last_four, external_ref, external_label, external_seen_at,
       default_category_id, is_default, sort_order, is_archived, created_at
FROM brokerage_accounts ORDER BY id
"""


def _alembic(*args: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "DATABASE_URL": f"postgresql+asyncpg://trademinder:password@localhost:5432/{DB_NAME}",
        "OWNER_EMAIL": "owner@example.com",
        "OWNER_DISPLAY_NAME": "The Owner",
    }
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )


async def _admin(sql: str) -> None:
    admin = await asyncpg.connect(ADMIN_DSN)
    try:
        await admin.execute(sql)
    finally:
        await admin.close()


async def _columns(conn) -> set[str]:
    rows = await conn.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'brokerage_accounts'")
    return {r["column_name"] for r in rows}


async def _constraints(conn) -> set[str]:
    rows = await conn.fetch(
        "SELECT conname FROM pg_constraint WHERE conrelid = 'brokerage_accounts'::regclass AND contype = 'c'")
    return {r["conname"] for r in rows}


async def test_migration_019_leaves_accounts_unset_and_reverses():
    try:
        await _admin(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)")
        await _admin(f"CREATE DATABASE {DB_NAME}")
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Postgres not available for migration test: {exc}")

    try:
        result = _alembic("upgrade", "018")
        assert result.returncode == 0, result.stderr
        conn = await asyncpg.connect(DSN)
        try:
            await conn.execute(SEED_SQL)
            before = [dict(r) for r in await conn.fetch(SNAPSHOT_SQL)]
            trades_before = await conn.fetchval("SELECT count(*) FROM trades")
            constraints_before = await _constraints(conn)
            assert not FACT_COLUMNS & await _columns(conn)
        finally:
            await conn.close()
        assert len(before) == 4

        result = _alembic("upgrade", "019")
        assert result.returncode == 0, result.stderr
        conn = await asyncpg.connect(DSN)
        try:
            assert FACT_COLUMNS <= await _columns(conn)
            assert CONSTRAINTS <= await _constraints(conn)
            # Existing accounts: every fact unset, everything else untouched.
            for column in FACT_COLUMNS:
                assert await conn.fetchval(f"SELECT count(*) FROM brokerage_accounts WHERE {column} IS NOT NULL") == 0
            assert [dict(r) for r in await conn.fetch(SNAPSHOT_SQL)] == before
            assert await conn.fetchval("SELECT count(*) FROM trades") == trades_before

            # The checks hold at the database level, and valid values are accepted.
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute("UPDATE brokerage_accounts SET options_tier = 'level_2'")
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute("UPDATE brokerage_accounts SET cash_balance = -1")
            await conn.execute(
                "UPDATE brokerage_accounts SET tax_treatment = 'roth_ira', account_purpose = 'long_term', "
                "margin_type = 'limited_margin', options_tier = 'cash_secured_and_long', "
                "net_liquidation_value = 1234.56, facts_updated_at = now() "
                "WHERE id = '00000000-0000-0000-0000-0000000000a2'")
        finally:
            await conn.close()

        result = _alembic("downgrade", "018")
        assert result.returncode == 0, result.stderr
        conn = await asyncpg.connect(DSN)
        try:
            assert not FACT_COLUMNS & await _columns(conn)
            assert await _constraints(conn) == constraints_before
            assert [dict(r) for r in await conn.fetch(SNAPSHOT_SQL)] == before
            assert await conn.fetchval("SELECT version_num FROM alembic_version") == "018"
        finally:
            await conn.close()

        # And forward again (the downgrade left nothing behind that blocks a re-run).
        result = _alembic("upgrade", "head")
        assert result.returncode == 0, result.stderr
    finally:
        await _admin(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)")
