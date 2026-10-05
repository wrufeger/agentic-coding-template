---
name: act-load-settings
description: Import a settings file (act-export-settings' output) into this project - mechanical checks decide new/identical/dead on their own, content overlaps go to a model for judgment, everything unresolved lands in the inbox instead of being applied silently. Use when handed a settings.md or settings.zip file to bring into this project.
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
4. An agent or skill whose name — file/folder name *or* frontmatter `name`, checked
   case-insensitively, `-high` variants included — matches one this template already ships is
   never written, only reported. Importing it would otherwise start silently overriding that
   template unit; if the human actually wants that, it is a deliberate `docs/ai/local/` override
   done by hand, not an import side effect. An agent with `permissionMode`/`hooks`/`mcpServers` in
   its frontmatter, or a skill with `allowed-tools`/`hooks`, is refused the same way — reported,
   never written, not even with `--yes`; the human adds it by hand if it is genuinely wanted.
   A topic already there with different content is reported as changed and left alone; an
   override whose template topic no longer exists is reported as dead and not written; one whose
   template topic changed since the export is reported as changed-since-export (review by hand).
5. A written own agent/skill gets its tool bridge automatically (`.claude/agents/<name>.md`, the
   matching skill copies) — nothing further to do for that. Importing is not the only way: an
   own skill or role written by hand under `docs/ai/local/skills/<name>/` or
   `docs/ai/local/agents/<name>.md` gets the same copies at the next session start or `update.py`
   run (`unit_copies.py`).
6. Whatever is left — dead/retired ids, cross-file disagreements, unreviewed candidates,
   `## setup-required` lines — lands in one `docs/ai/inbox/U<n>-settings-import.md`. Read it out to the
   human; a `setup-required` entry needs configuring before that rule/agent/skill actually works.
7. A file `apply` could not fully resolve stays in `.act-local/import/` and prints, per item, why:
   declined by you, needs `--yes`, needs a judgment (content overlap), a name/id collision, or
   rejected (risky frontmatter, shadowing, a bad path, ...) — plus how many items from that file
   already applied. Put that in your own words for the human (why it is stuck, not just the raw
   line) and ask for one of the four decisions:
   - **keep** (offered again next run) — the safe default when nothing is actually wrong, just
     `--yes`/a judgment is still missing and the human wants to supply it later. Suggest a plain
     rerun with `--yes`/`--judgments` only when that could actually resolve it — a name/id
     collision or a rejected bundled file needs `partial`/`ignore`/`delete` instead, a rerun
     reproduces the exact same outcome.
   - **partial** — close it now, keep what applied, discard the rest. Suggest this when the open
     items are things that will not resolve themselves (a genuine content collision, an import the
     human has decided against for part of the file).
   - **ignore** — never offer this file again; for a file the human wants gone from view entirely.
   - **delete** — remove the file outright. Only pass this after the human has explicitly said so
     in this conversation — never infer it from "clean it up" or similar.
   Call `python .act/scripts/settings_load.py apply --resolve <file>=<action>` with the decision
   (repeatable for several files in one call). **`--resolve` is a pure filing run, not a second
   `apply`:** as soon as it is given, every file in `.act-local/import/` other than the one(s)
   named — including one dropped in since the last `apply` — is left completely alone, and even a
   named file only gets the action asked for, nothing from it is written/applied. There is no TTY
   prompt in this mode either. `partial` still needs to know what it is discarding, so for that one
   action the file is read again — but only read, never applied — to list what stays open; a file
   that fails to load cannot be given `partial` at all (nothing to list), only `keep`/`ignore`/
   `delete`.

## When not

A merge conflict from a template update (`act-update`/`act-doctor` handle that) or a fresh
project's own initial setup (`init.py`) — this is for a settings file specifically, not a template
diff.
