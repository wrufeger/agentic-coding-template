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
3. **`security-check: full` only — the deep scan (Art C, before tagging):**
   1. Run `python .act/scripts/security_deep.py` (files changed since the latest tag). Exit 3
      means Semgrep is not installed — note this once with the install command its own output
      names, and go on without Art C (never install it unasked, `R-code-tools`); list the skip in
      the release checklist (step 5) so it stays visible. Exit 4 means the run itself failed
      (timeout, unparsable output, a Semgrep error) — treat this like a finding: it blocks the
      release the same as step 3.3 below, until fixed or explicitly accepted.
   2. Start a security pass of the `reviewer` role over the same changed files: `Tier: elevated ·
      Estimate: <scope/duration> · Cap: <n> · Write scope: none` (`R-cost-delegate`).
   3. A finding of severity ERROR/high (from either step) blocks the release until it is either
      fixed, or explicitly accepted with a reason in `docs/ai/local/security-accepted.md` — one
      line per accepted Semgrep finding, `<rule-id> <path>: <reason>` (advisory ids from the
      library-vulnerability check use their own line form, defined where that check lives). No
      code reads this line for a Semgrep finding — this skill step does, i.e. whoever (assistant
      or human) runs this release checks the file by hand before treating a finding as accepted.
   4. A lower-severity finding is not a blocker — list it in the release notes as a checklist item
      instead.
   Skip this step entirely (not even a no-op run) when `security-check` is anything other than
   `full` — Art C is on request and before a release, never implied by a lower level.
4. **Pick the version** (`MAJOR.MINOR.PATCH`): a break with the existing interface/behavior is
   MAJOR, new backward-compatible functionality MINOR, a pure fix PATCH. An unclear break goes to
   the human as a question, not a guess.
5. **Generate the changelog** from the commits since the last tag (`git log <last-tag>..HEAD`) —
   readable, what users notice, features/fixes/breaking changes listed separately; append the
   lower-severity checklist from step 3 (when it ran) under its own heading.
6. **Set the version in one place** and file the changelog — no other functional change in this
   commit.
7. **Commit and tag** — one commit for the version bump (`R-code-commit`), then the tag
   (`vX.Y.Z`).
8. **Record it** in `docs/ai/work/ledger/` (version, date, summary), then `act-commit` unless the
   tag commit already covers it.

No release on a red required check, not even "just this once."
