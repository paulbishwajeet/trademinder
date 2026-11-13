#!/usr/bin/env python3
# scripts/schwab_auth.py
"""
One-time Schwab OAuth flow. Run before first use and any time before the
7-day refresh token expires. (The admin can also do this in the web app:
the "Reconnect Schwab" button on the banner or in Settings → Market data.)

Prerequisites:
  1. Set callback URL in Schwab developer portal to: https://127.0.0.1:8765/callback
  2. Set SCHWAB_APP_KEY, SCHWAB_APP_SECRET, DATABASE_URL in .env
  3. Run: python scripts/schwab_auth.py

After login, the browser will show a connection error at 127.0.0.1:8765 — that is
expected. Copy the full URL from the address bar and paste it when prompted.

The authorize URL, code exchange and token-row write live in
backend/app/services/schwab_oauth.py (shared with the web app's reconnect). That
module needs no app settings, so this script still runs standalone from .env.
"""
import asyncio
import os
import sys
import webbrowser
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.services.schwab_oauth import (  # noqa: E402
    REDIRECT_URI, CodeRejected, RedirectUrlError, SchwabUnreachable,
    authorize_url, exchange_code, parse_redirect_url, store_tokens,
)

load_dotenv(ROOT / ".env")

APP_KEY = os.environ["SCHWAB_APP_KEY"]
APP_SECRET = os.environ["SCHWAB_APP_SECRET"]
DATABASE_URL = os.environ["DATABASE_URL"]


def main():
    url = authorize_url(APP_KEY)

    print("\nOpening browser to authorize TradeMinder...")
    print("Log in with your Schwab brokerage credentials.\n")
    webbrowser.open(url)

    print(f"After login, the browser redirects to {REDIRECT_URI}")
    print("and shows a connection error. That is expected.")
    print("\nCopy the FULL URL from the browser address bar and paste it here:")
    redirected_url = input("> ").strip()

    try:
        auth_code, _state = parse_redirect_url(redirected_url, require_state=False)
    except RedirectUrlError as exc:
        if exc.reason == "missing_code":
            print("ERROR: No 'code' found in the URL. Make sure you copied the full redirect URL.")
        elif exc.reason == "authorization_denied":
            print("ERROR: Schwab did not authorize the connection (the URL carries an error).")
        else:
            print(f"ERROR: That is not the redirect URL ({REDIRECT_URI}...).")
        sys.exit(1)

    print("\nAuth code received. Exchanging for tokens...")
    try:
        tokens = exchange_code(APP_KEY, APP_SECRET, auth_code)
    except CodeRejected as exc:
        print(f"ERROR: Token exchange failed: {exc} (the code may have expired; run the script again and paste promptly)")
        sys.exit(1)
    except SchwabUnreachable as exc:
        print(f"ERROR: Token exchange failed: {exc}")
        sys.exit(1)

    asyncio.run(store_tokens(DATABASE_URL, tokens))

    print(f"\nTokens stored successfully.")
    print(f"  Access token expires:  {tokens.access_expires_at.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Refresh token expires: {tokens.refresh_expires_at.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"\nRe-run this script before {tokens.refresh_expires_at.strftime('%Y-%m-%d')} to stay authenticated.")


if __name__ == "__main__":
    main()
