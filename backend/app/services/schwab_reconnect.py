# backend/app/services/schwab_reconnect.py
"""In-app Schwab reconnect, phase 1 ("paste the redirect URL"). Admin only (enforced by the router).

start(): the CLI's authorize URL plus a state — HMAC-signed with AUTH_STATE_SECRET, bound to the admin's user id,
10-minute expiry, single use (pending nonces in process memory; one backend process, so no Redis or table).
complete(): validate the pasted redirect URL (callback, code, state), exchange the code exactly as the CLI does,
and write the token row through the provider (SchwabClient.install_tokens), which comes back online at once.

Never log or return tokens, codes or the pasted URL: one line on success (user id, new refresh expiry) and
one WARNING line per failure with the error code only.
"""
import logging
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone

from app.config import settings
from app.services.auth import read_state, sign_state
from app.services.market_data import get_market_data
from app.services.schwab_oauth import (
    CodeRejected, RedirectUrlError, SchwabUnreachable, authorize_url, exchange_code, parse_redirect_url,
)

log = logging.getLogger(__name__)

STATE_PURPOSE = "schwab_reconnect"
STATE_TTL_SECONDS = 600


class ReconnectError(Exception):
    """A failure the dialog can show: `code` is stable for the frontend, `message` is for people."""

    def __init__(self, code: str, message: str, http_status: int, log_detail: str = ""):
        super().__init__(code)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.log_detail = log_detail  # sanitized (status codes / Schwab's short error name), for the log line only


_MESSAGES: dict[str, tuple[int, str]] = {
    "not_configured": (409, "Schwab app key and secret aren't configured on the server."),
    "bad_url": (400, "That isn't the Schwab redirect address. After the Schwab login, copy the whole address of the "
                     "page that failed to load (it starts with https://127.0.0.1:8765/callback) and paste it here."),
    "authorization_denied": (400, "Schwab didn't authorize the connection. Start again and approve access at Schwab."),
    "missing_code": (400, "No authorization code in that address. Copy the whole address from the address bar."),
    "missing_state": (400, "That address has no reconnect state, so it can't be checked. Start again from this "
                           "dialog (not the CLI's link)."),
    "state_invalid": (409, "This reconnect link isn't valid any more (already used, from another session, or the "
                           "server restarted). Start again."),
    "state_expired": (409, "This reconnect link expired (they last 10 minutes). Start again."),
    "code_expired": (400, "Schwab rejected the authorization code — it has probably expired. Start again and paste "
                          "the address promptly after logging in."),
    "schwab_unreachable": (502, "Couldn't reach Schwab to finish the connection. Try again in a minute."),
}


def _error(code: str, log_detail: str = "") -> ReconnectError:
    status, message = _MESSAGES[code]
    return ReconnectError(code, message, status, log_detail)


# ── single-use state: nonces issued by this process and not yet used ────────

_pending: dict[str, float] = {}   # nonce → expiry (time.time())
_pending_lock = threading.Lock()


def _remember(nonce: str, exp: float) -> None:
    now = time.time()
    with _pending_lock:
        for stale in [n for n, e in _pending.items() if e < now]:
            del _pending[stale]
        _pending[nonce] = exp


def _consume(nonce: str) -> bool:
    with _pending_lock:
        return _pending.pop(nonce, None) is not None


def _check_configured() -> None:
    if not settings.schwab_app_key or not settings.schwab_app_secret:
        raise _error("not_configured")


def start(user_id: uuid.UUID) -> tuple[str, datetime]:
    """(Schwab authorize URL, state expiry) for this admin."""
    try:
        _check_configured()
    except ReconnectError as exc:
        _log_failure(user_id, exc)
        raise
    nonce = secrets.token_urlsafe(16)
    state = sign_state({"p": STATE_PURPOSE, "uid": str(user_id), "n": nonce}, ttl_seconds=STATE_TTL_SECONDS)
    exp = read_state(state)["exp"]
    _remember(nonce, exp)
    return authorize_url(settings.schwab_app_key, state), datetime.fromtimestamp(exp, timezone.utc)


def _check_state(state: str, user_id: uuid.UUID) -> None:
    payload = read_state(state, allow_expired=True)
    if not payload or payload.get("p") != STATE_PURPOSE or payload.get("uid") != str(user_id) \
            or not isinstance(payload.get("n"), str):
        raise _error("state_invalid")
    if payload.get("exp", 0) < time.time():
        _consume(payload["n"])
        raise _error("state_expired")
    # Consumed before the exchange: a failed exchange still needs a fresh start (Schwab codes are single use).
    if not _consume(payload["n"]):
        raise _error("state_invalid")


def complete(user_id: uuid.UUID, pasted_url: str) -> datetime:
    """Validate, exchange, install. Returns the new refresh expiry. Sync (network + DB): run in an executor."""
    try:
        _check_configured()
        try:
            code, state = parse_redirect_url(pasted_url)
        except RedirectUrlError as exc:
            raise _error(exc.reason) from None
        _check_state(state, user_id)
        try:
            tokens = exchange_code(settings.schwab_app_key, settings.schwab_app_secret, code)
        except CodeRejected as exc:
            raise _error("code_expired", f"HTTP {exc.status} {exc.error or ''}".strip()) from None
        except SchwabUnreachable as exc:
            raise _error("schwab_unreachable", str(exc)) from None
        get_market_data().install_tokens(tokens)
    except ReconnectError as exc:
        _log_failure(user_id, exc)
        raise
    # WARNING, not INFO: the app has no logging config, so INFO lines never reach the container log.
    log.warning("Schwab reconnected by user %s; refresh token expires %s",
             user_id, tokens.refresh_expires_at.isoformat(timespec="minutes"))
    return tokens.refresh_expires_at


def _log_failure(user_id: uuid.UUID, exc: ReconnectError) -> None:
    detail = f" ({exc.log_detail})" if exc.log_detail else ""
    log.warning("Schwab reconnect failed for user %s: %s%s", user_id, exc.code, detail)
