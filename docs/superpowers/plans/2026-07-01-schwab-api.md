# Schwab API Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace yfinance with direct Schwab REST API calls in `technicals_fetcher`, `cc_signal`, and `price_fetcher`, persisting OAuth tokens in Postgres.

**Architecture:** A `SchwabClient` singleton (sync, runs in thread executor) handles token refresh and three API methods. Service files are rewritten to call it while keeping identical function signatures so the router layer is untouched. The wheel dashboard CC signal column already exists in the frontend — the backend change powers it automatically.

**Tech Stack:** Python httpx (sync), SQLAlchemy (sync engine for token row), psycopg2 (CLI script only), pytest + unittest.mock

## Global Constraints

- Branch: `feature/technicals` (checkout from master)
- Python 3.14+, FastAPI, SQLAlchemy 2.0 async for main app; sync SQLAlchemy engine only inside `SchwabClient`
- `httpx` must be added as an explicit dependency (may already be present as a test dep via starlette)
- `options_scanner.py` and its yfinance usage are NOT touched
- `_get_next_earnings()` in `technicals_fetcher.py` stays on `yf.Ticker().calendar` (Schwab has no earnings API)
- All existing function signatures in `fetch_technicals`, `compute_cc_signal`, `fetch_quote`, `fetch_rsi_batch`, `refresh_open_trades` must remain unchanged
- Schwab API base: `https://api.schwabapi.com`
- Schwab callback URL registered in dev portal: `https://127.0.0.1:8765/callback`
- Env vars: `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET` (already in `.env`)
- Run all backend tests with: `cd backend && python -m pytest tests/ -v`

---

## File Map

| Action | Path | Purpose |
|---|---|---|
| Create | `backend/app/models/schwab_token.py` | ORM model — single-row token store |
| Modify | `backend/app/models/__init__.py` | Register SchwabToken |
| Create | `backend/alembic/versions/009_schwab_tokens.py` | DB migration |
| Create | `backend/app/services/schwab_client.py` | Schwab HTTP client + token refresh |
| Create | `backend/tests/test_schwab_client.py` | Tests for client |
| Create | `scripts/schwab_auth.py` | One-time CLI OAuth flow |
| Modify | `backend/app/services/technicals_fetcher.py` | Replace yf.download with Schwab price history |
| Modify | `backend/tests/test_technicals_fetcher.py` | Update mocks to use SchwabClient |
| Modify | `backend/app/services/cc_signal.py` | Replace yf.Ticker with Schwab quotes + chain |
| Modify | `backend/tests/test_cc_signal.py` | Add test for _compute_fresh with mock client |
| Modify | `backend/app/services/price_fetcher.py` | Replace yf batch calls with Schwab quotes |
| Modify | `backend/tests/test_price_fetcher.py` | Update mocks to use SchwabClient |

---

### Task 1: SchwabToken model + migration

**Files:**
- Create: `backend/app/models/schwab_token.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/009_schwab_tokens.py`

**Interfaces:**
- Produces: `schwab_tokens` table with columns `id` (int PK, always 1), `access_token` (text), `refresh_token` (text), `access_expires_at` (timestamptz), `refresh_expires_at` (timestamptz), `updated_at` (timestamptz)

- [ ] **Step 1: Write the model**

```python
# backend/app/models/schwab_token.py
from datetime import datetime
from sqlalchemy import Integer, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.database import Base


class SchwabToken(Base):
    __tablename__ = "schwab_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    access_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    refresh_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

- [ ] **Step 2: Register model in `__init__.py`**

Add to `backend/app/models/__init__.py`:
```python
from app.models.schwab_token import SchwabToken
```
And add `"SchwabToken"` to the `__all__` list.

- [ ] **Step 3: Write the migration**

```python
# backend/alembic/versions/009_schwab_tokens.py
"""schwab_tokens table

Revision ID: 009
Revises: 008
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa

revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schwab_tokens",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("access_token", sa.Text, nullable=False),
        sa.Column("refresh_token", sa.Text, nullable=False),
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("schwab_tokens")
```

- [ ] **Step 4: Run migration**

```bash
cd backend && alembic upgrade head
```

Expected: `Running upgrade 008 -> 009` with no errors.

- [ ] **Step 5: Verify table exists**

```bash
docker exec -it <postgres_container> psql -U <user> -d <db> -c "\d schwab_tokens"
```

Expected: table with 6 columns listed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/schwab_token.py backend/app/models/__init__.py backend/alembic/versions/009_schwab_tokens.py
git commit -m "feat(schwab): add schwab_tokens model and migration"
```

---

### Task 2: SchwabClient

**Files:**
- Create: `backend/app/services/schwab_client.py`
- Create: `backend/tests/test_schwab_client.py`

**Interfaces:**
- Consumes: `schwab_tokens` table (Task 1), `SCHWAB_APP_KEY` + `SCHWAB_APP_SECRET` env vars, `DATABASE_URL` env var
- Produces:
  - `get_schwab_client() -> SchwabClient` — module-level singleton factory
  - `SchwabClient.get_quotes(tickers: list[str]) -> dict[str, dict]` — maps original ticker → `{lastPrice, closePrice, ...}`
  - `SchwabClient.get_price_history(ticker, period_type, period, frequency_type, frequency) -> pd.DataFrame` — DatetimeIndex, columns `Open/High/Low/Close/Volume`
  - `SchwabClient.get_option_chain(ticker, contract_type, from_date, to_date) -> dict` — raw Schwab chain response
  - `SchwabAPIError(Exception)` — raised on HTTP errors or missing tokens

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_schwab_client.py
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone
import pandas as pd
import pytest


def _make_client():
    from app.services.schwab_client import SchwabClient
    client = SchwabClient("key", "secret", "postgresql://user:pass@localhost/test")
    client._Session = MagicMock()
    return client


def _future(minutes=60):
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def _past(minutes=10):
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)


def test_get_quotes_returns_mapped_result():
    from app.services.schwab_client import SchwabClient
    client = _make_client()
    client._access_token = "tok"
    client._access_expires_at = _future()
    client._refresh_expires_at = _future(minutes=48 * 60)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "AAPL": {"quote": {"lastPrice": 189.84, "closePrice": 188.33}}
    }

    with patch("app.services.schwab_client.httpx.get", return_value=mock_resp):
        result = client.get_quotes(["AAPL"])

    assert "AAPL" in result
    assert result["AAPL"]["lastPrice"] == 189.84


def test_get_price_history_returns_dataframe():
    client = _make_client()
    client._access_token = "tok"
    client._access_expires_at = _future()
    client._refresh_expires_at = _future(minutes=48 * 60)

    candles = [
        {"datetime": 1704067200000, "open": 186.0, "high": 190.0, "low": 185.0, "close": 189.0, "volume": 50000000},
        {"datetime": 1704153600000, "open": 189.0, "high": 192.0, "low": 188.0, "close": 191.0, "volume": 45000000},
    ]
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"symbol": "AAPL", "empty": False, "candles": candles}

    with patch("app.services.schwab_client.httpx.get", return_value=mock_resp):
        df = client.get_price_history("AAPL", "year", 1, "daily", 1)

    assert not df.empty
    assert "Close" in df.columns
    assert len(df) == 2
    assert float(df["Close"].iloc[-1]) == 191.0


def test_get_price_history_empty_candles_returns_empty_df():
    client = _make_client()
    client._access_token = "tok"
    client._access_expires_at = _future()
    client._refresh_expires_at = _future(minutes=48 * 60)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"symbol": "AAPL", "empty": True, "candles": []}

    with patch("app.services.schwab_client.httpx.get", return_value=mock_resp):
        df = client.get_price_history("AAPL", "year", 1, "daily", 1)

    assert df.empty


def test_token_refresh_called_when_access_token_expired():
    client = _make_client()
    client._access_token = "old_tok"
    client._access_expires_at = _past()
    client._refresh_token = "refresh_tok"
    client._refresh_expires_at = _future(minutes=48 * 60)

    refresh_resp = MagicMock()
    refresh_resp.status_code = 200
    refresh_resp.json.return_value = {
        "access_token": "new_tok",
        "refresh_token": "new_refresh",
        "expires_in": 1800,
    }

    mock_session_ctx = MagicMock()
    mock_session_ctx.__enter__ = MagicMock(return_value=mock_session_ctx)
    mock_session_ctx.__exit__ = MagicMock(return_value=False)
    client._Session.return_value = mock_session_ctx

    with patch("app.services.schwab_client.httpx.post", return_value=refresh_resp):
        client._ensure_valid_token()

    assert client._access_token == "new_tok"


def test_api_error_raises_schwab_api_error():
    from app.services.schwab_client import SchwabAPIError
    client = _make_client()
    client._access_token = "tok"
    client._access_expires_at = _future()
    client._refresh_expires_at = _future(minutes=48 * 60)

    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"

    with patch("app.services.schwab_client.httpx.get", return_value=mock_resp):
        with pytest.raises(SchwabAPIError):
            client.get_quotes(["AAPL"])


def test_schwab_alias_maps_spx():
    client = _make_client()
    client._access_token = "tok"
    client._access_expires_at = _future()
    client._refresh_expires_at = _future(minutes=48 * 60)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "$SPX.X": {"quote": {"lastPrice": 5000.0, "closePrice": 4980.0}}
    }

    captured_params: dict = {}

    def capture_get(url, **kwargs):
        captured_params.update(kwargs.get("params", {}))
        return mock_resp

    with patch("app.services.schwab_client.httpx.get", side_effect=capture_get):
        result = client.get_quotes(["SPX"])

    assert "$SPX.X" in captured_params["symbols"]
    assert "SPX" in result


def test_get_quotes_no_tokens_raises():
    from app.services.schwab_client import SchwabClient, SchwabAPIError
    client = SchwabClient("key", "secret", "postgresql://user:pass@localhost/test")

    mock_session_ctx = MagicMock()
    mock_session_ctx.__enter__ = MagicMock(return_value=mock_session_ctx)
    mock_session_ctx.__exit__ = MagicMock(return_value=False)
    mock_session_ctx.execute.return_value.fetchone.return_value = None
    client._Session = MagicMock(return_value=mock_session_ctx)

    with pytest.raises(SchwabAPIError, match="No Schwab tokens"):
        client.get_quotes(["AAPL"])
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && python -m pytest tests/test_schwab_client.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` — file doesn't exist yet.

- [ ] **Step 3: Write `schwab_client.py`**

```python
# backend/app/services/schwab_client.py
import base64
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

log = logging.getLogger(__name__)

SCHWAB_API_BASE = "https://api.schwabapi.com"
SCHWAB_TOKEN_URL = f"{SCHWAB_API_BASE}/v1/oauth/token"

_SCHWAB_ALIASES: dict[str, str] = {
    "SPX":  "$SPX.X",
    "SPXW": "$SPX.X",
    "XSP":  "$XSP.X",
    "NDX":  "$NDX.X",
    "RUT":  "$RUT.X",
    "VIX":  "$VIX.X",
}


class SchwabAPIError(Exception):
    pass


class SchwabClient:
    def __init__(self, app_key: str, app_secret: str, database_url: str):
        self._app_key = app_key
        self._app_secret = app_secret
        self._lock = threading.Lock()

        sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
        engine = create_engine(sync_url, pool_pre_ping=True)
        self._Session = sessionmaker(engine)

        self._access_token: Optional[str] = None
        self._access_expires_at: Optional[datetime] = None
        self._refresh_token: Optional[str] = None
        self._refresh_expires_at: Optional[datetime] = None

    def _load_tokens_from_db(self) -> None:
        with self._Session() as session:
            row = session.execute(
                text("SELECT access_token, refresh_token, access_expires_at, refresh_expires_at FROM schwab_tokens WHERE id = 1")
            ).fetchone()
            if row is None:
                raise SchwabAPIError("No Schwab tokens in DB. Run: python scripts/schwab_auth.py")
            self._access_token = row.access_token
            self._refresh_token = row.refresh_token
            aex = row.access_expires_at
            rex = row.refresh_expires_at
            self._access_expires_at = aex if aex.tzinfo else aex.replace(tzinfo=timezone.utc)
            self._refresh_expires_at = rex if rex.tzinfo else rex.replace(tzinfo=timezone.utc)

    def _save_tokens_to_db(
        self,
        access_token: str,
        refresh_token: str,
        access_expires_at: datetime,
        refresh_expires_at: datetime,
    ) -> None:
        with self._Session() as session:
            session.execute(
                text("""
                    INSERT INTO schwab_tokens (id, access_token, refresh_token, access_expires_at, refresh_expires_at, updated_at)
                    VALUES (1, :at, :rt, :aex, :rex, NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        access_token = :at, refresh_token = :rt,
                        access_expires_at = :aex, refresh_expires_at = :rex, updated_at = NOW()
                """),
                {"at": access_token, "rt": refresh_token, "aex": access_expires_at, "rex": refresh_expires_at},
            )
            session.commit()
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._access_expires_at = access_expires_at
        self._refresh_expires_at = refresh_expires_at

    def _ensure_valid_token(self) -> None:
        with self._lock:
            if self._access_token is None:
                self._load_tokens_from_db()

            now = datetime.now(timezone.utc)

            if self._refresh_expires_at and (self._refresh_expires_at - now) < timedelta(hours=24):
                log.warning(
                    "Schwab refresh token expires at %s — re-run scripts/schwab_auth.py soon",
                    self._refresh_expires_at,
                )

            if self._access_expires_at and (self._access_expires_at - now) > timedelta(minutes=5):
                return

            log.info("Refreshing Schwab access token")
            creds = base64.b64encode(f"{self._app_key}:{self._app_secret}".encode()).decode()
            resp = httpx.post(
                SCHWAB_TOKEN_URL,
                headers={
                    "Authorization": f"Basic {creds}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"grant_type": "refresh_token", "refresh_token": self._refresh_token},
                timeout=15,
            )
            if resp.status_code != 200:
                raise SchwabAPIError(f"Token refresh failed: {resp.status_code} {resp.text}")

            data = resp.json()
            new_access = data["access_token"]
            new_refresh = data.get("refresh_token", self._refresh_token)
            new_access_exp = now + timedelta(seconds=data["expires_in"])
            new_refresh_exp = now + timedelta(days=7)
            self._save_tokens_to_db(new_access, new_refresh, new_access_exp, new_refresh_exp)

    def _get(self, path: str, params: dict) -> dict:
        self._ensure_valid_token()
        resp = httpx.get(
            f"{SCHWAB_API_BASE}{path}",
            headers={"Authorization": f"Bearer {self._access_token}"},
            params=params,
            timeout=15,
        )
        if resp.status_code != 200:
            raise SchwabAPIError(f"Schwab API {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def get_quotes(self, tickers: list[str]) -> dict[str, dict]:
        """Returns {original_ticker: quote_dict} where quote_dict has lastPrice, closePrice, etc."""
        alias_map = {_SCHWAB_ALIASES.get(t.upper(), t.upper()): t.upper() for t in tickers}
        data = self._get("/marketdata/v1/quotes", {
            "symbols": ",".join(alias_map.keys()),
            "fields": "quote",
        })
        result: dict[str, dict] = {}
        for schwab_sym, orig in alias_map.items():
            entry = data.get(schwab_sym) or data.get(orig) or {}
            quote = entry.get("quote", {})
            if quote:
                result[orig] = quote
        return result

    def get_price_history(
        self,
        ticker: str,
        period_type: str,
        period: int,
        frequency_type: str,
        frequency: int,
    ) -> pd.DataFrame:
        """Returns DataFrame with DatetimeIndex (UTC) and columns Open/High/Low/Close/Volume."""
        data = self._get("/marketdata/v1/pricehistory", {
            "symbol": ticker.upper(),
            "periodType": period_type,
            "period": period,
            "frequencyType": frequency_type,
            "frequency": frequency,
            "needExtendedHoursData": False,
        })
        candles = data.get("candles", [])
        if not candles:
            return pd.DataFrame()
        df = pd.DataFrame(candles)
        df["datetime"] = pd.to_datetime(df["datetime"], unit="ms", utc=True)
        df = df.set_index("datetime")
        df = df.rename(columns={
            "close": "Close", "open": "Open", "high": "High", "low": "Low", "volume": "Volume",
        })
        return df[["Open", "High", "Low", "Close", "Volume"]]

    def get_option_chain(
        self,
        ticker: str,
        contract_type: str = "CALL",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> dict:
        """Returns raw Schwab options chain response."""
        params: dict = {
            "symbol": ticker.upper(),
            "contractType": contract_type,
            "includeUnderlyingQuote": True,
        }
        if from_date:
            params["fromDate"] = from_date
        if to_date:
            params["toDate"] = to_date
        return self._get("/marketdata/v1/chains", params)


_client: Optional[SchwabClient] = None
_client_lock = threading.Lock()


def get_schwab_client() -> SchwabClient:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                app_key = os.environ.get("SCHWAB_APP_KEY", "")
                app_secret = os.environ.get("SCHWAB_APP_SECRET", "")
                database_url = os.environ.get("DATABASE_URL", "")
                if not app_key or not app_secret:
                    raise SchwabAPIError("SCHWAB_APP_KEY and SCHWAB_APP_SECRET must be set in environment")
                _client = SchwabClient(app_key, app_secret, database_url)
    return _client
```

- [ ] **Step 4: Ensure `httpx` is an explicit dependency**

Check `backend/pyproject.toml` or `backend/requirements.txt`. If `httpx` is not listed (only as a test dep), add it to the main dependencies.

For `pyproject.toml` (uv workspace style), add to `[project] dependencies`:
```toml
"httpx>=0.27",
```

Then run:
```bash
cd backend && uv sync
```

- [ ] **Step 5: Run tests**

```bash
cd backend && python -m pytest tests/test_schwab_client.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/schwab_client.py backend/tests/test_schwab_client.py
git commit -m "feat(schwab): add SchwabClient with token refresh and market data methods"
```

---

### Task 3: CLI Auth Script

**Files:**
- Create: `scripts/schwab_auth.py`

**Interfaces:**
- Consumes: `.env` with `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`, `DATABASE_URL`; Schwab dev portal callback configured to `https://127.0.0.1:8765/callback`
- Produces: upserts `schwab_tokens` row `id=1`; prints token expiry times

- [ ] **Step 1: Create the script**

```python
#!/usr/bin/env python3
# scripts/schwab_auth.py
"""
One-time Schwab OAuth flow. Run before first use and any time before the
7-day refresh token expires.

Prerequisites:
  1. Update Schwab developer portal callback URL to https://127.0.0.1:8765/callback
  2. Set SCHWAB_APP_KEY, SCHWAB_APP_SECRET, DATABASE_URL in .env
  3. Run: python scripts/schwab_auth.py
"""
import base64
import os
import sys
import urllib.parse
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

APP_KEY = os.environ["SCHWAB_APP_KEY"]
APP_SECRET = os.environ["SCHWAB_APP_SECRET"]
DATABASE_URL = os.environ["DATABASE_URL"]
REDIRECT_URI = "https://127.0.0.1:8765/callback"
AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"

_auth_code: str | None = None


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _auth_code
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            _auth_code = params["code"][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Auth code captured. You can close this tab.")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing code param.")

    def log_message(self, format, *args):
        pass  # suppress request logging


def main():
    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": APP_KEY,
        "redirect_uri": REDIRECT_URI,
        "scope": "readonly",
    })
    url = f"{AUTH_URL}?{params}"
    print(f"\nOpening browser to:\n{url}\n")
    webbrowser.open(url)

    print("Waiting for callback on https://127.0.0.1:8765 ...")
    server = HTTPServer(("127.0.0.1", 8765), _CallbackHandler)
    server.handle_request()

    if not _auth_code:
        print("ERROR: No auth code received.")
        sys.exit(1)

    print("Auth code received. Exchanging for tokens...")
    import httpx
    creds = base64.b64encode(f"{APP_KEY}:{APP_SECRET}".encode()).decode()
    resp = httpx.post(
        TOKEN_URL,
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": _auth_code,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=15,
    )
    if resp.status_code != 200:
        print(f"ERROR: Token exchange failed: {resp.status_code} {resp.text}")
        sys.exit(1)

    data = resp.json()
    access_token = data["access_token"]
    refresh_token = data["refresh_token"]
    now = datetime.now(timezone.utc)
    access_expires_at = now + timedelta(seconds=data["expires_in"])
    refresh_expires_at = now + timedelta(days=7)

    sync_url = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    conn = psycopg2.connect(sync_url)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO schwab_tokens (id, access_token, refresh_token, access_expires_at, refresh_expires_at, updated_at)
        VALUES (1, %s, %s, %s, %s, NOW())
        ON CONFLICT (id) DO UPDATE SET
            access_token = EXCLUDED.access_token,
            refresh_token = EXCLUDED.refresh_token,
            access_expires_at = EXCLUDED.access_expires_at,
            refresh_expires_at = EXCLUDED.refresh_expires_at,
            updated_at = NOW()
    """, (access_token, refresh_token, access_expires_at, refresh_expires_at))
    conn.commit()
    cur.close()
    conn.close()

    print(f"\nTokens stored successfully.")
    print(f"  Access token expires:  {access_expires_at.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Refresh token expires: {refresh_expires_at.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"\nRe-run this script before {refresh_expires_at.strftime('%Y-%m-%d')} to stay authenticated.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Ensure `psycopg2-binary` and `python-dotenv` are available**

The script runs outside Docker. Check your local venv or install:
```bash
pip install psycopg2-binary python-dotenv httpx
```

- [ ] **Step 3: Run the script (with live Schwab credentials)**

```bash
python scripts/schwab_auth.py
```

Expected:
- Browser opens to Schwab login page
- After login and approval, terminal prints: `Tokens stored successfully.` with two timestamps

- [ ] **Step 4: Verify tokens in DB**

```bash
docker exec -it <postgres_container> psql -U <user> -d <db> -c "SELECT id, access_expires_at, refresh_expires_at FROM schwab_tokens;"
```

Expected: one row with `id=1` and future timestamps.

- [ ] **Step 5: Commit**

```bash
git add scripts/schwab_auth.py
git commit -m "feat(schwab): add one-time OAuth CLI script"
```

---

### Task 4: Rewrite technicals_fetcher

**Files:**
- Modify: `backend/app/services/technicals_fetcher.py`
- Modify: `backend/tests/test_technicals_fetcher.py`

**Interfaces:**
- Consumes: `get_schwab_client()` (Task 2); `yf.Ticker().calendar` (unchanged, earnings only)
- Produces: `fetch_technicals(ticker, return_closes=False)` — same signature and return shape as before

- [ ] **Step 1: Write new test helpers and update integration tests**

Replace the `test_fetch_technicals_*` tests (the last 5 tests in the file) with Schwab-mocked versions. Keep all helper/unit tests (`test_bollinger_*`, `test_infer_sentiment_*`, `test_macd_*`) unchanged.

```python
# Add these helpers at the top of test_technicals_fetcher.py (replace _daily/_weekly):
import pandas as pd
import numpy as np
from datetime import timezone
from unittest.mock import patch, MagicMock


def _make_daily_df(n: int = 200, base: float = 100.0, step: float = 0.25) -> pd.DataFrame:
    close = [base + i * step for i in range(n)]
    idx = pd.date_range(end=pd.Timestamp.now(tz="UTC"), periods=n, freq="B")
    return pd.DataFrame(
        {"Open": close, "High": close, "Low": close, "Close": close, "Volume": [1_000_000] * n},
        index=idx,
    )


def _make_weekly_df(n: int = 60, base: float = 95.0, step: float = 0.5) -> pd.DataFrame:
    close = [base + i * step for i in range(n)]
    idx = pd.date_range(end=pd.Timestamp.now(tz="UTC"), periods=n, freq="W")
    return pd.DataFrame(
        {"Open": close, "High": close, "Low": close, "Close": close, "Volume": [500_000] * n},
        index=idx,
    )


def _mock_client(daily_df, weekly_df):
    client = MagicMock()
    client.get_price_history.side_effect = [daily_df, weekly_df]
    return client
```

Replace the 5 integration tests:

```python
def test_fetch_technicals_success():
    mock_client = _mock_client(_make_daily_df(200), _make_weekly_df(60))
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client), \
         patch("app.services.technicals_fetcher.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.calendar = {"Earnings Date": ["2026-08-15"]}
        result = fetch_technicals("AAPL")

    assert result["fetch_status"] == "ok"
    assert result["fetch_error"] is None
    assert result["price_action"] is not None
    assert result["rsi_14"] is not None
    assert result["ma_200d"] is not None
    assert result["ma_50d"] is not None
    assert result["bollinger_upper"] is not None
    assert result["macd_signal"] in ("bullish", "bearish", "neutral")
    assert result["sentiment"] in ("bullish", "bearish", "neutral")
    assert result["next_earnings_date"] == "2026-08-15"
    assert result["day_color"] in ("green", "red")


def test_fetch_technicals_empty_daily_data():
    mock_client = MagicMock()
    mock_client.get_price_history.return_value = pd.DataFrame()
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        result = fetch_technicals("INVALID")

    assert result["fetch_status"] == "error"
    assert result["fetch_error"] is not None


def test_fetch_technicals_insufficient_daily_rows():
    mock_client = _mock_client(_make_daily_df(1), _make_weekly_df(60))
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        result = fetch_technicals("AAPL")

    assert result["fetch_status"] == "error"


def test_fetch_technicals_no_ma200_when_insufficient_history():
    mock_client = _mock_client(_make_daily_df(60), _make_weekly_df(60))
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client), \
         patch("app.services.technicals_fetcher.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.calendar = {}
        result = fetch_technicals("AAPL")

    assert result["fetch_status"] == "ok"
    assert result["ma_200d"] is None
    assert result["ma_50d"] is not None


def test_fetch_technicals_schwab_error_returns_error():
    from app.services.schwab_client import SchwabAPIError
    mock_client = MagicMock()
    mock_client.get_price_history.side_effect = SchwabAPIError("network error")
    with patch("app.services.technicals_fetcher.get_schwab_client", return_value=mock_client):
        result = fetch_technicals("AAPL")

    assert result["fetch_status"] == "error"
    assert "network error" in result["fetch_error"]
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && python -m pytest tests/test_technicals_fetcher.py -v -k "fetch_technicals"
```

Expected: 5 failures (function still uses yfinance).

- [ ] **Step 3: Rewrite `fetch_technicals` in technicals_fetcher.py**

Replace only `fetch_technicals` and its `yf.download` calls. All helper functions (`_compute_macd_weekly`, `_bollinger_position`, `_infer_sentiment`, `_get_next_earnings`) remain unchanged. Remove the top-level `import yfinance as yf` and replace with a function-scoped import (earnings only).

```python
# backend/app/services/technicals_fetcher.py
import pandas as pd

from app.services.price_fetcher import _compute_rsi_14
from app.services.schwab_client import get_schwab_client, SchwabAPIError


def _compute_macd_weekly(close_w: pd.Series) -> dict[str, str]:
    # unchanged
    ...


def _bollinger_position(price: float, upper: float, mid: float, lower: float) -> str:
    # unchanged
    ...


def _infer_sentiment(macd_signal: str, price: float, ma_50d: float | None, rsi_14: float | None) -> str:
    # unchanged
    ...


def _get_next_earnings(ticker: str) -> str | None:
    import yfinance as yf
    try:
        cal = yf.Ticker(ticker).calendar
        if not cal:
            return None
        dates = cal.get("Earnings Date")
        if not dates:
            return None
        if isinstance(dates, list) and dates:
            return str(dates[0])[:10]
        return str(dates)[:10]
    except Exception:
        return None


def fetch_technicals(ticker: str, return_closes: bool = False) -> dict | tuple[dict, pd.Series]:
    try:
        client = get_schwab_client()

        df_d = client.get_price_history(ticker, "year", 1, "daily", 1)
        if df_d is None or df_d.empty:
            err = {"fetch_status": "error", "fetch_error": f"No daily data for {ticker}"}
            return (err, pd.Series(dtype=float)) if return_closes else err

        close_d = df_d["Close"].dropna()
        if len(close_d) < 2:
            err = {"fetch_status": "error", "fetch_error": f"Insufficient daily history for {ticker}"}
            return (err, pd.Series(dtype=float)) if return_closes else err

        df_w = client.get_price_history(ticker, "year", 2, "weekly", 1)
        close_w = pd.Series(dtype=float)
        if df_w is not None and not df_w.empty:
            close_w = df_w["Close"].dropna()

        price = round(float(close_d.iloc[-1]), 2)
        prev_price = round(float(close_d.iloc[-2]), 2)
        day_color = "green" if price >= prev_price else "red"

        rsi_14 = _compute_rsi_14(close_d)
        rsi_result = None
        if rsi_14 is not None:
            if rsi_14 < 30:
                rsi_result = "rsi_oversold"
            elif rsi_14 > 70:
                rsi_result = "rsi_overbought"

        ma_200d = round(float(close_d.rolling(200).mean().iloc[-1]), 2) if len(close_d) >= 200 else None
        ma_50d = round(float(close_d.rolling(50).mean().iloc[-1]), 2) if len(close_d) >= 50 else None

        price_vs_ma200 = ("above" if price > ma_200d else "below") if ma_200d is not None else None
        price_vs_ma50 = ("above" if price > ma_50d else "below") if ma_50d is not None else None

        rolling_mean = close_d.rolling(20).mean()
        rolling_std = close_d.rolling(20).std()
        b_mid = round(float(rolling_mean.iloc[-1]), 2) if len(close_d) >= 20 else None
        b_upper = round(float((rolling_mean + rolling_std * 2).iloc[-1]), 2) if len(close_d) >= 20 else None
        b_lower = round(float((rolling_mean - rolling_std * 2).iloc[-1]), 2) if len(close_d) >= 20 else None
        b_pos = (
            _bollinger_position(price, b_upper, b_mid, b_lower)
            if (b_upper is not None and b_mid is not None and b_lower is not None)
            else None
        )

        macd = _compute_macd_weekly(close_w)
        sentiment = _infer_sentiment(macd["macd_signal"], price, ma_50d, rsi_14)
        next_earnings = _get_next_earnings(ticker)

        result = {
            "macd_signal": macd["macd_signal"],
            "macd_notes": macd["macd_notes"],
            "rsi_14": rsi_14,
            "rsi_result": rsi_result,
            "ma_200d": ma_200d,
            "ma_50d": ma_50d,
            "price_vs_ma200": price_vs_ma200,
            "price_vs_ma50": price_vs_ma50,
            "bollinger_upper": b_upper,
            "bollinger_mid": b_mid,
            "bollinger_lower": b_lower,
            "bollinger_position": b_pos,
            "day_color": day_color,
            "price_action": str(price),
            "sentiment": sentiment,
            "next_earnings_date": next_earnings,
            "notes": None,
            "fetch_status": "ok",
            "fetch_error": None,
        }
        return (result, close_d) if return_closes else result

    except SchwabAPIError as exc:
        err = {"fetch_status": "error", "fetch_error": str(exc)}
        return (err, pd.Series(dtype=float)) if return_closes else err
    except Exception as exc:
        err = {"fetch_status": "error", "fetch_error": str(exc)}
        return (err, pd.Series(dtype=float)) if return_closes else err
```

- [ ] **Step 4: Run all technicals tests**

```bash
cd backend && python -m pytest tests/test_technicals_fetcher.py -v
```

Expected: all tests pass (unit tests for bollinger/macd/sentiment unchanged; 5 integration tests now pass).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/technicals_fetcher.py backend/tests/test_technicals_fetcher.py
git commit -m "feat(schwab): replace yfinance in technicals_fetcher with Schwab price history"
```

---

### Task 5: Rewrite cc_signal

**Files:**
- Modify: `backend/app/services/cc_signal.py`
- Modify: `backend/tests/test_cc_signal.py`

**Interfaces:**
- Consumes: `get_schwab_client()` (Task 2); `fetch_technicals(ticker, return_closes=True)` (Task 4)
- Produces: `compute_cc_signal(ticker) -> dict` — same shape as before; `_compute_iv_percentile_from_chain(daily_closes, chain, ticker) -> tuple[float|None, float|None]` replaces `_compute_iv_percentile_from_ticker`

**Schwab options chain key facts:**
- `chain["callExpDateMap"]` keys are `"YYYY-MM-DD:DTE"` (e.g. `"2024-01-19:30"`)
- Strike keys within each expiration are strings (e.g. `"185.0"`)
- IV is in `option["volatility"]` as a **percentage** (e.g. `28.5` means 28.5% = 0.285) — divide by 100
- Spot price is in `chain["underlyingPrice"]`

- [ ] **Step 1: Add `test_compute_fresh_with_mock_client` to test_cc_signal.py**

```python
# Add to backend/tests/test_cc_signal.py

def test_compute_fresh_calls_schwab_for_quote_and_chain():
    """_compute_fresh must use SchwabClient for live price + options chain."""
    from unittest.mock import patch, MagicMock
    import pandas as pd
    import numpy as np
    from datetime import date, timedelta

    closes = _make_daily_closes(252)

    mock_client = MagicMock()
    mock_client.get_quotes.return_value = {"AAPL": {"lastPrice": 189.84}}

    exp_date = (date.today() + timedelta(days=37)).strftime("%Y-%m-%d")
    mock_client.get_option_chain.return_value = {
        "underlyingPrice": 189.84,
        "callExpDateMap": {
            f"{exp_date}:37": {
                "190.0": [{"volatility": 28.5}],
            }
        },
    }

    with patch("app.services.cc_signal.get_schwab_client", return_value=mock_client), \
         patch("app.services.cc_signal.fetch_technicals") as mock_tech, \
         patch("app.services.cc_signal._get_llm_commentary", return_value={"commentary": None, "strike_hint": None, "caution": None}):
        mock_tech.return_value = (_make_technicals(), closes)
        from app.services.cc_signal import _compute_fresh
        result = _compute_fresh("AAPL")

    assert result["fetch_status"] == "ok"
    assert result["spot_price"] == 189.84
    mock_client.get_quotes.assert_called_once_with(["AAPL"])
    mock_client.get_option_chain.assert_called_once_with("AAPL", contract_type="CALL")


def test_iv_percentile_from_chain_parses_atm_iv():
    """_compute_iv_percentile_from_chain must divide Schwab volatility% by 100."""
    from datetime import date, timedelta
    import pandas as pd
    import numpy as np
    from app.services.cc_signal import _compute_iv_percentile_from_chain

    closes = _make_daily_closes(252)
    exp_date = (date.today() + timedelta(days=37)).strftime("%Y-%m-%d")
    chain = {
        "underlyingPrice": 100.0,
        "callExpDateMap": {
            f"{exp_date}:37": {
                "100.0": [{"volatility": 35.0}],
            }
        },
    }
    iv_pct, atm_iv = _compute_iv_percentile_from_chain(closes, chain)
    assert atm_iv is not None
    assert 0.01 < atm_iv < 2.0  # 35% / 100 = 0.35


def test_iv_percentile_from_chain_skips_expired_expirations():
    """Expirations with DTE < 14 should be ignored."""
    from datetime import date, timedelta
    from app.services.cc_signal import _compute_iv_percentile_from_chain

    closes = _make_daily_closes(252)
    near_exp = (date.today() + timedelta(days=5)).strftime("%Y-%m-%d")
    chain = {
        "underlyingPrice": 100.0,
        "callExpDateMap": {
            f"{near_exp}:5": {"100.0": [{"volatility": 35.0}]},
        },
    }
    iv_pct, atm_iv = _compute_iv_percentile_from_chain(closes, chain)
    assert iv_pct is None
    assert atm_iv is None
```

- [ ] **Step 2: Run new tests to confirm they fail**

```bash
cd backend && python -m pytest tests/test_cc_signal.py::test_compute_fresh_calls_schwab_for_quote_and_chain tests/test_cc_signal.py::test_iv_percentile_from_chain_parses_atm_iv tests/test_cc_signal.py::test_iv_percentile_from_chain_skips_expired_expirations -v
```

Expected: 3 failures.

- [ ] **Step 3: Rewrite cc_signal.py**

Replace `_compute_iv_percentile_from_ticker` with `_compute_iv_percentile_from_chain` and update `_compute_fresh`. All other functions (`_score_factors`, `_get_llm_commentary`, `compute_cc_signal`) are unchanged.

```python
# backend/app/services/cc_signal.py
import json
import logging
import math
import os
import time
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from app.services.price_fetcher import _compute_rsi_14
from app.services.schwab_client import get_schwab_client

log = logging.getLogger(__name__)

_cc_signal_cache: dict[str, tuple[dict, float]] = {}
_CACHE_TTL = 14400  # 4 hours


def compute_cc_signal(ticker: str) -> dict:
    ticker = ticker.upper()
    now = time.time()
    cached = _cc_signal_cache.get(ticker)
    if cached and (now - cached[1]) < _CACHE_TTL:
        return cached[0]

    try:
        result = _compute_fresh(ticker)
        _cc_signal_cache[ticker] = (result, now)
        return result
    except Exception as exc:
        log.exception("cc_signal failed for %s", ticker)
        return {
            "ticker": ticker,
            "score": 0,
            "grade": "wait",
            "iv_percentile": None,
            "atm_iv": None,
            "spot_price": None,
            "factors": [],
            "commentary": None,
            "strike_hint": None,
            "caution": None,
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "fetch_status": "error",
            "fetch_error": str(exc),
        }


def _compute_fresh(ticker: str) -> dict:
    from app.services.technicals_fetcher import fetch_technicals

    technicals, close_d = fetch_technicals(ticker, return_closes=True)
    if technicals.get("fetch_status") != "ok":
        raise ValueError(f"Technicals fetch failed: {technicals.get('fetch_error')}")
    if close_d.empty:
        raise ValueError(f"No daily data for {ticker}")

    client = get_schwab_client()

    quotes = client.get_quotes([ticker])
    quote = quotes.get(ticker, {})
    try:
        live_price = float(quote.get("lastPrice", close_d.iloc[-1]))
    except Exception:
        live_price = float(close_d.iloc[-1])

    chain = client.get_option_chain(ticker, contract_type="CALL")
    iv_percentile, atm_iv = _compute_iv_percentile_from_chain(close_d, chain, ticker)

    prev_close = float(close_d.iloc[-1])
    technicals = dict(technicals)
    technicals["day_color"] = "green" if live_price > prev_close else "red"
    technicals["price_action"] = str(round(live_price, 2))
    spot = live_price
    score, grade, factors = _score_factors(technicals, iv_percentile, atm_iv, close_d)
    commentary_data = _get_llm_commentary(ticker, score, grade, factors, technicals, iv_percentile, spot)

    return {
        "ticker": ticker,
        "score": score,
        "grade": grade,
        "iv_percentile": round(iv_percentile, 1) if iv_percentile is not None else None,
        "atm_iv": round(atm_iv, 4) if atm_iv is not None else None,
        "spot_price": round(spot, 2),
        "factors": factors,
        "commentary": commentary_data.get("commentary"),
        "strike_hint": commentary_data.get("strike_hint"),
        "caution": commentary_data.get("caution"),
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "fetch_status": "ok",
        "fetch_error": None,
    }


def _compute_iv_percentile_from_chain(
    daily_closes: pd.Series, chain: dict, ticker: str = "?"
) -> tuple[float | None, float | None]:
    try:
        log_returns = np.log(daily_closes / daily_closes.shift(1)).dropna()
        if len(log_returns) < 60:
            return None, None
        hv30 = log_returns.rolling(window=30).std() * math.sqrt(252)
        hv30 = hv30.dropna()
        if len(hv30) < 30:
            return None, None

        call_exp_map = chain.get("callExpDateMap", {})
        if not call_exp_map:
            return None, None

        spot = float(chain.get("underlyingPrice", 0))

        today = date.today()
        best_exp_key = None
        best_dist = float("inf")
        for exp_key in call_exp_map:
            exp_str = exp_key.split(":")[0]
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - today).days
            if dte < 14:
                continue
            dist = abs(dte - 37)
            if dist < best_dist:
                best_dist = dist
                best_exp_key = exp_key

        if best_exp_key is None:
            return None, None

        strikes = call_exp_map[best_exp_key]
        best_strike_key = min(strikes.keys(), key=lambda s: abs(float(s) - spot))
        atm_option = strikes[best_strike_key][0]
        raw_iv = float(atm_option.get("volatility", 0))
        if raw_iv <= 1.0:
            return None, None
        atm_iv = raw_iv / 100.0

        pct = float((hv30 < atm_iv).sum()) / len(hv30) * 100
        return round(pct, 1), atm_iv

    except Exception as exc:
        log.warning("IV percentile failed for %s: %s", ticker, exc)
        return None, None


# _score_factors, _get_llm_commentary — UNCHANGED from original, paste them here verbatim
```

**Important:** Copy `_score_factors` and `_get_llm_commentary` verbatim from the original file. Do not modify them.

- [ ] **Step 4: Run all cc_signal tests**

```bash
cd backend && python -m pytest tests/test_cc_signal.py -v
```

Expected: all tests pass (original scoring tests unchanged; 3 new tests pass).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/cc_signal.py backend/tests/test_cc_signal.py
git commit -m "feat(schwab): replace yfinance in cc_signal with Schwab quotes + options chain"
```

---

### Task 6: Rewrite price_fetcher

**Files:**
- Modify: `backend/app/services/price_fetcher.py`
- Modify: `backend/tests/test_price_fetcher.py`

**Interfaces:**
- Consumes: `get_schwab_client()` (Task 2)
- Produces: `fetch_quote(ticker) -> dict | None`, `fetch_rsi_batch(tickers) -> dict[str, dict|None]`, `refresh_open_trades(db) -> dict` — all same signatures; `_compute_unrealized_pnl` and `_compute_rsi_14` are unchanged pure functions; `_fetch_prices_from_yfinance` renamed to `_fetch_prices_from_schwab`; `_fetch_rsi_from_yfinance` renamed to `_fetch_rsi_from_schwab`; `_fetch_one_rsi` removed (replaced by internal helper in `_fetch_rsi_from_schwab`)

- [ ] **Step 1: Update tests**

In `test_price_fetcher.py`:
1. Replace `patch("app.services.price_fetcher.yf.Ticker")` in `test_fetch_quote_*` with `patch("app.services.price_fetcher.get_schwab_client")`
2. Replace `patch("app.services.price_fetcher._fetch_prices_from_yfinance")` with `patch("app.services.price_fetcher._fetch_prices_from_schwab")`
3. Remove the `test_fetch_one_rsi_*` tests (function is removed)
4. Add `test_fetch_rsi_from_schwab_*` tests

```python
# Replace test_fetch_quote_success:
async def test_fetch_quote_success():
    mock_client = MagicMock()
    mock_client.get_quotes.return_value = {"AAPL": {"lastPrice": 192.43, "closePrice": 194.04}}

    with patch("app.services.price_fetcher.get_schwab_client", return_value=mock_client):
        result = await fetch_quote("AAPL")

    assert result is not None
    assert result["ticker"] == "AAPL"
    assert result["price"] == 192.43
    assert "change_pct" in result
    assert "last_updated" in result


# Replace test_fetch_quote_returns_none_when_price_missing:
async def test_fetch_quote_returns_none_when_price_missing():
    mock_client = MagicMock()
    mock_client.get_quotes.return_value = {}

    with patch("app.services.price_fetcher.get_schwab_client", return_value=mock_client):
        result = await fetch_quote("INVALID")

    assert result is None


# Replace test_fetch_quote_returns_none_on_exception:
async def test_fetch_quote_returns_none_on_exception():
    from app.services.schwab_client import SchwabAPIError
    mock_client = MagicMock()
    mock_client.get_quotes.side_effect = SchwabAPIError("network error")

    with patch("app.services.price_fetcher.get_schwab_client", return_value=mock_client):
        result = await fetch_quote("AAPL")

    assert result is None


# Replace patch target in refresh tests:
# Change: patch("app.services.price_fetcher._fetch_prices_from_yfinance", ...)
# To:     patch("app.services.price_fetcher._fetch_prices_from_schwab", ...)


# Replace the 4 test_fetch_one_rsi_* tests with:
def test_fetch_rsi_from_schwab_returns_rsi_and_price():
    from app.services.price_fetcher import _fetch_rsi_from_schwab
    import pandas as pd

    close_vals = [100.0 + i * 0.5 for i in range(45)]
    idx = _pd.date_range(end=_pd.Timestamp.now(tz="UTC"), periods=45, freq="B")
    mock_df = _pd.DataFrame(
        {"Open": close_vals, "High": close_vals, "Low": close_vals, "Close": close_vals, "Volume": [1_000_000] * 45},
        index=idx,
    )

    mock_client = MagicMock()
    mock_client.get_price_history.return_value = mock_df

    with patch("app.services.price_fetcher.get_schwab_client", return_value=mock_client):
        result = _fetch_rsi_from_schwab(["AAPL"])

    assert "AAPL" in result
    assert result["AAPL"] is not None
    assert set(result["AAPL"].keys()) == {"rsi", "price"}


def test_fetch_rsi_from_schwab_returns_none_on_empty_df():
    from app.services.price_fetcher import _fetch_rsi_from_schwab

    mock_client = MagicMock()
    mock_client.get_price_history.return_value = _pd.DataFrame()

    with patch("app.services.price_fetcher.get_schwab_client", return_value=mock_client):
        result = _fetch_rsi_from_schwab(["BADTICKER"])

    assert result["BADTICKER"] is None
```

- [ ] **Step 2: Run tests to confirm failures**

```bash
cd backend && python -m pytest tests/test_price_fetcher.py -v
```

Expected: `test_fetch_quote_*` and RSI tests fail; P&L tests and `refresh_open_trades` tests still pass.

- [ ] **Step 3: Rewrite price_fetcher.py**

Keep `_compute_unrealized_pnl`, `_compute_rsi_14`, and `refresh_open_trades` unchanged (except the internal call from `_fetch_prices_from_yfinance` → `_fetch_prices_from_schwab`). Remove `_YF_ALIASES`, `_resolve`, `_fetch_prices_from_yfinance`, `_fetch_rsi_from_yfinance`, `_fetch_one_rsi`.

```python
# backend/app/services/price_fetcher.py
import asyncio
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trade import Trade
from app.services.schwab_client import get_schwab_client, SchwabAPIError


def _compute_unrealized_pnl(trade: Trade, current_price: float) -> float | None:
    if trade.premium is None or trade.strike_price is None:
        return None
    premium = float(trade.premium)
    strike = float(trade.strike_price)
    qty = trade.quantity
    if trade.type == "Sell" and trade.strategy in ("Put", "PutCreditSpread"):
        return round((premium - max(strike - current_price, 0)) * qty * 100, 2)
    if trade.type == "Sell" and trade.strategy in ("Call", "CoveredCall"):
        return round((premium - max(current_price - strike, 0)) * qty * 100, 2)
    return None


def _compute_rsi_14(close: pd.Series) -> float | None:
    close = close.dropna()
    if len(close) < 15:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    last_loss = float(avg_loss.iloc[-1])
    if last_loss == 0:
        return 100.0
    rs = float(avg_gain.iloc[-1]) / last_loss
    return round(100 - (100 / (1 + rs)), 2)


def _fetch_prices_from_schwab(tickers: list[str]) -> dict[str, float]:
    try:
        client = get_schwab_client()
        quotes = client.get_quotes(tickers)
        return {t: float(q["lastPrice"]) for t, q in quotes.items() if "lastPrice" in q}
    except Exception:
        return {}


async def fetch_quote(ticker: str) -> dict | None:
    try:
        loop = asyncio.get_event_loop()

        def _sync():
            client = get_schwab_client()
            return client.get_quotes([ticker]).get(ticker)

        quote = await loop.run_in_executor(None, _sync)
        if quote is None:
            return None
        price = quote.get("lastPrice")
        if price is None:
            return None
        prev_close = quote.get("closePrice")
        change_pct = round((float(price) - float(prev_close)) / float(prev_close) * 100, 2) if prev_close else None
        return {
            "ticker": ticker,
            "price": round(float(price), 2),
            "change_pct": change_pct,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        return None


def _fetch_rsi_from_schwab(tickers: list[str]) -> dict[str, dict | None]:
    result: dict[str, dict | None] = {t: None for t in tickers}
    client = get_schwab_client()

    def fetch_one(ticker: str) -> tuple[str, dict | None]:
        try:
            df = client.get_price_history(ticker, "month", 2, "daily", 1)
            if df is None or df.empty:
                return ticker, None
            close = df["Close"].dropna()
            if close.empty:
                return ticker, None
            price = round(float(close.iloc[-1]), 2)
            rsi = _compute_rsi_14(close)
            return ticker, {"rsi": rsi, "price": price}
        except Exception:
            return ticker, None

    with ThreadPoolExecutor(max_workers=min(len(tickers), 10)) as executor:
        pairs = list(executor.map(fetch_one, tickers))
    for ticker, data in pairs:
        result[ticker] = data
    return result


async def fetch_rsi_batch(tickers: list[str]) -> dict[str, dict | None]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_rsi_from_schwab, tickers)


async def refresh_open_trades(db: AsyncSession) -> dict:
    stmt = select(Trade).where(Trade.status == "open")
    result = await db.execute(stmt)
    trades = result.scalars().all()

    if not trades:
        return {"trades_updated": 0, "tickers_fetched": 0, "errors": []}

    tickers = list({t.ticker for t in trades})
    prices = _fetch_prices_from_schwab(tickers)

    errors: list[str] = []
    now = datetime.now(timezone.utc)
    trades_updated = 0

    for trade in trades:
        price = prices.get(trade.ticker)
        if price is None:
            errors.append(f"No price for {trade.ticker}")
            continue
        trade.current_price = price
        trade.last_price_at = now
        trade.unrealized_pnl = _compute_unrealized_pnl(trade, price)
        trades_updated += 1

    if trades_updated > 0:
        await db.commit()

    return {"trades_updated": trades_updated, "tickers_fetched": len(prices), "errors": errors}
```

- [ ] **Step 4: Update patch targets in refresh tests**

In `test_price_fetcher.py`, change all three `patch("app.services.price_fetcher._fetch_prices_from_yfinance", ...)` to `patch("app.services.price_fetcher._fetch_prices_from_schwab", ...)`.

- [ ] **Step 5: Run all price_fetcher tests**

```bash
cd backend && python -m pytest tests/test_price_fetcher.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Run full backend test suite**

```bash
cd backend && python -m pytest tests/ -v
```

Expected: all tests pass. Confirm the count includes wheel tests (25), cc_signal tests, technicals tests, price_fetcher tests, schwab_client tests.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/price_fetcher.py backend/tests/test_price_fetcher.py
git commit -m "feat(schwab): replace yfinance in price_fetcher with Schwab quotes and price history"
```

---

## Post-Implementation Checklist

- [ ] Run `python scripts/schwab_auth.py` to store live tokens (if not done in Task 3)
- [ ] Start the backend: `docker-compose up` and test `GET /api/market/cc-signal/AAPL` in browser — confirm it returns `fetch_status: "ok"` with `iv_percentile` populated
- [ ] Visit the Wheel Dashboard — confirm Signal column shows grade chips (not `—`) for your tickers
- [ ] Watch backend logs for any `SchwabAPIError` or `Token refresh failed` messages
- [ ] Set a calendar reminder to re-run `python scripts/schwab_auth.py` before the refresh token expires (~7 days from initial auth)
