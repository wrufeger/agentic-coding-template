# Cost rules

summary: when to delegate, delegation tiers and caps, waiting on workers, amending a running assignment, scripting recurring checks, commit gate

## `R-cost-delegate` — Name the tier, the estimate, and the cap

summary: delegate where a handover pays off, template roles before the tool's own agents; tier, estimate in minutes and tkn fresh/cache, a mechanically checked cap, small assignments

A handover costs a worker's fresh start and loses context, so delegate only where it pays off:
independent parts that run in parallel, a check that should not share the implementation's
context (the review), output of unknown or large length not needed afterwards, long reading or
runs that a cheaper tier does just as well. A known file or spot, a few tool calls or a small
change you do yourself; its review still follows `R-code-commit`. The template's roles come before
the tool's own agents (in Claude Code `Explore`, `general-purpose`, `Plan`; its `claude-code-guide`
stays for questions about the tool itself).

Every assignment to a worker states its tier explicitly — `light` for reads/counts, `standard` for
implementation, `elevated` for review/security judgment, `expert` only for an escalation after two
failed attempts on the same task — an estimate in the fixed form `~<n> min · ~<n> tkn fresh · ~<n>
tkn cache` (wall-clock minutes; `fresh` = input, cache-writing and output tokens, `cache` =
cache-read tokens; never person-days), based on `python .act/scripts/usage.py --estimates` where it
has measured runs of that role/tier — and a cap. Name the cap as its own `Cap: <n>`, checked
mechanically, not from memory (`worker-cap`, `docs/ai/config.md` § Checks). Need more reasoning for
one assignment without raising the role's tier itself: name its `-high` variant instead (same tier,
one reasoning step further — see `docs/ai/config.md` § Roles for a permanent override). Read large
files in excerpts rather than in full. Cut assignments small: a judgment assignment (a verdict per
entry or per file) covers about 10–12 units per worker — with more, the verdicts turn shallow while
every further tool call re-reads a growing context; rework goes out as a new, short assignment
instead of continuing a worker whose context is already full; plain reading and counting suits
`light`. Only the orchestrator starts workers; a worker's proposal to split its task comes back to
the orchestrator, which cuts and starts the new assignments itself. Details (compact header, default
cap per tier, the note at the cap and the refusal beyond it): `topics/checks.md`.

Every assignment also states its write scope as a `Write scope: <glob>[, <glob> ...]` line, patterns
relative to the project root. `Write scope: none` means read-only: no writes in the project, only
into the system temp directory as a path written out (`/tmp/...` in Bash, or its absolute path) —
every worker may write there, whatever its scope, unless the project itself lies inside it. Leaving
the line out means no restriction beyond the template's own `.act/` write-guard. Checked
mechanically by `worker-write-scope` (`docs/ai/config.md` § Checks); pattern syntax and limits:
`topics/checks.md`.

Workers running at the same time get separate write scopes; assignments whose scopes overlap run one
after the other. Checked mechanically by `worker-scope-overlap` (`docs/ai/config.md` § Checks).

An assignment that reads another worker's result names it as its own line, `Depends on: <whose
result>`. It starts only after that worker has ended. When several workers are to read the same
material, the orchestrator writes what it found once to a brief note
`.act-local/notes/brief-<slug>.md` and names that file in each assignment.

## `R-cost-wait` — Let a started worker finish

summary: letting a started worker finish; checking in only past the estimate

A worker reports back on its own when it is done; polling its status repeatedly does not speed it up
— it costs tokens on every call and clutters the chat. Start the assignment, then either work on
something independent or wait; check in only once runtime clearly exceeds the estimate given in the
assignment — not on a hunch. Checked mechanically by `status-poll` (`docs/ai/config.md` § Checks),
which refuses a second status query in a row. An addition from the human that concerns the running
assignment does not wait for its end (`R-cost-amend`). Details: `topics/checks.md`.

## `R-cost-amend` — Amend a running assignment instead of queuing a second

summary: an addition that fits a running worker goes to it at once; stop and reassign when one new run is cheaper than two; only an unrelated addition waits

Saving tokens is the aim here too: a second assignment after the first reads the same files and
context again that the first one has just read. So an addition from the human that concerns a
running worker's assignment — it changes, extends or replaces it — goes to that worker at once,
where the tool can message a running worker. If it changes the assignment so far that one new run
costs less than letting the current one finish and starting a second (the current one heads the
wrong way, or most of what it still has to do would be redone), stop it and assign anew, passing on
what it has found so far. Only an addition that does not touch the running assignment becomes its
own assignment once the first one has ended. An addition that needs a wider `Write scope:` or a
higher `Cap:` than the running assignment has always means stop and reassign: both are read once,
from the assignment that started the worker, so a message to the running worker cannot widen them.

## `R-cost-script` — Script instead of worker for recurring checks

summary: recurring counting or status checks as a script, not a repeated worker task

Recurring counting or status work (file counts, state checks) becomes a script the first time it
comes up, then is only run, not re-delegated to a worker.

## `R-code-commit` — Committing is the orchestrator's job alone

summary: pathspec-only commits after lint/typecheck/tests where configured; reviewer verdict CONDITIONAL filed in the inbox

Only accepted work gets committed, staged by pathspec — never `git add -A`, `git add .`, or
`git commit -a`. Lint, typecheck, and tests run first, but only where the project has them set up
(an IDE's own check counts as evidence, not as a configured lint) and no rule suspends the check for
this case. A missing tool is not a reason to install one or add tests on the spot — at most a
one-time note that it is missing. The `reviewer` runs once per task before acceptance, not after
every step, and ends with a verdict: `ALLOW`, `CONDITIONAL` or `BLOCK`; for a trivial change (typo,
docs only) the orchestrator skips it and says so. `CONDITIONAL` means acceptable once one named
condition is met that cannot be checked in the same step (a run only possible after the commit, a
measurement, an approval); a known bug or a missed part of the assignment is always `BLOCK`, and so
is a `CONDITIONAL` with no recognisable condition or with more than one. On `CONDITIONAL` the
orchestrator commits, files the condition in the same step as a `todo` or `question` in the inbox
(`entries.py new …`), and names its id in the commit message (`act-commit`). After a BLOCK the
orchestrator checks the fixes itself — a second review only for a critical finding.
