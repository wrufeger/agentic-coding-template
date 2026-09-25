# Cost rules

summary: delegation tiers and caps, waiting on workers, scripting recurring checks, commit gate

## `R-cost-delegate` — Name the tier, the estimate, and the cap

summary: tier, scope/duration estimate, and a mechanically checked cap

Every assignment to a worker states its tier explicitly — `light` for reads/counts, `standard` for
implementation, `elevated` for review/security judgment, `expert` only for an escalation after two
failed attempts on the same task — an estimate for scope or duration, and a cap. Name the cap as its
own `Cap: <n>`, checked mechanically, not from memory (`worker-cap`, `docs/ai/config.md` § Checks).
`Cap:` is recognized either on its own line or right after a `·`/`|`/`;`/`,` further into a line, so
a compact header works too, e.g. `Tier: standard · Estimate: 45–65 tool calls, ~30 minutes · Cap:
95.` Leaving the line out falls back to the tier's own default: `light` 10, `standard` 40, `elevated`
60, `high`/`expert` 80; with neither a `Cap:` nor a `Tier:` line, `standard`. The worker gets one
note on reaching the cap ("cap reached — deliver your current state now") and is refused from 1.5×
the cap onward — wrap up and report rather than push past it. Need more reasoning for one assignment
without raising the role's tier itself: name its `-high` variant instead (same tier, one reasoning
step further — see `docs/ai/config.md` § Roles for a permanent override). Read large files in
excerpts rather than in full. Only the orchestrator starts workers; a worker's proposal to split its
task comes back to the orchestrator, which cuts and starts the new assignments itself.

Every assignment also states its write scope as a `Write scope: <glob>[, <glob> ...]` line —
patterns relative to the project root, `/` as the separator, `*` crossing `/` freely (so `src/*`
already reaches any depth under `src/`); a whole directory can also be named as `dir/**` or, as a
shorthand, `dir/` (read the same way). A relative pattern (`src/**`) is the usual case; an absolute
path inside the project root (`D:/dev/x/project/src/**`) is accepted too and read as if it had been
written relative — one outside the project root is refused, unless it lies in a directory listed in
`permissions.additionalDirectories` (a sibling checkout: `../other/.act/**` or its absolute path).
`Write scope: none` means read-only, no writes at all. Leaving the line out means no restriction
beyond the template's own `.act/` write-guard.
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
given in the assignment — not on a hunch. Mechanically refused from the second status query in a
row (`status-poll`, `docs/ai/config.md` § Checks) — any other tool use in between resets it.

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
