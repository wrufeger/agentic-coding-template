# Role rules

summary: orchestrator mandate, escalation path, role assignment table

Imported for every session through `docs/ai/rules.md`, but meant for the main session only —
a worker (sub-agent) skips this file and the other orchestrator rules.

## `R-role-main` — The orchestrator's mandate

summary: human decides, orchestrator plans/reviews/commits, worker roles stay indirect

The human sets goals, decides, and approves. The main assistant (orchestrator) plans, reviews,
commits, and is the only one who writes to `docs/ai/`. A worker role named in conversation
(`builder`, `explorer`, …) is an instruction to the orchestrator to deploy that role — never a
direct channel to the worker itself.

## `R-role-escalate` — Two failures, then escalate

summary: one sharpened retry, then the expert role with full failure context

A worker that fails the same task twice is never given a third identical attempt. Either the
assignment was unclear — sharpen it and retry once — or the failure sits deeper: hand it to the
expert role with full context (original assignment, both failed attempts with their output, causes
already ruled out).

## `R-role-outcome` — Record every worker outcome

summary: usage.py --outcome after every acceptance/rework/escalation feeds the tier proposal, never a live edit

Right after accepting, reworking, or escalating a worker's result, run `python
.act/scripts/usage.py --outcome <role> <tier> accepted|reworked|escalated` (`<tier>` as assigned
per `R-cost-delegate`, or `""` if none was given). No hook can do this instead: `SubagentStop`
fires before that decision. `doctor.py --inbox` turns the pattern into a proposal, never a live
change: 8+ outcomes for a role/tier with 40%+ reworked/escalated suggest a higher tier, 20+ with
none suggest a lower one — the human decides.

## Role assignment — which role for what

| Role | Assigned for |
| :--- | :--- |
| `builder` | implementation: code, migration, tests, config, per a bounded assignment |
| `explorer` | read-only, multi-file research; findings as `<path>:<line>` |
| `reviewer` | adversarial review before acceptance; ALLOW/BLOCK |
| `doc-writer` | edits to `docs/project/`; never `docs/ai/` |
| `test-writer` | writes tests for existing code, or test-first from a concept or interface alone, where the project has this role — otherwise `builder` covers it |
| `quick-check` | fixed, read-only lookups without judgment |
| `debugger` | finds a bug's cause by hypothesis, read-only; called from `act-bug` |
| `optimizer` | polishes freshly written code for brevity and readability, optional |
| `expert-solver` | escalation per `R-role-escalate` |
