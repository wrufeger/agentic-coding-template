# Table rules (step 2)

Read from step 2 of `SKILL.md`: why each action is proposed and where to deviate. `adopt.py --help` lists the allowed
actions per class and what it refuses; this file is the judgment.

**Own or the predecessor's, before the approval.** Every row with an `origin` gets this check (two earlier runs needed
`--abort --force` because `CLAUDE.md` and `AGENTS.md` stood on `adopt` with nothing of their own):

- `template only`: nothing to take over. An `ai-config` file goes `legacy`, a unit of the predecessor `delete`;
  `--finish` refuses an `adopt` row whose target never changed.
- `own text: n lines`: read them first (`git -C <dir> diff <base_commit> HEAD -- <path>`, the `+` lines minus a pair that
  only fills in a placeholder). Rules or content of the project's own keep `adopt` for an `ai-config` file (they become
  proposals in step 6); lines that are no rule (a date, a filled-in example, a line the owner deleted) mean `legacy`,
  reason in `note`. A predecessor's tooling or `coding_rules.d/` file with own text is `legacy`, not `delete`; `keep`
  where the project still uses it.
- `unknown (base_commit not reachable)`: compare with a checkout of the predecessor at that state; `adopt`/`keep`, never a
  blind `delete`.

The same diff separates the project's own rule prose from the predecessor's text in step 6.

**Proposals and deviations:**

- `log` → `legacy` (byte-identical, never reinterpreted).
- `work` → `legacy`: done items stay in the legacy copy, open items become entries in step 6 from that copy. `adopt`
  only for a work file whose entire content becomes entries (nothing done, nothing else in it), since it is removed at
  `--finish`.
- `project-doc` → `keep`, a foreign root `README.md` too. `adopt` only where the file has to move: at a place `init.py`
  writes itself (`docs/project/coding_rules.md`, `docs/README.md`) the target is the same path (`legacy` when `template
  only`; with `keep`, `init.py` writes no template version), step 6 merges the old content; outside `docs/project/` and
  belonging there, the target is the new path. Never `adopt` a doc into itself anywhere else.
- `ai-config` → `adopt` for `CLAUDE.md`, `AGENTS.md`, `AI-CONFIG.md` and other tool rule files with content of their own;
  `legacy` for one with none (`template only`, or only "see AGENTS.md"). Never `delete` `AGENTS.md` or `CLAUDE.md`: no
  bridge would be written (`legacy` moves the file before `init.py`, which then writes it). `keep` for the local files
  named in `SKILL.md`; `.claude/settings.json` stays `keep` (`init.py` merges hooks, backed up first); a predecessor's
  `.claude/settings.local.json.example` is `delete`. The script refuses `delete`/`legacy` on "never bridge" rows but not
  an `adopt` into a proposal: this rule is the real safeguard.
- `ai-machinery` → `delete` for a unit that is `template only`. `adopt` for the project's **own** skills and agents,
  target `docs/ai/local/skills/<name>` or `docs/ai/local/agents/<name>.md` (`<name>` no template unit). Own text under a
  name the new template ships → `legacy` with the reason in `note`; to keep it in force the owner chooses an override:
  `adopt`, target `docs/ai/local/<area>/<name>`, note `"override"`. Own **scripts and hooks**, and a predecessor script the
  project changed, stay `keep` (no target yet; a moved hook script breaks the command in `.claude/settings.json`).
- `predecessor` → `legacy` for documents (a rule in force among them becomes a proposal in step 6), `delete` for tooling
  (`.mcp.json.example`, `.claude/mcp-katalog.md`) and `coding_rules.d/` files, each only where `template only`.
  `.claude/template.json`, `.claude/TEMPLATE-LICENSE` → `legacy`, never a blind delete; `.github/workflows/ci.yml` →
  `legacy` while it still has the predecessor's placeholder steps, `keep` once replaced.
- `unknown` → `keep`.

**Foreign ids with the template's prefixes.** An old document may number its sections with the same letter-plus-number
shape as this template's ids; once its items get new entries, the old number and the new entry id mean different things.
The sighting's `foreign ids:` line names documents found by pattern; spotting it in old `work` files is your reading in
step 6. Where wording stays or becomes an entry body, offer the owner the choice before step 3:

- **Keep the old numbers** with a note sentence above every adopted block that uses them ("Numbers in this block are the
  old list's own, not this project's entry ids."); or
- **New numbers** (next free ids), the old one in `formerly`, the same note sentence above the old wording, and
  references in `docs/project/` bent to the new number, a wording change in the project's docs, so only with the owner's
  yes, listed in the report.

Record the choice in the row's `note`.

**Targets.** Fill `target` now wherever the destination is known (`docs/project/coding_rules.md`, `docs/README.md`,
`docs/ai/config.md` for `AI-CONFIG.md`, the `docs/ai/local/...` path of an own unit); `--apply` records what each existing
target looks like and `--finish` refuses a target still unchanged. Leave it empty only where the name is chosen at write
time (entries, proposals; `ai-config` and `work` rows are exempt). An `adopt` row of another class without a target: put
the question into step 3 and pass `--confirm-no-targets` only on the owner's yes.

Only `target` and `done` may change after `--apply`. `unknown` rows other than `keep`, `delete` on a `project-doc`, a unit
folder with untracked or ignored files and anything below a source/test/content tree need `"confirmed": true`; a link or
anything below one may only be `keep`.
