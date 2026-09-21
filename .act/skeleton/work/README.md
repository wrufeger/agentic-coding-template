The assistant's shared working memory — tasks, backlog items, journal entries — not personal
notes. Only the assistant writes here, one file per entry; overviews are generated from these
files, never hand-maintained.

- `tasks/` — one open task per file, goal and check criteria; read by `board.py` for the board.
- `backlog/` — ideas and change requests not yet built, one per file.
- `ledger/` — journal entries, one per step, named `YYYY-MM-DD-<slug>.md`; read by `board.py` for
  the board's recent history.
- `archive/` — finished business moved out of the three folders above; see its own `README.md`.
