# Content as entries (step 6)

Read from step 6 of `SKILL.md`: harvest, cutting bodies, titles and the batch files for `adopt_entries.py`.

## Contents

- Harvest for the template, alongside reading
- Where to read
- Cut, don't retype
- What counts as the heading
- Open items, board approvals, proposals — one batch file per worker, one call at a time

**Harvest for the template, alongside reading.** Every old source in this step is read
anyway — while reading it, judge each rule, skill, doc/form convention or code convention against
one question: **does this help someone who will never see this project?** (the scope
reaches rule files, skills, and doc/form/code conventions alike; a code convention need not become
a `.act/coding/` bundle of its own, project directory layouts differ too much for that, but a
transferable idea from one is still worth a line.) A hit gets one line in
`<dir>/.act-local/adopt/harvest.md` (create it on the first hit): source as `<path>:<line>`, what
it is, why it would help a stranger — the wording never copied verbatim from the old project, no
project name, no code, no numbers, same bar as `.act/rules/topics/feedback.md`'s "Privacy check"
and its "What a good entry looks like" table. This file is local only (`.act-local/` is
gitignored) and judgment only — nothing here is sent yet; step 7 asks consent and only then turns
lines into outbox entries or discards them.

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
| a bullet or checkbox without a heading (`- [ ] **T12 · …** — …`, a board list) | the bold lead, else the text up to the first ` — ` or `: `; where either is only a label or the start of a sentence without a statement (fewer than four words — a bold lead like "Release" counts too), the whole logical line (the item's first line joined with the lines it wraps onto, by single spaces) | the whole bullet with its indented continuation lines |
| a backlog table row | the cell of the title column (`Titel`, `Title`) | the table's header and separator line, the row, then its detail section (`### B12 …` with the heading, up to the next heading of the same or a higher level) where the file has one |
| rule prose without a heading of its own | its first sentence, up to `. `, `: ` or the line end | the passage |

A title longer than 80 characters is shortened by `adopt_entries.py` itself: its first sentence, else a cut at a
word boundary with "…"; the full old text then opens the entry's body.

A title never carries the old id, bold markers, a status emoji (🔴, 🟡, ✅, ⏳, ⚠️, …) or a
closing colon — the emoji and the space next to it go, a colon at the very end goes, every other
character stays. No two items of a batch get the
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

Batch items (a JSON list): `kind` (`task`|`backlog`|`question`|`inbox`|`proposal`|`reserved`), `title`,
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
- **Old ids that get no live entry and no legacy copy** (they sat in a file `--finish` deletes):
  `kind: "reserved"`, `id` the old id, `title` a short reason. Nothing is written but the id, so
  `entries.py` never hands out that number again.
- **The config report** from step 5: one `inbox` item, title `Config adoption report`,
  `body_file` `.act-local/adopt/config-report.md`, `source` the old `AI-CONFIG.md`, `for: "all"`,
  so nothing of it stays outside the entry system.

`ledger` is not a kind: a journal is a `log` row, always `legacy`, never a new entry. A batch is
refused as a whole on any single problem; nothing partial. A rerun after an interrupted write
skips the items already written unchanged instead of refusing them. After each successful run,
`<dir>/.act-local/adopt/entries-map.json` lists every written file under `entries`, each with its
`source_path`, `source_line` and `file`.
