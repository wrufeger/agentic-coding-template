# Working methods

Optional working patterns a project can switch on. Each file is a rule set in the grammar of the coding
rule sets in `.act/coding/` — a `summary:` line, then groups with stable ids (`MR-<set>-<name>`) — but a
set is switched on by one row in `docs/ai/config.md` § Scope, not by a checkbox:

| Key | Value |
| :--- | :--- |
| `methods` | test-first, simple-changes |

The value is a comma-separated list of the names below, or `none` (the default). The session start, `init`,
`update.py` and `python .act/scripts/rules.py --sync-methods` write each named set into
`docs/project/coding_rules.md` as an import (a section marked `<!-- act:methods -->`), so the orchestrator
and every worker load it; a group can be unchecked there like in any rule set. A name without a file here (or
in `docs/ai/local/methods/`) is reported by `act-doctor`. A project's own method is a file of the same shape
in `docs/ai/local/methods/<name>.md`.

| Name | What it asks |
| :--- | :--- |
| `test-first` | a failing test before every behavior change; a test for every acceptance criterion |
| `spec-first` | a story with numbered, checkable criteria in `docs/project/stories/` before the code |
| `simple-changes` | the smallest change, only what was assigned, assumptions named |

Not a switch, always on: concept before code (`R-work-idea-first`), evidence before "done"
(`R-work-evidence`), a red test before a fix (`act-bug`).
