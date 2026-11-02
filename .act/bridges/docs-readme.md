<!-- act:default -->
# Documentation index

What lives under `docs/`, in one table, so a new session (or a new person) knows what to read
before doing what. `act-commit` adds the line for anything new right after a task is accepted
(step 5, in the README.md of the file's folder); `act-audit-docs` sweeps the whole table for stale "data as of" dates (step 4). Edit
this file directly for anything those two miss — it stays a plain table, not a generated one.

## Index

| File | Contents | Data as of | When to read |
| :--- | :--- | :--- | :--- |
| `docs/project/` | The project's documentation as it is now; its `README.md` has one line per file and subfolder, each folder of five or more entries has one of its own (`R-docs-order`). Starts with `coding_rules.md` (which rule sets are on for this stack) and `glossary.md` (the project's own terms) | <today> | before writing or reviewing code; when a term is unclear; to find a document, read the `README.md` of its folder |
| `docs/ai/config.md` | Project configuration — steers the assistant | <today> | before any task; re-read after a change |
| `docs/ai/board.md` | Board — generated overview of what is open (not versioned by default, see `board` in `config.md`) | <today> | at session start, for the current picture |
| `docs/ai/rules.md` | Orchestrator-only rule digest, loaded at session start | <today> | orchestrator, every session (automatic) |
| `docs/ai/concept/` | One ideas file per person (`ideas-<identity>.md`): your own ideas and concept notes, picked up at the next session start | <today> | whenever you have an idea; the assistant when the session start names new entries |
| `docs/ai/inbox/`, `docs/ai/proposals/` | Things waiting for a decision: questions, tasks for a human, tool reports, notes, proposed rule changes | <today> | at session start, and before starting a new task |
| `docs/ai/work/tasks/`, `docs/ai/work/backlog/` | Open tasks (the assistant's own work) and backlog items | <today> | when picking a task or grooming the backlog |
| `docs/ai/work/ledger/` | Journal — one entry per file, newest first | <today> | to see recent activity; `board.py` reads it too |
| `docs/ai/work/archive/` | Journal collections (`ledger-*.md`), `legacy/` and `proposals/`; finished tasks, backlog items and inbox entries too where `done-entries` is `keep` (under `delete` Git history keeps them) | <today> | rarely — history, not current state |
| `docs/ai/local/` | This project's own overrides of template files | <today> | whenever the matching template file changes |
| `docs/ai/local/resources.md` | Your own reading list: own sources and private links; the template's maintained list is on the documentation site under "Further reading" | <today> | when looking for background reading, and to add a source |

This index names folders and top-level files only. A document created later under `docs/project/`
(`architecture.md`, `features.md`, `testing.md`, `decisions.md`, `incidents/`, `learnings/` — one short note per
lesson the code doesn't carry, created on first use) gets its line in `docs/project/README.md`, or in the
`README.md` of its folder — nothing here creates those files, the indexes only list what is already there.

## Per-tool display settings

`docs/ai/config.md` § "Output depth" controls what the assistant itself writes as chat text
(`verbose`, `normal`, `sparse`; levels defined in `R-human-chat`) — not what the tool's own
interface shows around that (its own verbosity/reasoning-display settings, notification style,
and similar). That is a setting of the tool, not of this project;
configure it where the tool documents it (for Claude Code, see `/config` inside a session or its
own settings file) — this file does not track it further.
