# Cost rules

summary: delegation tiers and caps, waiting on workers, scripting recurring checks, commit gate

## `R-cost-delegate` — Name the tier, the estimate, and the cap

summary: tier, scope/duration estimate, and a mechanically checked cap

Every assignment to a worker states its tier explicitly — `light` for reads/counts, `standard` for
implementation, `elevated` for review/security judgment, `expert` only for an escalation after two
failed attempts on the same task — an estimate for scope or duration, and a cap. The cap is checked
mechanically, not from memory. Need more reasoning for one assignment without raising the role's
tier itself: name its `-high` variant instead (same tier, one reasoning step further — see
`docs/ai/config.md` § Roles for a permanent override). Read large files in excerpts rather than in
full. Only the orchestrator starts workers; a worker's proposal to split its task comes back to the
orchestrator, which cuts and starts the new assignments itself.

Every assignment also states its write scope as a `Write scope: <glob>[, <glob> ...]` line —
patterns relative to the project root, `/` as the separator, `*` crossing `/` freely (so `src/*`
already reaches any depth under `src/`); a whole directory can also be named as `dir/**` or, as a
shorthand, `dir/` (read the same way). `Write scope: none` means read-only, no writes at all.
Leaving the line out means no restriction beyond the template's own `.act/` write-guard.
`worker-write-scope` (`docs/ai/config.md` § Checks) checks it mechanically, the same way the cap is
checked mechanically rather than from memory — for a Bash command this is best-effort (it catches
redirection and the common write commands, not a full shell parse), not a complete guarantee:
writes made from inside a program (`python -c "open(...)"`, a script file) stay invisible to it.

## `R-cost-wait` — Let a started worker finish

summary: letting a started worker finish; checking in only past the estimate

A worker reports back on its own when it is done; polling its status repeatedly does not speed it
up — it costs tokens on every call and clutters the chat (trigger: over forty consecutive idle
status checks in one real case, none of them changing anything). Start the assignment, then either
work on something independent or wait; check in only once runtime clearly exceeds the estimate
given in the assignment — not on a hunch.

## `R-cost-script` — Script instead of worker for recurring checks

summary: recurring counting or status checks as a script, not a repeated worker task

Recurring counting or status work (file counts, state checks) becomes a script the first time it
comes up, then is only run, not re-delegated to a worker.

## `R-code-commit` — Committing is the orchestrator's job alone

summary: pathspec-only commits after lint/typecheck/tests where configured

Only accepted work gets committed, staged by pathspec — never `git add -A`, `git add .`, or
`git commit -a`. Lint, typecheck, and tests run first, but only where the project has them set up
(an IDE's own check counts as evidence, not as a configured lint) and no rule suspends the check for
this case. A missing tool is not a reason to install one or add tests on the spot — at most a
one-time note that it is missing. The `reviewer` runs once per task before acceptance, not after
every step; for a trivial change (typo, docs only) the orchestrator skips it and says so. After a
BLOCK the orchestrator checks the fixes itself — a second review only for a critical finding.
