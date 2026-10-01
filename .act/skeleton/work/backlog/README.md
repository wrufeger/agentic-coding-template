<!-- act:default -->
One idea or change request per file, created with `python .act/scripts/entries.py new backlog
<title>`. The header carries the assigned `id: B<n>` once one exists (`docs/ai/config.md` §
`mode`). Once an id exists the file is named `B<n>-<slug>.md`; in team mode, before that,
`B-<identity>-<YYYYMMDD-HHMM>-<slug>.md`, renamed by `entries.py assign`. Read by
`.act/scripts/board.py` for the board's backlog list; picked up as a task once work on it starts,
left in place otherwise. With `inbox-decisions: at-start` (`docs/ai/config.md`) an entry may carry
the header field `decision: open` while its open decisions are still unanswered; the board lists it
under "Open decisions in backlog", and work on it starts only once they are answered.
