---
name: act-setup
description: Use when setting up a project in a fresh template clone, or when the owner asks to set up, initialize or install one (triggers "setup", "initialize", "install", "richte … ein", "neues Projekt"). Docks this checkout onto a project. Not for taking over existing docs - use act-adopt.
---

# Set up a project

Runs in the main session, with the owner. Nobody types a `python` command by hand — the assistant runs every
command itself and reports what happened. In order:

## 1. Check Python is there

Accept the first of `python3`, `python`, `py -3` whose `-c "import sys; print(sys.version)"` genuinely prints a
version `>= 3.9` (the Windows Store placeholder does not count). If none does, read
`references/python-install.md` and stop until it works; after the owner installs it, check again — don't take
their word for it.

## 2. Ask which of the two ways

Skip this in a checkout that is already a project (`CLAUDE.md`/`AGENTS.md` have no `<!-- act:bootstrap -->` on
line 1) — offer only way 2 there. Otherwise ask, in the owner's own words, and answer in their language (suggest
it as `--language-docs`):

1. **A new project, right here in this clone.** The template's `origin` is cut and the project starts on a fresh
   `main` without history; the template's branch is removed (it stays, with an inbox entry, if it holds commits of
   the owner's own). Template updates come only through `act-update` from then on.
2. **A project somewhere else** (a new folder, or one with a project in it). Ask for the path.

Then ask once whether a working method should be on (`test-first`, `spec-first`, `simple-changes`; default none;
list in `.act/methods/README.md`).

## 3. Run it

`init.py` never prompts when the assistant runs it (no terminal for the owner to answer into): it takes its
defaults and logs every open point to the project's inbox. Flags: `python .act/scripts/init.py --help` — pass
what step 2 established (`--language-docs`, `--language-chat`, `--methods <names>`, `--no-commit`). The scope
profile follows the detected stack (`full` for a web project, `standard` otherwise; `--scope` overrides).

**Way 1:** `python .act/scripts/init.py --plan`, show the output, get a go-ahead, run it for real. Then go
through the `U<n>-init-notes.md` inbox entry with the owner and enter the answers into `docs/ai/config.md`.

**Way 2:** with a missing or empty folder, `init.py --target <path> --plan`, then without `--plan`. A folder
with content goes to `.act/skills/act-adopt/SKILL.md` instead.

**Translate the scaffold in this same run.** With a `language-docs` other than `en`, `init.py` files
`docs/ai/inbox/U<n>-translate-scaffold.md` listing the files still in English (`<!-- act:default -->` on line 1);
it has no model to translate with, so the todo is only the fallback, never something to hand to the owner.
Translate every listed file following the todo (`R-work-language`) and drop that line. Set the todo to
`status: done`, `git mv` it to `docs/ai/work/archive/` (with `--no-commit` the todo is untracked: move it as a plain
file), and commit the translated files and both paths of the todo
by pathspec in one commit (`docs: translate scaffold into <code>`); with `--no-commit` leave everything
uncommitted together with `init.py`'s changes.

**What `init.py` also writes.** A `CHANGELOG.md` with an empty `## [Unreleased]` (switch `changelog` in
`docs/ai/config.md` § Formats) and a README in the layout of `readme-format`. Both formats: `.act/formats/README.md`.
Mention it once. The methods go into the `methods` row and `docs/project/coding_rules.md`; change them later with
`/act-config methods <names|none>`, then `python .act/scripts/rules.py --sync-methods`.

## 4. Say what is there now

In three sentences: where the board and open questions live now (`docs/ai/work/`, `docs/ai/inbox/`), that the
rules and skills are live from here on, and what to look at first (an inbox note `init` left, or the adoption
table for way 2's second path). Read `references/after-setup.md` when one of those notes offers
`security-check: deps`.
