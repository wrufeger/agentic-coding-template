# Cost rules

## `R-cost-delegate` — Name the tier, the estimate, and the cap

Every assignment to a worker states its model tier explicitly (strong plans and reviews, medium
implements, small counts and reads), an estimate for scope or duration, and a cap. The cap is
checked mechanically, not from memory. Read large files in excerpts rather than in full.

## `R-cost-wait` — Let a started worker finish

A worker reports back on its own when it is done; polling its status repeatedly does not speed it
up — it costs tokens on every call and clutters the chat (trigger: over forty consecutive idle
status checks in one real case, none of them changing anything). Start the assignment, then either
work on something independent or wait; check in only once runtime clearly exceeds the estimate
given in the assignment — not on a hunch.

## `R-cost-script` — Script instead of worker for recurring checks

Recurring counting or status work (file counts, state checks) becomes a script the first time it
comes up, then is only run, not re-delegated to a worker.

## `R-code-commit` — Committing is the orchestrator's job alone

Only accepted work gets committed, staged by pathspec — never `git add -A`, `git add .`, or
`git commit -a`. Lint, typecheck, and tests run first, but only where the project has them set up
(an IDE's own check counts as evidence, not as a configured lint) and no rule suspends the check for
this case. A missing tool is not a reason to install one or add tests on the spot — at most a
one-time note that it is missing.
