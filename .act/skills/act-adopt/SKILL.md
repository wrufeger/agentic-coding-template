---
name: act-adopt
description: One-time takeover of an existing project's docs and AI tooling into this template's layout - old template, foreign template, or a homegrown structure, all through the same path. Use instead of a plain init.py --target whenever the project already has its own docs or AI tooling, or when asked to adopt/migrate an existing project's docs/ai-tooling.
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

Every row carries `proposed`, the action the table starts from (`-> <action>` in the table;
rules under `PROPOSED ACTION` in `--help`). A project made from the previous template has a
`.claude/template.json`; then the first line names its `base_commit` and whether it is in the
history, the previous template's own files that fit no other class are `predecessor` (its
`docs/ai/README.md`, `checklists.md`, `config-guide.md`, `ai-config-hilfe.md`, `resources.md`,
`template-feedback/`, `.claude/mcp-katalog.md`, `.mcp.json.example` and whatever else its
`base_commit` holds), and every row carries an `origin` (`[...]` in the table):

- `template only` — every line is the predecessor's own, after putting in the placeholder values
  of `template.json` § `values`. Replacing `{{PROJEKTNAME}}` by the project name is no text of its
  own.
- `own text: n lines` — n lines the base text does not have, `(not in the predecessor template)`
  for a file the project added.
- `unknown (base_commit not reachable)` — the commit is not in the history (a shallow clone, a
  squashed import); nothing can be told apart mechanically.

ADR folders (`adr/`, `adrs/`, `decisions/`, `decision-records/`) are `project-doc`; a dated file
(`YYYY-MM-DD…`) in `journal(s)/` or `docs/journal(s)/` is `log`.

## 2. Propose the table

Build `<dir>/.act-local/adopt/table.json`: `{"rows": [...]}`, exactly one row per `scan.json` row
(`adopt.py` refuses on a mismatch, in either direction), each row `path` and `class` as in
`scan.json`, `action` from the row's `proposed`, plus `target`/`done`/`confirmed`/`note` where
needed. `proposed` is where the table starts, not the decision: check it against the rules below
and put the reason for every row that deviates into its `note`.

**Own or the predecessor's — before the approval, not after.** Every row with an `origin` gets
this check before the table goes to the owner. Two earlier runs had to go back with
`--abort --force` because `CLAUDE.md` and `AGENTS.md` stood on `adopt` although they held nothing
of their own:

- `template only`: nothing to take over. An `ai-config` file goes `legacy`, a unit of the
  predecessor `delete`; `adopt` would leave step 6 without content, and `--finish` refuses an
  `adopt` row whose target never changed.
- `own text: n lines`: read those lines first —
  `git -C <dir> diff <base_commit> HEAD -- <path>`, its `+` lines, minus a pair that only puts a
  placeholder value in (the scan already leaves those out of n). Rules or content of the
  project's own keep `adopt` for an `ai-config` file (they become proposals in step 6); lines that
  are no rule (a date, a filled-in example, a line the owner deleted from the template) mean
  `legacy`, with the reason in `note`. A `delete` proposal on a row with own text becomes `keep`
  where those lines are the project's (its own servers in a predecessor's `.mcp.json.example`, say
  — the scan proposes `delete` for that tooling whatever its origin).
- `unknown (base_commit not reachable)`: compare with a checkout of the predecessor template at
  that state before deciding; the proposal is `adopt`/`keep` there, never a blind `delete`.

The same diff separates the project's own rule prose from the predecessor's text in step 6.

Why the proposals are what they are, and where to deviate:

- `log` -> `legacy` (protocols are kept byte-identical, never reinterpreted).
- `work` -> `legacy`. The file moves byte-identical to `docs/ai/work/archive/legacy/<old path>`,
  done items included; its open items become single entries with their old ids in step 6, read
  from that legacy copy. `adopt` would remove the file at `--finish` (`git rm`), so done items
  would survive only in the Git history — propose `adopt` only for a work file whose entire
  content becomes entries (nothing done, nothing else in it).
- `project-doc` -> `keep`, a foreign root `README.md` too: `init.py` never replaces it and an
  `adopt` into it is refused. `adopt` only where the file has to move:
  - it sits where `init.py` writes a file itself (`docs/project/coding_rules.md`,
    `docs/README.md`): `--apply` moves the old file to legacy first, `init.py` writes the
    template's version, and step 6 merges the old content into it — `target` is the same path
    (`legacy` instead when its origin is `template only`). With `keep`, `init.py` leaves the old
    file in place and writes no template version.
  - it lives outside `docs/project/` and belongs there: `target` is the new path, step 6 copies
    the file there byte-identical, and `--finish` removes the source (`git rm`).

  Never `adopt` a doc into itself anywhere else: `adopt.py` refuses a target equal to its own
  source, and an `adopt` row with an empty target still passes `--apply --plan` — after `--apply`
  the only ways on are moving it (the source is removed) or `--abort`.
- `ai-config` -> `adopt` for `CLAUDE.md`, `AGENTS.md`, `AI-CONFIG.md` and other tool rule files
  (`GEMINI.md`, `.github/copilot-instructions.md`, `.cursorrules`, ...) that hold content of their
  own; `legacy` for one that holds none (`template only`, or only "see AGENTS.md") — an `adopt`
  row there would have nothing to take over. Never `delete` `AGENTS.md` or `CLAUDE.md`: `init.py`
  does not write their bridge while the old file stands, and `--finish` bridges only `adopt` rows,
  so the project would end up without one (`legacy` moves the file before `init.py`, which then
  writes the bridge). `keep` for the local files named above; the scan marks the
  personal/ignored ones "never bridge" or "git-ignored/local", and `adopt.py` refuses
  `delete`/`legacy` on those and an `adopt` into a bridge file, but not an `adopt` into, say, a
  proposal — the rule above is the real safeguard. `.claude/settings.json` stays `keep`:
  `init.py` merges its hook entries into it (backed up first), the project's own entries stay. A
  predecessor's `.claude/settings.local.json.example` is `delete`.
- `ai-machinery` -> `delete` for every unit that is `template only` — a previous template's own
  skills, agents, scripts and hooks (on branch `act-adopt`, so nothing is lost for good).
  `adopt` for the project's **own** skills and agents, with the target
  `docs/ai/local/skills/<name>` or `docs/ai/local/agents/<name>.md` (`<name>` must not be one of
  the template's own units — `--finish` refuses that). Own **scripts and hooks**, and a
  predecessor's script the project changed, stay `keep` for now: there is no target for them yet
  (`--finish` bridges skills and agents only), and a moved or deleted hook script breaks the
  command that calls it from `.claude/settings.json`.
- `predecessor` -> `legacy` for its documents (they stay readable in the archive; own lines in
  them show in the origin, and a rule still in force among them becomes a proposal in step 6),
  `delete` for its tooling (`.mcp.json.example`, `.claude/mcp-katalog.md`, anything that is no
  document).
- `unknown` -> `keep`.

`.claude/template.json` is not a scan row and gets no table row (`adopt.py` refuses a row that is
not in `scan.json`): it stays where it is, and `adopt_config.py` reads its values in step 5.

**Targets now, where they are fixed.** Fill `target` in this step whenever the destination is
already known — `docs/project/coding_rules.md` and `docs/README.md` as above, `docs/ai/config.md`
for the old `AI-CONFIG.md`, the `docs/ai/local/...` path of an own skill or agent. `--apply`
records what each target that exists at that moment looks like, and `--finish` refuses when any
recorded target is still unchanged ("content not adopted?"); a target added after `--apply` is
never checked that way. Leave `target` empty only where the file name is chosen at write time
(entry and proposal files, step 6).

**Actions are fixed once `--apply` has run**: `--finish` refuses every row whose action differs
from the one recorded then ("action changed since --apply"). Only `target` and `done` may change
afterwards; a wrong action means `--abort` and a new table.

Check every row against `adopt.py --help` (`ALLOWED ACTIONS PER CLASS` and `REFUSED`): `unknown`
rows other than `keep`, `delete` on a `project-doc`, a unit folder holding untracked or
git-ignored files, and anything below a source/test/content tree (`src`, `app`, `lib`, `test*`,
...) need `"confirmed": true`. **A link, or anything below one, may only be `keep`** — there is no
`confirmed` for that.

**Validate before asking for approval, not after:**

```bash
python .act/scripts/adopt.py --target <dir> --apply --plan
```

It checks the whole table (plus what needs the disk: existence, links, untracked files, a stale
scan, and on Windows the length of every legacy path) and changes nothing. Fix what it refuses,
then present the table for step 3 — as a table with the origin column, not the raw JSON.

**Windows: long paths.** A legacy path is the old path plus `docs/ai/work/archive/legacy/`; at 260
characters or more Git fails on it unless the repository sets `core.longpaths`. `--apply --plan`
refuses then and names the longest paths. Setting it is a change to the owner's repository
config, so ask with the table in step 3, and only on a yes:

```bash
git -C <dir> config core.longpaths true
```

## 3. Owner approves once

The whole table, one pass — no partial start. The owner may change any number of rows; nothing
runs until the table is accepted as it stands (or after those corrections, validated again).
`core.longpaths` (step 2) is part of the same answer where it is needed.

## 4. Apply

```bash
python .act/scripts/adopt.py --target <dir> --apply --plan   # dry run first, changes nothing
python .act/scripts/adopt.py --target <dir> --apply          # branch act-adopt, then run it
```

Refuses on an existing `act-adopt` branch, a detached HEAD, or a working tree that is not clean
(only `.act-local/` may be untracked). Creates and switches to `act-adopt`, backs up
`.claude/settings.json`, moves every `legacy` row byte-identical to
`docs/ai/work/archive/legacy/<old path>` — and there too every `adopt` row that sits where
`init.py` writes a file itself or carries the name of a template skill/agent (a `keep` row at
such a place stays and `init.py` leaves it; a `keep` row colliding by skill/agent name moves; a
`delete` row there is removed right away) — then runs
`init.py --target <dir> --non-interactive --no-commit` and stages the moves. `CLAUDE.md` and
`AGENTS.md` stay in place until `--finish`. `<dir>/.act-local/adopt/state.json` records the
result: `moved` (old path -> legacy path), `removed_at_apply` (`delete` rows removed before
`init.py`), `created` (the files `init.py` wrote where nothing was versioned before — never a
git-ignored one; those are in `created_ignored`, for `--abort` only), `dirty_after_apply` (every
versioned file that differs from the start: the moves, and what `init.py` wrote over versioned
paths — `.gitignore`, a moved or removed place it filled again), and the hash of each target that
existed. The accounting counts a legacy copy only when it is on disk **and** in the Git index.

Run again after success, it prints the recorded state and exits 0. Any failing Git call stops the
run without an accounting: state `stage-failed` (the moves could not be staged) or `init-failed`
(`init.py` itself failed). A second `--apply` is refused then — the way back is `--abort`, not a
retry; fix the cause (a path too long: `core.longpaths`, step 2) and start again at step 1.

## 5. Settings — check `docs/ai/config.md` before anything else

`init.py` ran non-interactively, so `docs/ai/config.md` holds its defaults: `name` the folder
name, `owner` the Git `user.name` (else `unknown`), `language-chat` `auto`, `language-docs` `en`,
`stack` `unspecified`, empty `commands`, `tools` `claude-code`, `mode` `solo` or `team` from the
number of distinct real author e-mails (placeholder and test identities left out). It says so in
`docs/ai/inbox/<date>-init-notes.md` ("Project config uses defaults for: ...").

```bash
python .act/scripts/adopt_config.py --target <dir> --plan   # show the report, write nothing
python .act/scripts/adopt_config.py --target <dir>          # write
```

It reads the old `AI-CONFIG.md` (at its place, or its legacy copy; `--source <file>` for another
one) and the old `.claude/template.json` values, and sets known keys in `docs/ai/config.md` only
where the value is still an `init.py` default — a value already set is reported, never
overwritten. The old `Coding-Guidelines` list checks those rule sets (plus what their `requires:`
pulls in) with their group lines in `docs/project/coding_rules.md`; that is no merge of the old
coding rules — step 6 still does that. Everything else — unknown keys, values without a
counterpart, every free-text passage with its line numbers — lands in
`<dir>/.act-local/adopt/config-report.md` (no title of its own: the inbox entry of step 6 gives
it one). It also brings the init notes up to date (`for:` the adopted owner, a section naming what
it set). Without any old configuration (no `AI-CONFIG.md`, no `template.json` values) it prints
"nothing to adopt" and exits 0 — the normal case for a project that never used the old
template; there is no report and no config inbox item then.

Then compare `docs/ai/config.md` with the old project by hand and correct it (orchestrator):
`tools`, `language-chat`, `language-docs`, `stack`, `commands`, `owner`, `mode`. A lint,
typecheck or test command that names a path the adoption removes (a predecessor script on
`delete`/`legacy`) is set as given and flagged in the report ("command refers to a path that the
adoption removes"): settle it with the owner — drop it, or point it at what replaces it.
`adopt_config.py` sets `language-docs` from the old template's `Sprache` row (`Deutsch` -> `de`);
an old `AI-CONFIG.md` without any language row gets `de` too, marked as an assumption in the report
(the old template was always German) — confirm it with the owner. It never sets `language-chat`
(stays `auto`) or `mode`. A `language-docs` other than English leaves
`docs/ai/inbox/<date>-translate-scaffold.md` (from `adopt_config.py`, or from you by hand if you
set it yourself: `init.py` wrote the scaffold in English, marked `act:default`) — translate that
scaffold once as `R-work-language` describes, never the adopted content, whose translation is a
separate assignment offered in the report, done only on request. This has to be right before
step 6 and 7: `--finish` chooses the bridges by `tools` (without `claude-code` there, an adopted
`CLAUDE.md` is removed instead of becoming the bridge), and `mode` decides whether an entry
without a kept id gets a new id now (`solo`) or none yet (`team`).

## 6. Fill the content — one worker per target, never "all the docs at once"

**Where to read.** The old content of a row that `--apply` moved is no longer at its `path` (at a
place `init.py` writes itself, the file there is now the template's version): `state.json`'s
`moved` map says where it is (`docs/ai/work/archive/legacy/<old path>`, byte-identical, same line
numbers). Everything else is still at its `path`.

**Cut, don't retype.** Every `body` goes in as `body_file`, a file cut mechanically from the old
source — never text written out by the model, which is retyping however it is done:

```bash
mkdir -p <dir>/.act-local/adopt/bodies
sed -n '<first>,<last>p' <dir>/<source file> > <dir>/.act-local/adopt/bodies/<name>.md
```

(or a byte slice in Python; several spans of the same file may go into one body, in their
order). A cut that starts at line 1 must leave out a leading BOM (U+FEFF), which `sed` would copy
along: slice the bytes from after `EF BB BF` instead. The `--plan` run below prints every title;
compare them with the old headings before writing.

**What counts as the heading.** Title and body per shape of the old item — the body never loses
text, so where the title line holds more than the title, the body starts with that line:

| Old item | Title | Body |
| :--- | :--- | :--- |
| a heading or a bold line (`### T12 · …`, `**Q3 · …**`) | its text | the lines below it, up to the next item |
| a bullet or checkbox without a heading (`- [ ] **T12 · …** — …`, a board list) | the bold lead, else the text up to the first ` — ` or `: ` | the whole bullet with its indented continuation lines |
| a backlog table row | the cell of the title column (`Titel`, `Title`) | the table's header and separator line, the row, then its detail section (`### B12 …` with the heading, up to the next heading of the same or a higher level) where the file has one |
| rule prose without a heading of its own | its first sentence, up to `. `, `: ` or the line end | the passage |

A title never carries the old id, bold markers or a status emoji (🔴, 🟡, ✅, ⏳, ⚠️, …) — the
emoji and the space next to it go, every other character stays. No two items of a batch get the
same title: where a passage starts with a sentence that is already a title, its next sentence is
the title. A link into the old file (`[Details](#b12)`) stays as it is in the body: rewriting it
would change the human's text, and a detail section cut into the same body brings its heading,
and so its anchor, along.

**Open items, board approvals, proposals — one batch file per worker, one call at a time:** each
worker writes its own `<dir>/.act-local/adopt/batch-<source>.json` (e.g. `batch-tasks.json`,
`batch-claude.json`), never a shared file; the orchestrator runs them one after the other, each
first with `--plan` (the map collects every run's files):

```bash
python .act/scripts/adopt_entries.py --target <dir> --from <dir>/.act-local/adopt/batch-<source>.json --plan
python .act/scripts/adopt_entries.py --target <dir> --from <dir>/.act-local/adopt/batch-<source>.json
```

Batch items (a JSON list): `kind` (`task`|`backlog`|`question`|`inbox`|`proposal`), `title`,
`source` (`"<table path>:<line>"` — the row's own `path` and the heading's line; for a moved row
the line in the legacy copy is the same), and optionally `id`, `formerly`, `body_file`, `status`
(question/inbox), `for` (inbox). `for` is the recipient: the person who has to act on the entry
— answer, decide or carry it out —, not the one waiting for the result; `all` when no single
person is meant. Per kind:

- **Open tasks, backlog items, questions** from `work` rows: `id` keeps the old `T`/`B`/`Q` id
  (an id that only survives in the legacy copy is free to reuse); an old number from another
  scheme goes into `formerly` instead. Done items are not entries — they stay in the legacy copy.
- **Tasks only the owner may do** (the old tasks file's section "Aufgaben nur für …", "Tasks only
  for …"): each item becomes `kind: "inbox"`, `for: "<owner>"`, `status: "open"`,
  `formerly: "<old id>"` — never `task` (an assistant would pick it up) and never `id` (an inbox
  entry takes none). The body keeps its `Antwort:` line.
- **A board approval or other open point without an entry shape of its own**: `kind: "inbox"`,
  `status: "open"`, `for: "<owner>"` where the owner has to decide or act, `for: "all"` where
  anyone may. Not a separate `entries.py new inbox` call — that has no `--target` and would write
  into this checkout.
- **Rule prose** from the old `CLAUDE.md`/`AGENTS.md`, and any `AI-CONFIG.md` free-text passage
  that is a rule of its own: `kind: "proposal"`, `target` one of `rules`|`coding`|`checklists`|
  `config` (the proposal's header, not the table's `target`), `author` optional. Every project
  built on an earlier generation of this template carries such prose — plan for it. Only the
  project's own passages become proposals, not the predecessor template's text (step 2, "Own or
  the predecessor's").
- **The config report** from step 5: one `inbox` item, title `Config adoption report`,
  `body_file` `.act-local/adopt/config-report.md`, `source` the old `AI-CONFIG.md`, `for: "all"`,
  so nothing of it stays outside the entry system.

`ledger` is not a kind: a journal is a `log` row, always `legacy`, never a new entry. A batch is
refused as a whole on any single problem; nothing partial. After each successful run,
`<dir>/.act-local/adopt/entries-map.json` lists every written file under `entries`, each with its
`source_path`, `source_line` and `file`.

**Files outside the entry system** (the orchestrator writes them; a worker drafts under
`.act-local/adopt/drafts/<same path>`):

- `docs/project/coding_rules.md` (adopted into itself, step 2): the old text from the legacy copy
  goes below `## Own rules` (after its marker and comment line), wording unchanged; only the
  heading levels move so the old top level becomes `###` (`#` -> `###`, `##` -> `####`, …).
- `docs/README.md` (adopted into itself): the old text goes at the end of the template's version,
  wording unchanged, the old top level becoming `##` (`#` -> `##`, `##` -> `###`, …). In its old
  index table, a row whose file is gone after the adoption (moved to legacy or removed) is left
  out — the template's rows already name the new places, and the legacy copy keeps the whole old
  table; every other row and line stays as it is.
- A doc that moves into `docs/project/` (step 2): copy it byte-identical to its target,
  `mkdir -p <dir>/docs/project && cp <dir>/<old path> <dir>/docs/project/<name>`.
- An own skill or agent: copy it byte-identical to its target:

  ```bash
  mkdir -p <dir>/docs/ai/local/skills && cp -r <dir>/.claude/skills/<name> <dir>/docs/ai/local/skills/
  mkdir -p <dir>/docs/ai/local/agents && cp <dir>/.claude/agents/<name>.md <dir>/docs/ai/local/agents/
  ```

**Record it in `table.json`.** For every `adopt` row, set `target` to the files its content
actually reached — for entries and proposals the `file` values of `entries-map.json` whose
`source_path` is the row's `path` (never the map's `proposal_target`, which is a proposal header
value) — and `"done": true`. `legacy` rows get no target: their open items are entries, the file
itself is in legacy. A recorded target the content did not change (e.g. `docs/ai/config.md` when
every value was already right) comes back out of `target`, replaced by the files that did receive
the content; never touch a file just to make it look changed.

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

**Dead references in `docs/project/`** to a path that is gone are bent to its new place — the
legacy copy, or the one successor an `adopt` row names: only the link target of a Markdown link
(relative stays relative, the anchor stays) or a path standing alone in backticks; no other
character, never inside a code block. `--finish --plan` shows each change first. A reference with
no successor or with several, and a path in plain text, stays as it is and is listed; with more
than 50 in all the full list goes to `<dir>/.act-local/adopt/references.txt`. The bent files are
left unstaged (group 5 in step 8). Then `doctor.py` runs and a report lands at
`docs/ai/inbox/<date>-adoption-report.md`.

Check the result against the project, not the checkout:

```bash
python .act/scripts/doctor.py --target <dir>
```

**Hooks and permissions on removed scripts.** `doctor` reports every hook command and every
`Bash(...)` permission in `.claude/settings.json` (and, read-only, `.claude/settings.local.json`)
that names a script no longer in the project — typically the predecessor's `.claude/scripts/…`
after their `delete`. The orchestrator settles them with the owner before committing and removes
those entries (a script that should have stayed needed `keep` in step 2; after `--finish` it is
gone with its row). The versioned `settings.json` is edited in place and goes with group 2; the
local `settings.local.json` is the owner's to clean. Afterwards `doctor.py --target <dir>`
reports 0 findings.

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
   `docs/ai/inbox/<date>-translate-scaffold.md` from step 5 (both are about the scaffold, not
   about old content; step 5 may have changed the init notes), `.gitignore`, the template copies
   now standing where an old unit of the same name was moved or removed (with the removal of that
   unit's other files), and `.claude/settings.json` as it is now (after step 7's cleanup).
3. **One commit per source** — an `adopt` row's `target` files (entries, proposals,
   `docs/ai/config.md`, `docs/project/coding_rules.md`, `docs/README.md`,
   `docs/ai/local/<unit>`); for a `legacy` row, the entry files `entries-map.json` lists under its
   `source_path` (they are nobody's table target, so they are easy to miss). A path that is both
   moved and a target — `docs/README.md` or `docs/project/coding_rules.md` adopted into itself —
   goes here with its source, not into group 1 or 2 (its legacy copy is in group 1).
4. **What `--finish` did** — `state.json`'s `bridged` and `removed_at_finish` paths, the tool
   copies it printed for own units (`skills: <path>: created`, role bridges), and the adoption
   report (`state.json`'s `report`).
5. **References** — the files under `docs/project/` whose links `--finish` bent:
   `git -C <dir> status --porcelain -- docs/project` lists them as modified; one that is already a
   table target stays in group 3.

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

Without `--force`, `--abort` refuses when a file `init.py` created has changed since `--apply`
(e.g. `docs/ai/config.md` and the init notes after step 5, an edited init note), when a tracked
file has an uncommitted change beyond what `--apply` left, or when something new or changed sits
where a moved unit has to return. A commit on `act-adopt` other than `init.py`'s own refuses it
**with or without `--force`** — take those commits off the branch first, the refusal says how.
With `--force`, the changed files are copied to `.act-local/adopt/aborted/` before they are
removed.

**What `--abort` does not catch:** files written after `--apply` by anything but `init.py` —
`docs/ai/inbox/<date>-translate-scaffold.md` from step 5, and everything the content step added:
entries under `docs/ai/work/`, `docs/ai/questions/`, `docs/ai/inbox/`, proposals under
`docs/ai/proposals/`, copies under `docs/ai/local/`. They neither block `--abort` nor are removed
by it: it ends with exit 0 and lists them as "left in place (not created by adopt/init): ...",
untracked on the base branch. Move them out of the way (e.g. into
`<dir>/.act-local/adopt/aborted/`) or delete them — a new `--apply` refuses the unclean tree, and
a new scan would sight them as sources. Before a new attempt, move `table.json` and
`entries-map.json` aside too; it starts again at step 1.

There is no `--abort` once `--finish` has run — undo means checking out the base branch and
deleting `act-adopt` by hand, after reviewing it.

## When not

The owner declines the rebuild: stop after step 1 (the read-only sight only) and run
`init.py --target <dir>` alone. **Gap:** `docs/ai/config.md` has no key today for "the project's
docs live at `<old location>`, not `docs/project/`" — until one exists, note that decision by hand
(a line in `docs/ai/config.md`'s free text, or an inbox entry) rather than pointing at a setting
that isn't there.
