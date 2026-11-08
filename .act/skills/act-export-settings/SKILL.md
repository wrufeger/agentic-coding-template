---
name: act-export-settings
description: Use to hand this project's setup to a new project, or to check what a settings export would reveal before sending it anywhere. Writes the project's own rule deviations, optionally scripts, checklists, agents, skills and topics, to a portable settings file.
disable-model-invocation: true
---

# Export the project's settings

Wrapper around `python .act/scripts/settings_export.py` (switches: `--help`): it writes what this project changed
against the template into one `settings.md`, readable and diffable. Nothing about the project itself (name, work
state, the `use:` selection) goes into it.

## Steps

1. Ask which switches apply — do not guess `--with-*`: handing over scripts, checklists, topics, an own role, an
   own skill or the format files is a deliberate choice, not a default. Ask separately whether the run goes to a
   file for another project (`--out`, or the default under `.act-local/export/`; dropped into another checkout's
   `.act-local/import/` it is what `act-load-settings` picks up) or to the Owner's own profile (`--profile`: the
   personal defaults for every future project, never a handover to someone else); the two exclude each other.
   Use `--strict` when the file goes to people outside the project.
2. Run the script. It replaces credentials, mail addresses, IPs, local paths and internal hosts with a visible
   `<setup:KIND>` placeholder plus a `## setup-required` line — never a silent drop.
3. **Show the human the finding count the script prints, and remind them to skim the file before sending it
   anywhere** — the script is the second check, not the only one. `--strict` failing with findings is not a bug:
   fix or accept each one, then decide whether to rerun with `--strict`.
4. A `--out` path outside the project is refused by the `outside-root` check: use the default folder, add the
   path to `outside-root-allow`, or set `ACT_OUTSIDE_ROOT=warn` for one run.

## When not

The file is for another project of the same human or for their own review — not a substitute for `act-feedback`
(a template-wide finding) or for handing a whole repo to someone.
