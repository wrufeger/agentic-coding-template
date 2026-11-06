# README format

summary: how the project README is laid out — presets standard, with-toc and minimal; sections, order, table of contents

Read by `init` (the README of a new project), `act-setup` and `act-audit-docs` (what a README should hold).
Chosen by `readme-format` in `docs/ai/config.md` § Formats, or replaced by `docs/project/formats/project-readme.md`
(not `readme.md`: a name that differs from the folder's own `README.md` only in case is the same file on Windows
and macOS). `init` only shapes the README it writes itself (the template's own README is replaced, a project's own
is never touched); on an existing README the format is what `act-audit-docs` compares against.

## Presets

### standard (default)

Sections in this order: title and one-sentence purpose · `## Getting started` (requirements, install, run) ·
`## Development` (tests, lint, how to contribute) · `## Documentation` (pointer to `docs/`) · `## License`.
No table of contents, no badges.

### with-toc

The same sections, plus a `## Contents` list of the `##` headings directly after the opening paragraph. A list
that no longer matches the headings is a finding for `act-audit-docs`.

### minimal

Title, the purpose in a few sentences and how to run it; nothing else. Fits a small tool or a library whose
documentation lives elsewhere.

## Applies to every preset

- Language: `language-docs`.
- Badges only if the format file asks for them; the README never holds anything that is only true today
  (version numbers, test counts) unless it is generated.
- The README describes the project, not the work with the assistant: that lives under `docs/ai/`.

## Own format file

A project file replaces all of this. Say: the sections and their order, table of contents yes or no, badges,
the language.
