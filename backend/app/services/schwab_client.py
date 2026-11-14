# backend/app/services/schwab_client.py
"""Schwab implementation of the market data provider (see app.services.market_data).

Only app.services.market_data may import SchwabClient; everything else uses get_market_data().

Offline mode: when the refresh token is past its expiry, the refresh grant is rejected
(invalid_grant), there are no tokens, or the app key/secret are missing, the client raises
MarketDataUnavailable and stops calling Schwab. It re-reads the schwab_tokens row at most once a
minute (TOKEN_RECHECK_SECONDS) and resumes as soon as the row changes — i.e. someone re-ran
scripts/schwab_auth.py. The in-app reconnect (app.services.schwab_reconnect) writes through
install_tokens(), which resumes immediately. Entering and leaving offline are each logged once.

Token follower mode (dev; SCHWAB_TOKEN_SYNC_URL set): one Schwab grant, owned by production. This client never
calls Schwab's token endpoint. Wherever it would refresh (access token near expiry, a 401 on a data call, no
token row, a past refresh expiry, or offline), it pulls the pair from production instead
(app.services.schwab_token_sync) under the same lock — single-flight, at most one attempt a minute — writes it to
its own schwab_tokens row, and retries the original call once. Pull failures use the same offline mode; a later
successful pull recovers. Production serves the pair through export_tokens(), which keeps it the only refresher.

In both modes a 401 on a data call renews the token once (refresh, or pull) and retries the call once.
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

from app.services import schwab_token_sync
from app.services.market_data_errors import MarketDataUnavailable
from app.services.schwab_oauth import TokenSet, store_tokens

log = logging.getLogger(__name__)

SCHWAB_API_BASE = "https://api.schwabapi.com"
SCHWAB_TOKEN_URL = f"{SCHWAB_API_BASE}/v1/oauth/token"  # == schwab_oauth.TOKEN_URL

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
REAUTH_HINT = "Reconnect Schwab in the app (or run scripts/schwab_auth.py)"
FOLLOWER_HINT = "Dev follows production's tokens: reconnect in production; the pull is retried at most once a minute"
# Renew the access token when less than this is left.
REFRESH_MARGIN = timedelta(minutes=5)
# Production's export guarantees the follower at least this much access-token life.
EXPORT_MIN_ACCESS_LEFT = timedelta(minutes=10)
# Follower: at most one pull attempt (success or failure) per this many seconds.
PULL_MIN_INTERVAL_SECONDS = 60


class SchwabAPIError(Exception):
    """A per-call / per-ticker Schwab failure (e.g. a non-optionable symbol). The provider as a
    whole being offline is MarketDataUnavailable instead."""
    pass


class PullRateLimited(Exception):
    """"Pull now" inside the one-minute window."""

    def __init__(self, retry_after_seconds: int):
        super().__init__(retry_after_seconds)
        self.retry_after_seconds = retry_after_seconds


class SchwabClient:
    name = "schwab"

    def __init__(self, app_key: str, app_secret: str, database_url: str, sync_url: str = "", sync_secret: str = ""):
        self._app_key = app_key
        self._app_secret = app_secret
        # Token follower mode when sync_url is set (never logged: the secret)
        self._sync_url = sync_url
        self._sync_secret = sync_secret
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

        # Follower bookkeeping (guarded by self._lock)
        self._last_pull_attempt: Optional[float] = None  # time.monotonic()
        self._last_pull_at: Optional[datetime] = None
        self._last_pull_outcome: Optional[str] = None

    @property
    def follower(self) -> bool:
        """Token follower mode: pull from production instead of calling Schwab's token endpoint."""
        return bool(self._sync_url)

    # ── offline state ──────────────────────────────────────────────────────

    def _go_offline(self, reason: str) -> None:
        """Enter offline mode (logged once per offline period) and raise."""
        if self._offline_reason is None:
            log.warning("Market data offline (Schwab): %s. %s.", reason, FOLLOWER_HINT if self.follower else REAUTH_HINT)
        self._offline_reason = reason
        self._last_error = reason
        self._last_token_check = time.monotonic()
        raise MarketDataUnavailable(reason)

    def _come_online(self, why: str = "token row changed") -> None:
        if self._offline_reason is not None:
            log.warning("Market data back online (Schwab): %s", why)
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
            if self.follower:
                self._refresh_follower_state_locked()
            elif not self._app_key or not self._app_secret:
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

    def _refresh_follower_state_locked(self) -> None:
        """Follower: load the local row the first time; when offline (or no row, or the refresh expiry is past),
        try a pull — rate-limited to one a minute — so dev recovers without waiting for a market call."""
        if self._access_token is None and self._offline_reason is None:
            try:
                self._load_tokens_from_db()
            except SchwabAPIError:
                pass  # no row: offline now; the pull below fills it
        if self.is_offline():
            self._pull_locked()

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
        asyncio.run(store_tokens(self._db_url, TokenSet(access_token, refresh_token, access_expires_at, refresh_expires_at)))
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._access_expires_at = access_expires_at
        self._refresh_expires_at = refresh_expires_at

    def install_tokens(self, tokens: TokenSet) -> None:
        """A fresh authorization (the in-app reconnect): write the token row under the same lock refreshes
        use, then reload it so the provider is online again at once — no wait for the one-minute recheck.
        Sync (DB I/O): run it in an executor from async code."""
        with self._lock:
            asyncio.run(store_tokens(self._db_url, tokens))
            self._load_tokens_from_db()  # also records the row's new (updated_at, refresh_expires_at) marker
            self._come_online()
            self._last_error = None
            self._expiry_warned_for = None

    def _ensure_valid_token(self, min_access_left: timedelta = REFRESH_MARGIN) -> None:
        with self._lock:
            if not self.follower and (not self._app_key or not self._app_secret):
                self._go_offline("SCHWAB_APP_KEY and SCHWAB_APP_SECRET are not set")

            if self._offline_reason is not None:
                if self.follower:
                    # Offline: never call Schwab; try production again (≤ once a minute).
                    self._pull_locked()
                else:
                    # Offline: never call Schwab. Only re-read the token row (≤ once a minute).
                    self._recheck_token_row()
                    if self._offline_reason is not None:
                        raise MarketDataUnavailable(self._offline_reason)
            elif self._access_token is not None:
                self._recheck_token_row()

            if self._access_token is None:
                if self.follower:
                    try:
                        self._load_tokens_from_db()
                    except SchwabAPIError:
                        self._pull_locked()  # no row yet: production has it
                else:
                    self._load_tokens_from_db()

            now = datetime.now(timezone.utc)

            if self._refresh_expires_at and self._refresh_expires_at <= now:
                if self.follower:
                    self._pull_locked()  # production may have reconnected since
                if self._refresh_expires_at and self._refresh_expires_at <= now:
                    self._go_offline(f"Schwab refresh token expired at {self._refresh_expires_at:%Y-%m-%d %H:%M} UTC")

            if self._refresh_expires_at and (self._refresh_expires_at - now) < timedelta(hours=24) \
                    and self._expiry_warned_for != self._refresh_expires_at:
                self._expiry_warned_for = self._refresh_expires_at  # once per token, not per request
                log.warning(
                    "Schwab refresh token expires at %s — %s",
                    self._refresh_expires_at,
                    "reconnect in production soon" if self.follower else "re-run scripts/schwab_auth.py soon",
                )

            if self._access_expires_at and (self._access_expires_at - now) > min_access_left:
                return

            self._renew_locked()

    # ── renewal: refresh (normal) or pull (follower) ───────────────────────

    def _renew_locked(self) -> None:
        if self.follower:
            self._pull_locked()
        else:
            self._refresh_from_schwab_locked()

    def _refresh_from_schwab_locked(self) -> None:
        """Normal mode only: the refresh grant at Schwab's token endpoint."""
        assert not self.follower, "a token follower never calls Schwab's token endpoint"
        now = datetime.now(timezone.utc)
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

    def _pull_wait_seconds(self) -> int:
        if self._last_pull_attempt is None:
            return 0
        left = PULL_MIN_INTERVAL_SECONDS - (time.monotonic() - self._last_pull_attempt)
        return max(0, int(left + 0.999))

    def _pull_locked(self) -> None:
        """Follower only: pull the pair from production (caller holds self._lock, so concurrent callers wait for
        this one pull). At most one attempt a minute; inside that window a still-valid token is used as is.
        Success writes the row and comes online; failure enters offline mode (raises MarketDataUnavailable)."""
        assert self.follower
        if self._pull_wait_seconds() > 0:
            if self._offline_reason is not None:
                raise MarketDataUnavailable(self._offline_reason)
            if self._access_token and self._access_expires_at and self._access_expires_at > datetime.now(timezone.utc):
                return
            raise SchwabAPIError("Schwab token pull from production is rate-limited (at most once a minute)")

        self._last_pull_attempt = time.monotonic()
        result = schwab_token_sync.pull(self._sync_url, self._sync_secret)
        self._last_pull_at = datetime.now(timezone.utc)
        self._last_pull_outcome = result.outcome
        if result.outcome != schwab_token_sync.OK or result.tokens is None:
            log.warning("Schwab token pull from production: %s", result.outcome)
            self._go_offline(schwab_token_sync.OUTCOME_REASONS.get(result.outcome, "Token pull from production failed"))

        tokens = result.tokens
        asyncio.run(store_tokens(self._db_url, tokens))
        self._load_tokens_from_db()  # also records the row's new marker
        self._come_online("tokens pulled from production")
        self._last_error = None
        log.warning(
            "Schwab token pull from production: ok; access token expires %s",
            tokens.access_expires_at.isoformat(timespec="seconds"),
        )

    def _renew_after_401(self, used_token: Optional[str]) -> None:
        """A data call got 401 with `used_token`: renew once, unless another caller already did."""
        with self._lock:
            if self._access_token != used_token:
                return
            self._renew_locked()

    # ── production export / follower "pull now" ────────────────────────────

    def export_tokens(self) -> TokenSet:
        """Production: the current pair with at least EXPORT_MIN_ACCESS_LEFT of access-token life, refreshing
        through the normal path (same lock) if needed. Raises MarketDataUnavailable when offline. Sync (I/O)."""
        self._ensure_valid_token(min_access_left=EXPORT_MIN_ACCESS_LEFT)
        with self._lock:
            if self._offline_reason is not None or not self._access_token or not self._refresh_token:
                raise MarketDataUnavailable(self._offline_reason or "No Schwab tokens")
            return TokenSet(self._access_token, self._refresh_token, self._access_expires_at, self._refresh_expires_at)

    def pull_now(self) -> None:
        """Follower: an admin's "Pull now". Raises PullRateLimited inside the one-minute window; a failed pull
        is reported through status (last_pull_outcome), not raised. Sync (I/O)."""
        with self._lock:
            wait = self._pull_wait_seconds()
            if wait > 0:
                raise PullRateLimited(wait)
            try:
                self._pull_locked()
            except MarketDataUnavailable:
                pass

    def _get(self, path: str, params: dict) -> dict:
        self._ensure_valid_token()
        for attempt in (1, 2):
            token = self._access_token
            resp = httpx.get(
                f"{SCHWAB_API_BASE}{path}",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
                timeout=30,
            )
            if resp.status_code == 401 and attempt == 1:
                # Renew once (refresh, or pull in follower mode) and retry once.
                self._renew_after_401(token)
                continue
            break
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
                token_source="production" if self.follower else "self",
                last_pull_at=self._last_pull_at,
                last_pull_outcome=self._last_pull_outcome,
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
