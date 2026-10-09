<!-- act:default -->
# Project configuration

`init` fills in the values below from what it asked or detected. Change them any time — nothing
here needs a rebuild; `.act/hooks/dispatch.py` reads this file at session start.

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

`immediate` (default) \| `at-start`. `immediate`: every open decision, and every step only a person
can take and can take now, goes into `docs/ai/inbox/` as soon as it is booked, so the inbox always
shows everything waiting. `at-start`: a backlog entry may keep its open decisions — header
`decision: open`, listed on the board — until work on it starts (`act-prepare`); a task always has
them in the inbox (`R-human-ask`).

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

## Dependencies

| Key | Value |
| :--- | :--- |
| `dependency-check` | once |

`never` \| `once` \| `regularly`. `once` (default) leaves a one-time inbox entry right after `init`
asking to run `act-deps`, then only on request; `regularly` instead notes at session
start when the last `act-deps` run (a journal entry titled `act-deps: ...`) is older than 30 days;
`never` does neither — the skill itself still runs on explicit request either way.

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

## Checks

Each check below runs before the action it names; `block` refuses the action, `warn` allows it
with a note, `off` skips the check entirely. A check that only ever notes (marked "never
refuses") treats `block` as `warn`.

| Check | Value | Guards |
| :--- | :--- | :--- |
| `template-write-guard` | block | writes under `.act/` — put a project version in `docs/ai/local/<same path>` instead |
| `session-start-refresh` | block | rebuilds the generated bridges and the board at session start; `warn` only reports what it would refresh (once per change, not at every start) and writes nothing, here and in `update.py`'s bridge step; `off` skips it, and `update.py` then only reports too |
| `orchestrator-rules` | block | fallback only: while `docs/ai/rules.md` does not import the orchestrator-only rules (an older, locally changed copy), the session start names them in short; `off` skips it |
| `worker-nesting-guard` | block | a sub-agent calling `Agent`/`Task` (no sub-sub-agents, `R-role-worker`) — `warn` reports without blocking, `off` skips it |
| `worker-write-scope` | block | a worker writing outside its assignment's `Write scope:` line (`R-cost-delegate`) — `warn` reports without blocking, `off` skips it |
| `commit-pathspec` | block | `git add -A`, `git add .`, `git add --all`, `git commit -a` — stage by pathspec instead (`R-code-commit`) |
| `git-reset-hard` | block | `git reset --hard` (Bash/PowerShell, also `git -C <dir> ...`) while the affected working tree has uncommitted changes (untracked files count as changes too) or its own working tree cannot be determined — `git stash`/`git reset --soft` first (`R-safe-git-reset`) |
| `recursive-delete` | block | recursive delete from the shell (`rm -r`, `rmdir /s`, `Remove-Item -Recurse`, `find -delete`) — delete with the language's own means or file by file (`R-safe-no-shell-delete`) |
| `secret-scan` | block | `git commit` while the staged diff holds a key/token pattern, a private key, an `.env` file or a high-entropy assignment; a line carrying `act:allow-secret` is exempt (`R-safe-no-secret-diff`) |
| `security-check` | local | `off` \| `local` \| `deps` \| `full`, not the usual block/warn/off. `off` runs nothing here; `local`/`deps`/`full` all run the dangerous-pattern scan (Art A: `eval`/`exec`, `shell=True`, `pickle.loads`, `yaml.load` without a SafeLoader, `v-html`, `innerHTML =`, SQL built by string concatenation, ... — only for a coding rule set the project has checked on in `docs/project/coding_rules.md`) on `git commit`, stopping the first hit once per file and pattern with its location; the repeat goes through, and a line carrying `act:allow-danger` is exempt. A doc file (`.md`, `.txt`, `.rst`) and anything under `.act/` are never scanned (prose and the template's own files, not project code). `deps`/`full` add Art B (`.act/scripts/security_scan.py`, `.act/hooks/checks/deps_scan.py`): a live dependency-vulnerability lookup — `osv-scanner` if installed, else `npm audit`/`composer audit`/`pip-audit` per ecosystem — run on `git commit` for exactly the lock files that commit touches (`package-lock.json`, `composer.lock`, `requirements.txt`, `go.mod`, `Cargo.lock`, ...; a finding in a lock file the commit leaves alone never holds it), and once a day at session start over every lock file in the project (reported as a line there, never delaying the start itself). The scan never runs inside the commit's own hook call: it runs as a detached background process, the hook waits briefly for its result and otherwise denies once ("dependency scan running — commit again in a moment"); the retry reads the finished result, cached for the day per lock-file content (recorded only if the files did not change while the tool ran), so a repeated commit does not query again; a background run that outlives the tools' own timeouts lets the commit through unchecked, with a note, instead of waiting forever. An unaccepted finding at severity high/critical holds the commit (package, version, advisory id, severity, fixed version); a lower or unknown severity only notes — pip-audit's own output carries no severity field at all, so a pip-audit finding is always "unknown" and can only ever note, never hold the commit on its own. Accept a finding deliberately with a line in `docs/ai/local/security-accepted.md`: `- <advisory-id>: <reason>` (one per line; `#`-comments and blank lines ignored). A missing tool notes once per machine with the install command, never blocks; a tool or network failure notes every time, never blocks, and is reused for a minute at most before the next commit scans afresh (fail-open — Art B never has a template-shipped fallback list to fall back on, see the concept). `full` additionally runs Art C (Semgrep with open rule sets, plus a `reviewer` security pass) via `.act/scripts/security_deep.py`, but only on request and before a release (`act-release`) — never on every commit, same as Art A/B never run a heavy static-analysis pass |
| `worker-docs-ai` | block | a worker writing under `docs/ai/` — only the orchestrator writes there (`R-role-worker`) |
| `worker-git-write` | block | a worker running a git command that changes the tree or history (`commit`, `add`, `stash`, `checkout`, `reset`, `restore`, `merge`, `rebase`, `clean`, `push`) (`R-role-worker`) |
| `ide-mcp` | block | a connected IDE MCP server's own tools (`execute_terminal_command`, `apply_patch`, `execute_run_configuration`, ...), classified as shell/write/exec-without-target and checked the same way the matching standard tool would be — a target this cannot evaluate denies rather than passing through unchecked; `warn` reports without blocking, `off` skips it (`topics/ide.md`) |
| `worker-cap` | block | a worker's tool calls beyond its `Cap: <n>` line (without one: `light` 10, `standard` 40, `elevated` 60, `high`/`expert` 80) — a note at the cap, refused from 1.5 × the cap (`R-cost-delegate`); known limit: a call these checks allow but Claude Code's own permission prompt then denies still counts, since the pre-call hook never sees that denial |
| `status-poll` | block | repeated status queries on a running worker with no real work in between — refused from the second in a row (`R-cost-wait`) |
| `encoding-hint` | block | writing to a file that is not UTF-8 — the first write per session and file is stopped once with a note, the repeat goes through; `warn` only notes after the write (`R-code-encoding`) |
| `update-branch-hint` | warn | update or settings import on a branch other than the default one: one note that the others get it only with the merge — never refuses, `block` counts as `warn`, `off` drops the note |
| `update-check` | block | at session start: a note if `.act/` was pulled in without `update.py`, and — at most once a day — a note if the template has moved on; never refuses, `off` skips both |

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
`feedback`: `off` \| `confirm` \| `automatic` \| `manual`. `feedback-cadence` is an upper limit:
`manual` \| `immediate` \| `hourly` \| `daily` \| `weekly` \| `adaptive`. `feedback-scope`: `a`
metrics, `b` rule and structure changes, `c` tool usage (counts of template skills/scripts used since the last send; your own only as one `own` count). Every sent payload's full copy stays
local (`.act-local/feedback/sent/`, gitignored) — each send also gets one line in the journal
(date, kind, entry count, schema version, never content). A message you write yourself
(`feedback: <text>`) always goes out, even with `off`, together with the template commit and the
random project id (a reply address only if you name one). Details: `.act/rules/topics/feedback.md`.

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
