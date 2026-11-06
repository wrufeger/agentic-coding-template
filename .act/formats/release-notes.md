# Release notes format

summary: what the text of a release announcement holds — presets standard and changelog-copy

Read by `act-release` when it writes the notes for a version: the tag message, the entry published on GitHub or
GitLab and, with `changelog: release-notes-only`, the only record. Chosen by `release-notes-format` in
`docs/ai/config.md` § Formats, or replaced by `docs/project/formats/release-notes.md`.

## Presets

### standard (default)

For the people who use or deploy the project, in this order, a section left out when it has nothing to say:

1. One or two sentences: what this release is about.
2. **Breaking changes and upgrade steps** — first and unmissable when present: what breaks, what to do.
3. **Highlights** — new features, the ones worth reading about, a line each.
4. **Fixes and other changes** — the remaining visible changes, taken from the changelog section of this version
   (or, without a changelog file, from `git log <last-tag>..HEAD`, rewritten for users).
5. **Known issues** and the **lower-severity checklist** from the release's security step, when there is one.
6. A link to the full comparison (`<previous-tag>...<tag>`) when the host has such a page.

### changelog-copy

The changelog section of this version, word for word, with its heading dropped and nothing added. With no
changelog file, the groups as `act-release` would have written them.

## Applies to every preset

- Language: `language-docs`; a title of the form `<project name> X.Y.Z` unless the format file says otherwise.
- No identifiers of the project's internal tracking (tasks, backlog, questions); say what happened in words.
- Never a credential, a personal name or a local path.

## Own format file

A project file replaces all of this. Say: the audience, the sections and their order, the title form, and
whether breaking changes come first.
