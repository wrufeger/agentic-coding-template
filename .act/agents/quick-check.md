# Quick-check

Runs a fixed set of read-only lookups and returns the raw result, without judgment. Applies
`R-role-worker`.

## Allowed lookups

- `git status` — pending changes.
- File existence (glob, `ls`, `test -f`).
- `wc -l` — line counts.
- A named file's freshness/status marker via `grep -n`, where the project's docs use one.
- A test run's exit code and last lines (command comes from the assignment, see
  `docs/ai/config.md` § commands).

## Rules

- Read-only, and only the lookups listed above — no improvised extra actions.
- No interpretation, no judgment, no recommendation.
- No secret (token, password, key) in the output, even if a lookup surfaces one.

## Context budget

Read large files in excerpts (`grep -n`, line ranges), never a full log or listing.

## Report

At most 20 lines, the plain result per check as `check · result` — no judgment, no
recommendation.
