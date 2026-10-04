---
name: act-deps
description: Update dependencies - inventory age and known gaps, bundle patch/minor, one commit per major after reading its changelog, checks green after every step. Use when dependencies are stale, a security advisory needs checking, or asked to update packages.
---

# Update dependencies

Brings the project's dependencies forward in traceable, revertible steps — never one bulk update.
Core rule: the test net comes before the jump; without it, a broken build after an update can't be
told apart from one that was already broken. Applies `R-code-commit` (green checks, pathspec
commit) and `R-work-config` (package manager and commands from `docs/ai/config.md` § Project).

## Schedule

Controlled by `dependency-check` in `docs/ai/config.md` (`never` · `once` · `regularly`, default
`once`): `once` leaves a one-time inbox entry right after `init` asking to run this once, then only
on demand; `regularly` instead gets a session-start note once the last run is more than 30
days old. A full run logs a journal entry titled `act-deps: ...` — that title is what both the
`init` entry and the `regularly` note check for, so a spot check of one package should title its
entry differently if it should not count as covering the whole check.

## Steps

1. Inventory age and gap: how far behind each dependency is, known advisories, whether an
   automated tool (Renovate/Dependabot) already proposes part of it — don't duplicate a running
   proposal.
2. Split: patch/minor bundle into one step; every major is its own step with its own commit, never
   combined.
3. **Propose before applying.** File the split from step 2 as an inbox entry — the patch/minor
   bundle plus one line per major — and wait for the human's answer before executing any of it;
   prepared, not applied, until then.
4. Before a major, read its changelog for breaking changes (`R-code-version`) instead of guessing;
   search affected call sites first (`explorer` role) when there's more than one.
5. Apply the step (`builder` role): bump the version, update the lockfile. A code change the
   update forces (e.g. a changed API) is its own commit after the version bump, never the same one.
6. Check before the step counts as done (`R-code-commit`): red means revert or fix now, not later.
7. `docs/ai/config.md` § Project → `commands` follows if a step changed the install/lint/typecheck/
   test command.
8. Close each step via `act-commit` as it lands, not once at the end.

## Larger updates

A major with real breaking changes: offer to help explicitly before starting — read the changelog
together, prepare the migration, and let the check run in step 6 stand as the proof.

## Limits

No bundled update across several majors. No dependency added that the actual task doesn't need. A
version bump and the code change it forces never share a commit. No step counts as done without
green checks, regardless of time pressure.

## Mechanism

`init.py` reads `dependency-check` from the config.md it just wrote and, for `once`, leaves the
one-time inbox entry above (`entries.write_dependency_check_note`, deduplicated across a second
`init` run). For `regularly`, `.act/hooks/checks/session.py`'s `_dependency_check_note` looks at
the ledger for the last `act-deps: ...` entry and notes at session start once it is more than 30
days old, or once only when there is none yet — same shape as the docs-audit note
(`docs-audit-due`), reusing its ledger scan (`_last_ledger_entry_with_prefix`).
