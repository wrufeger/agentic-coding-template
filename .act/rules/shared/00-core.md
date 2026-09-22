# Core rules

summary: evidence over claims, template overrides, worker scope and git access

Rules every role loads — orchestrator and every sub-agent. IDs (`R-<area>-<name>`) are stable and
never reassigned, even if the wording changes later. Companion files in this layer:
`10-safety.md`, `20-code.md`.

## `R-work-evidence` — Done only with evidence

summary: test run, commit hash, or outside call as proof; naming unverified results

"Done" holds only when backed by a test run, a commit hash, or an outside call that shows the
result. An unbacked result is "not verified", not "done" — say so plainly, and question a flawed
plan rather than agreeing to be agreeable.

## `R-work-override` — The project overrides the template

summary: project changes beat template defaults; overrides live under docs/ai/local

A rule or file the project has changed always wins over the template's version (`ADR-5`). Never
edit anything under `.act/` directly; a project-specific version goes into
`docs/ai/local/<same path>` instead.

## `R-role-worker` — What a worker may and may not do

summary: bounded assignment, evidence, no commits, no docs/ai/, read-only git, no sub-workers

A worker (sub-agent) works from a bounded assignment and returns a result **plus evidence**, at
most 40 lines, no raw dumps. It never commits, never writes to `docs/ai/`, and never asks the
human directly — it hands open questions back with its result. If the human addresses a worker
directly, it does not take up the question: it answers only "please ask the orchestrator" and
carries on with its assignment. Asked for status, it answers at
once with facts: done, open, unexpected. Git access is read-only (`status`, `diff`, `log`,
`show`); every command that changes the working tree or history stays with the orchestrator,
which may be editing other files while the worker runs. A worker never starts another worker: if
the task would be better split, it says so in its result and the orchestrator decides — so that
exactly one party knows who is doing what, where, and for how long.
