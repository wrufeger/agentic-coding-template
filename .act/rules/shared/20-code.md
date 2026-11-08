# Code rules

summary: English identifiers, encoding, installed tools and versions, checks left intact, project docs order

## `R-code-language` — English identifiers, project-language prose

summary: English identifiers; prose, UI text and comments in language-docs

Code identifiers — variables, functions, classes, the file and folder names of code, config keys — are
always English. Documentation, UI text and comments follow `language-docs` (`R-work-language`).

## `R-code-encoding` — Preserve file encoding

summary: detect encoding before editing; change it only as its own commit

Check a file's encoding before editing it, and keep it — don't let a UTF-8 write corrupt a
Latin-1/Windows-1252 file. Changing encoding on purpose is its own, separate commit.

## `R-code-tools` — Use what the project has installed

summary: use the project's actual tools; suggest a better one once, never install or swap unasked

Use the tools the project has actually installed and set up — testrunner, linter, formatter,
compiler, package manager. If one is outdated, or a better-fitting alternative exists, say so **once, as a hint** — never enforce it,
never install or swap it unasked.

## `R-code-version` — Match the actually installed version

summary: check the installed version before applying a version-dependent rule

Rules apply to the **actually installed** version of a language, framework, or library. Before
applying a version-dependent rule, check the version from the project files.

## `R-code-checks-intact` — Fix the code, not the check

summary: fix the code, never delete, skip, loosen or silence a failing check; a wrong check is changed as its own step

A failing test, lint or type check is made to pass in the code under test, never by weakening the
check: no deleted or skipped test (`skip`, `xfail`, `.only`, `@Disabled` …), no loosened assertion,
expected value, tolerance or timeout, no suppression (`# noqa`, `@ts-ignore`, `eslint-disable` …), no
file, rule or threshold taken out of or lowered in a check's configuration — unless the assignment
asks for exactly that. A check that is itself wrong is named in the report with the reason and
changed as its own step, never inside the fix that needed it green.

## `R-docs-order` — Project docs stay findable

summary: folder README from five entries; one topic per file; concepts archived once decided or built; mechanically checked

Every folder under `docs/project/` with five or more entries has a `README.md` naming each file and
subfolder in one line with its state (a smaller one needs none; `docs/README.md` names folders and
top-level files only); whoever adds, moves or finishes a document changes that line in the same step.
One topic per file; past about 300 lines it becomes a folder with a `README.md` and parts. Numbers in
file names only for a series with a reading order, in a folder of its own. A concept lives only while
it is open: once decided, the build goes into its backlog item or task and the reason into an ADR;
once built, the result is in the code, the journal, the project docs or a learning. Then it is
archived with `entries.py archive <file>`, `act-compact` folds it into the monthly file, and only then
is it gone — never just deleted. Checked mechanically by `act-doctor` (`docs-order`); details:
`topics/docs-order.md`.
