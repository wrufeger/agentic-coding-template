# Project configuration

`init` fills in the values below from what it asked or detected. Change them any time — nothing
here needs a rebuild; `.act/hooks/dispatch.py` reads this file at session start.

## Project

| Key | Value |
| :--- | :--- |
| `name` | <name> |
| `owner` | <owner> |
| `language` | <language> |
| `stack` | <stack> |
| `commands` | <lint-command>, <typecheck-command>, <test-command> |
| `tools` | <tool-list> |
| `mode` | <mode> |

`mode` is `solo` or `team`, and it changes **one** thing: when an entry gets its short ID. In
`solo` the assistant assigns it right away (`Q66`, `T19`, `B99`) and carries on. In `team` only
whoever files the entry on the default branch assigns it, so two people can never hand out the
same number; until then the file name is what you cite. File name, location and format are the
same either way, so you can switch back and forth at any time — IDs already assigned stay as they
are, only later ones follow the new value.

## Output depth

| Key | Value |
| :--- | :--- |
| `output-depth` | normal |

`verbose` \| `normal` \| `sparse`. Controls what the assistant *writes* in chat, not what the
tool's own interface displays — see `docs/README.md` for the per-tool display settings.

## Dependencies

| Key | Value |
| :--- | :--- |
| `dependency-check` | once |

`never` \| `once` \| `regularly`. `once` runs the `act-deps` check during setup and afterwards only
on request; `regularly` repeats it on the periodic review; `never` skips it. Today only the
`act-deps` skill itself reads this key — no mechanism runs it automatically yet.

## Checks

Each check below runs before the action it names; `block` refuses the action, `warn` allows it
with a note, `off` skips the check entirely. Stage 1 ships one mechanized check; later stages
add more rows to this same table.

| Check | Value | Guards |
| :--- | :--- | :--- |
| `template-write-guard` | block | writes under `.act/` — put a project version in `docs/ai/local/<same path>` instead |
| `session-start-refresh` | block | rebuilds the generated bridges and the board at session start; `warn` reports without writing, `off` skips it |
| `orchestrator-rules` | block | hands the orchestrator-only rules to the main session at session start; `off` skips it |
| `worker-nesting-guard` | block | a sub-agent calling `Agent`/`Task` (no sub-sub-agents, `R-role-worker`) — `warn` reports without blocking, `off` skips it |
| `worker-write-scope` | block | a worker writing outside its assignment's `Write scope:` line (`R-cost-delegate`) — `warn` reports without blocking, `off` skips it |
| `update-branch-hint` | warn | update or settings import on a branch other than the default one: one note that the others get it only with the merge — never refuses, `block` counts as `warn`, `off` drops the note |
| `update-check` | block | at session start: a note if `.act/` was pulled in without `update.py`, and — at most once a day — a note if the template has moved on; never refuses, `off` skips both |

## Roles

| Role | Tier | Reasoning | Model |
| :--- | :--- | :--- | :--- |

Empty by default: every role runs the tier/reasoning the template ships. Fill a row to override
one role's tier and/or reasoning, or set `Model` outright — a filled `Model` wins over `Tier`.
