# Code rules

summary: English identifiers, encoding preservation, installed tools, installed versions, checks left intact

Shared code rules, loaded by every role. IDs (`R-<area>-<name>`) are stable and never reassigned.

## `R-code-language` — English identifiers, project-language prose

summary: English identifiers, project-language prose and comments

Code identifiers — variables, functions, classes, the file and folder names of code, config keys — are
always English. Documentation, UI text, and comments stay in the project's language.

## `R-code-encoding` — Preserve file encoding

summary: detect encoding before editing; change it only as its own commit

Check a file's encoding before editing it, and keep it — don't let a UTF-8 write corrupt a
Latin-1/Windows-1252 file. Changing encoding on purpose is its own, separate commit.

## `R-code-tools` — Use what the project has installed

summary: use the project's actual tools; suggest a better one once, never install or swap unasked

Use the tools the project has actually installed and set up — testrunner, linter, formatter,
compiler, package manager — and read them from the project files instead of assuming a favorite
tool. If a tool is outdated, or a better-fitting alternative exists, say so **once, as a hint** —
never enforce it, never install or swap it unasked. Example: if the project has Selenium,
Nightwatch, or Cypress set up, use that one, not Playwright.

## `R-code-version` — Match the actually installed version

summary: check the installed version before applying a version-dependent rule

Rules apply to the **actually installed** version of a language, framework, or library. Before
applying a version-dependent rule, check the version from the project files (lockfile,
`package.json`, `composer.json`, `pyproject.toml`, `pom.xml`, `go.mod`, project file) and match
the rule to it; a rule for a version the project doesn't have is not applied.

## `R-code-checks-intact` — Fix the code, not the check

summary: a failing test, lint or type check is fixed in the code, never by deleting, skipping, loosening or silencing it; a wrong check is named and changed as its own step

A failing test, lint or type check is made to pass in the code under test, never by weakening the
check: no deleted or skipped test (`skip`, `xfail`, `.only`, `@Disabled`, `t.Skip` …), no loosened
assertion, expected value, tolerance or timeout, no suppression (`# noqa`, `# type: ignore`,
`@ts-ignore`, `eslint-disable` …), no file, rule or threshold taken out of or lowered in a check's
configuration — unless the assignment asks for exactly that. A check that is itself wrong is
named in the report with the reason and changed as its own step, never inside the fix that needed
it green.
