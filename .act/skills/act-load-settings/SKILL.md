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

1. `python .act/scripts/settings_load.py plan <file...> [<file2>...]` — writes nothing, shows what
   would happen. Several files in one run are checked against each other too (a cross-file
   disagreement on the same id applies from neither).
2. Content overlaps (an imported rule against one of this project's own) come back as candidate
   pairs, not a verdict — judge each one (`same` / `extends` / `contradicts` / `unrelated`) and pass
   the verdicts back via `--judgments PATH` (`plan --candidates-out PATH` writes the pairs as
   JSON). A pair with no verdict stays unreviewed and unapplied.
3. `python .act/scripts/settings_load.py apply <file...> [--judgments PATH] [--yes]` — writes what
   is now clear: rules/coding into `docs/ai/rules.md` / `docs/project/coding_rules.md`; mitgegebene
   scripts, checklists, agents and skills into `docs/ai/local/<area>/<name>` — **show every such
   file to the human before writing it** (the script already asks unless `--yes`; never pass `--yes`
   without the human having seen the list first, and never in a non-interactive run without it).
4. An agent or skill whose name — file/folder name *or* frontmatter `name`, checked
   case-insensitively, `-high` variants included — matches one this template already ships is
   never written, only reported. Importing it would otherwise start silently overriding that
   template unit; if the human actually wants that, it is a deliberate `docs/ai/local/` override
   done by hand, not an import side effect. An agent with `permissionMode`/`hooks`/`mcpServers` in
   its frontmatter, or a skill with `allowed-tools`/`hooks`, is refused the same way — reported,
   never written, not even with `--yes`; the human adds it by hand if it is genuinely wanted.
5. A written own agent/skill gets its tool bridge automatically (`.claude/agents/<name>.md`, the
   matching skill copies) — nothing further to do for that.
6. Whatever is left — dead/retired ids, cross-file disagreements, unreviewed candidates,
   `## setup-required` lines — lands in one `docs/ai/inbox/<date>-settings-*.md`. Read it out to the
   human; a `setup-required` entry needs configuring before that rule/agent/skill actually works.

## When not

A merge conflict from a template update (`act-update`/`act-doctor` handle that) or a fresh
project's own initial setup (`init.py`) — this is for a settings file specifically, not a template
diff.
