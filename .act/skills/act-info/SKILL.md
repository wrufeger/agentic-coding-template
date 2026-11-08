---
name: act-info
description: Use when asked which project, folder, branch or template version this session works in, or what is open here ("act-info"). Read-only, no network. Not for the newest version - use act-version.
disable-model-invocation: true
---

# Show the project and its state

The session hook answers `/act-info [--limit N]` before the model sees it. If you see this anyway, run
`python .act/scripts/info.py [--limit N]` and show its output unchanged.
