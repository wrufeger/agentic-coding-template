<!-- act:default -->
The assistant's shared working memory — tasks, backlog items, journal entries — not personal
notes. Only the assistant writes here, one file per entry; overviews are generated from these
files, never hand-maintained. Every file `entries.py new` creates carries `created: <timestamp>`
in its header — without it, two branches filing the same title on the same day could produce two
byte-identical files that Git then merges into one silently instead of flagging a conflict.

- `tasks/` — one open task per file, only the assistant's own work; goal and check criteria; read
  by `board.py` for the board. The header carries `for: <identity>` (whose task it is;
  `entries.py new task` writes the current workspace identity, `--for` changes it, `all` or no
  field = shared); the board lists other people's tasks apart (`board-others` in `config.md`).
  Working state (`Stand ...`) goes to `.act-local/state/` instead (`entries.py state <id> <text>`),
  not into the task file itself.
- `backlog/` — ideas and change requests not yet built, one per file.
- `ledger/` — journal entries, one per step, named `YYYY-MM-DD-<slug>.md`; read by `board.py` for
  the board's recent history.
- `archive/` — finished business moved out of the three folders above; see its own `README.md`.
