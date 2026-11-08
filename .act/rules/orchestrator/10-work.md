# Work rules

summary: recording, process errors, restarts, concept-first, config.md, handover

## `R-work-record-now` — Write immediately, not at session end

summary: journal, task status, and inbox entries updated right after each step

Journal, task status, and new questions go to their place right after the step that produced them,
while the evidence is still fresh — not reconstructed from memory later. Where a question or open
decision goes: `R-human-ask`.

## `R-work-process-error` — A process error is reported and fixed the first time

summary: a process fault is reported at first sight as an inbox question with fixes and the process changed; template cause is feedback

A fault in how the work itself runs — workers getting in each other's way, a run checking the wrong
state, a step against a rule — is reported the first time it shows, as an inbox question with proposed
fixes (`R-human-ask`); the process changes before the work goes on, a workaround alone is not enough.
A cause in the template (a rule, skill or check) is also feedback to the template (`R-work-override`).

## `R-work-session-start` — Check restarts yourself; "continue" means work

summary: verifying a forced restart; a bare continue means keep working

After a forced restart (needed for a hook, a tool setting or a new rule file to take effect), check
unprompted whether it worked and report the result. A bare "continue" or "go on", also after `/clear`
at a task boundary (`R-work-handover`), means: read the current status — the board and the open
task's state — and keep working, not a question back. With `board-at-start` on (`docs/ai/config.md`),
it works from the board excerpt at session start and reads only the named task and its state
further.

## `R-work-idea-first` — Concept before code

summary: concept with options and a decision before building, exceptions stated aloud

An idea, feature, or change request first gets a short concept with options (`act-idea`) and a
decision, and only then gets built. Skipping this for something small is allowed, but say so out loud
so the human can object.

## `R-work-config` — `config.md` steers the work

summary: read docs/ai/config.md before a task without the hook; update it with the project

Without the session-start hook, read `docs/ai/config.md` before a task instead of assuming it is
unchanged. If the project changes in a way `config.md` describes, update it in the same step.

## `R-work-handover` — Every step ends ready to hand over

summary: state, open task, decisions and assumptions recorded for a fresh session; handover check before /clear

Even a sub-step is done only once a fresh session with no prior context could pick it up: status and
next step in `entries.py state <id> <text>` (`--wait` for a task waiting on someone or something), the
open task with goal and check criteria in its file, evidence in the journal, decisions written down,
not just in the chat. An assumption an accepted worker result rests on is confirmed, put to the human
in the inbox, or recorded in the task's state — never left only in the worker's report. A work place
outside the repo (second checkout, worktree) goes into the task with its full path. Before a manual compaction (`/compact`) record the state, after any compaction re-read the open task's state. Before advising a restart,
confirm this holds and run `act-handover`.

At a task boundary (task done and committed, no worker running, nothing left only in chat), once the
context has reached `context-hint` (`docs/ai/config.md`): run `python .act/scripts/handover.py`, fix
what it finds, and leave every open task's state line so the board alone names its next step. Only
then does the closing line say "now `/clear`" with the context size as `ctx <n>k` (`python
.act/scripts/context_size.py`), no sentence to copy: after `/clear` a bare "continue" picks up from the
board (`R-work-session-start`).
