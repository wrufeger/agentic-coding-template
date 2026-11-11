# Changelog format

summary: how CHANGELOG.md is laid out and when entries are written — presets keep-a-changelog and at-release, the starter file

Read by `init` and a migration (the starter file), `act-commit` (adds entries as it goes, only when the format says
so), `act-release` (cuts a release section, writes the notes) and `act-update`. Chosen by `changelog-format` in
`docs/ai/config.md` § Formats, or replaced by `docs/project/formats/changelog.md`. Whether the file exists at all
is the separate switch `changelog` (`file`, `release-notes-only`, `off`).

## Presets

### keep-a-changelog (default)

The layout of keepachangelog.com, one file `CHANGELOG.md` in the project root, newest release first.

- A release section is `## [X.Y.Z] - YYYY-MM-DD` and has, in this order: one head line (what the release is about, one
  sentence); `### Highlights`, 3 to 5 entries giving the reader a ten-second overview, none of them repeated in the
  list below; `### Upgrading from v<previous version>`, one line for every duty at update, each with the exact
  setting or command; then the groups `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`, only those
  with content.
- `## [Unreleased]` sits above them with a head line of its own from the first entry on (what the coming release
  is about so far, one sentence) and no highlights (they are added at release). Its first group is `### Upgrading`
  (no "from") as soon as there is a duty at update, then the groups as above.
- Writing rules, for every entry; the reader is someone who uses the project:
  1. One line; two only when an important detail would be missing otherwise. Never more than 250 characters per
     entry (the text from `- ` to the next entry, continuation lines joined by a space).
  2. Say what the reader gets or has to do, never how it is built.
  3. Keep the important details: the command or setting, its default, how to switch it off, a limit that can
     surprise, and whether an update changes anything for the reader. Leave out internals, names the reader never
     types, edge cases of checks and identifiers of your tracker.
  4. Small fixes in one area become one line.
  5. A duty at update is always its own line under `Upgrading`, never part of a collective line.
  6. A security fix is named briefly, not hidden under "smaller fixes".
- `act-doctor` reports an entry under `[Unreleased]` longer than 250 characters (switch `changelog-length` in
  `docs/ai/config.md` § Checks, default `warn`, `off` disables it).
- Entries as you go: `act-commit` adds a line under `[Unreleased]` for every commit with a visible effect (a
  feature, a changed behaviour, a fix, a removal), in the same commit. A purely internal commit gets none. It also
  keeps the head line right: writes it with the first entry (or when the section has none yet) and rewrites it
  when an entry changes what matters most.
- `act-release` renames `[Unreleased]` to the new version with the date, checks that the head line still says what
  the release is about (writes one if it is missing), adds the highlights (taking those entries out of the list),
  turns `Upgrading` into `Upgrading from <last tag>`, shortens entries that are too long and opens a new empty
  `[Unreleased]`.
  Link references at the bottom (`[X.Y.Z]: <compare url>`) only if the file already has them.

### at-release

The same layout and writing rules, but nobody touches the file between releases: `act-commit` adds nothing.
`act-release` writes the whole section for the new version, with head line, highlights and `Upgrading from
<last tag>`, from the commits since the last tag (`git log <last-tag>..HEAD`), grouped as above, and leaves
`[Unreleased]` empty.

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
