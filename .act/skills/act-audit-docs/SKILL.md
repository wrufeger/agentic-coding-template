---
name: act-audit-docs
description: Use after a feature wave, before a handover, or when docs/project might be stale or contradict the code (architecture, coding rules, testing, features, decisions). Brings outdated entries in line with the actual code. Not for template drift - use act-doctor.
---

# Audit docs/project against the code

`docs/project/` describes the actual state, not the plan — this skill closes the gap between the
two. Whether the project still matches the template's own `.act/` is a separate concern, covered
by `act-doctor`.

1. `git status` and `git diff --stat -- docs/project`: sight open changes from earlier sessions
   first.
2. Run each pair in sequence, not in parallel: `explorer` first — what actually exists — modules,
   endpoints, tables, commands, tests — each claim backed by `<path>:<line>` (`R-role-worker`);
   then `doc-writer` compares that report against `docs/project/*` and corrects it directly. On a
   larger project, one such pair per doc area — those pairs may run in parallel with each other,
   never explorer and doc-writer within the same pair.
3. Fold in what the wave produced: a new interface or table into `architecture.md`/`features.md`,
   a newly learned convention into `coding_rules.md`, changed tests into `testing.md`, a severe
   failure into `docs/project/incidents/`. Maintaining `testing.md`: check that the runner it names
   actually exists and that its command isn't interactive (no unattended install prompt), same
   check as before any test run (`.act/agents/builder.md`). Also check `glossary.md`: add terms the wave
   introduced, drop or correct entries the code no longer matches.
4. **Structure** (`R-docs-order`, details `.act/rules/topics/docs-order.md`). Run `python .act/scripts/doctor.py`
   and read the `docs-*` findings: a folder or file without its index line, an index line without a file,
   a dead link, a decided concept still lying around. Fix them in this order: a file that sits in the wrong
   place is moved with `python .act/scripts/move_doc.py <from> <to>` (plan first, then again
   with `--apply`) - never by hand, the script pulls links, paths and the index line along and lists what it
   cannot know (a bare file name, a README.md that is missing); then `doc-writer` writes the missing index
   lines and `README.md` files (one line per file with its state), and a decided concept is deleted after
   its build and reason stand in the backlog item, the task or a decision record. A file past about 300
   lines is split into a folder with a `README.md`. Run `doctor.py` again and stage the old and the new
   path of every move.
5. `doc-writer` updates `docs/README.md` (folders and top-level files only, data-as-of dates).

In Claude Code, steps 2, 3 and 5 can also run as the workflow script `workflow.js.txt` beside this file — only
when the human asks for that variant explicitly; it has no Structure step, so run step 4 by hand first. Read `references/workflow.md` before starting it.

A full pass across all doc areas logs a journal entry whose title starts with `act-audit-docs`
(`entries.py new ledger "act-audit-docs: ..."`); a spot check of one area skips the entry — this is
how session start tells how long ago the last full pass ran.

With `teach-lessons: docs` (`docs/ai/config.md` § Teaching), the lessons under `docs/learn/` are
one more area: the explorer reports code examples (`<path>:<line>`) and version statements that no
longer match the code, and the `doc-writer` assignment names `docs/learn/` in its write scope, since
its role covers `docs/project/` only. The workflow variant takes `docs/project/` only; after it,
check `docs/learn/` the manual way.

## Limits

Nothing here touches code. A finding that needs a code change becomes a task, not a doc edit
worked around it. No doc entry without a code check first — docs describe the actual state, never
the wish (`R-work-evidence`).

Close with `act-commit`.
