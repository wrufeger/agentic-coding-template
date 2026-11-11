---
name: act-release
description: Use when asked to prepare a release, publish a new version, tag a version or generate a changelog. Results in a tagged semantic version with a readable changelog from the commits. Not for ordinary commits - use act-commit.
---

# Prepare a release

Prepares a new version: check preconditions, pick a version number, generate a readable changelog,
set the version, tag it, and — after an explicit yes — publish the release entry on GitHub or GitLab.
An automated release process (CI pipeline, semantic-release) gets triggered, not rebuilt — this skill
then covers only its preconditions.

**Formats.** The layout of the changelog and of the release notes comes from the project's format files:
`docs/project/formats/changelog.md` and `.../release-notes.md` when they exist, otherwise the preset named by
`changelog-format` and `release-notes-format` in `docs/ai/config.md` § Formats, taken from
`.act/formats/changelog.md` and `.act/formats/release-notes.md` (a missing row, an empty value, `auto` or an unknown name is the default
preset). **Where the changelog goes** is the switch `changelog` there: `file` (default) writes it into
`CHANGELOG.md` in the project root; `release-notes-only` keeps no file; `off` keeps no changelog at all.
Say which of the three applies when you start, so the human sees where the text will land.

1. **Check preconditions** — `git status` clean; required checks green (`docs/ai/config.md` §
   commands, the full or E2E suite included); `docs/ai/work/backlog/` sighted for open critical
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
      Estimate: ~<n> min · ~<n> tkn fresh · ~<n> tkn cache · Cap: <n>`, then `Write scope: none` on a line
      of its own, since the check reads that line only at a line start (`R-cost-delegate`).
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
   readable, what users notice, features/fixes/breaking changes listed separately, in the layout of the
   changelog format; append the lower-severity checklist from step 3 (when it ran) under its own heading.
   - `changelog: file` — into `CHANGELOG.md`: with a format that collects entries as you go
     (`keep-a-changelog`), turn the `[Unreleased]` section into `[X.Y.Z] - <date>`, add what the commits show
     and the section lacks, check that its head line still says what the release is about (write one if it is
     missing), add 3 to 5 highlights (taking those entries out of the list), turn `### Upgrading` into
     `### Upgrading from <last tag>`, shorten entries over the format's limit, open a new empty `[Unreleased]`;
     with `at-release` write the whole section in that form. No
     `CHANGELOG.md` yet: create it from the starter of the changelog format first (`act-update` offers the file
     to older projects too).
   - `release-notes-only` — no `CHANGELOG.md`; write the notes in the release notes format and keep them in the
     tag message (step 7) and the release entry (step 9) only.
   - `off` — no changelog and no notes kept; the tag message is one line. Step 9 still needs a text, so it is
     written then, from the commits, in the release notes format, and only when the human asks for the entry.
6. **Set the version in one place** and file the changelog (`CHANGELOG.md` is part of this commit) — no other
   functional change in this commit.
7. **Commit and tag** — one commit for the version bump (`R-code-commit`), then the tag
   (`vX.Y.Z`). With a message file use `git tag -a --cleanup=verbatim -F <file>`: the default
   cleanup drops every line starting with `#`, i.e. all Markdown headings. Before any push compare
   `git for-each-ref refs/tags/<tag> --format="%(contents)"` with the file.
8. **Record it** in `docs/ai/work/ledger/` (version, date, summary), then `act-commit` unless the
   tag commit already covers it.
9. **Publish the release entry** (GitHub or GitLab; last step, after the tag is made).
   1. **Skip it** when the project's own pipeline already creates releases — step 2 found one, or one of these
      exists: a semantic-release or release-please configuration (`.releaserc*`, `release.config.*`, a
      `release` key or the dependency in `package.json`, `release-please-config.json`), a CI workflow that runs
      on a pushed tag and creates the release (`gh release create`, `softprops/action-gh-release`,
      `actions/create-release`, a GitLab job with a `release:` keyword). Name the file that made you skip and
      stop; publishing twice would fail or duplicate.
   2. **Access** — read the flow in `.act/rules/topics/live-systems.md` ("Repo host and issue tracker") before
      the first write; access as in `act-pr` step 1.
   3. **Push** — the tag must be on the remote before the entry is made, or the host would create it at the
      head of its default branch. Ask "push the version commit and tag `<tag>` to `<remote>`?" and push only
      after the human's own "yes" (never a worker).
   4. **Text** — write the notes to a file under `.act-local/` (never into the repo): with `changelog: file`
      the changelog section of this version (a `changelog-copy` format) or the notes in the release notes
      format built from it; title `<project name> X.Y.Z` unless the format says otherwise.
   5. **Preview** — `python .act/scripts/forge.py create-release --tag <tag> --title "<title>" --body-file
      <file> --show-body` without `--apply` sends nothing and shows what would be sent. A tag with a
      pre-release suffix (`-rc.1`, `-beta`) is published as a pre-release by itself (GitLab has no such flag;
      the preview says so). The preview also names the tag check that `--apply` runs first. Show it, then offer:
      **publish** · **cancel**.
   6. **Publish** — after the "yes" for exactly this preview: the same command plus `--apply` (after a local
      `git ls-remote` for the tag; a tag not on the remote stops the run with exit 2, so push it and run again).
      Way back: `live-systems.md`.
   7. **Verify and record** — `forge.py releases --limit 5` lists the tag with the right title; show the link;
      journal entry.
   On a `forge.py` failure the release stays unpublished; tag and changelog are not undone.

No release on a red required check, not even "just this once."
