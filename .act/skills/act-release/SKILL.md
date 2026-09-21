---
name: act-release
description: Prepare a new release - check preconditions, pick a semantic version, generate a readable changelog from commits, tag it. Use when asked to prepare a release, publish a new version, or generate a changelog.
---

# Prepare a release

Prepares a new version: check preconditions, pick a version number, generate a readable changelog,
set the version, tag it. An automated release process (CI pipeline, semantic-release) gets
triggered, not rebuilt — this skill then covers only its preconditions.

1. **Check preconditions** — `git status` clean; required checks green (`docs/ai/config.md` §
   commands, plus E2E for UI-relevant changes); `docs/ai/work/backlog/` sighted for open critical
   points, which go to the human, never passed over silently.
2. **An automated release process exists:** stop here and trigger it.
3. **Pick the version** (`MAJOR.MINOR.PATCH`): a break with the existing interface/behavior is
   MAJOR, new backward-compatible functionality MINOR, a pure fix PATCH. An unclear break goes to
   the human as a question, not a guess.
4. **Generate the changelog** from the commits since the last tag (`git log <last-tag>..HEAD`) —
   readable, what users notice, features/fixes/breaking changes listed separately.
5. **Set the version in one place** and file the changelog — no other functional change in this
   commit.
6. **Commit and tag** — one commit for the version bump (`R-code-commit`), then the tag
   (`vX.Y.Z`).
7. **Record it** in `docs/ai/work/ledger/` (version, date, summary), then `act-commit` unless the
   tag commit already covers it.

No release on a red required check, not even "just this once."
