# Work rules

## `R-work-record-now` — Write immediately, not at session end

Journal, task status, and new questions go to their place right after the step that produced them,
while the evidence is still fresh — not reconstructed from memory later. Every decision goes into
the inbox, including one made only in chat. If the project changes in a way `config.md` describes,
update `config.md` in the same step.

## `R-work-session-start` — Check restarts yourself; "continue" means work

After a forced restart (needed for a hook, a tool setting, or a new rule file to take effect), check
unprompted whether it worked and report the result. A bare "continue" or "go on" means: read the
current status and keep working from there — not a question back to the human.

## `R-work-idea-first` — Concept before code

An idea, feature, or change request first gets a short concept with options and a decision, and only
then gets built — not the other way round. Skipping this for something small is allowed, but say so
out loud so the human can object.

## `R-work-config` — `config.md` steers the work

`docs/ai/config.md` governs how this project is worked on. The dispatcher reports at session start
what changed since the last sync; without that hook, read `config.md` before starting a task
instead of assuming it is unchanged.

## `R-work-handover` — Every step ends ready to hand over

Even a sub-step (a stage, a partial task) is done only once a fresh session with no prior context
could pick it up: status and next step in the board, the open task with goal and check criteria in
place, evidence in the journal, and decisions made while building written down where someone would
look for them — not just in the chat history. Before advising a restart ahead of a big rebuild,
first confirm this handover actually holds; only then give the advice.
