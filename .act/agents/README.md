# Agent roles

One file per role: `.act/agents/<name>.md`, the role's rules, without frontmatter — everything a
worker in this role must follow, written tool-neutral. `.act/bridges/agents/<name>.md` is the
matching bridge: YAML frontmatter (`name`, `description`, `model` as an alias — `haiku`, `sonnet`,
`opus`, never a fixed model ID — `tools`), followed by the line "Apply the rules from
`.act/agents/<name>.md` before the ones below.", followed by room for the project's own additions
to the role. A role with no bridge yet has nothing written into the project.

**No sub-sub-agents (`R-role-worker`):** a role's `tools` list never includes `Agent`/`Task` — a
worker starts no further workers. `.act/hooks/dispatch.py`'s `worker-nesting-guard` check backs
this mechanically, independent of what a role's own `tools` list says: a `PreToolUse` call to
`Agent`/`Task` whose payload carries an `agent_id` (the harness stamps every sub-agent's own tool
calls this way; the orchestrator's own calls carry none) is refused.

`.act/scripts/init.py`'s `agent_bridge_targets()` pairs a role with its bridge and writes the
result to `.claude/agents/<name>.md` when `claude-code` is one of the project's configured tools —
but only once: unlike a skill copy, an existing role bridge is never replaced, not even when it
still matches what the template ships (`docs/project/concepts/ai-dev-app/02-directory-plan.md` in
the template-pflege repo: "einmal erzeugt, danach der Nutzer"). `.act/scripts/update.py` only
creates bridges for roles new since the last update; an existing bridge is the project's own from
that point on, free to be edited without a later update overwriting it.
