<!-- act:default -->
# Documentation index

What lives under `docs/`, in one table, so a new session (or a new person) knows what to read
before doing what. `act-commit` adds a row for anything new right after a task is accepted
(step 5); `act-audit-docs` sweeps the whole table for stale "data as of" dates (step 4). Edit
this file directly for anything those two miss — it stays a plain table, not a generated one.

## Index

| File | Contents | Data as of | When to read |
| :--- | :--- | :--- | :--- |
| `docs/project/coding_rules.md` | Which rule sets/groups are on for this stack | <today> | before writing or reviewing code |
| `docs/ai/config.md` | Project configuration — steers the assistant | <today> | before any task; re-read after a change |
| `docs/ai/board.md` | Board — generated overview of what is open (not versioned by default, see `board` in `config.md`) | <today> | at session start, for the current picture |
| `docs/ai/rules.md` | Orchestrator-only rule digest, loaded at session start | <today> | orchestrator, every session (automatic) |
| `docs/ai/inbox/`, `docs/ai/proposals/` | Things waiting for a decision: questions, tasks for a human, tool reports, notes, proposed rule changes | <today> | at session start, and before starting a new task |
| `docs/ai/work/tasks/`, `docs/ai/work/backlog/` | Open tasks (the assistant's own work) and backlog items | <today> | when picking a task or grooming the backlog |
| `docs/ai/work/ledger/` | Journal — one entry per file, newest first | <today> | to see recent activity; `board.py` reads it too |
| `docs/ai/work/archive/` | Finished tasks/backlog/proposals, kept for reference | <today> | rarely — history, not current state |
| `docs/ai/local/` | This project's own overrides of template files | <today> | whenever the matching template file changes |

A file created later under `docs/project/` (`architecture.md`, `features.md`, `testing.md`,
`decisions.md`, `incidents/`) gets its own row here once it exists — nothing here creates those
files, this index only lists what is already there.

## Per-tool display settings

`docs/ai/config.md` § "Output depth" controls what the assistant itself writes as chat text —
not what the tool's own interface shows around that (its own verbosity/reasoning-display
settings, notification style, and similar). That is a setting of the tool, not of this project;
configure it where the tool documents it (for Claude Code, see `/config` inside a session or its
own settings file) — this file does not track it further.
