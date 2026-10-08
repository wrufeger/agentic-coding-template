# Table rules (step 2)

Read from step 2 of `SKILL.md`: the rules behind each proposed action, the own-or-predecessor check, foreign ids and targets.

## Contents

- Own or the predecessor's — before the approval, not after
- Foreign ids with the template's prefixes
- Targets now, where they are fixed
- Actions are fixed once `--apply` has run

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
  `legacy`, with the reason in `note`. A predecessor's tooling or `coding_rules.d/` file with own
  text is proposed `legacy`, not `delete` (its own servers in `.mcp.json.example`, say); make it
  `keep` where the project still uses the file.
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
  source, and an `adopt` row with an empty target still passes `--apply --plan` (with a warning);
  `--apply` itself refuses it without `--confirm-no-targets` — after `--apply` the only ways on are
  moving it (the source is removed) or `--abort`.
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
  the template's own units — `--finish` refuses that). A unit with own text whose name the new
  template ships itself is proposed `legacy` (allowed for `ai-machinery` for this case), its note
  says why: the own lines stay in the archive. To keep them in force, the owner chooses an
  override instead — action `adopt`, target `docs/ai/local/<area>/<name>` (`<name>/` for a skill,
  `<name>.md` for an agent), note `"override"`. Own **scripts and hooks**, and a predecessor's
  script the project changed, stay `keep` for now: there is no target for them yet
  (`--finish` bridges skills and agents only), and a moved or deleted hook script breaks the
  command that calls it from `.claude/settings.json`.
- `predecessor` -> `legacy` for its documents (they stay readable in the archive; own lines in
  them show in the origin, and a rule still in force among them becomes a proposal in step 6),
  `delete` for its tooling (`.mcp.json.example`, `.claude/mcp-katalog.md`, anything that is no
  document) and its `coding_rules.d/` files, each only where it is `template only` — with own text
  `legacy`.
- `unknown` -> `keep`.

`.claude/template.json` and `.claude/TEMPLATE-LICENSE` are sighted by name (`predecessor`,
proposed `legacy` — never a blind delete: they are the project's own marker and license file, kept
readable in the archive), and so is `.github/workflows/ci.yml`, proposed `legacy` only while it
still carries the predecessor's own placeholder steps (an `echo "TODO` line naming
`create-project.py`/`checklists.md`), `keep` once the project replaced them with its own
(none of the three has a document extension the generic scan would otherwise reach).
`adopt_config.py` reads `template.json`'s values in step 5 from wherever it now is — its own place,
or its legacy copy (renamed) once `--apply` moved it there.

**Foreign ids with the template's prefixes.** An old document may number its own sections
`A1`–`A4`, `B5`–`B8`, `B16`, `T3` … — the same prefixes and shape as this template's `T`/`B`/`Q`
ids. Once the items behind them get new entries, `B16` in the adopted wording means something else
than the new entry `B16`. The sighting's `foreign ids: …` line names the documents it found by
pattern (`project-doc`/`unknown` files with two or more distinct ids); spotting the same in the old
`work` files is your reading in step 6 (`legacy_ids()` of `entries.py` only keeps ids of the old
template's own headings, never numbers inside prose). Where the adoption meets such ids — wording
that stays as it is, or that becomes an entry body — offer the owner the choice before step 3:

- **Keep the old numbers** as they are, and put a note sentence above every adopted block that
  uses them ("Numbers in this block are the old list's own, not this project's entry ids."); or
- **Give new numbers** (new entries take the next free ids), the old number in `formerly`, the same
  note sentence above the old wording, and the references in `docs/project/` that name an old
  number changed to the new one — a wording change in the project's own docs, so only with the
  owner's yes, listed in the report.

Record the choice in the row's `note`; a row without foreign ids needs neither.

**Targets now, where they are fixed.** Fill `target` in this step whenever the destination is
already known — `docs/project/coding_rules.md` and `docs/README.md` as above, `docs/ai/config.md`
for the old `AI-CONFIG.md`, the `docs/ai/local/...` path of an own skill or agent. `--apply`
records what each target that exists at that moment looks like, and `--finish` refuses when any
recorded target is still unchanged ("content not adopted?"); a target added after `--apply` is
never checked that way. Leave `target` empty only where the file name is chosen at write time
(entry and proposal files, step 6). An `adopt` row of class `project-doc`, `ai-machinery`, `predecessor` or `unknown` without a
target makes `--apply` refuse (and `--apply --plan` warn): `--finish` has nothing to compare it
against, so content that never arrived would pass. `ai-config` and `work` rows (content that becomes
proposals and entries) are exempt. Fill the target where the destination is known; where it is not,
put the question into the approval of step 3 and, only on the owner's yes, pass
`--confirm-no-targets` to `--apply` (step 4).

**Actions are fixed once `--apply` has run**: `--finish` refuses every row whose action differs
from the one recorded then ("action changed since --apply"). Only `target` and `done` may change
afterwards; a wrong action means `--abort` and a new table.

Check every row against `adopt.py --help` (`ALLOWED ACTIONS PER CLASS` and `REFUSED`): `unknown`
rows other than `keep`, `delete` on a `project-doc`, a unit folder holding untracked or
git-ignored files, and anything below a source/test/content tree (`src`, `app`, `lib`, `test*`,
...) need `"confirmed": true`. **A link, or anything below one, may only be `keep`** — there is no
`confirmed` for that.
