<!-- act:default -->
Finished business, kept instead of deleted: completed tasks, processed inbox entries (questions
included), and under `proposals/` every proposal that was decided. One file per entry, same name
it had before (`<ID>-<slug>.md`, `<kind>-<YYYYMMDD-HHMM>-<slug>.md`, or `YYYY-MM-DD-<slug>.md` for
journal entries); move it here rather than editing it away, so the overviews stay generated and
the history stays readable.

A finished entry always lands here: `entries.py archive` moves it, and a decided or built concept file
(`docs/ai/concept/`, `docs/project/concepts/`) too. Nothing leaves `docs/` before it stands in its monthly
file: `act-compact` folds files older than 7 days into `Q-/T-/B-/U-/other-<YYYY-MM>.md` (concepts into
`other-`) with the overview `<YYYY-MM>.md`, and only then are the single files gone. Entries an older
template version deleted stay in Git history only.
