# Context Directory

This directory provides fast session context for AI-assisted development.

| File | Purpose |
|---|---|
| `_project.md` | High-level project map — stack, modules, conventions, directories |
| `_active.md` | Currently active feature, branch, and pointer to its context file |
| `context/<feature>.md` | Per-feature context files (created when starting a feature) |

## Usage

At the start of a new session, read `_active.md` first, then `_project.md`, then the linked feature context file. This gives full working context without re-exploring the codebase.

When switching features, update `_active.md` to point to the new feature's context file (create one if it doesn't exist).
