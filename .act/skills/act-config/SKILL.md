---
name: act-config
description: Use when asked to show or change a setting in docs/ai/config.md ("act-config", "set feedback to manual"). Answered by a script without the model. Not for the Roles table.
disable-model-invocation: true
---

# Show and set the project settings

The session hook answers `/act-config [<key> [<value>]]` before the model sees it. If you see this anyway, run
nothing and change nothing: say in one line that the hook did not answer, so the human runs
`python .act/scripts/config.py [<key> [<value>]]` in a terminal.
