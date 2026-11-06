# Changelog format

summary: how CHANGELOG.md is laid out and when entries are written — presets keep-a-changelog and at-release, the starter file

Read by `init` and a migration (the starter file), `act-commit` (adds entries as it goes, only when the format says
so), `act-release` (cuts a release section, writes the notes) and `act-update`. Chosen by `changelog-format` in
`docs/ai/config.md` § Formats, or replaced by `docs/project/formats/changelog.md`. Whether the file exists at all
is the separate switch `changelog` (`file`, `release-notes-only`, `off`).

## Presets

### keep-a-changelog (default)

The layout of keepachangelog.com, one file `CHANGELOG.md` in the project root, newest release first.

- Sections per release: `## [X.Y.Z] - YYYY-MM-DD`, above them `## [Unreleased]`. Inside a section, groups in this
  order and only those with content: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.
- One line per entry, from the point of view of someone who uses the project, not the commit title.
- Entries as you go: `act-commit` adds a line under `[Unreleased]` for every commit with a visible effect (a
  feature, a changed behaviour, a fix, a removal), in the same commit. A purely internal commit gets none.
- `act-release` renames `[Unreleased]` to the new version with the date and opens a new empty `[Unreleased]`.
  Link references at the bottom (`[X.Y.Z]: <compare url>`) only if the file already has them.

### at-release

The same layout, but nobody touches the file between releases: `act-commit` adds nothing. `act-release` writes the
whole section for the new version from the commits since the last tag (`git log <last-tag>..HEAD`), grouped as
above, and leaves `[Unreleased]` empty.

## Starter file

`init` creates `CHANGELOG.md` with this text when the project has none (and `changelog` is `file`); a project
format file may carry its own block of this kind under the same heading, which then wins. The first fenced block
below the heading is the file, exactly:

```markdown
# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]
```

## Own format file

A project file replaces all of this. Say: the layout and the grouping (by release, by date, by type, by
commit), the language, whether entries are written as you go or at release, and optionally a `## Starter file`
block as above.
