# Schwab Hardening (Part 4) — Implementation Plan

Spec: `docs/superpowers/specs/2026-11-04-schwab-hardening-design.md`. No commits unless asked.
Worktree `.claude/worktrees/schwab-hardening`; verify against a DB copy, never the live DB.

- [x] 1. Inventory SchwabClient importers/callers (spec table).
- [x] 2. Provider boundary: `market_data.py` (Protocol, factory, setting + startup validation, errors module), callers switched, test patch targets updated.
- [x] 3. Offline detection in `SchwabClient` (expired / invalid_grant / no tokens / unconfigured), no calls while offline, ≤1/min token-row recheck, transitions logged once, `status()`.
- [x] 4. Status endpoint `GET /api/market-data/status` (admin) + `GET /api/me`.
- [x] 5. Router degradation: 503 handler; offline propagated through services; stale signal caches; mixed endpoints blank market fields + header/body flag; screener safety.
- [x] 6. Scheduler + engines: skip price refresh / price rules offline; no deactivation on missing data; price refresh off the event loop.
- [x] 7. Frontend: status polling, banner, apiFetch code/header, dashes/tooltips, stale tooltips, no stale client caching.
- [x] 8. Extension: offline notice from header/503.
- [x] 9. Tests: thresholds, provider offline/resume, 503s, mixed endpoints, stale cache, signals not deactivated, scheduler, import guard.
- [x] 10. Manual checklist on a DB copy (results in the spec).
- [x] 11. Docs: README, TradeMinder-Context §5, context file.
