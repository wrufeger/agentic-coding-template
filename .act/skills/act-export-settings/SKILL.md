---
name: act-export-settings
description: Write this project's own rule deviations, and optionally its own scripts/checklists/agents/skills, to a portable settings file for another project or for review before sharing. Use to hand this project's setup to a new project, or to check what a settings export would reveal before sending it anywhere.
---

# Export the project's settings

Thin wrapper around `python .act/scripts/settings_export.py` — writes what this project changed
against the template (rules/coding: own rules, switched-off groups, `replaces` overrides) into one
`settings.md`, readable and diffable. Nothing about the project itself (name, work state, the
`use:` selection) goes into it.

## Switches

- Default: only `[~]`/`[-]`/`[+]` deviations for rules + coding — `--all` also lists every
  unchanged (`[=]`) rule/group.
- `--with-scripts` / `--with-checklists` / `--with-agents` / `--with-skills`: also include
  `docs/ai/local/scripts/`, `docs/ai/local/checklists/`, this project's own roles
  (`docs/ai/local/agents/`) and its own skills (`docs/ai/local/skills/`). Any of the four forces a
  `.zip` (`--with-files`) instead of a plain `.md`, since these carry whole files alongside the
  summary line settings.md shows for each one.
- `--strict`: abort instead of substituting a placeholder — use this when the file is headed to
  people outside the project, not just another one of the human's own.
- `--out PATH`: write there instead of the default `.act-local/export/act-settings-<date>.md`/
  `.zip` (machine-local, gitignored, created on demand). The natural handover is dropping that file
  straight into another checkout's `.act-local/import/` — that's exactly what `act-load-settings`
  picks up when run with no path.

## Steps

1. Ask which switches apply — do not guess `--with-*`: handing over scripts, checklists, an own
   role, or an own skill is a deliberate choice, not a default.
2. Run the script. It scans every value it writes for credentials, mail addresses, IPs, local
   paths and internal hosts on its own and replaces a hit with a visible `<setup:KIND>` placeholder
   plus a `## setup-required` line — never a silent drop, never a silent secret.
3. **Always show the human the finding count the script prints, and remind them to skim the file
   before sending it anywhere** — the script is the second check, not the only one.
4. `--strict` failing with findings is not a bug: fix or accept each one, then decide whether to
   rerun with `--strict` or drop it for this handover.

## When not

The file is meant for another project of the same human, or for the human's own review — not a
substitute for `act-feedback` (a template-wide finding) or for handing a whole repo to someone.
