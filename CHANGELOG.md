<!-- act:template-changelog -->
# Changelog

Changes to the template itself, newest first. Each release opens with a summary line, its highlights and what to do
when upgrading; below that the changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The longer wording of earlier entries stays in the
Git history and in the release notes of each tag. A project set up from this template keeps its own changelog: `init`
removes this file (step 8, recognized by the marker on its first line, like the template's own README), and
`act-update` and `act-adopt` never bring it into a project.

## [Unreleased]

### Upgrading
- Assignments that run tests need a `Tests:` line beside `Write scope:`; workers run tests only with it.
- An absolute `outside-root-allow` entry outside the project and home is read-only now; writes there are refused.
- A commit touching a lock file is held while the scan cache folder is a link; the message names it, or set
  `security-check: off`.
- `act-update` skips new coding rule sets while `coding_rules.md` has uncommitted changes; commit, then run
  `python .act/scripts/rules.py --add-new-coding`.
- Fix what `act-doctor` and `rules.py` report: `docs/ai/local/` files whose template file is gone, shadowed rule files.
- Optional: to change the default changelog handling, add the `changelog` row to `docs/ai/config.md` § Formats.
- A project older than `v2.2.0` is no longer updated by `act-update`; it stops with a message naming `act-adopt`.
- A `file:` entry in `outside-root-allow` is now ignored.
- Shorten the `[Unreleased]` entries of your `CHANGELOG.md` that `act-doctor` names (over 250 characters), or set
  `changelog-length: off` in `docs/ai/config.md` § Checks.

### Added
- `act-doctor` notes a `docs/project/` file of 300 lines or more and a `docs/README.md` index line pointing below a
  subfolder (switch `docs-order`, never a block); the changelog length check skips code blocks and counts `*`/`+` items.
- Staged test cadence in `R-code-commit`: affected tests in a step, lint, typecheck and unit tests before a commit, the
  full suite before a push; `commands` takes an optional fourth entry for it (three entries work as before).
- `throwaway-place` check (`warn`|`off`, default `warn`): a note when a command or file write puts throwaway output
  in the system temp directory or directly under `.act-local/`; `off` in `docs/ai/config.md` § Checks silences it.
- Incident log: real faults (restored files, warn-mode misses, crashed checks, model switches) arrive as one inbox
  report per day at session start; no commands or paths are logged; `ACT_INCIDENT_LOG=off` pauses it.
- Check refusals are counted per check and role; `doctor.py --inbox` asks once after 3 refusals of one check in 7 days.
- Rule `R-work-process-error`: a fault in how the work runs is reported once as an inbox question, then fixed.
- `protected-watch` (`block`|`warn`|`off`, default `block`) puts back protected files a worker changed (`.git/hooks`,
  `.claude/settings*.json`, `.mcp.json`); changes by the orchestrator are only reported.
- `model-switch` check (`warn`|`off`, default `warn`) tells you when a worker or session continues on another model.
- Formats: `commit-format`, `changelog-format`, `release-notes-format`, `readme-format` in `docs/ai/config.md`;
  `docs/project/formats/<name>.md` replaces a preset; `act-export-settings --with-formats` carries them over.
- `CHANGELOG.md` for new projects (`changelog: file|release-notes-only|off`, default `file`); `act-update` offers it.
- `act-release` publishes the release on GitHub or GitLab after an explicit yes and a pushed tag.
- Working methods `test-first`, `spec-first`, `simple-changes`: the `methods` row in § Scope (default `none`).
- `act-adopt` ships in every project; `--carry` picks what a new project takes over.
- `outside-root-allow` takes a program folder such as `D:/Program Files/Browser`.
- Small additions: `entries.py new --triage`, a reason after a rule set path.
- `act-doctor` warns, never blocking, about an entry under `[Unreleased]` over 250 characters (`changelog-length`,
  default `warn`).

### Changed
- `update.py --plan` shows what each due migration does, not only its name; `act-update` shows those lines before you agree.
- Work with no task (skill runs, doctor report, feedback) writes throwaway output to
  `.act-local/tmp/<YYYYMMDD>-<slug>/`; `act-local-tidy` clears it after 7 days.
- `reviewer` blocks only for errors on ordinary paths; the full suite runs once on the accepted state.
- `/act-version` shows three lines (`--all` the long list); `/act-info` and `/act-version` are answered by the hook.
- Daily core rules are about 8 000 characters shorter, `act-adopt` half as long; every rule id stays.
- `init` sets the scope profile from the stack (`full` for web, else `standard`); existing projects keep theirs.
- `git-reset-hard` and `git-discard` are one check (both lines stay); `git branch -D` only for a branch HEAD contains.
- Nothing leaves `docs/` before it is in its monthly file; `done-entries: delete` projects now archive (migration 008).
- The recommended option of an inbox question comes first, as `**Recommended:**`; tier proposals are short.
- Hooks also try `py -3`, so checks no longer go silent on Windows with only that launcher.
- `protected-watch` leaves Claude Code's own "always allow" entries in `settings.local.json` and reports them.
- `protected-watch` stays silent on the orchestrator's skill copies under `.claude/skills/` that `act-update` writes
  unchanged; any other change there is still reported, a worker's change still put back.
- A danger-scan finding booked in the baseline passes the first hold.
- `init.py --target` refuses a target inside the project.
- One changelog form (`.act/formats/changelog.md`): one line per entry, at most 250 characters, duties under
  `### Upgrading`; a release adds a head line and 3–5 highlights.
- The template's own `CHANGELOG.md` is rewritten in that form, about a sixth of its former length; the full old wording
  stays in the Git history and the release notes of each tag.

### Removed
- The config key `done-entries` (projects behave as `keep` did) and `entries.py purge` (a call prints a notice).
- Migrations `001` to `004` for projects older than `v2.2.0`; `005` to `008` stay.

### Fixed
- `context_size.py` measures the session named by `CLAUDE_CODE_SESSION_ID`; without it and with two live transcripts
  it refuses ("several sessions, no assignment") instead of guessing; `--transcript <path>` still overrides.
- `worker-git-write` no longer refuses `git stash list` and `git stash show` for workers; every other `git stash` form
  stays refused.
- `worker-scope-overlap` also notes a run of the fourth `commands` entry (full or E2E suite) in a tree a running worker
  writes in.
- `write-guard` and the scope checks no longer refuse a `shutil.rmtree(..., onerror=h)` chmod helper that only calls
  `func(path)`, also on absolute folders.
- `worker-write-scope` no longer refuses inline Python that only adds an import folder (`sys.path.insert(0, 'lib')`,
  `append`, `extend`, `site.addsitedir`) next to a write elsewhere; code that reads the folder back is still checked.
- `outside-root` no longer refuses a URL route as an argument of a script call (`python x.py "/api/users"`,
  `node x.js /api/users`, `npx tsx`) when no such folder exists.
- `outside-root` no longer refuses `node -e`, `deno eval` or `bun -e` code that only passes a string to `new URL(`,
  `url.resolve(` or `path.normalize(`; code that names a file API (`fs`, `open(`) or a `file:` URL is still checked.
- The safety checks refuse fewer harmless commands: `cd` round trips before `xargs`, URL loops, `rsync` to remote
  hosts, PowerShell loops and assignments, `echo '$(...)'`, a single-quoted `` `rm x` `` in a commit message.
- The commit scans: `secret-scan` reads quoted file names, renames to `.env` and `$'` text correctly; `danger-scan`
  holds PHP `${name}` SQL and ignores messages that merely contain `select ... from`.
- The dependency scan keeps its time limit on Windows (`npm.cmd`, `pnpm`, `composer`) and counts `pnpm audit` as
  clean when all findings are ignored through `auditConfig.ignoreGhsas`.
- Session start survives a `config.md` that is not UTF-8 and no longer reports "update is available" at every start
  for a template source that is a plain folder without git.
- `init.py` commits only the paths it wrote and no longer fails on a Python bytecode cache in a skill folder.
- `i18n_check.py` reports no false missing or unused keys for a Nuxt i18n setup.
- Hook locks, hint buffers and `entries.py` no longer lose data or block.
- Smaller fixes: worker scope after a stop or continue, the default `worker-cap`, `/act-version`, `/act-info`,
  `act-local-tidy`, `act-doctor` and `rules.py` findings, rule-line moves in `rules.md`, the feedback link check.

### Security
- The write guard refuses `shutil.rmtree` of the project root or a folder that holds it (passed before), and an
  rmtree error helper that does more than `func(path)`.
- The write guard no longer lets a write through that takes its files from a list it cannot read (`xargs`, `$(...)`,
  loops, `find -exec`, PowerShell pipes, `mapfile`); a list passes only if it names fixed folders other than the root.
- Write checks see more targets (`sort -o`, `ssh -E`, `git clone`, `pushd`, `robocopy`), refuse one they cannot
  identify (inline code with an unseen path, `dir_fd=`, wildcard `cd`) and read `echo '...' | bash`.
- `outside-root` reads a `file:` URL and a lone `/` as the paths they name, and refuses a command that crashes its
  scanner or is too wide.
- IDE MCP read tools (`.env`, `~/.ssh/id_rsa`, outside paths) now pass through `secret-read` and `outside-root`.
- The git guards (`worker-git-write`, `git-discard`, `git-metadata-guard`) see git commands in subshells and
  PowerShell assignments; `worker-docs-ai` sees PowerShell writes into `docs/ai/`.
- `git-metadata-guard` sees copies of protected files with quoted names or inside `bash -c` and `pwsh -Command`.
- The `.act/` write guard recognizes `.act` in any letter case.
- Migrations, session start and hooks never write, move or remove through a link or junction (`docs/ai/inbox`,
  `.act-local`).
- `act-release` starts its security reviewer with `Write scope: none` again; it ran without a write scope.
- A failing `secret-read` or `outside-root` no longer lets a command through; a hook that cannot load refuses the call.

## [2.5.0] - 2026-11-05

Settings in one command, a slimmer template per project, tidier docs, stricter and quieter safety checks.

### Highlights
- **`/act-config`** lists every setting with allowed values and default, and changes one without a model turn.
- **`profile` and `exclude`** in `config.md` leave out unused skills, roles and rule files; safety stays.
- **Finished entries are deleted under Git** instead of archived; Git keeps their text, and their ids stay taken.
- **`act-seo`** is now a full page check: build, crawl and Lighthouse (`--live`), or PageSpeed for a public URL,
  which then goes to Google (key only from `PAGESPEED_API_KEY`).

### Upgrading from v2.4.0
- Run `act-update`, then start a new session. It adds `docs/ai/local/resources.md` and `docs/project/README.md` once,
  and the rule `R-docs-order` as a checkbox line in an edited `docs/ai/rules.md`.
- New keys (`done-entries`, `profile`, `exclude`, `docs-order`, `own-rules-budget`) take their default until you copy
  their row from `.act/skeleton/config.md`; `/act-config` changes only rows that exist.
- To keep archiving finished entries, add `done-entries: keep` under § Archive; under Git the default is now `delete`.
- Optional: your old archive stays; the first session start names its file count, `entries.py purge --all` deletes it.
- `act-doctor` warns about `docs/project/` files and folders without index lines; add them or set `docs-order: off`.
- `act-doctor` warns when "Own rules" exceed 6000 characters; raise the limit or set `own-rules-budget: off`. It
  may also report setting values it passed over before.
- A `config.md` value ending in `\` right before the next `|` now needs a space before the `|`.
- If you override `docs/ai/local/skills/act-audit-docs/workflow.js`, rename it to `workflow.js.txt`.
- Optional: `python .act/scripts/id_links_install.py` sets up clickable ids per machine, again after each update.

### Added
- Rule `R-docs-order`: one topic per file, a `README.md` in every folder of five or more entries, decided concepts
  removed; `move_doc.py` moves a document and its links.
- `feedback: local`: the project never sends feedback; template bugs become backlog entries instead.
- `act-integrations` allows the read-only tools of a catalog MCP server in one step; writing tools keep asking.

### Changed
- Inbox questions follow one form: question as heading, 2–5 options with effort, recommendation marked.
- `act-update` adds new template rules to an edited `docs/ai/rules.md`; your own text and lines you removed stay.

### Fixed
- Parallel worker starts on Windows no longer lose each other's write scope or cap.
- The safety checks refuse fewer harmless commands: heredocs, `ssh` calls, brackets in folder names.
- The dependency scan after `git merge` or `git pull` is no longer skipped on a busy machine.
- Updates keep the line endings of `rules.md` and `coding_rules.md`.

### Security
- The worker write scope also checks files that inline Python writes, even with paths built by
  `os.path.join`, f-strings or `glob`.
- The background dependency scan ignores merges aimed at another repository and accepts only full commit ids.
- Copies into protected paths such as `.git` are checked at any source size; a source that cannot be read in time
  is refused.
- `git branch -D @{-1}` is judged by the branch it names; a branch spelled two ways is never released as cherry-picked.
- `exec -a NAME cmd` and `sudo -nu NAME cmd` no longer hide `cmd` from the write checks.
- The write checks and `outside-root` read a WSL path `/mnt/<x>/...` as the Windows drive `<X>:`.
- Removing a throwaway folder never follows a junction out of it.
- secret-scan reads text behind a form feed or lone carriage return; an unreadable dependency report is not "clean".

## [2.4.0] - 2026-10-30

Named sessions and `/act-info`, advisories for faulty versions, a tidy `.act-local/`, leaner worker rules.

### Highlights
- **Session title from the project** (`session-name`) shows which project a Remote Control session belongs to.
- **Advisories** let the template author warn projects on a faulty version; a critical one shows at every start.
- **Throwaway files and the hooks' cache move to `.act-local/`**, which `act-local-tidy` keeps small.
- **A pending update stays visible** at session start, on the board and in the status line until installed.

### Upgrading from v2.3.0
- Run `act-update`, then start a new session so the new hooks take effect; there is no new migration.
- The update sets `PYTHON_BASIC_REPL=1` in `.claude/settings.json` and moves three rule lines in an edited `rules.md`.
- Six roles lose their `-high` variant; an assignment naming one names the role, or `builder-high`/`reviewer-high`.
- Set `session-name: auto` to leave titles to Claude Code; the default `project` uses the project's name.
- A worker's `Write scope:` that needs throwaway files names `.act-local/tmp/<task-id>-<slug>/**`.
- `advisory-check: off` in `docs/ai/config.md` switches advisories off; they are on by default.
- `act-local-tidy` only reports on its first run and removes from the next day; `act-local-keep` protects own entries.
- `act-version`, `act-export-settings` and `act-load-settings` start only as a slash command now.
- Delete `archive-shorten` from `docs/ai/config.md`; it is no longer read.
- Once every project on the machine is updated, delete the old `act-pycache` folder in the system temp directory.
- The update adds `.act-local/` to the IDE excludes (`.idea/*.iml`, `.vscode/settings.json`) and replaces the old
  worker-rule hook entries; your own hooks stay.

### Added
- `/act-info` shows folder, host, branch, last commit, changes, template version and open tasks; no network.
- `act-local-tidy` removes throwaway entries in `.act-local/` older than 7 days; `act-local-tidy: warn` only reports,
  `off` skips it.

### Changed
- `act-commit` removes a task's throwaway folders; the hooks' cache lives in `.act-local/pyc/`, none in long paths.
- Rules are shorter, no obligation removed; workers load 1,600 fewer characters.
- `git branch -D` of a branch taken over by cherry-pick is allowed; `act-compact` only merges now.

### Fixed
- Windows: an empty heredoc no longer hangs a Bash call, and umlauts in the branch name show right.
- `update.py` and `init.py` no longer crash when a question finds no input; they take the safe default.
- `security-check` no longer holds commits for query-builder templates or a fixed `DELETE FROM`/`INSERT INTO`.

### Security
- A worker with a `Write scope:` can no longer write to the system temp directory; `Write scope: none` allows no writes.
- The update check's `git ls-remote` allows only `file`, `git`, `http`, `https`, `ssh`, so `ext::` starts no program.
- `git branch -D` of an unmerged branch is refused also when a tag of the same name exists.
- Inline `python`/`node` code that writes outside a worker's `Write scope:` is refused; a refused write is reported.

## [2.3.0] - 2026-10-25

Outside-root checks, a choice of update channel, slimmer and measured workers, ten new coding sets.

### Highlights
- **`outside-root`** refuses reads and writes outside the project; extra places go into `outside-root-allow`.
- **`update-channel`** (`release` default, or `latest`) decides whether `act-update` follows releases or the branch.
- **Ten new coding sets** (PowerShell, Docker, CI, Rust, C, C++, Kotlin, CSS, JavaScript, React); `init` picks them.

### Upgrading from v2.2.0
- Run `act-update`, then start a new session so the new hooks and role fields take effect.
- Without `update-channel` in `docs/ai/config.md` you follow `release`; set `update-channel: latest` to keep the branch.
- `outside-root` runs as `warn`; set `block` in `docs/ai/config.md` § Checks; extra places: `outside-root-allow`.
- The update gives the template's roles `omitClaudeMd: true` and `.claude/settings.json` a `SubagentStart` hook;
  Claude Code before 2.1.271 ignores the field, so workers there get the rules twice.

### Added
- Workers start with about 24k characters less rule text; `usage.py --estimates` shows what runs cost.
- `entries.py compact` merges old archive entries into monthly files; git keeps the full text.
- `docs/ai/local/secret-accepted.md` accepts a known false alarm of the commit secret scan.
- `/act-version` shows installed version, channel and what `act-update` would take.

### Fixed
- pnpm projects are scanned (`pnpm audit`, pnpm 9+); the board no longer drops tasks silently.
- Smaller fixes in `init`, `act-adopt`, the shell guards and bridges under `core.autocrlf=true`.

### Security
- The dependency scan no longer reports findings as clean on Windows; an unreadable report holds the commit.
- `git-metadata-guard` checks what a recursive copy brings along, e.g. `cp -r payload/. .` with a `.git/config`.
- `secret-scan` catches a literal fallback after an environment lookup in more spellings; `sql-fstring` more templates.
- Credentials in a template source URL are masked in `update.py` output.

## [2.2.0] - 2026-10-20

Quick capture from chat, YAML frontmatter on entries, one-step archive, four new safety checks. Update: `act-update`.

### Highlights
- **Quick capture:** `todo:`, `note:` or `idea:` in chat is filed with no model turn; `quick-capture: off` stops it.
- **Entries open with YAML frontmatter,** so GitHub and Markdown editors show their fields as metadata.
- **`entries.py archive <id|file>`** archives a finished entry in one step and takes pasted images along.

### Upgrading from v2.1.0
- Run `act-update`: migrations `003` and `004` rewrite each inbox, task, backlog, journal and archive entry once.
- Updating now needs Git 2.25 or newer.
- Claude Code's `Artifact` tool is off after the update (saves ~13,700 tokens a session); `artifacts: on` keeps it.

### Added
- Rules `R-safe-dev-server` (test servers on their own port) and `R-code-checks-intact` (fix the code, not the check).
- `act-teach` lessons, coding rule set `nuxt5`, `board-at-start` (`on`|`off`): open tasks shown at session start.
- Four safety checks: `secret-read` (no secret file read into the context), `git-metadata-guard`, `git-discard` (no
  `git clean -f`, `stash drop`, force push to the default branch) and `worker-scope-overlap`.

### Changed
- New projects default to `feedback: confirm`: each payload is shown, nothing leaves without your yes; `off` stays.

### Fixed
- Updates on Windows no longer fail with "WinError 206"; session start no longer rewrites unchanged bridges.

### Security
- The Bash write checks read backslash-newline and heredocs the way bash does, also those fed to a shell, so a write
  after them no longer slips past the `.act/` guard; very many heredocs are scanned in linear time.
- `git-metadata-guard` also blocks workers from `.vscode/tasks.json`, `.devcontainer/`, `.envrc`, `.mcp.json`;
  workflow-script agents are bound to their `Write scope:` and `Cap:`.
- The `git reset --hard` guard holds on an undecodable file name; the recursive-delete check covers more forms.

## [2.1.0] - 2026-10-09

Six new skills, a status line that shows the context size, and safety checks that hold more and block less.

### Highlights
- **Six new skills:** `act-integrations`, `act-pr`, `act-issue`, `act-handover`, `act-check-translations`, `act-seo`.
- **Status line** shows the context size (`ctx 127k`); from `context-hint` (default 150000) the assistant suggests
  `/clear` at the next task boundary.

### Upgrading from v2.0.0
- Run `act-update` (or `python .act/scripts/update.py`); in `solo` mode it renames each inbox todo to `U<n>-<slug>.md`.
- In `team` mode run `entries.py assign` on the default branch for the same; the archive is never rewritten.

### Security
- `secret-scan` holds more credential forms (URL queries, quoted keys, PHP arrays) and no longer holds a
  commit over plain code.
- Write scanners read backtick and `$(…)` spans; worker write scope reads brackets literally, no outside wildcards.
- Lock files that come in via `git merge`, `pull` or `cherry-pick` get a dependency scan; findings never block.

## [2.0.0] - 2026-09-28

The rebuild with checks through hooks; replaces the previous generation on `main`, frozen on the branch `v1`.

### Highlights
- **One layer under `.act/`** with setup (`act-setup`), updates (`act-update`, `act-doctor`) and layered rules.
- **9 worker roles with model tiers, 23 skills;** Codex, Copilot, Cursor and Gemini CLI read `AGENTS.md` and
  `.agents/skills/`.
- **Checks through hooks:** secret and danger scans before a commit, worker caps and write scopes, a
  `git reset --hard` guard.

### Upgrading from the previous generation
- Do not merge or pull the new `main` into a project built on the previous generation; the layouts differ.
- Run `act-adopt` from a checkout of this release; it works on a branch of its own and the old state stays reachable.
- If `session start` says `.act/ was pulled in without update.py`, run
  `python .act/scripts/update.py` (or `--catch-up`) once.

## [0.1.0-beta] - 2026-09-13

First public pre-release of the previous generation (now the branch `v1`), documentation in German only.

### Added
- Rules in two layers (`AGENTS.md`, `CLAUDE.md`), 8 sub-agents, 6 skills and a `docs/ai/` working folder.

[Unreleased]: https://github.com/wrufeger/agentic-coding-template/compare/v2.5.0...HEAD
[2.5.0]: https://github.com/wrufeger/agentic-coding-template/compare/v2.4.0...v2.5.0
[2.4.0]: https://github.com/wrufeger/agentic-coding-template/compare/v2.3.0...v2.4.0
[2.3.0]: https://github.com/wrufeger/agentic-coding-template/compare/v2.2.0...v2.3.0
[2.2.0]: https://github.com/wrufeger/agentic-coding-template/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/wrufeger/agentic-coding-template/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/wrufeger/agentic-coding-template/releases/tag/v2.0.0
[0.1.0-beta]: https://github.com/wrufeger/agentic-coding-template/releases/tag/v0.1.0-beta
