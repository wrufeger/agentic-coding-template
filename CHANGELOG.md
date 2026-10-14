<!-- act:template-changelog -->
# Changelog

Changes to the template itself. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html); the sections up to 2.1.0 keep the headings of their
release notes. A project set up from this template keeps its own
changelog: `init` removes this file (step 8, recognized by the marker on its first line, like the template's own
README), and `act-update` and `act-adopt` never bring it into a project.

## [Unreleased]

### Added

- **`act-teach`** — short Markdown lessons on a topic, ideally on the project's own code, with exercises and a
  learning record. New config key `teach-lessons: local | docs` (`.act-local/learn/` or versioned under `docs/learn/`,
  which `act-audit-docs` then covers).
- **Board excerpt at session start** — open tasks with their last state, waiting and answered inbox entries, about
  2,000 characters, so a bare "continue" works from it. New config key `board-at-start: on | off`.
- **New rule `R-code-checks-intact`** — a failing test, lint or type check is fixed in the code, never by deleting,
  skipping, loosening or silencing the check; a check that is itself wrong is changed as its own step.
- **Reviewer verdict `CONDITIONAL`** next to `ALLOW` and `BLOCK`: committed with its one condition filed in the inbox;
  a known bug is always `BLOCK`.
- **Four new safety checks:** `secret-read` (no secret file such as `.env`, private keys or cloud credentials read
  into the context; `.env.example` and `*.pub` stay free), `git-metadata-guard` (no write to `.git/hooks`,
  `.git/config` or a git config key that runs code; workers also not to `.claude/` settings, roles and skills),
  `git-discard` (no `git clean -f`, folder checkout/restore over changes, `stash drop/clear`, force push to the default
  branch or `branch -D` of an unmerged branch), `worker-scope-overlap` (no worker start whose `Write scope:` overlaps a
  running worker's). `R-cost-delegate` gains `Depends on:` and a shared read note for several workers.
- **Learning step** — `act-bug`, `act-perf` and `act-refactor` end by asking whether the finished code carries what
  was learned; if not, a short note goes under `docs/project/learnings/`, which `act-prepare` and `act-bug` read first.
  `act-commit` asks the same after two or more rework rounds.
- `context_size.py --report` (and `--json`): base load of the first call, cache hit rate and cache breaks, read from
  the transcript.
- `doctor.py` checks skill and role frontmatter (YAML pitfalls, required fields, name vs. folder, known values) and
  reports an expired or invalid `revisit:` date under a decision.
- `act-audit-docs` can run as a Claude Code workflow script (one explorer and one doc-writer per doc area, in
  parallel), only on explicit request.
- Feedback: the project id is created with the first payload, so a direct message is never anonymous;
  `--direct --contact <email>` adds an optional reply address.
- This `CHANGELOG.md`, filled back to `0.1.0-beta` from the release notes. `init` removes it from a new project in
  step 8 like the template's own README; an edited copy is kept with an inbox note.
- Community files for the template's GitHub repository under `.github/`: code of conduct, contributing guide,
  security policy, issue forms and a pull request template. They recommend `/act-feedback` as the first way to
  report a problem.

### Changed

- `init` removes these community files from a new project in step 8, like the template's own README; an edited
  copy is kept with an inbox note, and `.github/` goes once nothing else is left in it.
- `R-work-evidence` counts a CI run, a log excerpt or a screenshot of the running application as evidence, and every
  reachable feedback loop runs before the human's.
- Workers mark every assumption; an accepted one is confirmed, asked in the inbox or recorded with the task's state.
- `R-work-idea-first` and `act-idea`: the recommended option names its failure modes and its way back; a throwaway
  prototype and an existing dependency or service count as options, and a `revisit:` date is set when the use is
  uncertain. `act-prepare` sets a first checkpoint after the first runnable slice.
- New projects get `dependency-check: regularly`; existing values stay.
- `context-hint` defaults to 180000 tokens, just below where Claude Code compacts on its own after an idle hour.

### Security

- `git-metadata-guard` also covers files that start code when the folder is opened: workers may not write
  `.vscode/tasks.json`, `.devcontainer/`, `.envrc` or `.mcp.json`, and nobody adds a `folderOpen` task. A copy or
  move into a directory (`cp`, `mv`, `Copy-Item`, `Move-Item`) is checked as `<dir>/<source name>`, which also closes
  `cp -r x/.claude .` for workers.
- Agents started by a Claude Code workflow script are bound to their `Write scope:` and `Cap:` like any other worker.
- The `git reset --hard` guard no longer lets the command through when `git status` prints a file name it cannot
  decode (`core.quotePath=false`).
- The recursive-delete check covers more forms: `rm --rec` prefixes, glued `rd/s/q` and `rd/q /s` switches,
  `del`/`erase`, wrappers such as `busybox` or `setsid`, `$SHELL`/`$0` as shell names, `iex`/`Invoke-Expression` like
  `eval`, and every `find -exec` block.

### Fixed

- The worker write scope reads a timestamp without a time zone as UTC.
- Feedback documentation: the reply address stays in the local copy of its one payload and is never reused for a
  later message (it said "never stored" before).

## [2.1.0] - 2026-10-09

Six new skills, a status line that says when a fresh session pays off, and safety checks that hold more and block
less. Projects on v2.0.0 update with `act-update`.

### New skills

- **`act-integrations`, `act-pr`, `act-issue`** — work with GitHub or GitLab, self-hosted included: check which
  access exists (REST token, MCP servers) and record it in `docs/project/integrations.md`; prepare a pull or merge
  request from the diff; read, create, comment on, close and start work on issues. Every write shows a preview and
  waits for your yes. New config section **Git hosting** (`target-branch`, `forge`, `forge-host`); a token goes only
  to github.com, gitlab.com or a host you named, never over plain http.
- **`act-handover`** — before you close a session or `/clear`: uncommitted changes, started tasks without a state
  line, answered inbox entries, and the sentence to type into the new session.
- **`act-check-translations`, `act-seo`** — code-only checks of translation files (missing, extra and empty keys,
  placeholders, keys used but not defined) and of on-page basics for search engines (title, description, headings,
  canonical, Open Graph, alt text, robots.txt, sitemap).

### Sessions, status line, board

- The status line shows the context size (`ctx 127k`) and splits tasks into `run`, `wait` and `new`. A started task
  waits when you mark it (`entries.py state <id> --wait`), when it has been quiet longer than `task-wait-hours`, or
  when an open question or todo names it. What waits for you appears by id — questions `Q<n>`, todos now `U<n>` —
  and every other kind as a count.
- Once the context reaches `context-hint` (default 150000 tokens), the assistant suggests `/clear` or a new session
  at the next task boundary: a fresh session after a finished task is the largest token saving there is. New config
  section **Session length**.
- Tasks get a `started:` header. Each person gets an ideas file under `docs/ai/concept/`; new entries are reported
  at session start.
- The board's place is a setting (`board: docs | shared | local`), and it is regenerated after git merge, pull,
  rebase, switch and similar commands.

### Rules and settings

- New rules: `R-cost-amend` (an addition to a running worker's assignment goes to it at once, or the worker is
  restarted when that is cheaper), `R-safe-no-personal-data` (no real personal or customer data in what the model
  sees), `R-work-bounded-output` (output of unknown length stays out of the context).
- `R-human-chat` makes compact chat a token-saving goal, with `output-depth` levels `normal`, `sparse` and `verbose`.
- `inbox-decisions: immediate | at-start` decides whether an open decision goes to the inbox at once or waits until
  work on its backlog entry starts.
- Reasoning per skill (`reasoning:` in a skill becomes `effort:` in the Claude Code copy, overridable in
  `config.md` § Roles); a `run` key for the start command; active environment overrides named at session start;
  promised replies kept as todos.
- Skill descriptions are trigger-first and linted (`skills.py --check`, `act-doctor`); long skills load in stages
  from `references/`.
- Your own skills and roles under `docs/ai/local/` get their tool copies automatically at session start and on
  update.

### Safety checks

- `secret-scan` now also holds credentials in URL query strings, single-quoted keys, PHP array entries, literal
  fallbacks after an environment lookup and credential pairs inside a quoted value — and no longer holds a commit
  over plain code expressions in source files. Every finding is named.
- After `git merge`, `pull` or `cherry-pick`, the lock files that came in get a dependency scan; findings become an
  inbox report, never a block.
- The Bash write scanners read backtick and `$(…)` spans, combined with the previous scanner so a check can only get
  stricter; they no longer block on `$'` inside quoted patterns or heredoc text, and fail closed beyond their nesting
  limit.
- Worker write scope: brackets are literal (`server/api/[id]/**`), and a wildcard that reaches outside the scope is
  refused.

### Update and adoption

- `update.py` refuses a downgrade unless `--allow-downgrade`; `--catch-up` keeps the recorded template commit; a
  failed fetch says what failed. `session-start-refresh: warn | off` is honoured by `update.py` too.
- `act-adopt` keeps the chosen languages, turns adopted rules into overrides or own rules, and asks before applying
  rows without a target.
- On Windows, a file held for a moment by a virus scanner or IDE no longer makes a write fail; the security scans
  print UTF-8.
- Documentation site in English and German: <https://wrufeger.github.io/agentic-coding-template-docs/>, linked from
  the README.

### Upgrading from v2.0.0

- Run `act-update` (or `python .act/scripts/update.py`). In `solo` mode, migration `002` gives every inbox todo a
  `U<n>` id and renames it to `U<n>-<slug>.md`; in `team` mode, `entries.py assign` on the default branch does the
  same. The archive is never rewritten.

## [2.0.0] - 2026-09-28

The rebuild. This release replaces the template's previous generation on `main`. The previous generation stays
available, frozen, on the branch `v1`.

### What changed

- **One layer under `.act/`**, in English, stdlib-only Python 3.9+. A project's own documentation stays in its
  own language (`language-docs`); the chat language is remembered per person and machine.
- **Setup from a fresh clone:** open it in your AI assistant and say what you want (`act-setup`) — a new project
  right in the clone, a new project elsewhere, or an existing codebase taken over with `act-adopt`.
- **Staying current:** `act-update` shows the diff first, tells local changes from template changes by a
  manifest, runs migrations, and a daily check at session start says when a newer template exists.
  `act-doctor` reports drift between project and template.
- **Rules in layers** — shared, orchestrator, topics — switched on and off per project in `docs/ai/rules.md`;
  coding rule sets per language in `docs/project/coding_rules.md`, preselected from the detected stack.
- **Roles and skills:** 9 worker roles with model tiers instead of model names, 23 skills. Claude Code gets
  the full bridge (hooks, skills, role bridges); Codex, GitHub Copilot, Cursor and Gemini CLI read `AGENTS.md`
  (Gemini CLI: `GEMINI.md`) and the skills under `.agents/skills/`.
- **Mechanical checks through hooks:** secret and danger scans before a commit, worker caps and write scopes,
  a guard before `git reset --hard`, a status-poll guard, and an optional security check (dependency scan;
  a deep scan before a release).
- **Work records as single files:** one inbox (questions, todos, reports, notes), tasks, backlog and journal
  under `docs/ai/`; the board is generated under `.act-local/`.
- **Settings export and import** between projects; opt-in feedback to the template author.

### Moving a project from the previous generation

- Do **not** merge or pull the new `main` into a project built on the previous generation — the layouts differ
  (`.claude/` there, `.act/` here). `update-template.py --apply` from the last state of `v1` refuses on its own.
- Instead run `act-adopt` from a checkout of this release. It moves board, tasks, questions, journal, backlog
  and the project's own docs into the new layout, on a branch of its own; the old state stays reachable.
  Details (German): `UMZUG.md` on `v1`.

### Notes

- A project set up from a pre-release state of the rebuild whose `.act-lock.json` has no
  `template.manifest_sha256` yet shows `.act/ was pulled in without update.py` at session start. Run
  `python .act/scripts/update.py` (or `--catch-up`) once; the lock then records it and the note stops.

## [0.1.0-beta] - 2026-09-13

First public pre-release of the previous generation (today the branch `v1`), documentation in German only.

- Rules in two layers: a tool-neutral `AGENTS.md` (roles, done only with evidence, commits by pathspec, live systems)
  and `CLAUDE.md` as the Claude Code addition, with pointer files for Cursor, Copilot, Aider and Gemini CLI.
- 8 sub-agents under `.claude/agents/` with a fixed model each, 6 skills (`/create-project`, `/apply-template`,
  `/update-template`, `/audit-docs`, `/commit`, `/run-maintenance`) and 9 stdlib-only scripts.
- Working folder `docs/ai/` (board, tasks, questions, ledger, backlog, checklists) and a `docs/project/` skeleton with
  coding rule modules for 10 languages and stacks; `AI-CONFIG.md` steers the collaboration.
- Optional live log `ai.log` through hooks.

[Unreleased]: https://github.com/wrufeger/agentic-coding-template/compare/v2.1.0...HEAD
[2.1.0]: https://github.com/wrufeger/agentic-coding-template/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/wrufeger/agentic-coding-template/releases/tag/v2.0.0
[0.1.0-beta]: https://github.com/wrufeger/agentic-coding-template/releases/tag/v0.1.0-beta
