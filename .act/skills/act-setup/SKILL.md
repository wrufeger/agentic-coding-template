---
name: act-setup
description: Set up this checkout as a project, or dock it onto one that already exists - the first thing to run in a fresh template clone, and whenever the owner asks to set up, initialize or install a project. Triggers include "setup", "initialize", "install", "richte ... ein", "neues Projekt".
---

# Set up a project

Runs in the main session, with the owner. Nobody types a `python` command by hand — the assistant
runs every command itself and reports what happened. Follow these steps in order.

## 1. Check Python is there

Try, in order, `python3 --version`, `python --version`, and on Windows `py -3 --version`; the
first one whose output looks like a version answers. A bare `python`/`py` reachable through the
Windows Store placeholder does not count — confirm with a command that actually runs code:

```bash
python3 -c "import sys; print(sys.version)"
```

Accept the first candidate where this genuinely prints a version `>= 3.9`. If none does, Python is
missing or too old — explain installing it, by platform, and stop until it works:

- **Windows:** https://www.python.org/downloads/ , or `winget install Python.Python.3.12` in a
  terminal; either way, tick "Add python.exe to PATH" in the installer. Details:
  https://docs.python.org/3/using/windows.html
- **macOS:** https://www.python.org/downloads/ , details:
  https://docs.python.org/3/using/mac.html
- **Linux/Unix:** the distribution's package manager, or https://www.python.org/downloads/ ,
  details: https://docs.python.org/3/using/unix.html

After the owner installs it, check again before continuing — don't take their word for it.

## 2. Ask which of the two ways

Skip this in a checkout that is already a project (`CLAUDE.md`/`AGENTS.md` in the root have no
`<!-- act:bootstrap -->` marker on line 1) — offer only way 2 there. Otherwise ask, in the owner's
own words if they already used any, and answer in the language they answer in (suggest that
language as `--language-docs` below):

1. **A new project, right here in this clone.** The connection to the template's own repository is
   cut (`origin` removed), and the project starts on a fresh `main` with no history of its own —
   the template's branch is removed afterward so nobody merges it into the project by accident
   (only while it holds nothing but the template's own history — with commits of the owner's own
   on it, it stays and an inbox entry says so).
   From then on, template updates come only through `act-update`.
2. **A project somewhere else** (a new folder, or one that already has a project in it). Ask for
   the path.

## 3. Run it

**Way 1:**

```bash
python .act/scripts/init.py --plan
```

Run by the assistant, `init.py` never prompts (in a terminal of their own the owner gets its
questions) — the assistant's own Bash tool has no terminal for the owner to answer into (`actlib.is_interactive()` reads false there), and there are no flags for name, owner,
stack or tools to pass along either. Show the plan output, get a go-ahead, then run `init.py` for
real; it takes its defaults and logs every open point (name, owner, stack, tools, and anything else
it could not decide) to the project's inbox instead of asking. Check
`python .act/scripts/init.py --help` for the exact flags before running it — `--language-docs`,
`--language-chat`, `--no-commit` — and pass what step 2 established. Afterward, go through the
`*-init-notes.md` inbox entry (`U<n>-init-notes.md`) ("Open points from `init.py`" / German "Offene Punkte von
`init.py`") with the owner and enter the answers into `docs/ai/config.md`.

**Way 2:** ask for the path if not given yet, then check it:

- Missing, or an empty folder: plan first, then create —
  ```bash
  python .act/scripts/init.py --target <path> --plan
  python .act/scripts/init.py --target <path>
  ```
- Already has content: follow `.act/skills/act-adopt/SKILL.md` for that path instead — it sights
  the existing material, proposes what happens to each piece, and only moves anything once the
  owner has approved the table once.

## 4. Say what is there now

In three sentences: where the project's board and open questions live now
(`docs/ai/work/`, `docs/ai/questions/`, `docs/ai/inbox/`), that the assistant's rules and skills
are live from here on, and what to look at first (an inbox note `init` left, or the adoption
table for way 2's second path). One of those notes may offer `security-check: deps` (only when
`init` found a tool installed that Art B — the dependency-vulnerability scan,
`.act/scripts/security_scan.py` — could use, and only while `security-check` is still `local`, the
default): ask the owner whether to turn it on, and only if they say yes, set it to `deps` in
`docs/ai/config.md` yourself — `init` never switches it there on its own.
