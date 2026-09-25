<!-- act:template-readme -->
# act — agentic coding template

A thin, versioned layer that gives any project the same working agreement with its AI assistant:
rules, coding rule sets, a session dispatcher, and the scripts that keep them in sync.

**Status: rebuild in progress.** This branch (`next`) carries the new layer under `.act/` only.
The previous generation of this template lives on `main` and stays usable for existing projects.

**Getting started, in short:** clone this, open the folder in your AI assistant, and say what you
want — it checks for Python, asks whether the project goes right here or in another folder, and
does the rest (`.act/skills/act-setup/SKILL.md`; commands below are the by-hand path).

This file is the template's own — `init` (step 8) replaces it with a short project skeleton once a
project is set up from here, recognized by the `<!-- act:template-readme -->` marker on its first
line and by its content still matching the template's own version at the commit the project was
cloned from (an edit made after cloning, marker or not, is kept and noted instead); a project's own
`README.md` never carries that marker and is left untouched either way. The GitHub-facing
description of the template itself lives in `.github/README.md` (GitHub shows that one in
preference to this one), removed by the same step under the same condition.

## What is in here

| Path | Contents |
| :--- | :--- |
| `.act/rules/` | core rules, `shared/` for every role and `orchestrator/` for the main session |
| `.act/coding/` | eleven coding rule sets (`CR-<set>-<group>`), from bash to nuxt |
| `.act/scripts/` | `init.py` (set up or adopt a project), `rules.py` (read the effective rules), `board.py`, `manifest.py`, `actlib.py` |
| `.act/hooks/dispatch.py` | one entry point per session event: write guard for `.act/**`, session start |
| `.act/bridges/` | the files `init.py` generates in a project (`CLAUDE.md`, `AGENTS.md`, `docs/ai/rules.md`, hooks, git files) |
| `.act/skeleton/` | starting files for `docs/ai/` — config, inbox, proposals, working memory |

## Getting started

```bash
python .act/scripts/init.py --plan          # show what would happen
python .act/scripts/init.py                 # set up the current folder
python .act/scripts/init.py --target ../my-project
python .act/scripts/init.py --language-docs de   # docs in the owner's language (default en)
```

Read the effective rules of a project:

```bash
python .act/scripts/rules.py                # what applies, for the assistant
python .act/scripts/rules.py --list         # overview for a human
python .act/scripts/rules.py CR-python-basics
python .act/scripts/rules.py --validate     # check the project's rule files
```

## License

MIT — see `LICENSE`.
