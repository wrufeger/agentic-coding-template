# Work rules

summary: recording promptly, restart checks, concept-first, config.md, handover readiness

## `R-work-record-now` — Write immediately, not at session end

summary: journal, task status, and inbox entries updated right after each step

Journal, task status, and new questions go to their place right after the step that produced them,
while the evidence is still fresh — not reconstructed from memory later. Every decision goes into
the inbox, including one made only in chat. If the project changes in a way `config.md` describes,
update `config.md` in the same step.

## `R-work-session-start` — Check restarts yourself; "continue" means work

summary: verifying a forced restart; a bare continue means keep working

After a forced restart (needed for a hook, a tool setting, or a new rule file to take effect), check
unprompted whether it worked and report the result. A bare "continue" or "go on" means: read the
current status and keep working from there — not a question back to the human.

## `R-work-idea-first` — Concept before code

summary: concept with options and a decision before building, exceptions stated aloud

An idea, feature, or change request first gets a short concept with options and a decision, and only
then gets built — not the other way round. Skipping this for something small is allowed, but say so
out loud so the human can object.

## `R-work-config` — `config.md` steers the work

summary: docs/ai/config.md governs the workflow; read before assuming it's unchanged

`docs/ai/config.md` governs how this project is worked on. The dispatcher reports at session start
what changed since the last sync; without that hook, read `config.md` before starting a task
instead of assuming it is unchanged.

## `R-work-handover` — Every step ends ready to hand over

summary: status, open task, and decisions left for a fresh session to continue; /clear suggested at a task boundary once the context is large

Even a sub-step (a stage, a partial task) is done only once a fresh session with no prior context
could pick it up: status and next step recorded with `entries.py state <id> <text>`
(`.act-local/state/`, surfaced on the board; the first one marks the task `started:` — a note on a
task not begun yet goes into the task file instead), the open task with goal and check criteria in the
versioned task file, evidence in the journal, and decisions made while building written down where
someone would look for them — not just in the chat history. A work place outside the repo — a
second checkout, a worktree — goes into the task with its full path. Before advising a restart
ahead of a big rebuild, first confirm this handover actually holds; only then give the advice. Before a
manual compaction (`/compact`), record the state with `entries.py state` first; after any compaction,
re-read the open task's state before continuing — the summary may have lost detail. A task waiting
on someone or something gets its state with `entries.py state <id> --wait <text>`.

Every step of a session re-sends the whole context, so a fresh session after a finished task is the
largest saving there is. At a task boundary — the task done and committed, no worker running, nothing
left only in chat — the closing line suggests `/clear` or a new session once the context has reached
`context-hint` (`docs/ai/config.md`; a one-time note says so, the status line shows the size as
`ctx`). `act-handover` checks that the handover holds and gives the sentence for the new session.
