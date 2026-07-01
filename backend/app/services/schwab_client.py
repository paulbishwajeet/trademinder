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

        self._sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
        self._Session: Optional[sessionmaker] = None  # lazy-initialized on first DB access

        self._access_token: Optional[str] = None
        self._access_expires_at: Optional[datetime] = None
        self._refresh_token: Optional[str] = None
        self._refresh_expires_at: Optional[datetime] = None

    def _get_session(self) -> sessionmaker:
        if self._Session is None:
            engine = create_engine(self._sync_url, pool_pre_ping=True)
            self._Session = sessionmaker(engine)
        return self._Session

    def _load_tokens_from_db(self) -> None:
        with self._get_session()() as session:
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
        with self._get_session()() as session:
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
