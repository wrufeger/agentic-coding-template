# Work rules

summary: recording promptly, restart checks, concept-first, config.md, handover readiness

## `R-work-record-now` — Write immediately, not at session end

summary: journal, task status, and inbox entries updated right after each step

Journal, task status, and new questions go to their place right after the step that produced them,
while the evidence is still fresh — not reconstructed from memory later. An open decision goes where
`inbox-decisions` puts it (`R-human-ask`), including one that arose only in chat;
one the human makes in chat goes into the inbox at once, answered.

## `R-work-session-start` — Check restarts yourself; "continue" means work

summary: verifying a forced restart; a bare continue means keep working

After a forced restart (needed for a hook, a tool setting, or a new rule file to take effect), check
unprompted whether it worked and report the result. A bare "continue" or "go on", also the one
after `/clear` at a task boundary (`R-work-handover`), means: read the current status — the board and
the open task's state — and keep working from there, not a question back to the human. With
`board-at-start` on (`docs/ai/config.md`), a bare "continue" works from the board excerpt at session
start and reads only the named task and its state further.

## `R-work-idea-first` — Concept before code

summary: concept with options and a decision before building, exceptions stated aloud

An idea, feature, or change request first gets a short concept with options (`act-idea`) and a
decision, and only then gets built — not the other way round. Skipping this for something small is
allowed, but say so out loud so the human can object.

## `R-work-config` — `config.md` steers the work

summary: read docs/ai/config.md before a task without the hook; update it with the project

Without the session-start hook, read `docs/ai/config.md` before a task instead of assuming it is
unchanged. If the project changes in a way `config.md` describes, update it in the same step.

## `R-work-handover` — Every step ends ready to hand over

summary: status, open task, decisions and accepted assumptions left for a fresh session to continue; at a task boundary once the context is large, the handover checked first, then /clear and a bare continue

Even a sub-step (a stage, a partial task) is done only once a fresh session with no prior context
could pick it up: status and next step recorded with `entries.py state <id> <text>`
(`.act-local/state/`, surfaced on the board), the open task with goal and check criteria in the
versioned task file, evidence in the journal, and decisions made while building written down where
someone would look for them — not just in the chat history. An assumption an accepted worker
result rests on is confirmed, put to the human in the inbox, or recorded with the task's state —
never left only in the worker's report. A work place outside the repo — a
second checkout, a worktree — goes into the task with its full path. Before advising a restart
ahead of a big rebuild, first confirm this handover actually holds; only then give the advice. Before
a restart, run `act-handover`. Before a
manual compaction (`/compact`), record the state with `entries.py state` first; after any compaction,
re-read the open task's state before continuing — the summary may have lost detail. A task waiting
on someone or something gets its state with `entries.py state <id> --wait <text>`.

At a task boundary (task done and committed, no worker running, nothing left only in chat), once the
context has reached `context-hint` (`docs/ai/config.md`), check the handover yourself first: run
`python .act/scripts/handover.py` and fix what it finds, and leave every open task's state line so
that the board alone names its next step. Only then does the closing line say "now `/clear`" — with
no sentence to copy: after `/clear` a bare "continue" picks up from the board
(`R-work-session-start`). `act-handover` stays for the human's question whether the session can be
left.
