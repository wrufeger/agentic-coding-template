---
name: act-commit
description: Close out an accepted task - check the evidence, archive it, update the journal, commit by pathspec. Use right after a task is accepted and its evidence (a test run, an outside call, a commit) is in hand.
---

# Close out a task and commit

Runs **after every accepted task**, not just at session end. Applies `R-work-evidence`,
`R-code-commit`, and `R-role-main` (only the orchestrator writes to `docs/ai/` and commits).

Journal, task status, and open questions are already current at this point — that happens during
the work itself (`R-work-record-now`), not here. This skill cleans up what accumulated and
secures the result.

## Steps

1. **Check the evidence.** A test run, an outside call, or a commit hash — nothing gets accepted
   without one. The project's required checks (`docs/ai/config.md` § commands) must be green.
2. **Archive.** Move the finished file(s) — task, backlog item, and any inbox entry marked `done`
   that belongs to it — from `docs/ai/work/tasks/` / `.../backlog/` / `docs/ai/inbox/` to
   `docs/ai/work/archive/` (`docs/ai/work/archive/README.md`). Short IDs already assigned stay
   valid; the file keeps its name.
3. **Add or tighten the journal entry** under `docs/ai/work/ledger/` — a new file if this step
   isn't recorded yet, older entries left as they are otherwise.
4. **Docs index.** New files go into `docs/README.md`; check the data-as-of note on files that
   changed.
5. **Commit by pathspec.** `git add <path …>` — never a catch-all. What gets committed is accepted
   work, not a time slice; several commits per session are normal. Short message in the repo's own
   style, attribution as given for the running session. Don't silently sweep up another session's
   uncommitted changes — look at them, then decide.
6. **Report to the human.** Result first, evidence (hash, test numbers), open points and questions
   by ID (`R-human-chat`).

## Limits

- Never runs as a sub-agent — only the orchestrator writes to `docs/ai/` and commits
  (`R-role-main`).
- A task that isn't accepted (red checks, missing evidence, an open question) doesn't get
  committed — its status under `docs/ai/work/tasks/` is updated to say what's still open instead.
