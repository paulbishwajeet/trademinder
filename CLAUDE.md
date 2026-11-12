# TradeMinder — instructions for Claude

Project map: `context/_project.md`. Detailed, authoritative reference: `docs/TRADEMINDER_MASTER_CONTEXT.md`.
Decision history: `docs/decisions.md`.

## Working notes (context/) — do this automatically

These are standing rules. Follow them without being asked.

- **Session start.** Before doing any work, read `context/_active.md`, then the feature context file it points to,
  then only the files listed under that file's Key Files. Give a 3-bullet summary of what we were doing and the
  next step, then wait for confirmation.
  - If `_active.md` has no active feature, say so and ask what we're working on.
  - If I name a different feature, switch: read its file, update `_active.md`, summarize, and wait.
- **New feature.** When I start new work that has no context file yet, do this before writing any code:
  - create `context/feature-<name>.md` from the template in `context/README.md`, with Status Not Started, branch
    `feature/<name>`, today's date, and the first concrete next step in Current State;
  - point `_active.md` at it;
  - create the branch.
- **During work.**
  - Log each decision in the feature's Decisions Made table (Decision, Chosen, Reason) as soon as it is made.
  - Add each blocker or open question to Open Questions as soon as it comes up.
  - Don't wait to be asked, and don't batch them up for the end.
- **Checkpoint (the parking note).** You can't reliably tell when I'm about to close a session, so park
  continuously.
  - **When:**
    - after every meaningful step (a sub-task finished, tests passing, a design choice settled);
    - before every commit;
    - whenever I say I'm stopping, switching, wrapping up or "park it";
    - whenever the conversation is long enough that context may be compacted.
  - **Each checkpoint does all five:**
    1. **Progress Log:** a dated 1–2 line entry for what was done. Add to today's entry rather than piling up
       duplicates.
    2. **Current State:** overwrite it with exactly where we stopped and the single next action, written for
       someone picking it up cold.
    3. **Key Files:** add any files created or significantly changed.
    4. **Decisions Made:** add any not yet logged.
    5. **Open Questions:** add new blockers and tick off resolved ones.
  - Checkpoint silently, without asking first. Mention it in one line only.
- **Feature complete.** When the feature is merged, or I say it's done:
  - set Status to Complete and add a final dated Progress Log summary;
  - resolve or clear Open Questions, moving anything still open to the master context's open items;
  - set Current State to "COMPLETE — merged to <branch>";
  - mark it done in `_project.md`'s Modules/Features list, and clear `_active.md`;
  - then run the "Keeping docs/ current" rules below for the whole feature, and promote any Decisions Made items
    that matter beyond this feature into `docs/decisions.md`.
- **Audit on request.** When I ask for a context audit:
  - read every file in `context/`;
  - give a table of feature, status, last Progress Log date and unresolved blockers;
  - flag files that look stale or out of sync with the code (for example, merged but still marked In Progress).

## Keeping docs/ current

`docs/` must always describe the project as it actually is: an outside planning project reads it to stay current.

- **When.** Before committing any feature, fix or refactor that changes behavior, update `docs/decisions.md` and
  `docs/TRADEMINDER_MASTER_CONTEXT.md`. Do it in the same commit, or in a `docs` commit on the same branch before
  merge.
- **`docs/decisions.md`** gets a new entry (newest first, using the template at the top of the file) whenever:
  - the implementation deviated from the prompt or plan;
  - the schema changed (new migration);
  - an endpoint was added, removed or changed shape;
  - a convention was introduced or changed;
  - something was deliberately deferred or descoped;
  - a production or deployment lesson was learned.
- **`docs/TRADEMINDER_MASTER_CONTEXT.md`** must stay true in these places:
  - Current State, re-dated;
  - data model;
  - migration head and next migration number;
  - API surface;
  - conventions;
  - environment variable names (never values);
  - "What Is Stubbed, Stale, or Known-Broken";
  - roadmap and open items.

  Edit those sections in place rather than appending a changelog: history belongs in `decisions.md`.
- **Trivial changes** (typos, pure styling, test-only changes) need no entry.
- **Never** put secrets, tokens, account numbers or personal emails in any doc under `context/` or `docs/`.
