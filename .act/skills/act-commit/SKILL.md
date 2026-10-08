---
name: act-commit
description: Use right after a task is accepted and its evidence (a test run, an outside call, a commit hash) is in hand, or when asked to close out and commit. Leaves the task archived and journaled, committed by pathspec. Never run by a sub-agent.
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
2. **Assign ids.** `docs/ai/config.md` § `mode` decides when a task/backlog/question got its short
   id: in `solo` it already has one. In `team`, run `python .act/scripts/entries.py assign` — it
   hands out `T`/`B`/`Q` numbers, but only once this commit lands on the project's default branch;
   on a feature branch it changes nothing and says so, and the entries stay identified by
   filename until a commit on the default branch runs it. It renames each file and reports
   `<old> -> <new>`; stage both paths (the old one as a deletion) — otherwise a clone that already
   has the pre-rename file keeps it lying around, unassigned, once this commit is pulled.
3. **Archive.** Move every finished file — a task, a backlog item, and **every** inbox entry
   marked `status: done`, whatever its `kind` (questions included) and whether or not it belongs
   to this task — from `docs/ai/work/tasks/` / `.../backlog/` / `docs/ai/inbox/` to
   `docs/ai/work/archive/` (`docs/ai/work/archive/README.md`). Short IDs already assigned stay
   valid; the file keeps its name.
4. **Add or tighten the journal entry** under `docs/ai/work/ledger/` — a new file if this step
   isn't recorded yet, older entries left as they are otherwise.
5. **Docs index.** New files go into `docs/README.md`; check the data-as-of note on files that
   changed.
6. **Commit by pathspec.** With `board: shared` in `docs/ai/config.md`, first run
   `python .act/scripts/board.py --shared` and add `docs/ai/board-<identity>.md` to the pathspec of
   this same commit (only `--shared` writes that versioned file; a plain run never does).
   `git add <path …>` — never a catch-all. What gets committed is accepted work, not a time slice; several commits per session are normal. Short message in the repo's own
   style, attribution as given for the running session. Don't silently sweep up another session's
   uncommitted changes — look at them, then decide.
7. **Anyone waiting?** Is anyone waiting for a reply from this session? Then file or close the todo
   (`entries.py new todo`, `for:` naming whom, `R-human-external`).
8. **Report to the human.** Result first, evidence (hash, test numbers), open points and questions
   by ID (`R-human-chat`).

## Limits

- Never runs as a sub-agent — only the orchestrator writes to `docs/ai/` and commits
  (`R-role-main`).
- A task that isn't accepted (red checks, missing evidence, an open question) doesn't get
  committed — its status under `docs/ai/work/tasks/` is updated to say what's still open instead.
