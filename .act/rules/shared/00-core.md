# Core rules

Three rules, placeholders that carry real weight until Stage 2 fills out the rest of
`rules/shared/`. Every rule keeps a stable ID (`R-<area>-<name>`) that is never reassigned, even
if its wording changes later. This file is imported by every role, including sub-agents.

## `R-work-evidence` — Done only with evidence

"Done" holds only when backed by a test run, a commit hash, or an outside call that shows the
result. An unbacked result is "not verified", not "done" — say so plainly, and question a plan
that does not hold up rather than agreeing to be agreeable.

## `R-role-worker` — What a worker may and may not do

A worker (sub-agent) works from a bounded assignment and returns a result **plus evidence**, at most
40 lines, no raw dumps. It never commits and never writes to `docs/ai/`. It reads git only:
`status`, `diff`, `log`, `show` — every command that changes the working tree or history (`commit`,
`add`, `stash`, `checkout`, `reset`, `restore`, `merge`, `rebase`, `clean`, `push`) stays with the
orchestrator, because the orchestrator may be editing other files while the worker runs. A worker
never asks the human directly: it hands open questions back with its result.

## `R-work-override` — The project overrides the template

A rule or file the project has changed always wins over the template's version (`ADR-5`). The
assistant never edits anything under `.act/` directly; a project-specific version goes into
`docs/ai/local/<same path>` instead.
