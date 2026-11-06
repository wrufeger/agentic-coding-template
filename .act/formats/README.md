# Formats

summary: the template's default formats for commit messages, the changelog, release notes and the README, and how a project overrides them

The skills that write a commit message, a changelog entry, release notes or a README read their format from
here. A project changes a format in two ways; the file wins.

1. **Switch** — one row per subject in `docs/ai/config.md` § Formats (`commit-format`, `changelog-format`,
   `release-notes-format`, `readme-format`) picks a named preset out of the file below. A missing row, an empty
   value, `auto` and an unknown name all mean the file's default preset.
2. **Project file** — `docs/project/formats/<name>.md` (same file name as here) replaces the template file for
   that subject completely: the skill reads the project file and ignores both the switch and this folder's file.
   Write it in the project's documentation language; copy the template file as a start.

| Subject | File | Switch | Read by |
| :--- | :--- | :--- | :--- |
| Commit message | `commit.md` | `commit-format` | `act-commit`, `act-pr` |
| Changelog | `changelog.md` | `changelog-format` (and `changelog`, whether the file exists) | `act-commit`, `act-release`, `init`, `act-update` |
| Release notes | `release-notes.md` | `release-notes-format` | `act-release` |
| README | `project-readme.md` | `readme-format` | `init`, `act-setup`, `act-audit-docs` |

`documents/` is a different kind of file: a guide to which project document to write and short scaffolds (decision
record, API spec, security checklist, deployment note) to copy into `docs/project/`. No switch, no override.

Never edit files here in a project (`R-work-override`); `docs/project/formats/` is the project's place.
`act-export-settings` carries the project's format files along, `act-load-settings` writes them back.
