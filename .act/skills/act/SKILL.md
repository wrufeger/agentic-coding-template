---
name: act
description: Use when asked what skills or commands exist, for a skill list, or for one skill's exact instructions, or on a bare /act or /act <name> prompt. Prints the skill table with one-line descriptions, or the named skill in full. Does not run any skill.
---

# List project skills

Fallback path only. In Claude Code, a prompt that is exactly `/act` or `/act <name>` is already
intercepted before it ever reaches the model (`.act/hooks/dispatch.py`'s `UserPromptSubmit
--act-check` entry, `.act/bridges/settings.hooks.json`) — this skill runs only where that hook
cannot: a tool without harness hooks, or a session with hooks turned off.

Run `python .act/scripts/skills.py` (no argument: the table, sorted by name) or
`python .act/scripts/skills.py <name>` (that skill's `SKILL.md` in full) and put its stdout,
unchanged, in a code block. Nothing else: no commentary, no summary, no skill started.
