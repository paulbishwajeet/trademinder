# Runbook: weekly Schwab reconnect

Schwab ends TradeMinder's market data connection **7 days after each login**. Refreshing the access token doesn't
extend it. Renew it once a week from the production app; it takes under a minute.

**Reconnect only in production; dev follows.** Each Schwab login creates a new grant and invalidates the previous
grant's refresh token, so two environments can't each hold their own. Production owns the one grant, and the Mac
(dev) pulls production's current tokens instead of refreshing or reconnecting.

## Weekly routine

1. **In production only:** Reconnect Schwab (steps below), before the amber banner turns red.
2. **Dev needs nothing.** It pulls the new tokens from production on its next market call, or immediately with
   Settings → Market data → **Pull now**. Never click Reconnect, or run `scripts/schwab_auth.py`, on dev; both are
   disabled or ask for confirmation there.

## One-time setup: dev follows production

1. Generate a secret: `openssl rand -hex 32`.
2. **NAS:** Portainer → the `trademinder` stack → Environment variables → add `SCHWAB_TOKEN_SYNC_SECRET` with that
   value. Leave `SCHWAB_TOKEN_SYNC_URL` unset there. **Pull and redeploy.** The export answers 404 until the secret
   is set.
3. **Mac:** in the repo-root `.env`, set `SCHWAB_TOKEN_SYNC_URL=https://tm.<domain>` and the same
   `SCHWAB_TOKEN_SYNC_SECRET`. Restart the backend.
4. Check dev's Settings → Market data: **Token source: Production**, **Last pull outcome: OK**.

The secret goes only into Portainer and the git-ignored `.env`, never into git. Dev must reach the NAS: on the home
network, the same as the browser.

If dev shows "Market data offline" with a last pull outcome of:
- **production unreachable:** the NAS backend is down, or you're off the home network. It recovers by itself
  within a minute of the NAS coming back.
- **production is offline:** production's own connection lapsed. Reconnect in production.
- **secret rejected:** the two secrets differ.
- **token sync not enabled on production:** the NAS stack has no secret, or wasn't redeployed.

## When

- **Amber banner** ("expires in N days"): reconnect when convenient.
- **Red banner** (hours left, or "Market data offline"): reconnect now. While offline, market fields show "—"
  everywhere; journals, wheels and Reconcile keep working.
- **Any time:** Settings → **Market data** shows the expiry and has the same button. Reconnecting early is fine;
  the new connection lasts 7 days from that moment.

Only admins see the banner, the tab and the button.

## Steps (in the production app, signed in as the admin)

1. Click **Reconnect Schwab** on the banner or in Settings → Market data.
2. Click **Open Schwab login**. A new tab opens at Schwab.
3. Log in with the Schwab brokerage credentials and approve access.
4. The tab goes to `https://127.0.0.1:8765/callback?code=…` and **fails to load. That's expected.**
5. Copy the **whole** address from that tab's address bar, switch back to TradeMinder, paste it, and click
   **Connect**. Do it promptly: Schwab's code lasts only a short time.
6. The dialog shows the new expiry and the banner disappears. Close the failed tab.

The new connection is live immediately: no restart, and no token copy to the NAS. Dev picks it up on its next
pull.

## If it fails

| Message | Do this |
|---|---|
| "Schwab rejected the authorization code — it has probably expired" | **Start again** and paste faster. Also the cause if the same address was pasted twice. |
| "This reconnect link expired" / "isn't valid any more" | **Start again**. Links last 10 minutes and work once. A backend restart (e.g. a redeploy) also forgets them. |
| "That isn't the Schwab redirect address" / "No authorization code" | Paste the full address of the failed tab, not the Schwab page or a partial copy. The same link still works: fix the paste and click Connect. |
| "That address has no reconnect state" | That address came from the CLI's link. Start again from the dialog. |
| "Schwab didn't authorize the connection" | You declined or cancelled at Schwab. Start again. |
| "Couldn't reach Schwab" | Network or Schwab trouble. Try again in a minute. |

The backend logs one line per attempt: `Schwab reconnected by user <id>; refresh token expires …` or
`Schwab reconnect failed for user <id>: <code>`. Codes, tokens and the pasted address are never logged.

## Fallback: the CLI

If the app can't do it (for example, the backend is down), use the CLI on a machine with the repo and its
`.env`:

```sh
python scripts/schwab_auth.py      # same login and paste, in the terminal
```

It writes the token row of the database that `DATABASE_URL` points to. For production, that means copying the row
to the NAS afterwards (see `qnap-login-and-https.md`, "Market data on the NAS"). The backend picks up a changed
row within a minute.

## Things that don't change

- Schwab's registered callback stays `https://127.0.0.1:8765/callback`. Its console accepts only one callback,
  which is why the address is pasted rather than received by the server.
- Market data is shared: one connection serves every user.
