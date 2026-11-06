# Commit message format

summary: how a commit message is built — presets auto, conventional, plain; subject length, language, trailers

Read by `act-commit` (step "Commit by pathspec") and `act-pr` (title in the commit style). Chosen by
`commit-format` in `docs/ai/config.md` § Formats, or replaced by `docs/project/formats/commit.md`.

## Presets

### auto (default)

Follow the repository's own style: look at the last ten commits (`git log --oneline -10`) and write the new
message the same way — same language, same prefix habit, same case. Without a usable history, use `plain`.

### conventional

Conventional Commits: `<type>(<scope>): <subject>`, scope optional.

- Types: `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.
- A breaking change adds `!` after the type or scope (`feat(api)!: drop v1`) and a `BREAKING CHANGE: <what
  breaks and what to do>` paragraph in the body.
- Subject: imperative, lower case after the colon, no full stop, at most 72 characters.
- Body (optional): what and why, not how; blank line after the subject, wrapped at 100.

### plain

A short imperative sentence, at most 72 characters, no type prefix and no full stop; a body only when the why is
not obvious from the diff.

## Applies to every preset

- Language: the project's `language-docs` unless the history clearly uses another one.
- A ticket or task reference goes into the body or the subject only if the history does it that way; never an
  identifier of the template's own maintenance.
- Trailers (`Co-Authored-By`, `Claude-Session`, …) stay exactly as the running session gives them and come last,
  after a blank line.
- One logical change per commit; the message describes that change, not the session.

## Own format file

A project file replaces all of this. Say at least: the pattern (an example line is enough), the language, the
longest subject, whether a ticket reference is required and where it goes, and which trailers appear. The skill
checks its message against the example before committing.
