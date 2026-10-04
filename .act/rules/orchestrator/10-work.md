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

summary: status, open task, and decisions left for a fresh session to continue

Even a sub-step (a stage, a partial task) is done only once a fresh session with no prior context
could pick it up: status and next step recorded with `entries.py state <id> <text>`
(`.act-local/state/`, surfaced on the board; the first one marks the task `started:` — a note on a
task not begun yet goes into the task file instead), the open task with goal and check criteria in the
versioned task file, evidence in the journal, and decisions made while building written down where
someone would look for them — not just in the chat history. A work place outside the repo — a
second checkout, a worktree — goes into the task with its full path. Before advising a restart
ahead of a big rebuild, first confirm this handover actually holds; only then give the advice.
