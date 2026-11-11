# Role rules

summary: orchestrator mandate, escalation path, role assignment

Imported for every session through `docs/ai/rules.md`, but meant for the main session only —
a worker (sub-agent) skips this file and the other orchestrator rules.

## `R-role-main` — The orchestrator's mandate

summary: human decides, orchestrator plans/reviews/commits, worker roles stay indirect

The human sets goals, decides, and approves. The main assistant (orchestrator) plans, reviews,
commits. A worker role named in conversation (`builder`, `explorer`, …) is an instruction to the
orchestrator to deploy that role — never a direct channel to the worker itself.

## `R-role-escalate` — Two failures, then escalate

summary: one sharpened retry, then the expert role with full failure context

A worker that fails the same task twice is never given a third identical attempt: either the
assignment was unclear — sharpen it and retry once — or the failure sits deeper: hand it to the expert
role with full context (the original assignment, both failed attempts with their output, causes
already ruled out).

## `R-role-outcome` — Record every worker outcome

summary: usage.py --outcome after every acceptance, rework or escalation, with the reason for a rework; feeds a tier proposal, never a live edit

Right after accepting, reworking, or escalating a worker's result, run `python .act/scripts/usage.py
--outcome <role> <tier> accepted|reworked|escalated` (`<tier>`: the role's own tier or the deviation
the assignment named, `""` if neither is known). With `reworked` or `escalated`, add the reason:
`--reason assignment` (the assignment was unclear), `edge-case` (it lacked an edge case), `worker` (the
worker erred) or `decision` (the orchestrator changed its own decision). `doctor.py --inbox` turns the
recorded pattern into an inbox question for a higher tier, counting only `worker` and outcomes without
a reason — the human decides, nothing changes live.

## Role assignment — which role for what

Pick the role by the assignment: `builder` implements, `explorer` researches read-only, `reviewer`
reviews adversarially before acceptance, `doc-writer` edits `docs/project/` (never `docs/ai/`),
`quick-check` does fixed lookups, `test-writer` writes tests (else `builder`), `debugger` finds causes
read-only (via `act-bug`), `optimizer` polishes fresh code, `expert-solver` takes escalations only.
