<!-- act:template-readme -->
# act — agentic coding template

A template repository for projects where a human works alongside AI assistants — new
applications as well as codebases that already exist. It ships a thin, versioned layer (`.act/`)
with rules for the assistant and its sub-agents, a set of skills for recurring workflows, coding
rule sets per language, and the scripts that keep all of it reproducible: set up a project from
here, adopt it into one that already exists, keep it current later, and check its own state for
drift.

**Version 2.** This replaces the template's previous generation, which lived spread across the
repository root; everything now lives under `.act/`, in English, for stdlib-only Python 3.9+. The
previous generation stays available, frozen, on the branch `v1`. A project built on it moves over
with `act-adopt` (see below) — never by merging or pulling this `main`; details in `UMZUG.md` on
`v1` (German).

## Getting started

Clone this repository (or use GitHub's "Use this template" button), open the folder in your AI
assistant — Claude Code, Codex, GitHub Copilot, Cursor, or any other that reads
`CLAUDE.md`/`AGENTS.md`, and Gemini CLI, which reads `GEMINI.md` instead — and say what you want.
It asks two questions and does the rest; no `python` command to type yourself.

**The two ways it offers:**

1. **A new project, right here in this clone.** The connection to the template's own repository is
   cut, and the project starts on a fresh `main` with no history of its own — the template's
   branch is removed afterward so nobody merges it into the project by accident (kept, with a note,
   if it already carries commits of your own). Template updates
   from then on come only through `act-update`.
2. **A project somewhere else** — a new folder, or one that already has a project in it. Give the
   path; an empty or missing folder is set up directly, one that already has content is taken over
   through the `act-adopt` skill (its docs and AI tooling sighted, proposed, and moved in only
   after you approve the table once).

### Installing Python

The assistant checks for Python 3.9+ itself (`init.py`, `update.py`, `doctor.py`, the feedback and
logging scripts, and the session-start hook all need it; nothing else under `.act/scripts/` needs
a third-party package). If it is missing, it explains installing it and waits:

- **Windows:** https://www.python.org/downloads/ , or `winget install Python.Python.3.12` in a
  terminal — tick "Add python.exe to PATH" in the installer. Details:
  https://docs.python.org/3/using/windows.html
- **macOS:** https://www.python.org/downloads/ , details: https://docs.python.org/3/using/mac.html
- **Linux/Unix:** the distribution's package manager, or https://www.python.org/downloads/ ,
  details: https://docs.python.org/3/using/unix.html

### By hand

The commands above run through `.act/skills/act-setup/SKILL.md` — read that file, or run its steps
yourself:

```bash
python .act/scripts/init.py --plan   # show what would happen, change nothing
python .act/scripts/init.py          # set up the current folder as a project
python .act/scripts/init.py --target ../my-new-project   # a new, empty folder elsewhere
```

For a project that already has its own docs and AI tooling — a previous template, a different one,
or something it made up on its own — adopt it instead of running the plain init above: open the
checkout in your assistant and have it follow `.act/skills/act-adopt/SKILL.md` for the project's
path. It sights what is there, proposes an action per source, gets the owner's approval once, then
moves it into this layout on a branch `act-adopt` (running `init.py` itself once the table is
approved — running it separately first would only mean redoing that step).

`init` never overwrites a file the project already owns. What it does instead — writing
`docs/ai/config.md` from a short interview, cutting Git loose from the template's own history onto
a fresh `main` with no prior commits (the template's branch removed afterward, so it can never be
merged into the project by accident), bridging into `CLAUDE.md`/`AGENTS.md`/`.claude/` for the
tools in use, thinning unused tool bridges back out, retiring the template's own `.github/README.md`
(removed outright, never rewritten — the project skeleton goes to the root `README.md` only, so
GitHub falls back to showing that one) and replacing the root `README.md` with that skeleton (only
once their content still matches the template's — an edit made after cloning is kept, not
overwritten), and keeping or deleting the template's own `LICENSE` — is ten fixed steps, each
printed as it runs. `--non-interactive` skips every prompt and logs anything it would otherwise
have asked into the project's inbox instead.

## Commands

Once a project is set up, its assistant has a set of skills under `.act/skills/` (copied into
`.agents/skills/` for any tool, and `.claude/skills/` for Claude Code). The skill `act` lists them:

| Skill | For |
| :--- | :--- |
| `act-setup` | set up this checkout as a project, or dock it onto one that already exists — also runs before any project exists, from the root `CLAUDE.md`/`AGENTS.md` |
| `act-idea` | take in a feature or change request, lay out options, get a decision, file it |
| `act-prepare` | prepare a larger block of work so it runs without interruptions |
| `act-bug` | fix a reported bug — reproduce, localize, a red test before the fix |
| `act-refactor` | restructure code without changing its behavior |
| `act-test-gap` | find untested areas, prioritize by risk, close them after approval |
| `act-perf` | measure, form a hypothesis, change one thing, measure again |
| `act-deps` | update dependencies, one commit per major |
| `act-release` | check preconditions, pick a version, generate a changelog, tag it |
| `act-a11y` | check an interface for accessibility, work through findings by severity |
| `act-design-ideas` / `act-design-build` / `act-design-assets` | design variants, implement one against a template, produce graphics |
| `act-audit-docs` | check `docs/project/` against the actual code and bring it back in line |
| `act-adopt` | one-time takeover of an existing project's docs and AI tooling — followed from a template checkout, see "Getting started" |
| `act-commit` | close out an accepted task: evidence, archive, journal, commit |
| `act-slides` | build or update a presentation about the project from its docs |
| `act-update` | pull a newer template state into the project |
| `act-doctor` | reconcile project and template state, mechanically and (on request) with judgment |
| `act-export-settings` / `act-load-settings` | hand a project's own setup to another project, or bring one in |
| `act-feedback` | send feedback about the working method itself to the template author |

Without Claude Code, the same work happens by saying what a skill would do — its `SKILL.md` under
`.act/skills/<name>/` (or the tool-neutral copy under `.agents/skills/<name>/`) is plain instructions,
readable and followable by any assistant.

## Stays current

A project keeps a link back to the template state it was set up from (`.act-lock.json`). Running
`python .act/scripts/update.py` (or the skill `act-update`) fetches the template's current state,
shows the old-to-new diff per rule and coding-set ID, asks for consent, then replaces `.act/`,
refreshes the files it generated outside `.act/`, reconciles hook entries and the `.gitattributes`/
`.gitignore` blocks it owns, runs any due migrations, and hands off to `doctor.py`. The project's
own values, its `docs/project/`, and its `docs/ai/` working files are never touched by an update.
`python .act/scripts/doctor.py` runs the same mechanical checks on demand — dead rule/coding-set
IDs, stale overrides, missing `act:ref`/bridge references, hook drift, duplicate short IDs
(`T<n>`/`B<n>`/`Q<n>`), and `.act/MANIFEST.json` drift — independent of whether an update just ran.

## Learns from real projects — off by default

A project can report back what served the **working method** well or was missing — never the
project itself. The test for every entry: would this help someone who will never see this project?
A rule that had to be added because the template lacked it, a workflow that kept failing, a script
or skill that proved itself — that is feedback; a fact about the project's own name, stack, data, or
code is not.

This is opt-in, controlled entirely by three keys in `docs/ai/config.md` (`feedback`,
`feedback-cadence`, `feedback-scope`) and off (`feedback: off`) until a project turns it on. Even
then, no file ever leaves the project — the assistant reads its rules and working files and writes
a short summary, checked against a privacy filter (secrets, paths, mail addresses, internal
addresses) before anything is sent. Every send is logged locally, in full, right after it goes out.
Full policy: `.act/rules/topics/feedback.md` in a set-up project; mechanism: `.act/scripts/feedback.py`.
A one-off message (`act-feedback <text>` or a sentence starting "feedback:") always goes, even with
feedback off — then anonymously, with nothing but that text and the template's own commit hash.

## What's inside

| Path | Contents |
| :--- | :--- |
| `.act/rules/` | core rules — `shared/` for every role, `orchestrator/` for the main session, `topics/` for detail pages a rule links to |
| `.act/coding/` | eleven coding rule sets (`CR-<set>-<group>`), one file per language, from bash to nuxt |
| `.act/agents/` | role definitions for sub-agents (builder, explorer, reviewer, doc-writer, debugger, test-writer, optimizer, quick-check, expert-solver) |
| `.act/skills/` | one folder per skill, a `SKILL.md` each, plus `act` itself, which lists the rest |
| `.act/scripts/` | `init.py`, `update.py`, `doctor.py`, `rules.py`, `board.py`, `feedback.py`, `tiers.py`, `usage.py`, and the shared `actlib.py` |
| `.act/hooks/dispatch.py` | one entry point per session event: write guard for `.act/**`, session start |
| `.act/bridges/` | the files `init.py` generates in a project — `CLAUDE.md`, `AGENTS.md`, `docs/ai/rules.md`, coding rules, hook entries, git file blocks, role bridges under `agents/`, and a project `README.md` skeleton (`project-readme.md`) |
| `.act/skeleton/` | starting files for `docs/ai/` — config, inbox (questions, tasks for a human, tool reports, notes), proposals, working memory |

## Tools

Every project gets `AGENTS.md` (read by convention by Codex, GitHub Copilot, and Cursor) and every
skill copied into `.agents/skills/` (read the same way by Codex, Copilot, Gemini CLI, and Cursor) —
both written regardless of which tools are selected. Beyond that, one tool at a time gets its own
generated bridge, wired into `init`'s tool list and `step_thin_bridges`; **Claude Code is the only
one built so far** — `CLAUDE.md`, `.claude/settings.json` (hooks), `.claude/skills/`, and
`.claude/agents/` role bridges with a model/effort tier resolved per role, none of which another
tool reads. Nothing tool-specific for Codex, Copilot, Gemini CLI, or Cursor exists yet.

## Language

Code, comments, and rule texts in `.act/` are in English. A project's own working language for
`docs/ai/` and `docs/project/` is a setting in `docs/ai/config.md`, chosen during `init`.

## Contributing

This repository carries almost no content of its own beyond `.act/`: it has no `docs/` — the
skeleton every derived project fills in as its own `docs/ai/` and `docs/project/` lives here under
`.act/skeleton/` and `.act/bridges/` instead. The template's own development — backlog, open
questions, journal, test projects — runs in a separate maintenance repository, not part of this
checkout. A message here that is not clearly about setting up or adopting a project gets a short
pointer to `.act/skeleton/` and `.act/bridges/` in reply, nothing more.

Maintainers: `init.py` run in place (no `--target`) refuses on the template's own development
checkout — either `.act-local/template-dev` (gitignored, per-checkout) is present, or the
repository has more than one `git worktree`. Use `--target <dir>` to build a project or a
throwaway probe elsewhere instead; delete the marker only if this checkout really is meant to
become a project (B130).

## License

MIT — see [LICENSE](../LICENSE). For a project's own code, that project's own license applies.

---

See the [README in the repository root](../README.md) for the file layout and the exact commands
in one place.
