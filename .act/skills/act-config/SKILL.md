---
name: act-config
description: Use when asked to show or change a setting in docs/ai/config.md ("act-config", "set feedback to manual", "which settings are there"). Lists the settings, explains one, or writes a new value, answered by a script without the model. Not for the Roles table - edit that by hand.
disable-model-invocation: true
---

# Show and set the project settings

Where the hook is active, `/act-config`, `/act-config <key>` and `/act-config <key> <value>` are answered
before the prompt reaches the model (`.act/hooks/dispatch.py`, `UserPromptSubmit --act-check`), so this
command normally never gets here. This file exists so that Claude Code knows the command; without it the
tool reports "Unknown command" and never calls the hook.

If the command reaches you anyway, run nothing and change nothing. Answer with one line: the hook did not
answer, so the human runs `python .act/scripts/config.py [<key> [<value>]]` in a terminal.
