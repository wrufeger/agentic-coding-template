---
name: act
description: List the project's skills with a one-line description from each one's frontmatter, like a man page; given a name, show that skill in full. Use when asked what skills or commands exist, or for one skill's exact instructions.
---

# List project skills

Fallback path only. In Claude Code, a prompt that is exactly `/act` or `/act <name>` is already
intercepted before it ever reaches the model (`.act/hooks/dispatch.py`'s `UserPromptSubmit
--act-check` entry, `.act/bridges/settings.hooks.json`) — this skill runs only where that hook
cannot: a tool without harness hooks, or a session with hooks turned off.

Run `python .act/scripts/skills.py` (no argument: the table, sorted by name) or
`python .act/scripts/skills.py <name>` (that skill's `SKILL.md` in full) and put its stdout,
unchanged, in a code block. Nothing else: no commentary, no summary, no skill started.
