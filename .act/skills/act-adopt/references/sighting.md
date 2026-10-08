# Sighting details (step 1)

Read from step 1 of `SKILL.md`: how to read the origin column, the predecessor template and the hint lines the sighting prints.

Every row carries `proposed`, the action the table starts from (`-> <action>` in the table;
rules under `PROPOSED ACTION` in `--help`). A project made from the previous template has a
`.claude/template.json`; then the first line names its `base_commit` and whether it is in the
history, the previous template's own files that fit no other class are `predecessor` (its
`docs/ai/README.md`, `checklists.md`, `config-guide.md`, `ai-config-hilfe.md`, `resources.md`,
`template-feedback/`, `docs/project/coding_rules.d/` (replaced by `.act/coding/`),
`.claude/mcp-katalog.md`, `.mcp.json.example` and whatever else its `base_commit` holds; a named
part is `predecessor` even where it would be `project-doc`), and every row carries an `origin`
(`[...]` in the table):

- `template only` — every line is the predecessor's own, after putting in the placeholder values
  of `template.json` § `values`. Replacing `{{PROJEKTNAME}}` by the project name is no text of its
  own.
- `own text: n lines` — n lines the base text does not have, `(not in the predecessor template)`
  for a file the project added.
- `unknown (base_commit not reachable)` — the commit is not in the history (a shallow clone, a
  squashed import); nothing can be told apart mechanically.

ADR folders (`adr/`, `adrs/`, `decisions/`, `decision-records/`) are `project-doc`; a dated file
(`YYYY-MM-DD…`) in `journal(s)/` or `docs/journal(s)/` is `log`.

**Show the owner the sighting's hints.** Besides the table, the sighting prints
`-- … --` info lines (also in `scan.json` under `info`; a row's own hint is `(hint: …)`). Read
them out to the owner before step 2, none is a classification:

- `language hint: …` — an old `AI-CONFIG.md` stands at the root; the line proposes the docs language
  for step 4 (its `Sprache` row, or `de` as an assumption where it has none).
- `possible home-made work system: …` — files whose name or folder uses a word a home-grown board
  or hand-over system uses (`board`, `chatlog`, `umbau`, `weiter`, `handover`, a `memory/` folder,
  also behind an `@` marker such as `@board.md`), anywhere in the project, not only in `docs/ai/`.
  Such a row is `unknown` with hint `work?`, except under a `docs/` folder: there it stays
  `project-doc` and only carries the hint — unless the name starts with `@`, which makes it
  `unknown` there too. The class is never `work` or `log` from a hint alone. Ask the owner what these
  files are — a board, a task list, a journal, copies of an assistant's memory — and set the
  action from the answer: `legacy` (with `"confirmed": true` on an `unknown` row) keeps them
  byte-identical in the archive, and their open items become entries in step 6, read from the
  legacy copy; plain documentation stays `keep`. Put the owner's answer into the row's `note`.
- `foreign ids: …` — documents that use numbers shaped like this template's own ids (`T12`,
  `B16`, `Q3`). See step 2.
- `predecessor leftover: git remote 'template' …` — the previous template's update script added a
  git remote named `template` that points at the template repository; this template does not use it
  (`update.py` takes the source from `.act-lock.json`). Left in place, a `git push`/`git pull`
  without a target goes to the template and a pull merges its whole history into the project.
  Propose removing it (`git remote remove template`) and do it only with the owner's yes. The line
  says when the current branch has no other remote or upstream: then the owner sets the project's
  own remote first, or a bare push/pull has no target left.
