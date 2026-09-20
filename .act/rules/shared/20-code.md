# Code rules

summary: English identifiers, encoding preservation, installed tools, installed versions

Shared code rules, loaded by every role. IDs (`R-<area>-<name>`) are stable and never reassigned.

## `R-code-language` — English identifiers, project-language prose

summary: English identifiers, project-language prose and comments

Code identifiers — variables, functions, classes, file and folder names, config keys — are
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
