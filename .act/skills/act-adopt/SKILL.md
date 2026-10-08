---
name: act-adopt
description: Use when a project already has its own docs or AI tooling, or when asked to adopt or migrate an existing project's docs or AI tooling (old template, foreign template, homegrown structure). Takes it over in eight steps instead of a plain init.py --target. Not for an empty folder - use act-setup.
---

# Adopt an existing project's material

Every structure a project can already have — a previous version of this template, a different
template, or something the project made up on its own — goes through the same eight steps. Use
this **instead of** running `init.py --target <dir>` alone whenever the project already has docs
or AI tooling of its own: `adopt.py --apply` (step 4) runs `init.py` itself once the table is
approved, so running it separately first would only mean redoing that step.

**How to start it.** This skill runs from a checkout of this template, against the project at
`<dir>`. The checkout has no `.claude/skills/` and no root `AGENTS.md`, so the skill cannot be
called by name there: open the checkout in the assistant and have it follow
`.act/skills/act-adopt/SKILL.md` for the project path. Every command below runs from the checkout
root, `--target <dir>` pointing at the project. Nothing changes before the owner has approved a
table once (step 3); no script commits anything (step 8).

**Three rules for every step:**

- **Who writes.** The orchestrator runs every script and writes every file under `<dir>/docs/ai/`
  and elsewhere in the project. A worker only reads the old material and writes batch, body and
  draft files under `<dir>/.act-local/adopt/` — nowhere else.
- **The human's wording stays.** A title is the old heading verbatim with only its bullet/heading
  marker, bold markers, a status emoji and the old id stripped (step 6 says what counts as the
  heading where an item has none); a body is the old text verbatim. Never summarized, translated
  or reworded.
- **Local files stay local.** `CLAUDE.local.md`, `.mcp.json`, `.cursor/mcp.json`,
  `.claude/settings.json` and `.claude/settings.local.json` are `keep`, and nothing from them is
  copied into a versioned file — no proposal, no inbox entry, no `body_file` cut from them.

## 1. Sight (read-only)

```bash
python .act/scripts/adopt_scan.py --target <dir>
```

Classifies every documentation and AI-tool source into `ai-config`, `ai-machinery`, `work`, `log`,
`project-doc`, `predecessor` or `unknown` (exact allow-list in the script's own `--help`), writes
`<dir>/.act-local/adopt/scan.json`, and prints a human-readable table (`--json` prints that
payload instead — the file is written either way). Changes nothing. An existing skeleton-like
structure found here (a previous run of this template) is a source to sight like any other, not a
shortcut around the rest of the steps.

Rows carry `proposed` (the action the table starts from) and, for a project made from the previous
template, an `origin`. **Before step 2**, when the sighting printed `-- … --` info lines, a row with an
`origin` or a `.claude/template.json` first line, read `references/sighting.md` (origins, the predecessor
template's files, and the hints to read out to the owner).

## 2. Propose the table

Build `<dir>/.act-local/adopt/table.json`: `{"rows": [...]}`, exactly one row per `scan.json` row
(`adopt.py` refuses on a mismatch, in either direction), each row `path` and `class` as in
`scan.json`, `action` from the row's `proposed`, plus `target`/`done`/`confirmed`/`note` where
needed. `proposed` is where the table starts, not the decision: check it against the rules below
and put the reason for every row that deviates into its `note`.

For the rules behind each proposed action, the own-or-predecessor check of every `origin` row, foreign
ids with this template's prefixes, fixed targets and which rows need `"confirmed": true`, read
`references/table-rules.md` before filling the table. Actions are fixed once `--apply` has run: a wrong
action means `--abort` and a new table.

**Validate before asking for approval, not after:**

```bash
python .act/scripts/adopt.py --target <dir> --apply --plan
```

It checks the whole table (plus what needs the disk: existence, links, untracked files, a stale
scan, and on Windows the length of every legacy path) and changes nothing. Fix what it refuses,
then present the table for step 3 — as a table with the origin column, not the raw JSON. Write
`table.json` and run this dry run as two separate tool calls: one command doing both was refused
by Claude Code's auto-mode safety classifier as a blind apply.

**Windows: long paths.** A legacy path is the old path plus `docs/ai/work/archive/legacy/`; at 260
characters or more Git fails on it unless the repository sets `core.longpaths`. `--apply --plan`
refuses then and names the longest paths. Setting it is a change to the owner's repository
config, so ask with the table in step 3, and only on a yes:

```bash
git -C <dir> config core.longpaths true
```

## 3. Owner approves once

The whole table, one pass — no partial start. If `--apply --plan` warned about `adopt` rows without
a target, name those rows in the same approval and ask whether to go on without targets for them. The owner may change any number of rows; nothing
runs until the table is accepted as it stands (or after those corrections, validated again).
`core.longpaths` (step 2) is part of the same answer where it is needed.


## 4. Apply

**Settle the language first.** `init.py` writes `docs/ai/config.md` in the docs language and
gives its own todos (`dependency-check`, `security-check-deps`, `init-notes`) titles in it (their
bullet points stay English), and a `translate-scaffold` note is only written for a language other than English — so the language has
to be known before `--apply`, not after step 5. Take it from the sighting's `language hint: …` line
(an old `AI-CONFIG.md`); with no such line, propose the owner's language after `R-human-language`
(the chat language, remembered per machine, else recognized from the owner's own messages) and
let the owner confirm or choose another one. The chat language is normally `auto`. Then pass both:

```bash
python .act/scripts/adopt.py --target <dir> --apply --plan --language-docs <code> --language-chat <code|auto>
python .act/scripts/adopt.py --target <dir> --apply --language-docs <code> --language-chat <code|auto>
```

`--plan` first, changes nothing. Pass `--confirm-no-targets` only
if the owner agreed to it in step 3, never on your own. Both options go straight to `init.py --target` and are recorded in
`state.json` as fixed by the owner: step 5 never overrides them, whatever the old `AI-CONFIG.md` says
(its report row reads "kept: set at --apply"). Without them `init.py` writes English, and step 5 can
still set `language-docs` from an old `AI-CONFIG.md`. The `mode`
has no option here: `init.py` derives it from the Git authors (step 5).


When `--apply` refuses or fails, or to see what `state.json` records, read
`references/apply-details.md`.

## 5. Settings — check `docs/ai/config.md` before anything else

`init.py` ran non-interactively, so `docs/ai/config.md` holds its defaults: `name` the folder
name, `owner` the Git `user.name` (else `unknown`), `language-chat`/`language-docs` what step 4
passed (else `auto`/`en`), `stack` `unspecified`, empty `commands`, `tools` `claude-code`, `mode`
`solo` or `team` from the number of distinct real author e-mails (placeholder and test identities
left out). It says so in `docs/ai/inbox/U<n>-init-notes.md` ("Project config uses
defaults for: ..."); `adopt_config.py` takes every key it sets out of that line afterwards, and
removes the note when nothing is left in it.

```bash
python .act/scripts/adopt_config.py --target <dir> --plan   # show the report, write nothing
python .act/scripts/adopt_config.py --target <dir>          # write
```

Read `references/config-adoption.md` when the project has an old `AI-CONFIG.md` or `.claude/template.json`,
and for the hand comparison of `docs/ai/config.md` (`tools`, `language-chat`, `language-docs`, `stack`,
`commands`, `owner`, `mode`) that has to be right before steps 6 and 7.

## 6. Fill the content — one worker per target, never "all the docs at once"

While reading every old source, harvest what would help someone who never sees this project; then cut
(never retype) each body from the old source, and write open items, board approvals and rule prose as
one batch file per worker for `adopt_entries.py` (`--plan` first, one call at a time).

- Harvest, where to read, cutting bodies, titles and batch kinds: `references/content-entries.md`.
- Passages into `docs/project/coding_rules.md` and `docs/README.md`, rules as overrides or own rules,
  moved docs, own skills and agents, and recording `target` and `"done": true` in `table.json`:
  `references/content-files.md`.

## 7. Finish

```bash
python .act/scripts/adopt.py --target <dir> --finish --plan
python .act/scripts/adopt.py --target <dir> --finish
```

Refuses while an `adopt` row is not `done`, has no target, a target is missing, any recorded
target is still unchanged since `--apply`, or an action differs from `--apply`'s. Then: adopted
`ai-config` files `init.py` has a bridge for become that bridge (`AGENTS.md` always, `CLAUDE.md`
with `claude-code` in `tools`); other adopted sources and every `delete` row are removed
(`git rm`); an own skill or agent under `docs/ai/local/` gets its tool copies/role bridge as
`act-load-settings` writes them. A failing Git call stops it with the state left at `applied`;
fix the cause and run the same `--finish` again. A second `--finish` after success says "already
finished".

Read `references/finish-details.md` for what `--finish` does after that (settings entries on removed
scripts, the `act:default` mark, dead references) and for the check of the result with
`doctor.py --target <dir>`. When `--finish` names `<dir>/.act-local/adopt/harvest.md`, read
`references/harvest.md` — the owner's consent comes now, not before.

## 8. Commit — the orchestrator, by pathspec, on `act-adopt`

`adopt.py` never commits. Each group below is one `git add -- <paths>` (only paths that exist)
and one `git commit -m "<message>" -- <paths>` (all of them). A path `--apply` or `--finish`
removed is already staged as a removal: `git add` fails on it ("did not match any files"),
`git commit -- <path>` takes it. A git-ignored file is never added — not with `-f` either: nothing
under `.act-local/`, no `__pycache__/` (`created` lists none). In this order:

1. **Legacy moves** — `docs/ai/work/archive/legacy` plus the old paths in `state.json`'s `moved`
   that are no longer on disk (staged as renames by `--apply`, nothing to add). A moved path that
   `init.py` filled again is not a rename; it belongs to group 2 or 3.
2. **The template layer** — every path in `state.json`'s `created` and `dirty_after_apply`, plus
   the `removed_at_apply` paths; except anything under `.act-local/` (git-ignored) or
   `docs/ai/work/archive/legacy/`, group 1's paths, and table targets. That is `.act/`, bridges,
   skeleton, tool copies, `.act-lock.json`, the init notes in the inbox together with
   `docs/ai/inbox/U<n>-translate-scaffold.md` from step 5 (both are about the scaffold, not
   about old content; step 5 may have changed the init notes), `.gitignore`, the template copies
   now standing where an old unit of the same name was moved or removed (with the removal of that
   unit's other files), and `.claude/settings.json` as it is now — `init.py`'s merged hooks and
   the entries `--finish` or the orchestrator removed in step 7 in one commit, since a pathspec
   commit always takes the whole file (the report lists the removed entries).
3. **One commit per target** — an `adopt` row's `target` files (entries, proposals,
   `docs/ai/config.md`, `docs/project/coding_rules.md`, `docs/README.md`,
   `docs/ai/local/<unit>`); for a `legacy` row, the entry files `entries-map.json` lists under its
   `source_path` (they are nobody's table target, so they are easy to miss). A path that is both
   moved and a target — `docs/README.md` or `docs/project/coding_rules.md` adopted into itself —
   goes here with its source, not into group 1 or 2 (its legacy copy is in group 1). Where several
   sources feed one target (five `project-doc` files into `docs/project/architecture.md`, several
   work files into the same entry set), that is one commit for the target, not one per source —
   name the sources in its message. Rows without a shared target stay one commit each.
4. **What `--finish` did** — `state.json`'s `bridged` and `removed_at_finish` paths, the tool
   copies it printed for own units (`skills: <path>: created`, role bridges), and the adoption
   report (`state.json`'s `report`).
5. **References and the docs index** — the files under `docs/project/`, and `docs/README.md`, whose links `--finish`
   bent: `git -C <dir> status --porcelain -- docs/project docs/README.md` lists them as modified;
   one that already belongs to group 2 or 3 (a table target, a file `init.py` wrote) stays there.
   `--finish` only bends links: **a new `docs/project/` target gets no line in the docs index
   `docs/README.md`** — add one per new file by hand, or in `act-commit` step 5 ("Docs index: new
   files go into `docs/README.md`"), before this commit, and count `docs/README.md` here.

Before the first commit, check the grouping: every line of
`git status --porcelain --untracked-files=all` (both sides of a rename) falls under exactly one
group. Afterwards `git status` shows nothing but git-ignored files; the owner reviews
`act-adopt` and merges it.

## Abort

```bash
python .act/scripts/adopt.py --target <dir> --abort --plan     # what it would do, or why it refuses
python .act/scripts/adopt.py --target <dir> --abort            # after --apply
python .act/scripts/adopt.py --target <dir> --abort --force    # saves changed files first
```

When `--abort` refuses, or files were written after `--apply`, read `references/abort-details.md`. There
is no `--abort` once `--finish` has run — undo means checking out the base branch and deleting
`act-adopt` by hand, after reviewing it.

## When not

The owner declines the rebuild: stop after step 1 (the read-only sight only) and run
`init.py --target <dir>` alone. **Gap:** `docs/ai/config.md` has no key today for "the project's
docs live at `<old location>`, not `docs/project/`" — until one exists, note that decision by hand
(a line in `docs/ai/config.md`'s free text, or an inbox entry) rather than pointing at a setting
that isn't there.
