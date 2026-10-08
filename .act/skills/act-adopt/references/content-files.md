# Content outside the entry system (step 6)

Read from step 6 of `SKILL.md`: passages into `coding_rules.md`/`README.md`, rules as overrides or own rules, moved docs, own skills and agents, and recording targets in `table.json`.

**Files outside the entry system** (the orchestrator writes them; a worker drafts under
`.act-local/adopt/drafts/<same path>`):

- `docs/project/coding_rules.md` and `docs/README.md` (adopted into themselves, step 2): only the
  project's own passages go in, found with the same diff as the `origin` (step 2), and cut
  byte-identical into a file the same way a `body_file` above is cut. The predecessor's own text
  stays out of that cut — its `Datenstand` line, the section "Vorgefertigte Regelsätze" and other
  scaffold prose the template's version replaces; the legacy copy keeps it. From there, a
  mechanical helper does the insertion — heading levels and the target file's line endings are
  exactly the two things a hand edit got wrong once; own text and where it goes in stay your call,
  not the script's:

  ```bash
  python .act/scripts/adopt_passages.py --target <dir> --into coding --from <cut file> --plan
  python .act/scripts/adopt_passages.py --target <dir> --into coding --from <cut file>
  python .act/scripts/adopt_passages.py --target <dir> --into readme --from <cut file> --plan
  python .act/scripts/adopt_passages.py --target <dir> --into readme --from <cut file>
  ```

  `--into coding` inserts at the end of `docs/project/coding_rules.md`'s `## Own rules` section
  (after its marker and comment line), the old top level becoming `###` (`#` -> `###`,
  `##` -> `####`, …); `--into readme` appends at the end of `docs/README.md`, the old top level
  becoming `##` (`#` -> `##`, `##` -> `###`, …) — wording never changes (the one exception:
  `--into coding` writes a `*`/`+` list marker at the start of a line, outside code fences, as
  `- `, so `rules.py` reads the list as own rules), and a rerun with the same
  cut file changes nothing (`--plan` first, as with every other write in this skill). In the old
  index table of `docs/README.md`, a row whose file is gone after the adoption (moved to legacy or
  removed) is left out of the cut by hand, and so is a footnote only such rows refer to (`¹`) —
  the template's rows already name the new places, and the legacy copy keeps the whole old table;
  every other row and line stays as it is. Several own passages for the same target go into one
  cut file, in their original order — one `adopt_passages.py` run per target, not one per passage.
- **Rules are adopted so that they are loaded and followed.** A rule the old project
  wrote down (coding standards in `coding_rules.md`/`coding_rules.d/`, working rules in
  `CLAUDE.md`/`AGENTS.md`/`AI-CONFIG.md`) is not left as text that only sits in a file. Decide per
  rule, before the cut file for `coding_rules.md` is made:
  - **It matches a rule or group of the template** (`R-…` in `docs/ai/rules.md`, `CR-<set>-<group>`
    in `docs/project/coding_rules.md`; `python .act/scripts/rules.py --list`, or
    `rules.py <id>` for the full text — for an `R-…` id `rules.py --area core <id>`): it becomes an **override**, one line
    ``- replaces `<ID>`: <the project's wording>`` under `## Overrides` of that file (after the
    `<!-- act:overrides -->` mark, the placeholder comment there may stay) — not a second copy under
    "Own rules". Write it by hand in the same line format `rules.py` reads; a script would only
    save one line, and the wording is your judgment call. A `replaces` line **replaces the whole
    text** of that rule or group (`rules.py` prints only the override text for it): if the old
    project's rule covers just part of a group, do not replace the group — adopt it as an own rule
    — or the override carries the complete adapted group text.
  - **It matches none:** it stays an **own rule** under `## Own rules` — through the cut file and
    `adopt_passages.py --into coding` (lists come out as `- ` bullets), or, for `docs/ai/rules.md`,
    as a ``- `ID`: text`` line by hand. A bare `- text` bullet counts as an own rule too.
  - Check it afterwards: `python .act/scripts/rules.py --list` and `--area core --list` show
    every override as `[~]` and every own rule as `[+]`; `--validate` (and `--area core
    --validate`) must not stay silent about a heading or prose under "Own rules" that carries a
    rule — a `note:` line there means `rules.py` did not read that text (it is missing from `--list`
    and from the effective text; Claude Code still loads the file whole through its import);
    rewrite it as bullets. An `unclosed code fence` finding means everything after it is ignored. Every
    adopted rule appears in one of these lists, otherwise it is not in force.
  - Record the decision per rule in the `note` of the table row it came from (for example
    `coding rules: 4 rules -> 2 x replaces CR-python-basics/CR-python-tests (full group text), 2 own rules`), so the
    report can list what replaced what.
- A doc that moves into `docs/project/` (step 2): copy it byte-identical to its target,
  `mkdir -p <dir>/docs/project && cp <dir>/<old path> <dir>/docs/project/<name>`. A new
  file there needs a line in the docs index `docs/README.md` (`--finish` does not write it — step 8).
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
