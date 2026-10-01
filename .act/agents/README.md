# Agent roles

One file per role: `.act/agents/<name>.md`, the role's rules, without frontmatter — everything a
worker in this role must follow, written tool-neutral. `.act/bridges/agents/<name>.md` is the
matching bridge: YAML frontmatter (`name`, `description`, `tier`/`reasoning` — the neutral scale,
never a real model name — `tools`), followed by the line "Apply the rules from `.act/agents/<name>.md`
before the ones below.", followed by room for the project's own additions to the role. A role with
no bridge yet has nothing written into the project.

**Tier/reasoning -> model/effort, only at generation time:** `.act/tiers.json` is the one place
under `.act/` a real model name is allowed, alongside a project's own fixed-model override in
`docs/ai/config.md` § Roles. `.act/scripts/init.py`'s `agent_bridge_targets()` pairs a role with
its bridge and, via `.act/scripts/tiers.py`, resolves that bridge's `tier`/`reasoning` — overridden
per role, or set outright, in `docs/ai/config.md` § Roles — into the generated file's `model`/
`effort` frontmatter, written to `.claude/agents/<name>.md` when `claude-code` is one of the
project's configured tools. A second file, `.claude/agents/<name>-high.md`
(`agent_bridge_variant_targets()`), gets the same resolution with the reasoning bumped one step
further — the runtime choice of giving one assignment more reasoning without ever writing a real
model ID into an assignment. No variant is generated for a role whose template reasoning is
already the top of the tool's reasoning scale (`expert-solver`).

**No sub-sub-agents (`R-role-worker`):** a role's `tools` list never includes `Agent`/`Task` — a
worker starts no further workers. `.act/hooks/dispatch.py`'s `worker-nesting-guard` check backs
this mechanically, independent of what a role's own `tools` list says: a `PreToolUse` call to
`Agent`/`Task` whose payload carries an `agent_id` (the harness stamps every sub-agent's own tool
calls this way; the orchestrator's own calls carry none) is refused.

**Once created, only `model`/`effort` are ever touched again.** Unlike a skill copy, an existing
role bridge's body — everything below the frontmatter, including a project's own additions — is
never replaced, not even when it still matches what the template ships
("once created, the user owns it from then on"). `.act/scripts/init.py` creates a role's bridge (and its `-high`
variant, where one applies) once; `.act/scripts/update.py` only creates bridges for roles new since
the last update, or a missing `-high` variant for an already-known role. What *does* change on
every `update` and at every session start (`dispatch.py`'s `session-start-refresh`) is the
`model`/`effort` frontmatter pair alone, re-derived from the current `.act/tiers.json` and
`docs/ai/config.md` § Roles (`.act/scripts/tiers.py`'s `refresh_project_bridge_frontmatter()`) — a
project's own role, named only in § Roles with a hand-written bridge, gets the same treatment as
long as that bridge file exists.
