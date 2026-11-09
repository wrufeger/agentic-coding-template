# Filling the content (step 6)

Read from step 6 of `SKILL.md`. Part A: entries by batch. Part B: files outside the entry system and recording targets.

## Contents

- A. Entries
- B. Files outside the entry system

## A. Entries

**Harvest while reading.** Judge each rule, skill, doc/form or code convention against one question: does this help someone
who will never see this project? A hit is one line in `<dir>/.act-local/adopt/harvest.md`: source `<path>:<line>`, what it
is, why it helps a stranger; wording never copied from the old project, no project name, code or numbers (the bar of
`.act/rules/topics/feedback.md`, "Privacy check"). Local and judgment only; nothing is sent before step 7.

**Where to read.** A row `--apply` moved is at `state.json`'s `moved` path (`docs/ai/work/archive/legacy/<old path>`,
byte-identical, same line numbers); the rest is still at its `path`.

**Cut, don't retype.** Every `body` is a `body_file` cut mechanically, never text the model wrote out:

```bash
mkdir -p <dir>/.act-local/adopt/bodies
sed -n '<first>,<last>p' <dir>/<source file> > <dir>/.act-local/adopt/bodies/<name>.md
```

Several spans of one file may go into one body, in order. A cut from line 1 leaves out a leading BOM (slice bytes after
`EF BB BF`). The `--plan` run prints every title: compare with the old headings.

**Title and body per old item** (the body never loses text; where the title line holds more, the body starts with it):

| Old item | Title | Body |
| :--- | :--- | :--- |
| heading or bold line | its text | the lines below, up to the next item |
| bullet or checkbox without heading | the bold lead, else text up to the first ` — ` or `: `; if that has fewer than four words, the whole logical line | the whole bullet with continuation lines |
| backlog table row | the title-column cell | table header and separator, the row, then its detail section if any |
| rule prose without heading | its first sentence | the passage |

A title never carries the old id, bold markers, a status emoji or a closing colon; no two titles of a batch are equal (take
the next sentence). A link into the old file stays as it is. `adopt_entries.py` shortens a title over 80 characters itself.

**One batch file per worker, one call at a time** (`<dir>/.act-local/adopt/batch-<source>.json`, never shared):

```bash
python .act/scripts/adopt_entries.py --target <dir> --from <dir>/.act-local/adopt/batch-<source>.json --plan
python .act/scripts/adopt_entries.py --target <dir> --from <dir>/.act-local/adopt/batch-<source>.json
```

Items: `kind` (`task`|`backlog`|`question`|`inbox`|`proposal`|`reserved`), `title`, `source` (`"<table path>:<line>"`), and
optionally `id`, `formerly`, `body_file`, `status`, `for` (the person who has to act, `all` when none). A batch is refused
whole on one problem; a rerun skips items already written. `entries-map.json` lists every written file.

- **Open tasks, backlog items, questions** from `work` rows: `id` keeps the old id; a number from another scheme goes into
  `formerly`. Done items are no entries.
- **Tasks only the owner may do**: `kind: "inbox"`, `for: "<owner>"`, `status: "open"`, `formerly`; never `task`, never `id`.
  The body keeps its `Antwort:` line.
- **A board approval or open point without entry shape**: `kind: "inbox"`, `status: "open"`, `for` the owner or `all`; not
  `entries.py new inbox` (no `--target`).
- **Rule prose** of the old `CLAUDE.md`/`AGENTS.md`/`AI-CONFIG.md`: `kind: "proposal"`, `target` one of `rules`|`coding`|
  `checklists`|`config`. Only the project's own passages, not the predecessor's text.
- **Old ids with no live entry and no legacy copy** (in a file `--finish` deletes): `kind: "reserved"`, `id`, short reason.
- **The config report** of step 5: one `inbox` item, title `Config adoption report`, `body_file`
  `.act-local/adopt/config-report.md`, `source` the old `AI-CONFIG.md`, `for: "all"`.

A journal is a `log` row, always `legacy`, never an entry.

## B. Files outside the entry system

The orchestrator writes them; a worker drafts under `.act-local/adopt/drafts/<same path>`.

- **`docs/project/coding_rules.md` and `docs/README.md`** (adopted into themselves): only the project's own passages, found
  with the `origin` diff, cut byte-identical like a body; the predecessor's scaffold prose (its `Datenstand` line, the
  section "Vorgefertigte Regelsätze") stays out. Where in the file is your call; the helper fixes heading levels and line
  endings (`--into coding`: end of `## Own rules`, old top level becomes `###`, `*`/`+` bullets become `- `; `--into readme`: end of the file, `##`):

  ```bash
  python .act/scripts/adopt_passages.py --target <dir> --into coding|readme --from <cut file> --plan
  python .act/scripts/adopt_passages.py --target <dir> --into coding|readme --from <cut file>
  ```

  One run per target, several passages in one cut file in original order. In the old index table of `docs/README.md` leave
  out by hand a row whose file is gone and a footnote only such rows use; every other row stays.
- **Rules are adopted so that they are loaded and followed**, decided per rule before the cut file is made:
  - It matches a template rule or group (`python .act/scripts/rules.py --list`, `rules.py <id>`; for `R-…` ids `--area core`):
    an **override**, one line ``- replaces `<ID>`: <the project's wording>`` under `## Overrides` after the
    `<!-- act:overrides -->` mark, written by hand. It replaces the **whole text** of the rule or group: if the old rule covers
    only part, adopt it as an own rule instead, or the override carries the complete adapted group text.
  - It matches none: never take a whole guideline file into "Own rules" (loaded every session). Sort its parts by the table in
    `.act/bridges/coding_rules.md` and propose a place per part; the human decides: every coding session → own rule, one
    imperative line; only some paths → `.claude/rules/<area>.md` with `paths:`; tied to a framework version → its own rule
    set; origin, incident, evidence → project docs; derivable from code → dropped or `stack`; doubles a template rule →
    dropped. Own rules go through `adopt_passages.py --into coding`, or for `docs/ai/rules.md` as a ``- `ID`: text`` line.
  - Check: `rules.py --list` and `--area core --list` show overrides `[~]` and own rules `[+]`; `--validate` must not name a
    `note:` or an `unclosed code fence` there (that text is not read: rewrite as bullets). A rule in neither list is not in force.
  - Record the decision per rule in the `note` of its table row.
- **A doc moving into `docs/project/`**: `mkdir -p <dir>/docs/project && cp <dir>/<old path> <dir>/docs/project/<name>`,
  byte-identical, and a line in `docs/README.md` (`--finish` writes none).
- **An own skill or agent**, byte-identical:

  ```bash
  mkdir -p <dir>/docs/ai/local/skills && cp -r <dir>/.claude/skills/<name> <dir>/docs/ai/local/skills/
  mkdir -p <dir>/docs/ai/local/agents && cp <dir>/.claude/agents/<name>.md <dir>/docs/ai/local/agents/
  ```

**Record it in `table.json`.** For every `adopt` row set `target` to the files its content reached (for entries and
proposals the `file` values of `entries-map.json` with the row's `path` as `source_path`, never `proposal_target`) and
`"done": true`. `legacy` rows get no target. A recorded target the content did not change (`docs/ai/config.md` with every
value already right) comes out of `target`; never touch a file to make it look changed.
