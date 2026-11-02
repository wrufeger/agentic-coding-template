<!-- act:default -->
Finished business, kept instead of deleted: completed tasks, processed inbox entries (questions
included), and under `proposals/` every proposal that was decided. One file per entry, same name
it had before (`<ID>-<slug>.md`, `<kind>-<YYYYMMDD-HHMM>-<slug>.md`, or `YYYY-MM-DD-<slug>.md` for
journal entries); move it here rather than editing it away, so the overviews stay generated and
the history stays readable.

That is `done-entries: keep` (`docs/ai/config.md` § Archive). With `done-entries: delete` — the
default in a project under Git — `entries.py archive` deletes a finished entry once Git holds it
unchanged, and this folder keeps only the journal (the collections `ledger-<YYYY-MM>.md` and any
single files `YYYY-MM-DD-<slug>.md`), `legacy/` and `proposals/`; an entry Git does not hold yet, and every accepted task, waits here until the next
`entries.py purge`, which `act-commit` runs. The ids of deleted entries stay taken (`docs/ai/work/reserved-ids.json`).
