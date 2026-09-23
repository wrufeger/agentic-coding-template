<!-- act:template-readme -->
# act — agentic coding template

A template repository for projects where a human works alongside AI assistants — new
applications as well as codebases that already exist. It ships a thin, versioned layer (`.act/`)
with rules for the assistant and its sub-agents, a set of skills for recurring workflows, coding
rule sets per language, and the scripts that keep all of it reproducible: set up a project from
here, adopt it into one that already exists, keep it current later, and check its own state for
drift.

**Status: rebuild in progress.** This replaces the template's previous generation, which lived
spread across the repository root; everything now lives under `.act/`, in English, for
stdlib-only Python 3.9+. The previous generation stays usable for projects already built on it.

## Prerequisites

**Python 3.9+** on the `PATH` (`python3 --version` / `python --version`). It runs `init.py`,
`update.py`, `doctor.py`, the feedback and logging scripts, and the session-start hook. No
third-party packages — everything under `.act/scripts/` is standard library only.

## Getting started

Either clone this repository, or use GitHub's "Use this template" button, then run:

```bash
python .act/scripts/init.py --plan   # show what would happen, change nothing
python .act/scripts/init.py          # set up the current folder as a project
```

To bring the layer into a project that already exists elsewhere, without touching anything it
already has:

```bash
python .act/scripts/init.py --target ../my-existing-project
```

`init` never overwrites a file the project already owns. What it does instead — writing
`docs/ai/config.md` from a short interview, detaching Git from the template's own history, bridging
into `CLAUDE.md`/`AGENTS.md`/`.claude/` for the tools in use, thinning unused tool bridges back out,
retiring the template's own `.github/README.md` (removed outright, never rewritten — the project
skeleton goes to the root `README.md` only, so GitHub falls back to showing that one) and replacing
the root `README.md` with that skeleton (only once their content still matches the template's — an
edit made after cloning is kept, not overwritten), and keeping or deleting the template's own
`LICENSE` — is ten fixed steps, each printed as it runs. `--non-interactive` skips every prompt and
logs anything it would otherwise have asked into the project's inbox instead.

## Commands

Once a project is set up, its assistant has a set of skills under `.act/skills/` (copied into
`.agents/skills/` for any tool, and `.claude/skills/` for Claude Code). The skill `act` lists them:

| Skill | For |
| :--- | :--- |
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
| `.act/skeleton/` | starting files for `docs/ai/` — config, inbox, proposals, questions, working memory |

## Tools

Every project gets `AGENTS.md` (read by convention by Codex, GitHub Copilot, and Cursor) and every
skill copied into `.agents/skills/` (read the same way by Codex, Copilot, Gemini CLI, and Cursor) —
both written regardless of which tools are selected. Beyond that, one tool at a time gets its own
generated bridge, wired into `init`'s tool list and `step_thin_bridges`; **Claude Code is the only
one built so far** — `CLAUDE.md`, `.claude/settings.json` (hooks), `.claude/skills/`, and
`.claude/agents/` role bridges with a model/effort tier resolved per role, none of which another
tool reads. Nothing tool-specific for Codex, Copilot, Gemini CLI, or Cursor exists yet in this
rebuild.

## Language

Code, comments, and rule texts in `.act/` are in English. A project's own working language for
`docs/ai/` and `docs/project/` is a setting in `docs/ai/config.md`, chosen during `init`.

## Contributing

This repository carries almost no content of its own beyond `.act/`: `docs/ai/` and `docs/project/`
are the skeletons every derived project fills in itself. The template's own development — backlog,
open questions, journal, test projects — runs in a separate maintenance repository, not part of
this checkout. A message here that is not clearly about setting up or adopting a project gets a
short pointer to `docs/ai/` and `docs/project/` in reply, nothing more.

## License

MIT — see [LICENSE](../LICENSE). For a project's own code, that project's own license applies.

---

See the [README in the repository root](../README.md) for the file layout and the exact commands
in one place.
