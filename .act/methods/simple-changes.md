# Working method — simple-changes

summary: the smallest change that does the job, only what was asked, assumptions named

Switched on by `methods: simple-changes` in `docs/ai/config.md` (§ Scope). Group IDs
(`MR-simple-changes-<name>`) are stable and never reassigned.

## `MR-simple-changes-minimal` — The smallest change that does the job

summary: no extra abstraction, option or error path nobody asked for

- Write the smallest code that fulfills the assignment, in the style of the code around it. No new
  abstraction, configuration option, parameter or error path for a case nobody named.
- Prefer deleting or reusing existing code over adding more. Three similar lines are better than a helper
  that has one caller.

## `MR-simple-changes-scope` — Change only what was assigned

summary: no refactoring, renaming or reformatting on the side; mention instead of doing

- Touch only the files and lines the assignment needs. No reformatting, renaming, cleanup or "improvement
  along the way" outside that; a drive-by change makes the diff harder to review and to undo.
- Something else worth changing goes into the report as a suggestion, with the file and the reason, for the
  human to decide.

## `MR-simple-changes-assumptions` — Name the assumptions

summary: state what was assumed; ask or report early rather than widen the change

- Where the assignment leaves a choice open, take the narrower reading, mark it **assumption** in the
  report and name what the other reading would have changed.
- A change that turns out much larger than the assignment is reported early, with what is done and a
  proposal to split it, instead of being worked through silently.
