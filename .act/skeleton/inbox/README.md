<!-- act:default -->
One file per entry — everything waiting on a person: questions, tasks for a human, tool reports,
and human notes. Both the user and the assistant add entries; nothing is deleted, only answered
and archived.

| `kind` | id | who creates it | lifecycle |
| :--- | :--- | :--- | :--- |
| `question` | `Q<n>` | assistant (`entries.py new question`) | `open` -> `answered` (reply below the question) -> `done` -> archive |
| `todo` | none | assistant or human; a task for a human, filed only once it is actionable (code pushed, questions answered) — also a tool's own action item: `init` (open points, the translate-scaffold hint), settings import (`setup-required`, a contradiction), `update` (locally-edited files it reset) | `open` -> `done` -> archive |
| `report` | none | a tool's own read-only report of what it found or did: `doctor --inbox`, `act-adopt` (adoption report) | `open` -> `done` (read) -> archive |
| `note` | none | human; the assistant replies below it | `open` -> `answered` -> `done` -> archive |

An entry without `kind:` counts as `todo`.

Which kind a tool writes follows what it asks of the reader, not who wrote it: nothing but reading
is asked -> `report`; some action is needed (configure, decide, pick up a hint) -> `todo`.

Each file opens with header fields, in this order (a field a given entry does not use is left out):

```text
id: Q101            # questions only
formerly: T29        # an id the entry had in an older numbering (adoption, --formerly)
kind: todo          # question | todo | report | note; omitted = todo
for: all            # or a workspace identity - who it is addressed to
status: open        # open -> answered -> done
created: 2026-09-25T18:30
```

File names: an entry with an id is `<ID>-<slug>.md` (e.g. `Q101-...md`); one without is
`<kind>-<YYYYMMDD-HHMM>-<slug>.md` (e.g. `report-20260925-1830-adoption.md`). In team mode, before
an id is assigned: `<P>-<identity>-<YYYYMMDD-HHMM>-<slug>.md`, renamed by `entries.py assign`.

`done` is finished and gets archived to `docs/ai/work/archive/`, whatever its `kind` —
questions included.
