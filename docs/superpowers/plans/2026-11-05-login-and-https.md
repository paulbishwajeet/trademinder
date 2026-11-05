# Login and HTTPS (Part 5) — Implementation Plan

Spec: `docs/superpowers/specs/2026-11-05-login-and-https-design.md`. No commits unless asked.
Worktree `.claude/worktrees/login-and-https`; verify against a DB copy, never the live DB.

- [x] 1. Settings: PUBLIC_BASE_URL, Google id/secret, SESSION_DAYS, AUTH_STATE_SECRET, EXTENSION_IDS; https fail-fast; .env.example.
- [x] 2. Migration 018: user_sessions, extension_tokens, users.invited_by/approved_by/approved_at.
- [x] 3. Services: auth (sessions, tokens, signed state), google_oidc (PKCE/state/nonce, google-auth verification, sign-in rules), user_admin (activation + default categories, admin guards).
- [x] 4. Routers: auth (login/callback/logout), me (+status), admin, extension (connect, tokens).
- [x] 5. Seam: cookie or bearer → 401/403; pending only /api/me; require_admin; require_session_user; every router mounted behind it.
- [x] 6. CORS to allow-listed extension origins; proxy headers; docs off on https.
- [x] 7. Frontend: AuthContext + guards, Sign in, Waiting, Admin (+Invite), Settings → Connected extensions, extension connect page, sidebar user + Logout, global 401.
- [x] 8. Extension: identity permission, Sign in/out in popup (worker runs launchWebAuthFlow), bearer on every call, 401 → "Signed out — Sign in again".
- [x] 9. Traefik in docker-compose.prod.yml (pinned, 443 only, DNS-01 Cloudflare, named volume, labels).
- [x] 10. Deployment guide docs/deployment/qnap-login-and-https.md.
- [x] 11. Tests: test_auth.py + authenticated client fixture.
- [x] 12. Docs: README, TradeMinder-Context.
- [ ] 13. Deploy to the QNAP and run the post-deployment checklist (owner).
