"""Migrations 015/016 on realistic pre-accounts data: backfill, memberships, account categories,
scoped uniqueness, and a clean downgrade back to 014. Runs alembic against a throwaway database."""
import os
import subprocess
import sys
from pathlib import Path

import asyncpg
import pytest

ADMIN_DSN = "postgresql://trademinder:password@localhost:5432/postgres"
DB_NAME = "trademinder_migration_test"
DSN = f"postgresql://trademinder:password@localhost:5432/{DB_NAME}"
BACKEND_DIR = Path(__file__).resolve().parents[1]
OWNER_EMAIL = "Owner@Example.com"

USER_OWNED = [
    "trades", "rationale", "commentary", "categories", "alerts", "technical_signals",
    "wheel_sessions", "wheel_slots", "wheel_slot_legs", "wheel_premium_logs",
    "trade_sessions", "screener", "screener_commentary", "daily_briefings",
]
ACCOUNT_SCOPED = ["trades", "wheel_sessions", "trade_sessions", "screener_commentary"]

SEED_SQL = """
INSERT INTO trade_sessions (id, ticker, strategy, status, rotation_number, opened_at)
  VALUES ('00000000-0000-0000-0000-0000000000a1', 'SPY', 'IRON_CONDOR', 'open', 1, '2026-10-01');
INSERT INTO trades (id, session_id, type, category, category_id, strategy, ticker, open_date, expiry_date,
                    strike_price, quantity, premium, status, etrade_symbol)
  VALUES ('00000000-0000-0000-0000-0000000000b1', NULL, 'Sell', 'WHEEL',
          (SELECT id FROM categories WHERE name = 'WHEEL'), 'Put', 'NVDA', '2026-10-01', '2026-11-20',
          120, 1, 3.10, 'open', 'NVDA--261120P00120000'),
         ('00000000-0000-0000-0000-0000000000b2', '00000000-0000-0000-0000-0000000000a1', 'Sell', 'IRON_CONDOR',
          NULL, 'Put', 'SPY', '2026-10-01', '2026-11-20', 550, 1, 1.20, 'open', NULL),
         ('00000000-0000-0000-0000-0000000000b3', NULL, 'Buy', 'WHEEL', NULL, 'Stock', 'NVDA', '2026-09-01',
          NULL, NULL, 100, 110, 'closed', NULL);
INSERT INTO rationale (id, trade_id, fetch_status, rsi_14) VALUES
  (gen_random_uuid(), '00000000-0000-0000-0000-0000000000b1', 'ok', 41.5);
INSERT INTO wheel_sessions (id, ticker, total_shares, status, opened_at) VALUES
  ('00000000-0000-0000-0000-0000000000c1', 'NVDA', 0, 'active', '2026-10-01'),
  ('00000000-0000-0000-0000-0000000000c2', 'NVDA', 100, 'active', '2026-09-01');
INSERT INTO wheel_slots (id, session_id, slot_number, contracts, shares_held, status, needs_action, rotation_number)
  VALUES ('00000000-0000-0000-0000-0000000000d1', '00000000-0000-0000-0000-0000000000c1', 1, 1, 0,
          'sold_put_active', false, 1);
INSERT INTO wheel_slot_legs (id, slot_id, trade_id, leg_role, rotation_number) VALUES
  ('00000000-0000-0000-0000-0000000000e1', '00000000-0000-0000-0000-0000000000d1',
   '00000000-0000-0000-0000-0000000000b1', 'sold_put', 1);
INSERT INTO wheel_premium_logs (id, slot_id, leg_id, rotation_number, premium_amount, event_type, event_date) VALUES
  (gen_random_uuid(), '00000000-0000-0000-0000-0000000000d1', '00000000-0000-0000-0000-0000000000e1', 1, 310,
   'put_sold', '2026-10-01');
INSERT INTO commentary (id, trade_id, note) VALUES (gen_random_uuid(), '00000000-0000-0000-0000-0000000000b1', 'trade note');
INSERT INTO commentary (id, slot_id, note) VALUES (gen_random_uuid(), '00000000-0000-0000-0000-0000000000d1', 'slot note');
INSERT INTO alerts (id, trade_id, alert_type, severity, title, message, is_read, is_dismissed) VALUES
  (gen_random_uuid(), '00000000-0000-0000-0000-0000000000b1', 'dte_threshold', 'warning', 't', 'm', false, false);
INSERT INTO technical_signals (trade_id, signal_type, is_active) VALUES
  ('00000000-0000-0000-0000-0000000000b1', 'rsi_oversold', true);
INSERT INTO screener (id, symbol, price) VALUES
  ('00000000-0000-0000-0000-0000000000f1', 'AAPL', 230), ('00000000-0000-0000-0000-0000000000f2', 'MSFT', 410);
INSERT INTO screener_commentary (id, screener_id, note) VALUES
  (gen_random_uuid(), '00000000-0000-0000-0000-0000000000f1', 'watch for pullback');
INSERT INTO daily_briefings (id, briefing_date, content) VALUES (gen_random_uuid(), '2026-11-01', 'brief');
"""


def _alembic(*args: str, owner_email: str = OWNER_EMAIL) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "DATABASE_URL": f"postgresql+asyncpg://trademinder:password@localhost:5432/{DB_NAME}",
        "OWNER_EMAIL": owner_email,
        "OWNER_DISPLAY_NAME": "The Owner",
    }
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )


async def _recreate_db() -> None:
    admin = await asyncpg.connect(ADMIN_DSN)
    try:
        await admin.execute(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)")
        await admin.execute(f"CREATE DATABASE {DB_NAME}")
    finally:
        await admin.close()


async def _drop_db() -> None:
    admin = await asyncpg.connect(ADMIN_DSN)
    try:
        await admin.execute(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)")
    finally:
        await admin.close()


async def _columns(conn, table: str) -> set[str]:
    rows = await conn.fetch("SELECT column_name FROM information_schema.columns WHERE table_name = $1", table)
    return {r["column_name"] for r in rows}


async def _counts(conn) -> dict[str, int]:
    return {t: await conn.fetchval(f"SELECT count(*) FROM {t}") for t in USER_OWNED}


async def test_migrations_015_016_backfill_and_reverse():
    try:
        await _recreate_db()
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Postgres not available for migration test: {exc}")

    try:
        result = _alembic("upgrade", "014")
        assert result.returncode == 0, result.stderr
        conn = await asyncpg.connect(DSN)
        try:
            await conn.execute(SEED_SQL)
            before = await _counts(conn)
        finally:
            await conn.close()

        # 015 refuses to run without an owner email
        result = _alembic("upgrade", "head", owner_email="")
        assert result.returncode != 0 and "OWNER_EMAIL" in result.stderr

        result = _alembic("upgrade", "head")
        assert result.returncode == 0, result.stderr

        conn = await asyncpg.connect(DSN)
        try:
            owner = await conn.fetchrow("SELECT * FROM users")
            assert owner["email"] == OWNER_EMAIL and owner["role"] == "admin" and owner["status"] == "active"
            assert owner["display_name"] == "The Owner" and owner["external_subject"] is None
            account = await conn.fetchrow("SELECT * FROM brokerage_accounts")
            assert account["user_id"] == owner["id"] and account["nickname"] == "E*TRADE" and account["is_default"]
            assert await conn.fetchval("SELECT count(*) FROM brokerage_accounts") == 1

            assert await _counts(conn) == before  # nothing lost
            for table in USER_OWNED:
                bad = await conn.fetchval(f"SELECT count(*) FROM {table} WHERE user_id IS DISTINCT FROM $1", owner["id"])
                assert bad == 0, table
            for table in ACCOUNT_SCOPED:
                bad = await conn.fetchval(
                    f"SELECT count(*) FROM {table} WHERE account_id IS DISTINCT FROM $1", account["id"])
                assert bad == 0, table
            for table in ["wheel_slots", "wheel_slot_legs", "wheel_premium_logs", "rationale", "commentary",
                          "alerts", "technical_signals"]:
                assert "account_id" not in await _columns(conn, table), table

            assert await conn.fetchval("SELECT count(*) FROM screener_account_memberships") == before["screener"]
            assert await conn.fetchval("SELECT count(*) FROM account_categories") == before["categories"]

            # email is unique case-insensitively
            with pytest.raises(asyncpg.UniqueViolationError):
                await conn.execute("INSERT INTO users (email, display_name) VALUES ('owner@example.COM', 'x')")
            # one default per user
            with pytest.raises(asyncpg.UniqueViolationError):
                await conn.execute(
                    "INSERT INTO brokerage_accounts (user_id, broker, nickname, is_default) VALUES ($1, 'Schwab', 'x', true)",
                    owner["id"])
            # only last four digits, never a full account number
            with pytest.raises(asyncpg.StringDataRightTruncationError):
                await conn.execute(
                    "INSERT INTO brokerage_accounts (user_id, broker, nickname, last_four) VALUES ($1, 'Schwab', 'x', '123456789')",
                    owner["id"])
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    "INSERT INTO brokerage_accounts (user_id, broker, nickname, last_four) VALUES ($1, 'Schwab', 'x', '12ab')",
                    owner["id"])

            # uniqueness is now per user: a second user may reuse a category name / symbol
            other = await conn.fetchval(
                "INSERT INTO users (email, display_name, status) VALUES ('b@example.com', 'B', 'active') RETURNING id")
            await conn.execute("INSERT INTO categories (user_id, name) VALUES ($1, 'WHEEL')", other)
            await conn.execute("INSERT INTO screener (id, user_id, symbol) VALUES (gen_random_uuid(), $1, 'AAPL')", other)
            with pytest.raises(asyncpg.UniqueViolationError):
                await conn.execute("INSERT INTO categories (user_id, name) VALUES ($1, 'WHEEL')", other)
            # one open trade per E*TRADE symbol is now per account
            other_acct = await conn.fetchval(
                "INSERT INTO brokerage_accounts (user_id, broker, nickname, is_default) "
                "VALUES ($1, 'E*TRADE', 'B', true) RETURNING id", other)
            dup_trade = ("INSERT INTO trades (id, user_id, account_id, type, category, strategy, ticker, open_date, "
                         "quantity, status, etrade_symbol) VALUES (gen_random_uuid(), $1, $2, 'Sell', 'WHEEL', 'Put', "
                         "'NVDA', '2026-10-01', 1, 'open', 'NVDA--261120P00120000')")
            await conn.execute(dup_trade, other, other_acct)
            with pytest.raises(asyncpg.UniqueViolationError):
                await conn.execute(dup_trade, owner["id"], account["id"])

            # the downgrade refuses while another user owns data
            result = _alembic("downgrade", "014")
            assert result.returncode != 0 and "other than the owner" in result.stderr
            await conn.execute("DELETE FROM users WHERE id = $1", other)  # cascades B's rows
        finally:
            await conn.close()

        result = _alembic("downgrade", "014")
        assert result.returncode == 0, result.stderr

        conn = await asyncpg.connect(DSN)
        try:
            assert await conn.fetchval("SELECT to_regclass('users')") is None
            assert await conn.fetchval("SELECT to_regclass('brokerage_accounts')") is None
            for table in USER_OWNED:
                cols = await _columns(conn, table)
                assert "user_id" not in cols and "account_id" not in cols, table
            assert await _counts(conn) == before
            # global uniqueness is back
            with pytest.raises(asyncpg.UniqueViolationError):
                await conn.execute("INSERT INTO categories (name) VALUES ('WHEEL')")
            assert await conn.fetchval("SELECT to_regclass('idx_trades_etrade_symbol_open')") is not None
        finally:
            await conn.close()

        result = _alembic("upgrade", "head")
        assert result.returncode == 0, result.stderr
    finally:
        await _drop_db()
