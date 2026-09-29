<!-- act:default -->
One task per file, created with `python .act/scripts/entries.py new task <title>`. The header
carries the assigned `id: T<n>` once one exists (`docs/ai/config.md` § `mode` decides when — see
`docs/ai/work/README.md`); the body states the goal and the check criteria. An optional header
field `issue: <URL>` links the task to an issue of the repo host — set by `act-issue` when it cuts
an issue into tasks, read by `act-pr` for the reference in the description. Once an id exists the
file is named `T<n>-<slug>.md`; in team mode, before that, `T-<identity>-<YYYYMMDD-HHMM>-<slug>.md`,
renamed by `entries.py assign`. Read by `.act/scripts/board.py` for the board; moved to
`docs/ai/work/archive/` once accepted (`docs/ai/work/archive/README.md`). The current working
state ("Stand ...") never goes into this file — it goes to the gitignored
`.act-local/state/<this file's name>` via `python .act/scripts/entries.py state <T-id> <text>`,
which the board then shows next to the task title.
