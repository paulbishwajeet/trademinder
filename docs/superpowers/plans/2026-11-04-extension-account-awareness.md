# Extension Account Awareness (Part 3) — Implementation Plan

Spec: `docs/superpowers/specs/2026-11-04-extension-account-awareness-design.md`. No commits unless asked.
Work in the worktree `.claude/worktrees/extension-account-awareness`; verify against a DB copy, never the live DB.

- [x] 1. Backend: migration 017 + model (label, seen_at, check constraint, partial unique index).
- [x] 2. Backend: link service + endpoints (resolve, create+link, link, unlink); `AccountResponse.link`.
- [x] 3. Backend: positions/status optional account + `account`/`matches`; reconcile requires account; drop default fallback.
- [x] 4. Backend tests: linking rules, per-user uniqueness, status both modes, reconcile requirement + scoping; update old reconcile tests.
- [x] 5. Extension service worker: stored address, path-based FETCH, error classes, fingerprint, resolve cache.
- [x] 6. Extension account detection: prefix selectors, grid by role/aria-label, dropdown read + change + observer, cache reset.
- [x] 7. Linking UI: account bar indicator, link card (existing / create new), refresh after link.
- [x] 8. Scoped calls: status, active-slots (TTL per context), sessions, add (All-view picker), edit; per-account chips.
- [x] 9. Reconcile gating + account_id in snapshot.
- [x] 10. Popup: server address, runtime host permission, reachability.
- [x] 11. SPA: Settings → Accounts link column + Unlink.
- [x] 12. Docs: extension DOM facts (context/extension.md, docs/TradeMinder-Context.md), README extension section.
- [x] 13. Verify: pytest, tsc, fixture-driven run (real content/background scripts + chrome shim, Playwright) against a DB copy.
- [x] 14a. Fresh masked DOM captures (single + All) analysed; All-view fixes applied and re-verified.
- [x] 14b. Live DB backed up and migrated to 017.
- [ ] 14. Serve this branch from the main checkout; real extension run on E*TRADE.
