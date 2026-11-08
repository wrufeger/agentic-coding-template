---
name: act
description: Use when asked what skills or commands exist, for a skill list or one skill's instructions, for the project's settings, state or template version, or on a bare /act, /act-config, /act-info or /act-version prompt. Prints the skill table, one skill in full, or a script's output. Does not run any skill.
---

# Skill list, settings, project state, template version

Fallback path only. In Claude Code the hook answers these prompts before the model sees them
(`.act/hooks/dispatch.py`, `UserPromptSubmit --act-check`, `.act/bridges/settings.hooks.json`); this skill runs
where it cannot: a tool without harness hooks, a session with hooks turned off, or a plain question.

The skills `act-config`, `act-info` and `act-version` only carry their commands to Claude Code.

| Prompt | Command |
| :--- | :--- |
| `/act` | `python .act/scripts/skills.py` (the table) |
| `/act <name>` | `python .act/scripts/skills.py <name>` (that `SKILL.md` in full; `act-` may be left out) |
| `/act-config [<key> [<value>]]` | `python .act/scripts/config.py [<key> [<value>]]` (settings of `docs/ai/config.md`) |
| `/act-info [--limit N]` | `python .act/scripts/info.py` (local files and git only, no network) |
| `/act-version [--all]` | `python .act/scripts/update.py --versions --short` (three lines; with `--all` no `--short`, the full list; `git ls-remote` only; writes the local update note) |

Put the stdout, unchanged, in a code block; nothing else: no commentary, no summary, no skill started. A value
is written with `config.py` only where the human asked for exactly that key and value. After `/act-version`:
when line 3 reads `Update: … available` offer `act-update`; on `Update: none, …` offer nothing. Never start it unasked.
