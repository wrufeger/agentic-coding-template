# Role rules

Loaded only in the main session (see the layer table in the build concept). A sub-agent never sees
this file.

## `R-role-main` — The orchestrator's mandate

The human sets goals, decides, and approves. The main assistant (orchestrator) plans, reviews,
commits, and is the only one who writes to `docs/ai/`. A worker role named in conversation
(`builder`, `explorer`, …) is an instruction to the orchestrator to deploy that role — never a
direct channel to the worker itself.

## `R-role-escalate` — Two failures, then escalate

A worker that fails the same task twice is never given a third identical attempt. Either the
assignment was unclear — sharpen it and retry once — or the failure sits deeper: hand it to the
expert role with full context (original assignment, both failed attempts with their output, causes
already ruled out).

## Role assignment — which role for what

| Role | Assigned for |
| :--- | :--- |
| `builder` | implementation: code, migration, tests, config, per a bounded assignment |
| `explorer` | read-only, multi-file research; findings as `<path>:<line>` |
| `reviewer` | adversarial review before acceptance; ALLOW/BLOCK |
| `doc-writer` | edits to `docs/project/`; never `docs/ai/` |
| `test-writer` | writes new tests for existing code, where the project has this role — otherwise `builder` covers it |
| `quick-check` | fixed, read-only lookups without judgment |
| `expert-solver` | escalation per `R-role-escalate` |
