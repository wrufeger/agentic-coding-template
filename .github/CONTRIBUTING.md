<!-- act:template-community -->
# Contributing

Thanks for helping improve the act template. Documentation, guides and the generated reference live at
https://wrufeger.github.io/agentic-coding-template-docs/. Everyone taking part follows the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Report a bug or suggest an idea

**The recommended and fastest way is `/act-feedback <text>`** in the AI assistant of a project built on the
template (or `feedback: <text>`). The text goes straight to the maintainer exactly as written, together with
the template commit it runs on, whether or not regular feedback is switched on in the project. Without a text after it,
`/act-feedback` collects what the project has learned about the template's rules, roles and skills, checks it
for private data and sends that. Details: [feedback guide](https://wrufeger.github.io/agentic-coding-template-docs/guides/feedback/).

No project on the template, or want a public discussion? Open an issue:

- Pick the matching form (bug report or feature request).
- Search the open issues first, and check [CHANGELOG.md](../CHANGELOG.md) for a fix in `[Unreleased]`.
- Never put secrets or real personal data in an issue; mask logs first.
- **Security vulnerabilities are never filed as an issue.** Follow [SECURITY.md](SECURITY.md).

## Pull requests

A bug report or an idea does not need a pull request; `/act-feedback` is faster for both. Pull requests make sense
for larger changes (a new rule, skill, check or config key) and for corrections you have already worked out.
Describe a larger change with `/act-feedback` or an issue first, so the direction is agreed before you spend time
on it.

Conventions for a pull request:

- Everything under `.act/` is written in English, identifiers included.
- A visible change (new or changed rule, skill, check, config key, script behavior, fix) gets an entry in
  [CHANGELOG.md](../CHANGELOG.md) under `[Unreleased]`, in Keep a Changelog form (`Added`, `Changed`, `Fixed`,
  `Security`, `Removed`), written for someone who runs a project on the template.
- After changing anything under `.act/`, refresh the manifest: `python .act/scripts/manifest.py --write`
  (`--check` shows drift).
- After changing a script's behavior or `--help`, regenerate the reference: `python .act/scripts/script_docs.py`
  (`--check` shows drift).
- A script change needs proof of a real run, for example a throwaway repo with the output pasted into the pull
  request. "It compiles" is not proof.
- No secrets, tokens or real personal data anywhere in the diff.

The maintainer runs the regression probes before merging; you do not need to run them, but say how you checked
your change.

## License

By contributing you agree that your contribution is licensed under the [MIT License](../LICENSE).
