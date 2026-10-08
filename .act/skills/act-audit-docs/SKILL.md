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
   check as before any test run (`.act/agents/builder.md`).
4. `doc-writer` updates `docs/README.md` (index, data-as-of dates).

A full pass across all doc areas logs a journal entry whose title starts with `act-audit-docs`
(`entries.py new ledger "act-audit-docs: ..."`); a spot check of one area skips the entry — this is
how session start tells how long ago the last full pass ran.

## Limits

Nothing here touches code. A finding that needs a code change becomes a task, not a doc edit
worked around it. No doc entry without a code check first — docs describe the actual state, never
the wish (`R-work-evidence`).

Close with `act-commit`.
