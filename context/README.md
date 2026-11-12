# Context Directory

Working notes for AI-assisted development. The rules for keeping them current are in the repo-root `CLAUDE.md`
("Working notes (context/) — do this automatically"). Durable project docs live in `docs/`
(`TRADEMINDER_MASTER_CONTEXT.md`, `decisions.md`).

| File | Purpose |
|---|---|
| `_project.md` | Short project map: stack, directories, conventions, modules. Points to the master context |
| `_active.md` | The feature in progress, its branch and its context file, or "No active feature" |
| `feature-<name>.md` | One per feature, using the template below |

## Usage

At the start of a session, read `_active.md`, then the linked feature file, then only that file's Key Files.
When switching features, update `_active.md`. When a feature is merged, mark it Complete and clear `_active.md`.

## Feature file template

```markdown
# Feature: <Name>

**Status:** Not Started | In Progress | Blocked | Complete
**Branch:** feature/<name>
**Created:** YYYY-MM-DD

## Goal
<one or two sentences>

## Scope
**In:** …
**Out:** …

## Key Files / Modules Involved
- `path` — why it matters

## Technical Approach
<how it works / will work>

## Decisions Made
| Decision | Chosen | Reason |
|---|---|---|

## Open Questions / Blockers
- [ ] …

## Progress Log
- YYYY-MM-DD: <1–2 lines>

## Current State (Resume Here)
<exactly where we stopped and the single next action, written for someone picking it up cold>
```

Older feature files predate this template and use slightly different headings. Their Status line and Current State
were normalised in the 2026-11-12 audit.
