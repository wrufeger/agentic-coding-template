<!-- act:template-readme -->
# act — agentic coding template

A working agreement between you and your AI coding assistant, set up in any project — a new one or
one that already exists. You set the goals and decide; the assistant plans, hands bounded pieces to
sub-agents, checks their results, and keeps the project's state in the repository, so the next
session picks up exactly where the last one stopped. Everything lives in one thin layer, `.act/`,
that a single command keeps current; all it needs is Python 3.9+.

What the assistant holds itself to — an excerpt:

- **Done means proven.** A test run, a commit, or an outside check backs every "done"; anything
  else is reported as "not verified".
- **Concept before code.** An idea gets options and a decision first, then it is built.
- **You decide.** Open questions are collected in an inbox (`docs/ai/inbox/`), bundled — never
  decided silently, never scattered through the chat.
- **Nothing irreversible without your yes** — no deployment, deletion, write to a live system,
  pull request or issue comment without approval for that exact case.
- **No secrets** on the command line, in a commit, or in a log — every commit is scanned first.
- **One orchestrator, bounded workers.** Sub-agents get a role, a write scope, and a cap on their
  tool calls; only the main session commits, and never with `git add -A`.
- **Recorded right away.** Tasks, decisions, and the journal land in `docs/ai/` as they happen,
  not reconstructed at the end.
- **The project has the last word.** Every rule can be switched off or replaced in
  `docs/ai/rules.md`.

## Getting started

Clone this repository (or use **Use this template**), open the folder in your assistant — Claude
Code, Codex, GitHub Copilot, Cursor, or Gemini CLI — and say what you want. Whatever the first
message is, the assistant starts the setup: it checks for Python, asks where the project goes,
shows the plan, and runs it. For example:

```text
start
Set up a new project right here.
Set up a new project in ../shop-api.
Take over my existing project in ~/dev/shop — it already has a CLAUDE.md and its own docs.
```

Any language works — "Richte hier ein neues Projekt ein." does the same. Right here means the clone
becomes the project: the link to the template repository is cut, and the project starts on a fresh
`main` of its own. An empty or missing folder elsewhere is set up directly; a folder that already
holds a project is taken over with `act-adopt` (see below).

Once the project exists, everyday work runs the same way:

| You say | What happens |
| :--- | :--- |
| `continue` | reads the board and picks up the open task |
| `Idea: export the orders as CSV` | options, a decision, then a backlog item and a task (`act-idea`) |
| `Bug: login fails when the password has an umlaut` | reproduce, a failing test, the fix, the test green (`act-bug`) |
| `Prepare the import feature, I'm away this afternoon` | cut into tasks, every question asked up front (`act-prepare`) |
| `Close out T12` | check the evidence, archive, journal, commit (`act-commit`) |
| `Check for a template update` | diff, your consent, update (`act-update`) |
| `Which skills are there?` | the list, one line each (`act`) |

### Python

The setup, the scripts, and the hooks need Python 3.9+, standard library only. The assistant checks
for it and walks you through installing it if it is missing:

- **Windows:** `winget install Python.Python.3.12`, or https://www.python.org/downloads/ — tick
  "Add python.exe to PATH" in the installer.
- **macOS:** https://www.python.org/downloads/
- **Linux:** the distribution's package manager.

### Without an assistant

For a **new project**, the setup runs entirely without AI. In a terminal, `init.py` asks for name,
owner, stack, lint and test commands, tools, and languages, then works through ten fixed steps and
prints each one:

```bash
python .act/scripts/init.py --plan                    # show what would happen, change nothing
python .act/scripts/init.py                           # turn this clone into the project
python .act/scripts/init.py --target ../my-project    # set up a new, empty folder instead
python .act/scripts/init.py --non-interactive         # no questions: defaults, open points to the inbox
```

For an **existing project**, `init.py --target <dir>` never overwrites a file. It adds `.act/` and
whatever is missing, appends its own blocks to `.gitignore`/`.gitattributes`, merges its hook entries
into `.claude/settings.json`, and leaves every other file exactly as it is — including an existing
`CLAUDE.md`, which then still lacks the import of the rules. What should become of the project's own
docs and AI files is a judgment per file, and that takes an assistant: `act-adopt` sights everything,
proposes an action per source, waits until you approve the table once, then moves the material
over on a branch `act-adopt` without committing it.

## Skills

Recurring work comes as skills — plain instructions in a `SKILL.md` each, so any assistant can
follow them; Claude Code also calls them by name (`/act-bug`).

| For | Skills |
| :--- | :--- |
| Planning | `act-idea` (options, decision, task) · `act-prepare` (a larger block, all questions up front) |
| Building and fixing | `act-bug` (failing test first) · `act-refactor` · `act-perf` (measure first) · `act-test-gap` · `act-deps` |
| Checking | `act-a11y` (accessibility) · `act-audit-docs` (docs against the code) |
| Design | `act-design-ideas` (variants) · `act-design-build` (implement one) · `act-design-assets` (logo, icons) |
| Shipping | `act-commit` · `act-release` (version, changelog, tag) · `act-pr` · `act-issue` · `act-integrations` (GitHub/GitLab access) |
| Presenting | `act-slides` (a deck from the project's docs) |
| The template itself | `act-setup` · `act-adopt` · `act-update` · `act-doctor` (drift check) · `act-export-settings` / `act-load-settings` · `act-feedback` |

## Stays current

`act-update` brings in a newer template state: it shows the diff per rule, asks for your consent,
replaces `.act/`, and runs any due migrations. The project's own settings, docs, and working files
are never touched; `act-doctor` checks for drift any time.

## Feedback to the template — off by default

A project can report back what helped or was missing in the working method — never anything about
the project itself. Off until switched on in `docs/ai/config.md`; even then no file leaves the
project, only a short summary after a privacy filter, logged locally in full. A message you send
explicitly (`act-feedback <text>`) goes even when it is off, anonymously. Policy:
`.act/rules/topics/feedback.md`.

## What's inside

A project set up from here has three places that matter:

- **`.act/`** — the template layer: rules, coding rule sets for eleven languages, skills, sub-agent
  roles, hooks, and scripts. Never edited in the project (a project version goes to `docs/ai/local/`
  instead), replaced as a whole by `act-update`.
- **`docs/ai/`** — the working state, versioned with the code: settings (`config.md`), the rules
  in effect (`rules.md`), inbox, tasks, backlog, and journal.
- **`docs/project/`** — the project's own documentation, including which coding rule sets apply.

Around them sit the small files each tool reads (`CLAUDE.md`, `AGENTS.md`, `.claude/`,
`.agents/skills/`) and `.act-local/`, which stays on your machine: the board, local state, caches.

## Tools

| Tool | Reads | What it gets |
| :--- | :--- | :--- |
| **Claude Code** | `CLAUDE.md`, `.claude/settings.json`, `.claude/skills/`, `.claude/agents/` | everything: rules loaded by import, skills by name, sub-agent roles with a model and effort tier per role, hooks that enforce the checks below, a status line, the board at session start |
| **Codex, GitHub Copilot, Cursor** | `AGENTS.md`, `.agents/skills/` | rules and skills as instructions; no hooks, so nothing is enforced mechanically, and no sub-agent roles |
| **Gemini CLI** | `GEMINI.md`, `.agents/skills/` | the skills; a project has no `GEMINI.md` yet — point Gemini CLI at `AGENTS.md` in its settings |
| **any other assistant** | — | tell it to read `docs/ai/rules.md`; every skill is a plain `SKILL.md` it can follow |

Every project gets `AGENTS.md` and the skill copies under `.agents/skills/` — read the same way by
Codex, Copilot, Gemini CLI, and Cursor; the Claude Code files come while `claude-code` is among the
project's tools (the default).

In Claude Code, hooks check before each action — each check can be set to `block`, `warn`, or `off`
in `docs/ai/config.md` § Checks:

- no writes into `.act/`; commits staged by name only, never `git add -A`/`git commit -a`
- every commit scanned for secrets and dangerous code patterns; optionally the touched lock files
  for known vulnerabilities
- `git reset --hard` only on a clean working tree; no recursive delete from the shell
- workers kept to their cap, their write scope, and read-only git; no sub-agents of sub-agents, no
  worker writes to `docs/ai/`
- no repeated polling of a running worker; a note before writing to a file that is not UTF-8

## Language

Everything under `.act/` is English. A project's own `docs/ai/` and `docs/project/` are written in
the language chosen at setup (`language-docs`), and the assistant talks to you in yours.

## Contributing

This repository holds nothing but `.act/`: the starting files every project fills in as its own
`docs/ai/` and `docs/project/` live under `.act/skeleton/` and `.act/bridges/`. The template's own
backlog, questions, and journal live in a separate maintenance repository.

Maintainers: in a development checkout (marker `.act-local/template-dev`), `init.py` runs only with
`--target <dir>`.

## License

MIT — see [LICENSE](../LICENSE). For a project's own code, that project's own license applies.
