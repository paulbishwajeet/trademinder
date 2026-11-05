# backend/app/services/schwab_client.py
"""Schwab implementation of the market data provider (see app.services.market_data).

Only app.services.market_data may import SchwabClient; everything else uses get_market_data().

Offline mode: when the refresh token is past its expiry, the refresh grant is rejected
(invalid_grant), there are no tokens, or the app key/secret are missing, the client raises
MarketDataUnavailable and stops calling Schwab. It re-reads the schwab_tokens row at most once a
minute (TOKEN_RECHECK_SECONDS) and resumes as soon as the row changes — i.e. someone re-ran
scripts/schwab_auth.py. Entering and leaving offline are each logged once.
"""
import asyncio
import base64
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg
import httpx
import pandas as pd

from app.services.market_data_errors import MarketDataUnavailable

log = logging.getLogger(__name__)

SCHWAB_API_BASE = "https://api.schwabapi.com"
SCHWAB_TOKEN_URL = f"{SCHWAB_API_BASE}/v1/oauth/token"

_SCHWAB_ALIASES: dict[str, str] = {
    "SPX":  "$SPX",
    "SPXW": "$SPX",
    "XSP":  "$XSP",
    "NDX":  "$NDX",
    "RUT":  "$RUT",
    "VIX":  "$VIX",
}


# How often (at most) the token row is re-read to notice a CLI re-auth.
TOKEN_RECHECK_SECONDS = 60
REAUTH_HINT = "Run scripts/schwab_auth.py"


class SchwabAPIError(Exception):
    """A per-call / per-ticker Schwab failure (e.g. a non-optionable symbol). The provider as a
    whole being offline is MarketDataUnavailable instead."""
    pass


class SchwabClient:
    name = "schwab"

    def __init__(self, app_key: str, app_secret: str, database_url: str):
        self._app_key = app_key
        self._app_secret = app_secret
        self._lock = threading.Lock()
        self._db_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

        self._access_token: Optional[str] = None
        self._access_expires_at: Optional[datetime] = None
        self._refresh_token: Optional[str] = None
        self._refresh_expires_at: Optional[datetime] = None

        # Offline bookkeeping (guarded by self._lock)
        self._offline_reason: Optional[str] = None
        self._token_marker: Optional[tuple] = None   # (updated_at, refresh_expires_at) of the loaded row
        self._last_token_check: float = 0.0           # time.monotonic() of the last row re-read
        self._last_success_at: Optional[datetime] = None
        self._last_error: Optional[str] = None
        self._expiry_warned_for: Optional[datetime] = None

    # ── offline state ──────────────────────────────────────────────────────

    def _go_offline(self, reason: str) -> None:
        """Enter offline mode (logged once per offline period) and raise."""
        if self._offline_reason is None:
            log.warning("Market data offline (Schwab): %s. %s.", reason, REAUTH_HINT)
        self._offline_reason = reason
        self._last_error = reason
        self._last_token_check = time.monotonic()
        raise MarketDataUnavailable(reason)

    def _come_online(self) -> None:
        if self._offline_reason is not None:
            log.warning("Market data back online (Schwab): token row changed")
        self._offline_reason = None

    def is_offline(self) -> bool:
        """No I/O: known offline, or the loaded refresh token is already past its expiry."""
        if self._offline_reason is not None:
            return True
        rex = self._refresh_expires_at
        return rex is not None and rex <= datetime.now(timezone.utc)

    def _refresh_state_locked(self) -> None:
        """Bring the offline state up to date without calling Schwab: load the token row the first
        time, then re-read it (≤ once a minute) to notice a CLI re-auth or a changed expiry."""
        try:
            if not self._app_key or not self._app_secret:
                self._offline_reason = self._offline_reason or "SCHWAB_APP_KEY and SCHWAB_APP_SECRET are not set"
                self._last_error = self._offline_reason
            elif self._refresh_expires_at is None and self._offline_reason is None:
                self._load_tokens_from_db()
            else:
                # Online or offline: pick up a changed row (CLI re-auth, or a manual edit) within a minute.
                self._recheck_token_row()
                if self._access_token is None:
                    self._load_tokens_from_db()
        except (MarketDataUnavailable, SchwabAPIError):
            pass
        except Exception as exc:  # DB hiccup: keep the current state
            log.debug("Schwab token row unreadable: %s", exc)

    def refresh_offline_state(self) -> bool:
        """Sync (may read the token row): run it in an executor from async code."""
        with self._lock:
            self._refresh_state_locked()
        return self.is_offline()

    def _fetch_token_marker(self) -> Optional[tuple]:
        async def _fetch():
            conn = await asyncpg.connect(self._db_url)
            try:
                return await conn.fetchrow("SELECT updated_at, refresh_expires_at FROM schwab_tokens WHERE id = 1")
            finally:
                await conn.close()

        row = asyncio.run(_fetch())
        return None if row is None else (row["updated_at"], row["refresh_expires_at"])

    def _recheck_token_row(self, force: bool = False) -> None:
        """At most once a minute: if the token row changed (a CLI re-auth), reload it."""
        now = time.monotonic()
        if not force and now - self._last_token_check < TOKEN_RECHECK_SECONDS:
            return
        self._last_token_check = now
        try:
            marker = self._fetch_token_marker()
        except Exception as exc:  # DB hiccup: keep the current state, try again next minute
            log.debug("Schwab token row re-check failed: %s", exc)
            return
        if marker is not None and marker != self._token_marker:
            self._access_token = None  # force a reload from the row
            self._come_online()

    def _load_tokens_from_db(self) -> None:
        async def _fetch():
            conn = await asyncpg.connect(self._db_url)
            try:
                return await conn.fetchrow(
                    "SELECT access_token, refresh_token, access_expires_at, refresh_expires_at, updated_at "
                    "FROM schwab_tokens WHERE id = 1"
                )
            finally:
                await conn.close()

        row = asyncio.run(_fetch())
        if row is None:
            # Offline from now on (status, banner, response flags), but the first caller still gets
            # the long-standing SchwabAPIError for this case.
            self._token_marker = None
            try:
                self._go_offline("No Schwab tokens stored")
            except MarketDataUnavailable:
                raise SchwabAPIError("No Schwab tokens in DB. Run: python scripts/schwab_auth.py")
        self._access_token = row["access_token"]
        self._refresh_token = row["refresh_token"]
        aex = row["access_expires_at"]
        rex = row["refresh_expires_at"]
        self._access_expires_at = aex if aex.tzinfo else aex.replace(tzinfo=timezone.utc)
        self._refresh_expires_at = rex if rex.tzinfo else rex.replace(tzinfo=timezone.utc)
        self._token_marker = (row.get("updated_at"), rex)
        self._last_token_check = time.monotonic()

    def _save_tokens_to_db(
        self,
        access_token: str,
        refresh_token: str,
        access_expires_at: datetime,
        refresh_expires_at: datetime,
    ) -> None:
        async def _store():
            conn = await asyncpg.connect(self._db_url)
            try:
                await conn.execute("""
                    INSERT INTO schwab_tokens (id, access_token, refresh_token, access_expires_at, refresh_expires_at, updated_at)
                    VALUES (1, $1, $2, $3, $4, NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        access_token = EXCLUDED.access_token, refresh_token = EXCLUDED.refresh_token,
                        access_expires_at = EXCLUDED.access_expires_at, refresh_expires_at = EXCLUDED.refresh_expires_at,
                        updated_at = NOW()
                """, access_token, refresh_token, access_expires_at, refresh_expires_at)
            finally:
                await conn.close()

        asyncio.run(_store())
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._access_expires_at = access_expires_at
        self._refresh_expires_at = refresh_expires_at

    def _ensure_valid_token(self) -> None:
        with self._lock:
            if not self._app_key or not self._app_secret:
                self._go_offline("SCHWAB_APP_KEY and SCHWAB_APP_SECRET are not set")

            if self._offline_reason is not None:
                # Offline: never call Schwab. Only re-read the token row (≤ once a minute).
                self._recheck_token_row()
                if self._offline_reason is not None:
                    raise MarketDataUnavailable(self._offline_reason)
            elif self._access_token is not None:
                self._recheck_token_row()

            if self._access_token is None:
                self._load_tokens_from_db()

            now = datetime.now(timezone.utc)

            if self._refresh_expires_at and self._refresh_expires_at <= now:
                self._go_offline(f"Schwab refresh token expired at {self._refresh_expires_at:%Y-%m-%d %H:%M} UTC")

            if self._refresh_expires_at and (self._refresh_expires_at - now) < timedelta(hours=24) \
                    and self._expiry_warned_for != self._refresh_expires_at:
                self._expiry_warned_for = self._refresh_expires_at  # once per token, not per request
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
                if _is_invalid_grant(resp):
                    self._go_offline(f"Schwab rejected the refresh token ({resp.status_code} invalid_grant)")
                self._last_error = f"Token refresh failed: HTTP {resp.status_code}"
                raise SchwabAPIError(f"Token refresh failed: {resp.status_code} {resp.text}")

            data = resp.json()
            new_access = data["access_token"]
            new_refresh = data.get("refresh_token", self._refresh_token)
            new_access_exp = now + timedelta(seconds=data["expires_in"])
            new_refresh_exp = self._refresh_expires_at
            self._save_tokens_to_db(new_access, new_refresh, new_access_exp, new_refresh_exp)

    def _get(self, path: str, params: dict) -> dict:
        self._ensure_valid_token()
        resp = httpx.get(
            f"{SCHWAB_API_BASE}{path}",
            headers={"Authorization": f"Bearer {self._access_token}"},
            params=params,
            timeout=30,
        )
        if resp.status_code != 200:
            self._last_error = f"Schwab API HTTP {resp.status_code} on {path}"
            raise SchwabAPIError(f"Schwab API {resp.status_code}: {resp.text[:200]}")
        self._last_success_at = datetime.now(timezone.utc)
        return resp.json()

    def status(self):
        """Provider status for the market data status endpoint. Loads the token row the first time
        (and re-checks it at most once a minute while offline) so expiry is known before any call."""
        from app.services.market_data import ProviderStatus

        with self._lock:
            self._refresh_state_locked()
            return ProviderStatus(
                provider=self.name,
                offline=self.is_offline(),
                refresh_expires_at=self._refresh_expires_at,
                last_success_at=self._last_success_at,
                last_error=self._last_error,
            )

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
        strike_count: Optional[int] = None,
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
        if strike_count is not None:
            params["strikeCount"] = strike_count
        return self._get("/marketdata/v1/chains", params)

    def get_instrument_fundamentals(self, ticker: str) -> dict:
        """Returns the raw `fundamental` object from Schwab's instruments endpoint,
        or {} if the symbol has no fundamental data on file."""
        data = self._get("/marketdata/v1/instruments", {
            "symbol": ticker.upper(),
            "projection": "fundamental",
        })
        instruments = data.get("instruments", [])
        if not instruments:
            return {}
        return instruments[0].get("fundamental", {})


def _is_invalid_grant(resp: httpx.Response) -> bool:
    """A refresh rejected for good (expired/revoked refresh token), as opposed to a transient error."""
    if resp.status_code not in (400, 401):
        return False
    try:
        body = resp.json()
    except Exception:
        return "invalid_grant" in resp.text
    return body.get("error") == "invalid_grant" if isinstance(body, dict) else False
