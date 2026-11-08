# Cost rules

summary: delegation and assignment header, waiting, amending, scripting, commit gate, diff check, reset and discard

## `R-cost-delegate` — Delegate where it pays off; the assignment header

summary: delegate where a handover pays off; header lines Write scope, Cap, Tests; tier from the role; small assignments, parallel parts, no test run beside a writer

A handover costs a fresh start and loses context, so delegate only where it pays off: independent
parts in parallel, a check that should not share the implementation's context (the review), output of
unknown or large length not needed afterwards, long reading or runs a cheaper tier does as well.
Research across more than three files or an unknown spot, the evaluation of transcripts, logs or
feedback, and material past about 20k tokens go to `explorer`; a test, probe or smoke-test run named
in the assignment goes to `quick-check`. A known spot, a few tool calls, a small change, an entry
under `docs/ai/`, a commit or `git status` you do yourself; its review still follows `R-code-commit`.
The template's roles come before the tool's own agents (`Explore`, `general-purpose`, `Plan`;
`claude-code-guide` stays for the tool itself).

**Assignment header.** Mandatory, each at the start of a line (only `Cap:` may also follow a `·`/`|`/`;`/`,`):
`Write scope: <glob>[, <glob> ...]` (relative to the project root; `none` = read-only; throwaway
material needs `.act-local/tmp/<task-id>-<slug>/**`), `Cap: <n>` (tool calls; a note at the cap,
refusal from 1.5×) and, where something runs, `Tests: <glob>[, <glob> ...]` (the tree it reads).
Checked mechanically by `worker-write-scope`, `worker-cap` and `worker-scope-overlap`. The tier follows
from the role; a `Tier:` line names a deviation only; more reasoning:
`builder-high`/`reviewer-high`. The estimate (`~<n> min · ~<n> tkn fresh · ~<n> tkn cache`, wall-clock
minutes, from `python .act/scripts/usage.py --estimates`) is given from `standard` up. `Depends on:
<whose result>` only where the assignment reads another worker's result; it starts after that worker
has ended. Cap defaults, pattern syntax, limits: `topics/checks.md`.

Cut assignments small: a judgment assignment (a verdict per entry or file) covers about 10–12 units;
rework goes out as a new, short assignment, not to a worker whose context is full. Work expected to
run longer than about five minutes is first checked for independent parts (test and probe runs, case
catalogs, separate files, a review per spot) and split into parallel assignments with separate write
scopes, the saving measured before and after — not when the parts write the same file, build on one
another or would each reread the same large material. Tasks that touch the same files get one joint
assignment first (one write scope, a higher cap, one review, commits by path); in sequence only when
that would overload one context, with the reason stated. Workers reading the same material get what
the orchestrator found once in `.act-local/notes/brief-<slug>.md`, named in each assignment.

No test or probe run (the full suite, a worker's probes, a review that executes something) goes
against a tree a worker writes in at that time: the full suite runs once after the reviews are
accepted, during rework only the rework's own tests, and a run still going when rework starts or
another worker begins writing there is stopped and restarted on the new state. Parallel builders that
must test while others build each test an isolated copy (clone or worktree). `worker-scope-overlap`
refuses a start whose `Tests:` meets a running worker's `Write scope:` or the reverse; the
orchestrator's own write or test run there only gets a note, the rest is its to keep.

## `R-cost-wait` — Let a started worker finish

summary: letting a started worker finish; checking in only past the estimate

A worker reports back on its own when it is done; polling its status does not speed it up. Start it,
then work on something independent or wait; check in only once the runtime clearly exceeds the
estimate. Checked mechanically by `status-poll`. An addition from the human that concerns the running
assignment does not wait for its end (`R-cost-amend`). Details: `topics/checks.md`.

## `R-cost-amend` — Amend a running assignment instead of queuing a second

summary: an addition that fits a running worker goes to it; stop and reassign if one new run is cheaper; an unrelated one waits

An addition from the human that concerns a running worker's assignment goes to that worker at once,
where the tool can message a running worker. If it changes the assignment so far that one new run
costs less than finishing the current one and starting a second, stop it and assign anew,
passing on what it found. Only an addition that does not touch the running assignment waits and
becomes its own assignment. One that needs a wider `Write scope:` or a higher `Cap:` always means
stop and reassign: both are read once, at the start.

## `R-cost-script` — Script instead of worker for recurring checks

summary: recurring counting or status checks as a script, not a repeated worker task

Recurring counting or status work (file counts, state checks) becomes a script the first time it
comes up, then is only run, never re-delegated.

## `R-code-commit` — Committing is the orchestrator's job alone

summary: pathspec-only commits after lint/typecheck/tests where configured; CONDITIONAL verdict filed in the inbox

Only accepted work gets committed, with no separate request, whatever the tool's default says. It is
staged by pathspec — never `git add -A`, `git add .` or `git commit -a`. Lint, typecheck and tests
run first where the project has them set up (an IDE's own check counts as evidence, not as a
configured lint) and no rule suspends them. The `reviewer` runs once per task before acceptance, not
after every step, and ends with `ALLOW`, `CONDITIONAL` or `BLOCK` (`act-commit`); for a trivial change
(typo, docs only) the orchestrator skips it and says so. On `CONDITIONAL` it commits, files the
condition in the same step as a `todo` or `question` in the inbox, and names its id in the commit
message. After a BLOCK it checks the fixes itself — a second review only for a critical finding.

## `R-safe-no-secret-diff` — Check the diff before every commit

summary: a secret in the diff stops the commit; mechanically checked

A secret in the diff stops the commit and is reported, never silently stripped. Checked mechanically
by `secret-scan`; what it looks for: `topics/checks.md`.

## `R-safe-git-reset` — Check before `git reset --hard`; no other git command discards work either

summary: never reset --hard over open changes; also no clean -f, folder checkout/restore, stash drop/clear, force push to the default branch, branch -D of an unmerged branch

With open changes — including untracked files, which `git reset --hard` overwrites silently too —
never run `git reset --hard`: use `git stash -u` or `git reset --soft`. Check what would be discarded
first (`git log -1`, `git reflog`) and run no Git experiments in a tree with open changes. These
throw work away with no way back as well: `git clean -f`; a folder checkout or restore, or a forced
checkout or switch, over uncommitted changes; dropping or clearing the stash; a forced push to the
default branch, or deleting it on the remote; `git branch -D` of an unmerged branch. Single files stay
free. Commit, `git stash`, or have the owner do it. Checked mechanically by `git-reset-hard` and
`git-discard`; exact conditions: `topics/checks.md`.

## `R-safe-git-discard` — Part of `R-safe-git-reset`

summary: part of R-safe-git-reset: the other work-discarding git commands, checked by git-discard

One rule with `R-safe-git-reset` above.
