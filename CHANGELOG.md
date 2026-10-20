<!-- act:template-changelog -->
# Changelog

Changes to the template itself. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html); the sections up to 2.1.0 keep the headings of their
release notes. A project set up from this template keeps its own
changelog: `init` removes this file (step 8, recognized by the marker on its first line, like the template's own
README), and `act-update` and `act-adopt` never bring it into a project.

## [Unreleased]

### Added

- **Worker runs are measured.** When a worker ends, the usage counter reads its transcript and records duration,
  steps and tokens — `fresh` (input, cache writes, output) and `cache` (cache reads) — per role and tier in
  `.act-local/usage.json`, the newest 50 runs each. Numbers only; they are never sent with feedback.
  `usage.py --estimates` shows median and 80th percentile per role and tier with the date of the last measurement;
  `usage.py --backfill` reads a project's existing transcripts once, without counting anything twice. Claude Code only.

### Changed

- **Estimates in minutes and `tkn`, never person-days.** `act-idea`, `act-prepare`, the task and backlog READMEs and
  `R-cost-delegate` ask for `~<n> min · ~<n> tkn fresh · ~<n> tkn cache` plus the assumption behind it, based on
  `usage.py --estimates` (runs per role times the median, up to the 80th percentile) where measurements exist.

## [2.2.0] - 2026-10-20

Quick capture from the chat, entries with YAML frontmatter, a one-step archive that takes pasted images along, four
new safety checks and a shell scanner that reads bash the way bash does. Projects on v2.1.0 update with `act-update`.

### Upgrading from v2.1.0

- Run `act-update` (or `python .act/scripts/update.py`). Migration `003` moves the header of every inbox entry into
  YAML frontmatter, migration `004` does the same for tasks, backlog, journal and the archive under `docs/ai/work/`
  (`archive/legacy/` and every `README.md` stay as they are). Both rewrite each file once and leave it alone after.
- Updating now needs Git 2.25 or newer.
- Claude Code's `Artifact` tool is off after the update; `artifacts: on` in `docs/ai/config.md` keeps it.

### Added

- **Quick capture from chat** — a message that begins with `todo:`, `note:` or `idea:` (any letter case) is filed by
  the `UserPromptSubmit` hook without a model turn and never reaches the model, so it costs no tokens and does not
  interrupt a running task. `todo:` and `note:` become inbox entries marked `triage: open`; `idea:` becomes a new
  section at the end of your `docs/ai/concept/ideas-<identity>.md`, text unchanged. The assistant then processes
  each `triage: open` entry right after the answered inbox entries: it decides whom a todo is for (or turns it into
  a backlog entry), or replies below a note. The board and the session-start excerpt list such entries under
  "Answered — the assistant processes these", and an answered note waits under "Waiting for you". Switch with
  `quick-capture: on|off` in `docs/ai/config.md` (a missing key counts as `on`); new rule `R-human-capture` covers
  tools without the hook, where the assistant files the entry itself.

- **Coding rule set `nuxt5`** — rules for Nuxt 5 and its nightly channel on top of `nuxt`: versions and channel,
  modules, Nitro 3/h3 v2 server code, typed `$fetch` and route targets, Unhead 3, and the checks after every Nuxt
  update. `init` checks it when `package.json` names `nuxt` at major 5 (`^5.0.0`, `npm:nuxt-nightly@5x`) or the
  `stack` value says "Nuxt 5"; `nuxt.md` points an existing project to it.

- **New rule `R-safe-dev-server`** — a server the assistant starts for tests, a browser check or a screenshot runs on
  a port of its own, never on one of the project's default ports; the owner's running server may be reused, but is
  stopped, restarted or moved only after asking, and processes are never ended by name.

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
  security policy, an accessibility statement (every environment "not tested", known barriers listed), issue forms
  and a pull request template. They recommend `/act-feedback` as the first way to report a problem.
- **`entries.py archive <id|file>`** archives a finished task, backlog item or inbox entry to
  `docs/ai/work/archive/` in one step; an inbox entry gets `status: done`. Images and other files it links beside
  itself (a pasted `img.png`, `image (1).png` …) move along: generic or already taken names get the entry id in front
  (`Q<n>-img.png`), links are rewritten, and a file another Markdown file under `docs/` still links is copied instead
  of moved. Everything is planned before the first write, so a failure leaves nothing half-done. `act-commit`,
  `act-idea`, the chat rule and the inbox and concept READMEs point to it.
- `doctor` reports files under `docs/ai/inbox/` and `docs/ai/concept/` that no Markdown file under `docs/` links
  (kind `orphan-file`), such as a pasted picture left behind when its entry was archived by hand.

### Changed

- **Entries open with YAML frontmatter** — the header fields of every inbox entry, task, backlog item and journal
  entry (`id`, `kind`, `for`, `status`, `created` …) now stand between two `---` lines, so GitHub, GitLab and Markdown
  editors show them as metadata instead of running them together into one paragraph. `entries.py`, quick capture and
  the reports of `doctor --inbox` and `act-adopt` write the new form; every reader accepts both forms, so hand-written
  entries in the old form keep working. `act-update` rewrites the existing entries once: migration
  `003-inbox-frontmatter` the inbox, migration `004-work-frontmatter` the tasks, backlog, journal and the archive under
  `docs/ai/work/` (archived inbox entries included). `docs/ai/work/archive/legacy/` and every `README.md` stay as they
  are.

- **Claude Code's `Artifact` tool is switched off by default** to save about 13,700 tokens at every session start.
  New config key `artifacts: on | off` (default `off`): `off` sets `"enableArtifact": false` in
  `.claude/settings.json` at session start, `init` and `update`; the tool is gone from the next session on. Existing
  projects lose it after their next update — `artifacts: on` in `docs/ai/config.md` keeps it. `on` only removes an
  entry the template set itself; a value the project set itself is never overwritten, a contradicting one is reported
  once.
- **Feedback to the template author defaults to `confirm` in new projects** instead of `off`: `init` writes
  `feedback: confirm` whenever nobody chooses — a run without a terminal (as `act-setup` and `act-adopt` run it), an
  empty answer, or three invalid ones. `confirm` shows every payload and asks before each send, so nothing leaves
  without a yes; `off` stays one edit away in `docs/ai/config.md` § Feedback. Existing projects keep their value, and
  a `config.md` without the key still counts as `off`. A project that has never sent counts the feedback cadence from
  its first session with sending on, so it is no longer shown "feedback due" from the very start.
- **`act-setup` and `act-adopt` translate the docs scaffold in the same run** when `language-docs` is not English,
  and close the `translate-scaffold` todo themselves; it is left for later only by an `init` run without either skill.
- **`doctor.py` no longer proposes a lower tier** for a role whose workers' results were all accepted; it
  proposes only a higher one, once 8+ outcomes show 40%+ reworked or escalated (`R-role-outcome`). An
  accepted result does not show that a cheaper tier would have done as well.
- **Nuxt coding rules, stuck dev server on Windows:** no longer advise ending the process on port 3000; they end only a
  server the assistant started itself, found by its listening PID (`Get-NetTCPConnection … -State Listen`, or
  `findstr /C:` with `LISTENING`, since plain `findstr ":<port> "` also matches longer ports and client connections).
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
- `worker-write-scope` refuses fewer harmless commands: every worker may write into the system temp directory, even
  with `Write scope: none`, when the path is written out (`/tmp/...` in Bash, or the directory's absolute path in
  any tool) and the project itself does not lie inside it; the resolved path counts, so `..` or a link back into the
  project is judged as a project target. A target with a variable such as `$TEMP` stays refused, and so does a
  temp or scratchpad path with a glob character (`.*` can match `..`); `R-cost-delegate` says what
  `Write scope: none` now allows. An unquoted brace
  list in Bash (`app/{css,js}`) is checked as every path it expands to and as its literal name. A refusal names the
  way out for a target with a variable or command substitution and for a relative target after a `cd` on an earlier
  line.
- `secret-read` no longer reads the search pattern of `grep`, `egrep`, `fgrep`, `rg` or `git grep` as a file name,
  so a secret scan such as `git diff --cached | grep -E '\.env|id_rsa'` runs; files named as operands, `-f` pattern
  files and anything after `-e` stay checked.

### Security

- **The Bash write checks read a backslash-newline the way bash does.** They no longer join it in a comment, in
  single quotes or in the body of a heredoc with a quoted delimiter (including a mixed one such as `<<'E'$x`, where
  bash expands nothing in the delimiter), and they follow comments, quotes and heredocs inside `$(...)` within double
  quotes; an escaped backslash before the pair is kept. Before, a write or delete after such a comment or heredoc
  could slip past the `.act/` guard, the worker write scope and the delete/reset checks.
- **A heredoc fed to a shell is scanned as a script** — `bash <<EOF`, `sh -s <<EOF`, `cat <<EOF | bash`,
  `{ bash; } <<EOF`, `(bash) <<EOF` — and the `$(...)` in any unquoted heredoc body counts on its own, since bash
  expands it before the shell reads the body. A `-c` after `--`, `-` or a script name is no longer taken as the
  shell's own option, and a `<<` bit shift in arithmetic no longer counts as a heredoc.
- **A crafted command with very many heredocs or pipe stages is scanned in linear time**, so it can no longer stall
  the `PreToolUse` hook past its timeout, which would have let the call through.
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

- **A template update that touches many files no longer fails on Windows** with "WinError 206" (command line too
  long) at its commit step, as a migration rewriting several hundred entries would. The paths now reach git on
  standard input instead of the command line, the commit still covers exactly those paths, and the read-only path
  queries run in chunks; `init`'s first commit does the same. This needs Git 2.25 or newer.
- **Session start no longer rewrites unchanged bridges.** `CLAUDE.md`, `AGENTS.md` and `docs/ai/rules.md` are written
  only when their content differs from the source apart from line endings. On a Windows checkout with
  `core.autocrlf=true`, the LF rewrite used to leave the files listed as modified with an empty `git diff`, which
  blocked `act-update` and `act-commit` until they were added again. `act-update` skips identical bridges the same way.
- **`update.py --plan` says "nothing to update" when there is nothing to update.** When the project is already at the
  source's commit and no migration is due, the plan used to describe steps 5 to 10 anyway, so `act-update` asked for
  consent to an update that did not exist. Plan and real run now end the same way.
- **Hidden files on Windows can be overwritten.** Writing an existing file with the Hidden attribute (a `.gitignore`
  set hidden by an editor, for example) used to abort `init` and `act-adopt` with `PermissionError` 13 and leave the
  adoption in `init-failed`. `init` and `act-adopt` now overwrite such a file in place and keep its attributes; where
  that is impossible, the error names the file and the way out (`attrib -R -H`).
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

[Unreleased]: https://github.com/wrufeger/agentic-coding-template/compare/v2.2.0...HEAD
[2.2.0]: https://github.com/wrufeger/agentic-coding-template/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/wrufeger/agentic-coding-template/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/wrufeger/agentic-coding-template/releases/tag/v2.0.0
[0.1.0-beta]: https://github.com/wrufeger/agentic-coding-template/releases/tag/v0.1.0-beta
