<!-- act:default -->
# Project configuration

`init` fills in the values below from what it asked or detected. Change them any time — nothing
here needs a rebuild; `.act/hooks/dispatch.py` reads this file at session start. `/act-config` (or
`python .act/scripts/config.py`) shows the values and sets them.

This file describes the **project** and is versioned. Secrets and per-machine or per-run deviations
belong in the environment, which overrides this file for that run and never the other way round; the
session start names every environment override that is active (names only, never values).

## Project

| Key | Value |
| :--- | :--- |
| `name` | <name> |
| `owner` | <owner> |
| `language-chat` | <language-chat> |
| `language-docs` | <language-docs> |
| `stack` | <stack> |
| `commands` | <lint-command>, <typecheck-command>, <test-command> |
| `tools` | <tool-list> |
| `mode` | <mode> |
| `run` | (not set) |

`language-chat` is the language the assistant talks in: `auto` (default) follows the owner's own
messages, a code such as `de` fixes it. `language-docs` is the language of everything the
assistant writes under `docs/` and of the scaffold there; `.act/` stays English either way
(`R-work-language`). A config.md with the older single `language` key still works — the value
counts for both.

`commands` is lint, typecheck, test, in this order; `(not set)` means no command is set up for that
slot, and the matching check is skipped (`R-code-commit`).

`run` is the command that starts the application; `(not set)` means none is recorded, and so does a
config.md without the row.

`mode` is `solo` or `team`, and it changes **one** thing: when an entry gets its short ID. In
`solo` the assistant assigns it right away and carries on. In `team` only
whoever files the entry on the default branch assigns it, so two people can never hand out the
same number; until then the file name is what you cite. File name, location and format are the
same either way, so you can switch back and forth at any time — IDs already assigned stay as they
are, only later ones follow the new value. Known limit: in a pure pull-request workflow where the default
branch is never checked out locally, nothing assigns IDs, so entries archived on feature branches stay
without one. The IDs are `T<n>` (task), `B<n>` (backlog item), `Q<n>`
(question) and `U<n>` (todo for you); a report or note has none.

## Scope

| Key | Value |
| :--- | :--- |
| `profile` | full |
| `exclude` | none |
| `methods` | <methods> |

`profile`: `minimal` \| `standard` \| `full`. How much of the template's skills and roles this project
loads; every skill description and every rule file is part of each session start, so fewer of them is a
smaller start. `full` (default; a missing key counts as `full`) keeps everything. `standard` leaves out the
web, design and teaching skills: `act-a11y`, `act-check-translations`, `act-design-assets`,
`act-design-build`, `act-design-ideas`, `act-seo`, `act-slides`, `act-teach`. `minimal` keeps only the core,
the skills `act`, `act-adopt`, `act-bug`, `act-commit`, `act-compact`, `act-config`, `act-doctor`,
`act-export-settings`, `act-feedback`, `act-handover`, `act-idea`, `act-info`, `act-load-settings`,
`act-prepare`, `act-setup`, `act-update`, `act-version` and the roles `builder`, `debugger`, `doc-writer`,
`explorer`, `quick-check`, `reviewer` (with their `-high` variants), and leaves out every other template
skill and role. A value that is none of the three counts as `full`, with a warning. A project's own skills
and roles (under `docs/ai/local/`) are never cut.

`exclude`: `none`, or a comma-separated list of what to leave out on top of the profile — the name of a
template skill (`act-seo`), of a template role (`test-writer`), of a rule file (`orchestrator/30-cost.md`)
or of a topic (`logging`, or `topics/logging.md`). Rule files fall only by name, never by profile. A rule
file stays under `.act/`, but its line in `docs/ai/rules.md` loses the `@` and Claude Code stops loading
it (so do the sub-agents); an excluded topic is no longer named at the session start. `shared/10-safety.md`
cannot be excluded (a warning, the entry is ignored), and an unknown name only gives a warning. The checks under
§ Checks stay in force either way: their blocks do not depend on rule text.

`methods`: `none`, or a comma-separated list of working methods from `.act/methods/` (`test-first`, `spec-first`,
`simple-changes`; what each asks: `.act/methods/README.md`; a project's own: `docs/ai/local/methods/<name>.md`).
Each named method is written into `docs/project/coding_rules.md` as an imported rule set (a section marked
`<!-- act:methods -->`), so the orchestrator and every worker load it; uncheck a single group there to switch it
off. The row decides: after a change run `python .act/scripts/rules.py --sync-methods`. `act-doctor` reports an
unknown name and a section that does not match the row. `init` asks once; the default is `none`.

The session start applies a change: it removes the copies of the skills and roles that are left out
(`.claude/skills/`, `.agents/skills/`, `.claude/agents/`; a copy you edited stays and is reported), switches
the import lines and says so in one line. Skills, roles and rules load when a session starts, so a change
takes effect from the **next** session. `init` and `update` respect the scope and never write a copy that
is left out. To undo it set `profile` to `full` and `exclude` to `none`: the next session start writes the
copies and import lines back.

## Status line

Claude Code's status line (`statusLine` in `.claude/settings.json`) shows what is waiting for you
in `docs/ai/inbox/` and how many open tasks there are — set by the template the first time there is
none yet. To turn it off for good: set your own `statusLine` command, even a trivial one — the
template only ever replaces its own previously generated entry, never a different one, so yours
then stays untouched by every later update. Removing the `statusLine` key outright turns it off
only until the next `init`/`update` run, which finds none set and adds the template's entry again
(unless a user-wide one exists by then, see below) — not a lasting way to turn it off. If a
user-wide `statusLine` already exists (`~/.claude/settings.json`), the project is left with none of
its own from the start, so the two never overlap — a one-line note says so at setup/update time.

## Board

| Key | Value |
| :--- | :--- |
| `board` | docs |
| `board-others` | |

`board`: `docs` (default) \| `shared` \| `local` — where the generated board goes. `docs`:
`docs/ai/board.md`, gitignored, one per checkout; its heading names the branch. `shared`: keeps the
local view in `docs/ai/board.md` and writes the versioned per-person board
`docs/ai/board-<identity>.md` (no last commit, no working tree, no timestamp) at commit time, by
`act-commit`. `local`: `.act-local/board-<branch>.md`. The local view is regenerated at session
start and after git commands in the session that change the checked-out state (merge, pull,
rebase, switch, checkout …); a versioned file is never rewritten by that. `board-others`: `on` \| `off` — a
section for tasks assigned to others (`for:` in the task header); with `shared` it also lists the others'
committed boards. Empty means `on` with `mode: team`, `off` otherwise.

## Inbox

| Key | Value |
| :--- | :--- |
| `inbox-decisions` | immediate |
| `quick-capture` | on |

`immediate` (default) \| `at-start`. `immediate`: every open decision, and every step only a person
can take and can take now, goes into `docs/ai/inbox/` as soon as it is booked, so the inbox always
shows everything waiting. `at-start`: a backlog entry may keep its open decisions — header
`decision: open`, listed on the board — until work on it starts (`act-prepare`); a task always has
them in the inbox (`R-human-ask`).

`quick-capture`: `on` \| `off`. `on` (default; a missing key counts as `on`): a chat message that begins
with `todo:`, `note:` or `idea:` is filed by the `UserPromptSubmit` hook without a model turn and never
reaches the model — `todo:` and `note:` as inbox entries marked `triage: open` (the assistant decides
whom a todo is for, or answers the note), `idea:` as a new section in your `ideas-<identity>.md`
(`R-human-capture`). `off`: the prefixes mean nothing special. If a message that starts with one of
the words was meant as an assignment, delete the file the hook names and send it again without the prefix.

## Output depth

| Key | Value |
| :--- | :--- |
| `output-depth` | normal |

`verbose` \| `normal` \| `sparse`. Controls what the assistant *writes* in chat, not what the
tool's own interface displays — see `docs/README.md` for the per-tool display settings. Defined in
`R-human-chat`: `normal` is compact and to the point (bullets rather than paragraphs); `sparse` gives
only what is needed — no interim status, one answer per question; `verbose` writes answers out —
the question as understood, reasons, notes on code it wrote and what to watch out for.

## Session length

| Key | Value |
| :--- | :--- |
| `context-hint` | 180000 |
| `task-wait-hours` | 12 |
| `board-at-start` | on |
| `session-name` | project |
| `artifacts` | off |

`board-at-start`: `on` \| `off`. `on` (default; a missing key counts as `on`) adds an excerpt of the
board to the session start — the "Open tasks" (with each task's last state line), "Answered" and
"Waiting for you" sections, about 2,000 characters at most; open tasks and answered entries stay whole,
the waiting entries fill the rest and end in a `+N more` line — so a bare "continue" can work from it
without first reading the board. It is shortened or dropped first when the session-start output
nears its size cap, and left out after a compaction (the compaction note already names the tasks).

`session-name`: `project` \| `auto` \| any other text. `project` (default; a missing key counts as
`project`) sets the Claude Code session title to the `name` from this file, or the project folder's name
while `name` is empty or still the placeholder, so a Remote Control session on the phone shows which
project it is. `auto` leaves naming to the tool. Any other text is used as the title itself (control
characters removed, 80 characters at most). Claude Code only; the title is set when a session starts,
resumes or forks, and never overwrites one you set with `/rename` or `claude -n`. A named session keeps
its title across `/clear`.

`artifacts`: `on` \| `off`. `off` (default; a missing key or any other value counts as `off`) puts
`"enableArtifact": false` into `.claude/settings.json`, so Claude Code no longer loads the `Artifact` tool —
about 13,700 tokens saved at every session start. It takes effect from the next session, not the running one.
`on` means "leave alone", not "switch on": it only removes an entry the template set itself, and a `false`
on user level or `CLAUDE_CODE_DISABLE_ARTIFACT=1` in the environment keeps the tool off regardless. Claude
Code only, and only an existing `.claude/settings.json` is touched. A value the project set itself is never
overwritten; one that contradicts `off` is reported once. The session start applies it under
`session-start-refresh` (`block` writes, `warn` only names it, `off` leaves it), `init` and `update` always.

`context-hint`: a token count, or `off`. Once the session's context (the input of its last model call,
read from the transcript) reaches this value, and again at each further multiple of it, the assistant
gets a one-time note to suggest `/clear` or a new session at the next task boundary
(`R-work-handover`); the status line shows the size as `ctx <n>k` either way. Every step of a long
session re-sends the whole context, so a fresh session after a finished task is the largest saving
there is. `task-wait-hours`: a started task counts as *waiting* rather than *running* in the status
line and on the board when any one of these holds: its last state line was written with
`entries.py state <id> --wait`; that line is older than this many hours (without a dated state line,
the task's `started:` time counts instead); or an open inbox todo or question names its id (reports
and notes do not count). A missing or malformed value counts as the default.

## Teaching

| Key | Value |
| :--- | :--- |
| `teach-lessons` | local |

`teach-lessons`: `local` \| `docs`. Where `act-teach` keeps its lessons. `local` (default; a missing
key counts as `local`, an unknown value as `local` with a note) writes lessons, exercises and the
learning record under `.act-local/learn/<topic>/`, in `language-chat`; nothing is versioned. `docs`
writes lessons and exercises under `docs/learn/<topic>/` in `language-docs`, versioned and checked by
`act-audit-docs`; the learning record stays under `.act-local/learn/<topic>/`.

## Dependencies

| Key | Value |
| :--- | :--- |
| `dependency-check` | regularly |

`never` \| `once` \| `regularly`. `regularly` (default) notes at session start when there is no
`act-deps` run on record yet ("no `act-deps` run on record yet", once), and afterwards when the last
run (a journal entry titled `act-deps: ...`) is older than 30 days; `once` instead leaves a one-time
inbox entry right after `init` asking to run `act-deps`, then only on request; `never` does neither — the skill itself still runs on explicit request either way.

## Docs audit

| Key | Value |
| :--- | :--- |
| `docs-audit-due` | 30d/100c |

`<n>d/<n>c` \| `off`. At session start, a note (at most once a day) when the last full
`act-audit-docs` sweep (a journal entry titled `act-audit-docs: ...`) is older than this many days
*or* this many commits, or once only when there is none yet — never a blocker, and only while
`docs/project/` exists. A missing or malformed value counts as `30d/100c`.

## Git hosting

| Key | Value |
| :--- | :--- |
| `target-branch` | auto |
| `forge` | auto |
| `forge-host` | auto |

`target-branch` is the branch a pull/merge request goes into. `auto` takes the remote's default
branch, else the first of `development`, `develop`, `main` that exists; a branch name fixes it (the
skill `act-pr` enters the value you confirm). `forge` is the host software of the `origin` remote:
`auto` tells GitHub from GitLab by the host name (`github.com`, `gitlab.com`), else by a read-only
probe of the host; `github` or `gitlab` sets it for a self-hosted instance. Empty, `(not set)` and a
missing key all count as `auto`, so a project from before this section needs no change.
`forge-host` names a self-hosted instance (one host name, or a comma list) that may receive the token;
`auto` or empty means none. `forge.py` sends a token only to `github.com` (`api.github.com`),
`gitlab.com`, a host named here or the host of `ACT_FORGE_API_URL` (an explicit override, for tests and
proxies), and never over `http://` except to loopback. Enter a host only after the human confirmed it —
this keeps a global token from going to a foreign host. Without it reads run without a token; `whoami`,
`issues --mine` and every write stop with a hint before any request. A confirmed host reached over
`http://` gets the same treatment until its address is `https://`.

## Formats

| Key | Value |
| :--- | :--- |
| `commit-format` | auto |
| `changelog` | file |
| `changelog-format` | keep-a-changelog |
| `release-notes-format` | standard |
| `readme-format` | standard |

How the assistant writes commit messages, the changelog, release notes and the README. Each `*-format` row picks
a preset from the template's default file in `.act/formats/` (`commit.md`, `changelog.md`, `release-notes.md`,
`project-readme.md`; an empty value, `auto` and an unknown name mean that file's default). A file of the same name
under `docs/project/formats/` replaces the template file completely and wins over the row. Values:
`commit-format`: `auto` (the repo's own style) \| `conventional` \| `plain`. `changelog`: `file` (a `CHANGELOG.md`
in the project root, created by `init`, offered to older projects by `act-update`) \| `release-notes-only` (no
file; `act-release` keeps the notes in the tag and the release entry) \| `off`. `changelog-format`:
`keep-a-changelog` (entries are added under `[Unreleased]` as commits are made) \| `at-release` (written by
`act-release` only). `release-notes-format`: `standard` \| `changelog-copy`. `readme-format`: `standard` \|
`with-toc` \| `minimal` (read by `init` when it writes the README, and by `act-audit-docs`).

## Checks

Each check below runs before the action it names; `block` refuses the action, `warn` allows it
with a note, `off` skips the check entirely. A check that only ever notes (marked "never
refuses") treats `block` as `warn`.

| Check | Value | Guards |
| :--- | :--- | :--- |
| `template-write-guard` | block | writes under `.act/` — put a project version in `docs/ai/local/<same path>` instead |
| `session-start-refresh` | block | rebuilds the generated bridges and the board at session start; `warn` only reports what it would refresh (once per change, not at every start) and writes nothing (one exception: a missing `.act-local/identity.json` is still created from `git config user.name`), here and in `update.py`'s bridge step; `off` skips it, and `update.py` then only reports too |
| `orchestrator-rules` | block | fallback only: while `docs/ai/rules.md` does not import the orchestrator-only rules (an older, locally changed copy), the session start names them in short; `off` skips it |
| `worker-nesting-guard` | block | a sub-agent calling `Agent`/`Task` (no sub-sub-agents, `R-role-worker`) — `warn` reports without blocking, `off` skips it |
| `worker-write-scope` | block | a worker writing outside its assignment's `Write scope:` line (`R-cost-delegate`) — `warn` reports without blocking, `off` skips it |
| `worker-scope-overlap` | block | a worker start whose `Write scope:` overlaps that of a worker still running — `none` overlaps nothing, a missing line counts as everything (`R-cost-delegate`); a finished worker or a failed start frees its scope, a crashed worker after three hours or when its file under `.act-local/worker-scopes/` is deleted; of two starts racing in one message the later one is refused; limit: a worker continued with `SendMessage` is invisible once ended; `warn` reports without blocking, `off` skips it |
| `commit-pathspec` | block | `git add -A`, `git add .`, `git add --all`, `git commit -a` — stage by pathspec instead (`R-code-commit`) |
| `git-reset-hard` | block | `git reset --hard` (Bash/PowerShell, also `git -C <dir> ...`) while the affected working tree has uncommitted changes (untracked files count as changes too) or its own working tree cannot be determined — `git stash`/`git reset --soft` first (`R-safe-git-reset`) |
| `git-discard` | block | `git clean -f` that would delete something, `git checkout`/`git restore` of a folder (or `checkout -f`, `switch -f`) with uncommitted tracked changes in the target, `git stash drop`/`clear`, a forced push to the default branch (`origin/HEAD`, else `init.defaultBranch`, else `main`/`master`), `git branch -D` of an unmerged branch (Bash/PowerShell, also `git -C <dir> ...`); deleting the default branch on the remote and `branch -M`/`-C` over an unmerged branch count as well; a target that cannot be determined, or a call that cannot be checked in time, is refused (`R-safe-git-discard`) |
| `git-metadata-guard` | block | writes to `.git/hooks/**`, `.git/config` (also a `.git` file's git directory) and `git config`/`git -c` keys that run code (`core.hooksPath`, `core.fsmonitor`, `core.sshCommand`, `!` aliases …) for everyone; for workers also `.claude/settings*.json`, `.claude/agents/**`, `.claude/skills/**`, `.claude/commands/**` (project and `~/.claude`), plus `.vscode/tasks.json`, `.devcontainer/**`, `.devcontainer.json`, `.envrc`, `.mcp.json` and tasks that run on `folderOpen` — ask the human (`R-safe-git-metadata`) |
| `protected-watch` | block | after every tool call (orchestrator and workers) a snapshot comparison of the files `R-safe-git-metadata` protects — `.git/hooks/**`, `.git/config` (only the keys that start code), `.claude/settings*.json`, `.claude/agents/**`, `.claude/skills/**`, `.claude/commands/**`, `.mcp.json`, `.envrc`, `.devcontainer/**`, `.vscode/tasks.json`; a change in a worker's call is put back at once from the snapshot taken before the call and kept under `.act-local/protected-watch/kept/`, a change by the orchestrator is only reported, with the command that puts it back; `warn` reports every change and restores nothing, `off` takes no snapshot; reports after the call, prevents nothing; `ACT_PROTECTED_WATCH` in the environment overrides the value for one run (`R-safe-git-metadata`, details in `topics/checks.md`) |
| `recursive-delete` | block | recursive delete from the shell (`rm -r`, `rmdir /s`, `Remove-Item -Recurse`, `find -delete`) — delete with the language's own means or file by file (`R-safe-no-shell-delete`) |
| `secret-scan` | block | `git commit` while the staged diff holds a key/token pattern, a private key, an `.env` file or a high-entropy assignment; a line carrying `act:allow-secret` is exempt, and for a file without comments (JSON) so is a line listed in `docs/ai/local/secret-accepted.md` as `- <path> <hash>: <reason>` — the hold message prints the finished entry (path and a line hash, never the value); a changed line, the same line in another file, or an unreadable list is held again (`R-safe-no-secret-diff`) |
| `secret-read` | block | Read, Grep (`path`, `glob`) and Bash/PowerShell reading commands (`cat`, `grep`, `Get-Content`, `< file` at any position, `git show HEAD:<file>`, ...) naming a secret file — `.env` and its variants (not a name ending in `.example`/`.sample`/`.template`, not a public key `*.pub`), private keys and keystores, `~/.ssh`, `~/.aws`, `~/.config/gcloud` and other credential paths; applies to workers too; `warn` reports without blocking; `ACT_SECRET_READ` in the environment overrides the value for one run (`R-safe-no-secret-read`) |
| `outside-root` | block | Read, Write, Edit, Grep, Glob and Bash/PowerShell naming a path outside the project root and its allowed places (`permissions.additionalDirectories`, the system temp directory, Claude Code's own folder for this project, the `outside-root-allow` entries); applies to workers too; `warn` reports without blocking; `ACT_OUTSIDE_ROOT` in the environment overrides the value for one run; a project without this row runs it as `warn` (`R-safe-outside-root`) |
| `outside-root-allow` | none | exceptions to `outside-root`: `none`, or a comma-separated list of paths, each relative to the project root or starting with `~`, each optionally followed by ` (read)` for read-only, e.g. `../other-repo (read), ~/shared/specs` — a pipe character inside the value gets a backslash in front of it (`R-safe-outside-root`) |
| `act-local-tidy` | block | session start, once a day in the background: removes from `.act-local/` the `tmp/` entries older than 7 days that belong to no open task, all but the newest 5 `backup/` folders, `pyc/` cache folders whose source folder is gone and that hold nothing newer than 7 days, and old entries that no template script creates (age = newest change inside); `warn` only reports what would go, `off` skips; the first run in a project only reports and removal starts the next calendar day; a project without this row runs it as `block` (`R-work-throwaway`) |
| `act-local-keep` | none | exceptions to `act-local-tidy`: `none`, or a comma-separated list of patterns relative to `.act-local/`, e.g. `exports, tmp/long-*` — matching entries are never removed; a pipe character inside the value gets a backslash in front of it (`R-work-throwaway`) |
| `security-check` | local | `off` \| `local` \| `deps` \| `full`, not the usual block/warn/off. `off` runs nothing here; `local`/`deps`/`full` all run the dangerous-pattern scan (Art A: `eval`/`exec`, `shell=True`, `pickle.loads`, `yaml.load` without a SafeLoader, `v-html`, `innerHTML =`, SQL built by string concatenation, ... — only for a coding rule set the project has checked on in `docs/project/coding_rules.md`) on `git commit`, stopping the first hit once per file and pattern with its location; the repeat goes through, and a line carrying `act:allow-danger` is exempt. A doc file (`.md`, `.txt`, `.rst`) and anything under `.act/` are never scanned (prose and the template's own files, not project code). `deps`/`full` add Art B (`.act/scripts/security_scan.py`, `.act/hooks/checks/deps_scan.py`): a live dependency-vulnerability lookup — `osv-scanner` if installed, else `npm audit`/`composer audit`/`pip-audit` per ecosystem — run on `git commit` for exactly the lock files that commit touches (`package-lock.json`, `composer.lock`, `requirements.txt`, `go.mod`, `Cargo.lock`, ...; a finding in a lock file the commit leaves alone never holds it), and once a day at session start over every lock file in the project (reported as a line there, never delaying the start itself). The scan never runs inside the commit's own hook call: it runs as a detached background process, the hook waits briefly for its result and otherwise denies once ("dependency scan running — commit again in a moment"); the retry reads the finished result, cached for the day per lock-file content (recorded only if the files did not change while the tool ran), so a repeated commit does not query again; a background run that outlives the tools' own timeouts lets the commit through unchecked, with a note, instead of waiting forever. An unaccepted finding at severity high/critical holds the commit (package, version, advisory id, severity, fixed version); a lower or unknown severity only notes — pip-audit's own output carries no severity field at all, so a pip-audit finding is always "unknown" and can only ever note, never hold the commit on its own. Accept a finding deliberately with a line in `docs/ai/local/security-accepted.md`: `- <advisory-id>: <reason>` (one per line; `#`-comments and blank lines ignored). A missing tool notes once per machine with the install command, never blocks; a tool or network failure notes every time, never blocks, and is reused for a minute at most before the next commit scans afresh (fail-open — Art B never has a template-shipped fallback list: a list shipped with an update is stale on arrival, the tools fetch their data live). `full` additionally runs Art C (Semgrep with open rule sets, plus a `reviewer` security pass) via `.act/scripts/security_deep.py`, but only on request and before a release (`act-release`) — never on every commit, same as Art A/B never run a heavy static-analysis pass |
| `worker-docs-ai` | block | a worker writing under `docs/ai/` — only the orchestrator writes there (`R-role-worker`) |
| `worker-git-write` | block | a worker running a git command that changes the tree or history (`commit`, `add`, `stash`, `checkout`, `reset`, `restore`, `merge`, `rebase`, `clean`, `push`) (`R-role-worker`) |
| `ide-mcp` | block | a connected IDE MCP server's own tools (`execute_terminal_command`, `apply_patch`, `execute_run_configuration`, ...), classified as shell/write/exec-without-target and checked the same way the matching standard tool would be — a target this cannot evaluate denies rather than passing through unchecked; `warn` reports without blocking, `off` skips it (`topics/ide.md`) |
| `worker-cap` | block | a worker's tool calls beyond its `Cap: <n>` line (without one: `light` 10, `standard` 40, `elevated` 60, `high`/`expert` 80) — a note at the cap, refused from 1.5 × the cap (`R-cost-delegate`); known limit: a call these checks allow but Claude Code's own permission prompt then denies still counts, since the pre-call hook never sees that denial |
| `status-poll` | block | repeated status queries on a running worker with no real work in between — refused from the second in a row (`R-cost-wait`) |
| `encoding-hint` | block | writing to a file that is not UTF-8 — the first write per session and file is stopped once with a note, the repeat goes through; `warn` only notes after the write (`R-code-encoding`) |
| `model-switch` | warn | at `SubagentStop` and `Stop`: a worker or the session that continues on another model (a `stop_reason: refusal`, a changed model in the transcript) is shown to the human as a message starting with a warning sign and `MODEL SWITCH`, naming role and models, and noted to the orchestrator with its next tool call; never refuses, `block` counts as `warn`, `off` skips it (`R-safe-block`, details in `topics/safeguards.md`) |
| `update-branch-hint` | warn | update or settings import on a branch other than the default one: one note that the others get it only with the merge — never refuses, `block` counts as `warn`, `off` drops the note |
| `update-check` | block | at session start: a note if `.act/` was pulled in without `update.py`, and — checked at most once a day — a note that the template has moved on, repeated at every start and shown on the board and in the status line until the update is installed; never refuses, `off` skips both |
| `docs-order` | warn | `act-doctor` only, never refuses: a folder under `docs/project/` with five or more entries and no `README.md`, a file its `README.md` does not name, an index line without a file, a dead relative link, a concept whose questions are all answered; `block` counts as `warn`, `off` skips it (`R-docs-order`) |
| `own-rules-budget` | 6000 | `act-doctor` only, never refuses: the characters the "Own rules" sections of `docs/ai/rules.md` and `docs/project/coding_rules.md` may have together before one warning names the size and up to five lines that read like history (a date, an entry identifier, "formerly … since …"); `off` or `0` skips it |

## Logging

| Key | Value |
| :--- | :--- |
| `logging` | off |
| `log-level` | INFO |

`logging`: `on` \| `off`. With `on`, every agent action lands as one line in `ai.log` at the
project root (not versioned) — to follow along live, e.g. in a second terminal during a talk.
`log-level`: `DEBUG` \| `INFO` \| `WARN` \| `ERROR`. Details: `.act/rules/topics/logging.md`.

## Feedback

| Key | Value |
| :--- | :--- |
| `feedback` | <feedback-mode> |
| `feedback-cadence` | weekly |
| `feedback-scope` | a,b,c |

Voluntary feedback to the template author about the working method, never about the project.
`feedback`: `off` \| `confirm` \| `automatic` \| `manual` \| `local` (this project never sends anything to
the template author; findings become backlog entries here instead). `feedback-cadence` is an upper limit:
`manual` \| `immediate` \| `hourly` \| `daily` \| `weekly` \| `adaptive`. `feedback-scope`: `a`
metrics, `b` rule and structure changes, `c` tool usage (counts of template skills/scripts used since the last send; your own only as one `own` count). Every sent payload's full copy stays
local (`.act-local/feedback/sent/`, gitignored) — the journal gets one entry per day with one line per send
(time, kind, entry count, each entry's kind and title, never its text). A message you write yourself
(`feedback: <text>`) always goes out, even with `off` (but never with `local`), together with the template commit and the
random project id (a reply address only if you name one). Details: `.act/rules/topics/feedback.md`.

## Update

| Key | Value |
| :--- | :--- |
| `update-channel` | <update-channel> |
| `advisory-check` | on |

`update-channel`: `release` \| `latest`. With `release` (the default) `act-update` offers only the newest
stable release tag of the template source and the session start announces only that; with `latest` it follows
the tip of the source's default branch. `--channel` on `update.py` overrides it for one run. Details:
`.act/skills/act-update/SKILL.md`.

`advisory-check`: `on` \| `off`. `on` (default; a missing key counts as `on`): the daily background check also asks
the template source for warnings about template versions with a known serious problem and shows the ones that apply to
your installed version (session start, status line, board, inbox) until you update or acknowledge them; `off` asks and
shows nothing. The lookup runs with the `update-check` background run, so `update-check: off` stops it too. Details:
`python .act/scripts/advisory.py --help`.

## Archive

| Key | Value |
| :--- | :--- |
| `done-entries` | delete |
| `archive-compact` | 30d 300 |

`done-entries`: `delete` \| `keep`. What happens to a finished task, backlog item or inbox entry. `delete`: once
Git holds the entry unchanged, `entries.py archive` deletes it (with the pasted files that travel with it) instead of
moving it to `docs/ai/work/archive/`; Git keeps the text (`git log --follow`, `git show <commit>:<path>`). An entry
Git does not hold yet (never committed, or changed since) still goes to the archive, marked `purge: after-commit`, and is removed by the next
`entries.py purge`, which `act-commit` runs; so does every task, with its `finished:` stamp, so a finished task
stays visible until the commit that holds it. An id stays taken: the highest id of each kind is kept in
`docs/ai/work/reserved-ids.json` and the next `new` hands out one above it. A link to a deleted entry in other
Markdown files becomes its bare id, so an id in text stays valid. `act-compact` then folds only the journal. `keep`:
finished entries go to the archive for good, as before. A missing, empty or unknown value is `delete` in a project
with its own Git repository and `keep` without one; `delete` without a repository counts as `keep`, since nothing would
hold the text. An archive that exists when a project moves to `delete` stays as it is until you decide: the session
start names the number of files once, `python .act/scripts/entries.py purge --all --plan` lists what would go and
`entries.py purge --all` deletes what Git holds unchanged. Plain `purge` touches only files marked
`purge: after-commit`, and the assistant never runs `--all` on its own.

`archive-compact`: `<n>d <n>` \| `off`. `entries.py compact` is due for the archive or the journal folder once its
oldest single entry is older than this many days, or the folder holds more than this many single files; the session
start says so once a day, with the number of entries (`act-compact`). Only entries archived more than 7 days ago are
merged, word for word, with a monthly overview `archive/YYYY-MM.md` of one line per entry; no worker takes part. A
missing or malformed value counts as `30d 300`; in team mode the note appears only on the default branch. With
`done-entries: delete` only the journal folder counts and is merged (`archive/ledger-<YYYY-MM>.md`).

## Tips

| Key | Value |
| :--- | :--- |
| `tips` | occasionally |

`never` \| `occasionally` (at most once a session and once a day) \| `regularly` (once a
session). Tips come from `.act/tips.md` and disappear once you use the feature. Your own reminders
in `docs/ai/local/reminders.md` are not affected by this key.

## Roles
<!-- act:roles -->

| Role | Tier | Reasoning | Model |
| :--- | :--- | :--- | :--- |

Empty by default: every role runs the tier/reasoning the template ships. Fill a row to override
one role's tier and/or reasoning, or set `Model` outright — a filled `Model` wins over `Tier`.
A skill's name in the `Role` column (e.g. `act-prepare`) overrides that skill's own `reasoning` level for this project; only `Reasoning` counts there.
