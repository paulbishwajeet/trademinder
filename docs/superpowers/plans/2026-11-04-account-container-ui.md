# Account Container UI (Part 2) — Implementation Plan

Spec: `docs/superpowers/specs/2026-11-04-account-container-ui-design.md`. No commits unless asked.

- [x] 1. Backend: restore, delete guard (+memberships), reorder, `can_delete`, `GET /api/dashboard/summary`; pytest.
- [x] 2. API client + types: accounts (restore, reorder), dashboard summary, categories, account params on trades/wheel/sessions/screener.
- [x] 3. Routing: `AccountsProvider`, `AccountLayout`, account/research/settings routes, path helpers.
- [x] 4. Sidebar (Radix Collapsible, native DnD reorder) replacing the top nav.
- [x] 5. Account management: `AccountDialog`, Settings → Accounts table.
- [x] 6. Account-scoped pages: Trades (+detail), WHEEL, Spreads, Margin pass the account; per-account group order; account categories.
- [x] 7. Screener (account vs Research), Chain/Scanner in both places; Scanner accepts `symbol`.
- [x] 8. Dashboard from the summary endpoint.
- [x] 9. Legacy redirects; account-aware internal links.
- [x] 10. Verify: tsc, backend suite, manual checklist against a DB copy; update context file.
