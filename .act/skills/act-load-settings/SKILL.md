---
name: act-load-settings
description: Use when handed a settings.md or settings.zip file (act-export-settings output) to bring into this project. Mechanical checks sort new, identical and dead items, content overlaps go to a model for judgment, unresolved items land in the inbox. Not for a template update conflict - use act-update.
---

# Import a settings file

Thin wrapper around `python .act/scripts/settings_load.py` — the counterpart to
`act-export-settings`. Never guesses past a genuine judgment call: a rule that merely restates or
extends one of this project's own is applied, one that contradicts is held back, and either way it
is reported, never silent.

## Steps

1. `python .act/scripts/settings_load.py plan [<file...>]` — writes nothing, shows what would
   happen. Several files in one run are checked against each other too (a cross-file disagreement
   on the same id applies from neither). **No `<file...>` given:** every `.md`/`.zip` directly in
   `.act-local/import/` is used instead (sorted by name, that folder's own `README.md` skipped) —
   the default when the human just dropped a file there rather than naming a path. A file that
   fails to load is reported and left alone; an empty or missing folder is a clean no-op.
2. Content overlaps (an imported rule against one of this project's own) come back as candidate
   pairs, not a verdict — judge each one (`same` / `extends` / `contradicts` / `unrelated`) and pass
   the verdicts back via `--judgments PATH` (`plan --candidates-out PATH` writes the pairs as
   JSON). A pair with no verdict stays unreviewed and unapplied.
3. `python .act/scripts/settings_load.py apply [<file...>] [--judgments PATH] [--yes]` — same
   no-argument default as `plan`, except a file it managed to process *and fully resolve* is then
   moved into `.act-local/import/done/` (a name collision there gets a timestamp appended) — `plan`
   never moves anything, neither does `apply` when given an explicit `<file...>` path, and neither
   does `apply` for a file that still left something open: needs `--yes` (a bundled file), needs a
   judgment (content overlap with a project rule), a name/id collision, or was rejected outright
   (risky frontmatter, shadowing, a bad path, ...). That file stays in `.act-local/import/`, named
   in the output with the reason, for the next `apply --yes`/`--judgments` run to pick it up — or
   for `apply --resolve` (step 7) to file it away by hand. Writes what is now clear:
   rules/coding into `docs/ai/rules.md` / `docs/project/coding_rules.md`; bundled scripts,
   checklists, agents and skills into `docs/ai/local/<area>/<name>`, own topic rules and topic
   overrides into `docs/ai/local/rules/topics/<name>.md` — **show every such file to the
   human before writing it** (the script already asks unless `--yes`; never pass `--yes` without
   the human having seen the list first, and never in a non-interactive run without it).
4. An agent or skill that clashes with a unit this template ships (by file/folder name or frontmatter
   `name`), or carries risky frontmatter, is reported and never written, not even with `--yes`; a
   topic or override that already exists differently, or is dead, is reported and left alone. Read
   `references/refused-units.md` for the exact rules.
5. A written own agent/skill gets its tool bridge automatically (`.claude/agents/<name>.md`, the
   matching skill copies) — nothing further to do for that. Importing is not the only way: an
   own skill or role written by hand under `docs/ai/local/skills/<name>/` or
   `docs/ai/local/agents/<name>.md` gets the same copies at the next session start or `update.py`
   run (`unit_copies.py`).
6. Whatever is left — dead/retired ids, cross-file disagreements, unreviewed candidates,
   `## setup-required` lines — lands in one `docs/ai/inbox/U<n>-settings-import.md`. Read it out to the
   human; a `setup-required` entry needs configuring before that rule/agent/skill actually works.
7. A file `apply` could not fully resolve stays in `.act-local/import/` and prints, per item, why.
   Put that in your own words for the human and ask for one of four decisions — keep, partial,
   ignore, delete — then call `python .act/scripts/settings_load.py apply --resolve <file>=<action>`.
   Read `references/unresolved-files.md` before asking: what each decision means, when to suggest
   which, and what `--resolve` does and does not do.

## When not

A merge conflict from a template update (`act-update`/`act-doctor` handle that) or a fresh
project's own initial setup (`init.py`) — this is for a settings file specifically, not a template
diff.
