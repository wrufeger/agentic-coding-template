# Code rules

Shared code rules, loaded by every role. IDs (`R-<area>-<name>`) are stable and never reassigned.

## `R-code-language` — English identifiers, project-language prose

Code identifiers — variables, functions, classes, file and folder names, config keys — are
always English. Documentation, UI text, and comments stay in the project's language.

## `R-code-encoding` — Preserve file encoding

Check a file's encoding before editing it, and keep it — don't let a UTF-8 write corrupt a
Latin-1/Windows-1252 file. Changing encoding on purpose is its own, separate commit.
