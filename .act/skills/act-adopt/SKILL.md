---
name: act-adopt
description: Use to start a new project from this one, or to adopt another project's docs or AI tooling (old or foreign template, own structure). Not for setting up the current folder - use act-setup.
---

# Adopt an existing project's material

A project that already has docs or AI tooling of its own goes through the steps below, a plan and an apply per
script, on branch `act-adopt`. Use this **instead of** `init.py --target <dir>` alone: `adopt.py --apply` runs
`init.py` itself. Every writing script has `--plan` (validates, changes nothing) and `--help` (actions per class, refusals,
what each mode does); the script's output, not this text, is the list. Nothing changes before the owner has
approved the table once (step 3); no script commits (step 8).

**Where it runs, against `<dir>`:** in a project (has `docs/ai/config.md` and `.act-lock.json`), called as
`/act-adopt`, from the project root; `<dir>` lies outside it, never the project or a folder inside it (also not via
symlink or junction). Or in the template checkout (no `.claude/skills/`, no root `AGENTS.md`): the assistant follows
`.act/skills/act-adopt/SKILL.md`, commands from the checkout root.

## 0. Which case, and what to carry

1. **Decide by `<dir>`** and say which case before running anything. Missing, or empty (nothing but `.git`) → **new
   project**: `python .act/scripts/init.py --target <dir>` (`--plan` first; `--non-interactive` without a terminal;
   from a project add `--carry <list>`; outside the project the owner starts it with the `!` prefix, as in
   step 1), then report what it printed and suggest `act-update` inside `<dir>`; the
   folder is the owner's. Any other content → **adoption**, steps 1-8.
2. **In a project only, what to carry over.** Ask once per category, default yes, after showing what this project
   has: `skills` (own skills in `docs/ai/local/skills/`), `rules` (`## Own rules`, `docs/project/coding_rules.md`),
   `exceptions` (rule groups switched off with a reason after ` — `; one without a reason is a stack default and
   stays behind), `overrides` (`replaces` lines and other files of `docs/ai/local/`), `topics`
   (`docs/ai/local/rules/topics/`). Answers become `--carry` (comma list; all yes = leave out; all no =
   `--carry none`; the owner's profile is separate, `--no-profile`). Only committed content travels, never `.env*`,
   symlinks or untracked files; what the new project cannot take goes to its inbox. The template checkout has nothing
   to ask. The new project gets this project's `.act/`, not the newest; its first `act-update` brings that.

**Three rules for every step:**

- **Who writes.** The orchestrator runs every script and writes every file in the project. A worker only reads the
  old material and writes batch, body and draft files under `<dir>/.act-local/adopt/`, nowhere else.
- **The human's wording stays.** Titles and bodies are the old text verbatim (step 6); never summarized, translated or
  reworded.
- **Local files stay local.** `CLAUDE.local.md`, `.mcp.json`, `.cursor/mcp.json`, `.claude/settings.json` and
  `.claude/settings.local.json` are `keep`; nothing from them is copied into a versioned file (no proposal, inbox
  entry or `body_file`).

## 1. Sight (read-only)

```bash
python .act/scripts/adopt_scan.py --target <dir>
```

Prints the table (`--json` the payload; `<dir>/.act-local/adopt/scan.json` is written either way) with each row's
class, `proposed` action and, for a project made from the previous template, `origin`. An existing structure of this
template is a source like any other, no shortcut.

A target outside the project root is protected by the `outside-root` guard (only where the hooks are installed): the
owner starts this first scan with the `!` prefix (`! python .act/scripts/adopt_scan.py --target <dir>`), since a `!`
command is no tool call. It leaves `.act-local/outside-allow/adopt.json`, which opens the target for 24 hours or until
`--abort`, also past `--finish` (steps 7-8 still reach it); `--apply` only refreshes a valid marker and never creates
one. The model's own call of the scan is reported beforehand as an access outside the project.

**Before step 2**, read out to the owner every `-- … --` info line, and read `references/sighting.md` when there is an
`origin`, a `.claude/template.json` or such a line.

## 2. Propose the table

Build `<dir>/.act-local/adopt/table.json`: `{"rows": [...]}`, one row per `scan.json` row (`path`, `class`, `action`
from `proposed`, plus `target`/`done`/`confirmed`/`note`). `proposed` is the start, not the decision: check each row
against `references/table-rules.md` (read it first), put the reason of every deviation into `note`. Actions are fixed
once `--apply` has run: a wrong action means `--abort` and a new table.

Validate before asking, as a **separate tool call** after writing `table.json` (one command doing both was refused by
the auto-mode classifier as a blind apply):

```bash
python .act/scripts/adopt.py --target <dir> --apply --plan
```

Fix what it refuses, then show the table with the origin column, not the raw JSON. When it refuses long legacy paths
on Windows (260 characters, Git fails without it), `git -C <dir> config core.longpaths true` changes the owner's
repository config: ask with the table, only on a yes.

## 3. Owner approves once

The whole table in one pass, no partial start; the owner may change any row, then validate again. Name every `adopt`
row without a target the plan warned about and ask whether to go on without targets; `core.longpaths` is part of the
same answer where needed. Nothing runs until the table is accepted as it stands.

## 4. Apply

**Settle the language first**: `init.py` writes the docs and its todos in it, so it must be known before `--apply`.
Take it from the sighting's `language hint: …` line; else propose the owner's language and let the owner confirm or
choose (chat language normally `auto`). Both options are recorded as fixed by the owner: step 5 never overrides them.

```bash
python .act/scripts/adopt.py --target <dir> --apply --plan --language-docs <code> --language-chat <code|auto>
python .act/scripts/adopt.py --target <dir> --apply --language-docs <code> --language-chat <code|auto>
```

From a project add `--carry <list>` to both. `--confirm-no-targets` only if the owner agreed in step 3, never on your
own. `mode` has no option (`init.py` derives it from the Git authors). `--apply` refuses a dirty tree, an existing
`act-adopt` branch and a detached HEAD, and records `<dir>/.act-local/adopt/state.json` (`moved`, `created`,
`dirty_after_apply`, …). After `stage-failed` or `init-failed` a second `--apply` is refused: fix the cause and
`--abort`.

## 5. Settings

`init.py` wrote `docs/ai/config.md` with defaults and said so in `docs/ai/inbox/U<n>-init-notes.md`.

```bash
python .act/scripts/adopt_config.py --target <dir> --plan   # the report, writes nothing
python .act/scripts/adopt_config.py --target <dir>          # write
```

It sets a key from an old `AI-CONFIG.md` or `.claude/template.json` only where the value is still a default; the rest goes
to `.act-local/adopt/config-report.md`. Then compare `docs/ai/config.md` with the old project by hand
and correct it: `tools`, `language-chat`, `language-docs`, `stack`, `commands`, `owner`, `mode`. It must be right
before steps 6 and 7: `--finish` chooses bridges by `tools` (no `claude-code` there removes an adopted `CLAUDE.md`),
and `mode` decides whether an entry without a kept id gets a new one (`solo`) or none yet (`team`). A command that names
a path the adoption removes is flagged: settle it with the owner. An old `AI-CONFIG.md` without a language row is
assumed `de`: confirm it with the owner.

## 6. Fill the content — one worker per target, never "all the docs at once"

While reading each old source, harvest what would help someone who never sees this project, cut (never retype) each
body, and write open items, board approvals and rule prose as one batch per worker for `adopt_entries.py`
(`--plan` first, one call at a time). Entries, titles, batches, harvest, ids: `references/content-entries.md`; passages
into `coding_rules.md` and `docs/README.md`, rules as overrides, moved docs, own skills and agents, recording `target`
and `"done": true`: its second half.

## 7. Finish

```bash
python .act/scripts/adopt.py --target <dir> --finish --plan
python .act/scripts/adopt.py --target <dir> --finish
```

It refuses while an `adopt` row is not `done`, has no target, a target is missing or unchanged, or an action differs
from `--apply`'s. It bridges adopted `ai-config` files, removes the other adopted sources and every `delete` row
(`git rm`), bends dead links, prunes settings entries on removed scripts, runs `doctor.py` and writes
`docs/ai/inbox/report-<timestamp>-adoption-report.md`. A failing Git call leaves state `applied`: fix the cause and rerun.

- **References:** the full list is `<dir>/.act-local/adopt/references.txt`. A path in backticks is text and is never
  changed; the orchestrator goes through every "mention in text" with the owner and changes it only on the owner's say.
- **Settings:** the report's own heading ("Remove it by hand, or check") lists entries it did not remove; the
  orchestrator settles them with the owner and edits `.claude/settings.json` in place; `settings.local.json` is the
  owner's to clean. Afterwards `python .act/scripts/doctor.py --target <dir>` reports 0 findings.
- **Harvest:** when `--finish` names `harvest.md`, read `references/harvest.md`; the owner's consent comes now.
- **Translate the scaffold in this same run** when `language-docs` is not `en`: translate every file listed in
  `docs/ai/inbox/U<n>-translate-scaffold.md` that still has `<!-- act:default -->` on line 1 (what carries it is pure
  scaffold), following the todo (`R-work-language`), drop that line, set the todo `status: done` and move it to
  `docs/ai/work/archive/`. Adopted content is never translated here.

## 7b. Baseline check — once, before the first commit

```bash
python .act/scripts/adopt_baseline.py --target <dir>
```

Read-only; it prints what it would add and book. Show the owner all of it; on the owner's yes:

```bash
python .act/scripts/adopt_baseline.py --target <dir> --write-gitignore --book
```

Count `<dir>/.gitignore` to commit group 2 and the new backlog entries to group 6 (step 8). A booked dangerous pattern
passes the first commit; **a secret finding keeps holding every attempt** until the value is removed (and rotated), the
line carries `act:allow-secret`, or it is listed in `docs/ai/local/secret-accepted.md` (the hold message prints the
entry). Tell the owner which applies per file; never accept a real secret. 

## 8. Commit — the orchestrator, by pathspec, on `act-adopt`

Commit by pathspec, one `git add -- <paths>` (existing paths only) and one `git commit -m "<message>" -- <paths>` per
group, never a git-ignored file (nothing under `.act-local/`). Read `references/commit-groups.md` for the six groups in
order and the check that every line of `git status --porcelain --untracked-files=all` falls under exactly one. Then
`git status` shows only git-ignored files; the owner reviews and merges `act-adopt`. From a project, suggest `act-update`
in the adopted one.

## Abort

```bash
python .act/scripts/adopt.py --target <dir> --abort --plan   # what it would do, or why it refuses
python .act/scripts/adopt.py --target <dir> --abort          # after --apply
python .act/scripts/adopt.py --target <dir> --abort --force  # saves changed files to .act-local/adopt/aborted/ first
```

A commit on `act-adopt` other than `init.py`'s refuses it even with `--force`: take those commits off first, the
refusal says how. It does not remove what was written after `--apply` by anything but `init.py` (entries, proposals,
copies under `docs/ai/local/`, the translate-scaffold todo): they are listed as "left in place"; move them to
`.act-local/adopt/aborted/` or delete them, and move `table.json` and `entries-map.json` aside, before a new attempt at
step 1. After `--finish` there is no `--abort`: check out the base branch and delete `act-adopt` by hand, after review.

## When not

The owner declines the rebuild: stop after step 1 and run `init.py --target <dir>` alone. There is no `docs/ai/config.md`
key for "the docs live at `<old location>`, not `docs/project/`": note that decision by hand (a line in the file's free
text, or an inbox entry), not as a setting that does not exist.
