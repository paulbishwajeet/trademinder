#!/usr/bin/env python3
# scripts/schwab_auth.py
"""
One-time Schwab OAuth flow. Run before first use and any time before the
7-day refresh token expires.

Prerequisites:
  1. Set callback URL in Schwab developer portal to: https://127.0.0.1:8765/callback
  2. Set SCHWAB_APP_KEY, SCHWAB_APP_SECRET, DATABASE_URL in .env
  3. Run: python scripts/schwab_auth.py

After login, the browser will show a connection error at 127.0.0.1:8765 — that is
expected. Copy the full URL from the address bar and paste it when prompted.
"""
import asyncio
import base64
import os
import sys
import urllib.parse
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg
import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

APP_KEY = os.environ["SCHWAB_APP_KEY"]
APP_SECRET = os.environ["SCHWAB_APP_SECRET"]
DATABASE_URL = os.environ["DATABASE_URL"]
REDIRECT_URI = "https://127.0.0.1:8765/callback"
AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"


def main():
    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": APP_KEY,
        "redirect_uri": REDIRECT_URI,
    })
    url = f"{AUTH_URL}?{params}"

    print("\nOpening browser to authorize TradeMinder...")
    print("Log in with your Schwab brokerage credentials.\n")
    webbrowser.open(url)

    print("After login, the browser redirects to https://127.0.0.1:8765/callback")
    print("and shows a connection error. That is expected.")
    print("\nCopy the FULL URL from the browser address bar and paste it here:")
    redirected_url = input("> ").strip()

    parsed = urllib.parse.urlparse(redirected_url)
    params_map = urllib.parse.parse_qs(parsed.query)
    if "code" not in params_map:
        print("ERROR: No 'code' found in the URL. Make sure you copied the full redirect URL.")
        sys.exit(1)

    auth_code = urllib.parse.unquote(params_map["code"][0])
    print("\nAuth code received. Exchanging for tokens...")

    creds = base64.b64encode(f"{APP_KEY}:{APP_SECRET}".encode()).decode()
    resp = httpx.post(
        TOKEN_URL,
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
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

    async def _store():
        conn = await asyncpg.connect(DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://"))
        await conn.execute("""
            INSERT INTO schwab_tokens (id, access_token, refresh_token, access_expires_at, refresh_expires_at, updated_at)
            VALUES (1, $1, $2, $3, $4, NOW())
            ON CONFLICT (id) DO UPDATE SET
                access_token = EXCLUDED.access_token,
                refresh_token = EXCLUDED.refresh_token,
                access_expires_at = EXCLUDED.access_expires_at,
                refresh_expires_at = EXCLUDED.refresh_expires_at,
                updated_at = NOW()
        """, access_token, refresh_token, access_expires_at, refresh_expires_at)
        await conn.close()

    asyncio.run(_store())

    print(f"\nTokens stored successfully.")
    print(f"  Access token expires:  {access_expires_at.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Refresh token expires: {refresh_expires_at.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"\nRe-run this script before {refresh_expires_at.strftime('%Y-%m-%d')} to stay authenticated.")


if __name__ == "__main__":
    main()
