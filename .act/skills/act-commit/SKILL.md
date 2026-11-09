---
name: act-commit
description: Use right after a task is accepted and its evidence (a test run, an outside call, a commit hash) is in hand, or when asked to close out and commit. Leaves the task archived and journaled, committed by pathspec. Never run by a sub-agent.
---

# Close out a task and commit

Runs **after every accepted task**, not just at session end. Applies `R-work-evidence`,
`R-code-commit`, and `R-role-worker` (only the orchestrator writes to `docs/ai/` and commits).

Journal, task status, and open questions are already current at this point — that happens during
the work itself (`R-work-record-now`), not here. This skill cleans up what accumulated and
secures the result.

## Steps

1. **Check the evidence.** A test run, an outside call, or a commit hash — nothing gets accepted
   without one. The project's required checks (`docs/ai/config.md` § commands) must be green; the
   full suite runs once here (via `quick-check`), not again from builder and reviewer. File each
   backlog case the `reviewer` listed (with its input) with `entries.py new backlog <title>`. If
   the `reviewer` returned `CONDITIONAL` (a named condition this step cannot check), file the
   condition now: `entries.py new todo <title>`, or `new question` if
   the human must decide — the condition and how its fulfilment shows in the body. Its id goes into
   the commit message in step 7. `BLOCK` still stops the commit; so does a `CONDITIONAL` with no
   recognisable condition or with more than one — treat it as `BLOCK` and send it back to the
   `reviewer`.
2. **Assign ids.** `docs/ai/config.md` § `mode` decides when a task/backlog/question got its short
   id: in `solo` it already has one. In `team`, run `python .act/scripts/entries.py assign` — it
   hands out `T`/`B`/`Q` numbers, but only once this commit lands on the project's default branch;
   on a feature branch it changes nothing and says so, and the entries stay identified by
   filename until a commit on the default branch runs it. It renames each file and reports
   `<old> -> <new>`; stage both paths (the old one as a deletion) — otherwise a clone that already
   has the pre-rename file keeps it lying around, unassigned, once this commit is pulled.
3. **Archive.** Finish every finished file — a task, a backlog item, and **every** inbox entry
   marked `status: done`, whatever its `kind` (questions included) and whether or not it belongs
   to this task — from `docs/ai/work/tasks/` / `.../backlog/` / `docs/ai/inbox/` with `python
   .act/scripts/entries.py archive <id|file>`; it also takes along the images and files the entry
   links beside itself and prints every path it moved, copied, deleted or changed: stage all of
   them (stage every file the script prints as `rewrote` too). Short IDs already assigned
   stay valid. The entry always moves to `docs/ai/work/archive/` (`docs/ai/work/archive/README.md`) and
   keeps its name; a generic image name gets the id in front. Nothing is deleted: `act-compact` folds
   the single files into the monthly files later. A concept file that was decided or built in this task
   is archived the same way, `entries.py archive <file>` (`R-docs-order`).
4. **Add or tighten the journal entry** under `docs/ai/work/ledger/` — a new file if this step
   isn't recorded yet, older entries left as they are otherwise. Journal entries stay single files
   only until they are old: `act-compact` later folds them into one file per month
   (`archive/ledger-<YYYY-MM>.md`); archived entries go into `Q-/T-/B-/U-<YYYY-MM>.md` and concepts into
   `other-<YYYY-MM>.md`.
5. **Docs index.** A new file under `docs/project/` gets its line (name, contents, state) in the `README.md` of
   its folder, a moved or deleted one loses or changes it (`R-docs-order`); a folder with fewer than five
   entries and no `README.md` of its own is listed by the line in the `README.md` above it; a new top-level folder or file
   under `docs/` goes into `docs/README.md`. Check the data-as-of note on files that changed. A concept
   whose questions are answered and whose build is done is archived in step 3.
6. **Learning check.** Did the task need at least two rework rounds (a worker result rejected
   twice, or two repair rounds after review or test)? Count them yourself. If so, run step 8 of
   `act-bug` and put the note into this commit. A rule recorded for a new pitfall is one imperative
   line under "Own rules"; its incident, evidence and identifiers go into the project docs.
7. **Commit by pathspec.** With `board: shared` in `docs/ai/config.md`, first run
   `python .act/scripts/board.py --shared` and add `docs/ai/board-<identity>.md` to the pathspec of
   this same commit (only `--shared` writes that versioned file; a plain run never does).
   `git add <path …>` — never a catch-all. What gets committed is accepted work, not a time slice; several commits per session are normal. Short message in the format of the
   project (see below), attribution as given for the running session; after a `CONDITIONAL`, the message names
   the id of the inbox entry from step 1. Don't silently sweep up another session's
   uncommitted changes — look at them, then decide.
   - **Message format:** `docs/project/formats/commit.md` when the project has it, else the preset named by
     `commit-format` in `docs/ai/config.md` § Formats, taken from `.act/formats/commit.md` (no row, empty,
     `auto` or an unknown name: the repo's own style, as before).
   - **Changelog entry:** with `changelog: file` (the default; the row is in the same section) and a
     `CHANGELOG.md` in the project root, read the changelog format the same way (`.act/formats/changelog.md`,
     `changelog-format`, or `docs/project/formats/changelog.md`). If it says entries are written as you go
     (preset `keep-a-changelog`), add one line under `## [Unreleased]` in the right group for a commit with a
     visible effect for someone using the project, and put `CHANGELOG.md` into this commit's pathspec. The entry
     follows the writing rules of that format; a duty at update gets its own line under `### Upgrading`. A purely
     internal commit gets no line; with `at-release`, `release-notes-only`, `off` or no file, nothing is written
     here.
8. **Throwaway folders.** Remove the task's folders under `.act-local/tmp/` with `python .act/scripts/act_local_tidy.py
   --task <id>` (`R-work-throwaway`); it removes `tmp/<id>` and `tmp/<id>-*` and nothing else.
9. **Anyone waiting?** Is anyone waiting for a reply from this session? Then file or close the todo
   (`entries.py new todo`, `for:` naming whom, `R-human-external`).
10. **Report to the human.** Result first, evidence (hash, test numbers), open points and questions
   by ID (`R-human-chat`).

## Limits

- Never runs as a sub-agent — only the orchestrator writes to `docs/ai/` and commits
  (`R-role-worker`, `R-code-commit`).
- A task that isn't accepted (red checks, missing evidence, an open question) doesn't get
  committed — its status under `docs/ai/work/tasks/` is updated to say what's still open instead.
  The one exception: the question or todo filed in step 1 for a `CONDITIONAL` does not hold the
  commit back.
