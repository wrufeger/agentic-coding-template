---
name: act-info
description: Use when asked which project, folder, branch or template version this session works in, or what is open here ("act-info", "where am I", "project status"). Prints a short block from a script, read-only and without network. Not for the newest available version - use act-version.
disable-model-invocation: true
---

# Show the project and its state

Run `python .act/scripts/info.py` and pass its output on unchanged, adding nothing. The script reads only local
files and local git: project name, folder, host, session name, branch, last commit, uncommitted changes, installed
template version with its update channel, open tasks and what waits for a human. It makes no network call.

`--limit N` shortens the task and waiting lists. For the newest available version, offer `act-version`.
