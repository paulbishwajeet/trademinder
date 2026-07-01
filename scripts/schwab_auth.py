#!/usr/bin/env python3
# scripts/schwab_auth.py
"""
One-time Schwab OAuth flow. Run before first use and any time before the
7-day refresh token expires.

Prerequisites:
  1. Set callback URL in Schwab developer portal to: https://127.0.0.1:8765/callback
  2. Set SCHWAB_APP_KEY, SCHWAB_APP_SECRET, DATABASE_URL in .env
  3. Run: python scripts/schwab_auth.py

The script starts a local HTTPS server (self-signed cert) on port 8765 to capture
the OAuth callback automatically. The browser will show a security warning when
Schwab redirects — click Advanced → Proceed to complete the flow.
"""
import asyncio
import base64
import os
import ssl
import subprocess
import sys
import tempfile
import urllib.parse
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
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
            self.wfile.write(b"<html><body><h2>Auth complete. You can close this tab.</h2></body></html>")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing code param.")

    def log_message(self, format, *args):
        pass  # suppress request logging


def _generate_self_signed_cert(tmpdir: str) -> tuple[str, str]:
    cert_file = os.path.join(tmpdir, "cert.pem")
    key_file = os.path.join(tmpdir, "key.pem")
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", key_file, "-out", cert_file,
            "-days", "1", "-nodes",
            "-subj", "/CN=127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    return cert_file, key_file


def main():
    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": APP_KEY,
        "redirect_uri": REDIRECT_URI,
        "scope": "readonly",
    })
    url = f"{AUTH_URL}?{params}"

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            cert_file, key_file = _generate_self_signed_cert(tmpdir)
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("ERROR: openssl not found. Install it and try again.")
            sys.exit(1)

        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.load_cert_chain(cert_file, key_file)

        server = HTTPServer(("127.0.0.1", 8765), _CallbackHandler)
        server.socket = ssl_ctx.wrap_socket(server.socket, server_side=True)

        print("\nStarted local HTTPS server on port 8765.")
        print("Opening browser to authorize TradeMinder...\n")
        print("NOTE: After login, the browser will redirect to localhost and show a")
        print("security warning (self-signed cert). Click Advanced → Proceed to 127.0.0.1\n")
        webbrowser.open(url)

        print("Waiting for callback...")
        server.handle_request()
        server.server_close()

    if not _auth_code:
        print("ERROR: No auth code received.")
        sys.exit(1)

    print("Auth code received. Exchanging for tokens...")

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
