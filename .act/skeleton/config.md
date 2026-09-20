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

## Output depth

| Key | Value |
| :--- | :--- |
| `output-depth` | normal |

`verbose` \| `normal` \| `sparse`. Controls what the assistant *writes* in chat, not what the
tool's own interface displays — see `docs/README.md` for the per-tool display settings.

## Checks

Each check below runs before the action it names; `block` refuses the action, `warn` allows it
with a note, `off` skips the check entirely. Stage 1 ships one mechanized check; later stages
add more rows to this same table.

| Check | Value | Guards |
| :--- | :--- | :--- |
| `template-write-guard` | block | writes under `.act/` — put a project version in `docs/ai/local/<same path>` instead |
| `session-start-refresh` | block | rebuilds the generated bridges and the board at session start; `warn` reports without writing, `off` skips it |
