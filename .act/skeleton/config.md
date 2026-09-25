<!-- act:default -->
# Project configuration

`init` fills in the values below from what it asked or detected. Change them any time — nothing
here needs a rebuild; `.act/hooks/dispatch.py` reads this file at session start.

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

`language-chat` is the language the assistant talks in: `auto` (default) follows the owner's own
messages, a code such as `de` fixes it. `language-docs` is the language of everything the
assistant writes under `docs/` and of the scaffold there; `.act/` stays English either way
(`R-work-language`). A config.md with the older single `language` key still works — the value
counts for both.

`commands` is lint, typecheck, test, in this order; `(not set)` means no command is set up for that
slot, and the matching check is skipped (`R-code-commit`).

`mode` is `solo` or `team`, and it changes **one** thing: when an entry gets its short ID. In
`solo` the assistant assigns it right away (`Q66`, `T19`, `B99`) and carries on. In `team` only
whoever files the entry on the default branch assigns it, so two people can never hand out the
same number; until then the file name is what you cite. File name, location and format are the
same either way, so you can switch back and forth at any time — IDs already assigned stay as they
are, only later ones follow the new value.

## Output depth

| Key | Value |
| :--- | :--- |
| `output-depth` | normal |

`verbose` \| `normal` \| `sparse`. Controls what the assistant *writes* in chat, not what the
tool's own interface displays — see `docs/README.md` for the per-tool display settings.

## Dependencies

| Key | Value |
| :--- | :--- |
| `dependency-check` | once |

`never` \| `once` \| `regularly`. `once` (default) leaves a one-time inbox entry right after `init`
asking to run `act-deps`, then only on request (`B102`); `regularly` instead notes at session
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

## Checks

Each check below runs before the action it names; `block` refuses the action, `warn` allows it
with a note, `off` skips the check entirely. A check that only ever notes (marked "never
refuses") treats `block` as `warn`.

| Check | Value | Guards |
| :--- | :--- | :--- |
| `template-write-guard` | block | writes under `.act/` — put a project version in `docs/ai/local/<same path>` instead |
| `session-start-refresh` | block | rebuilds the generated bridges and the board at session start; `warn` reports without writing, `off` skips it |
| `orchestrator-rules` | block | fallback only: while `docs/ai/rules.md` does not import the orchestrator-only rules (an older, locally changed copy), the session start names them in short; `off` skips it |
| `worker-nesting-guard` | block | a sub-agent calling `Agent`/`Task` (no sub-sub-agents, `R-role-worker`) — `warn` reports without blocking, `off` skips it |
| `worker-write-scope` | block | a worker writing outside its assignment's `Write scope:` line (`R-cost-delegate`) — `warn` reports without blocking, `off` skips it |
| `commit-pathspec` | block | `git add -A`, `git add .`, `git add --all`, `git commit -a` — stage by pathspec instead (`R-code-commit`) |
| `git-reset-hard` | block | `git reset --hard` (Bash/PowerShell, also `git -C <dir> ...`) while the affected working tree has uncommitted changes (untracked files count as changes too) or its own working tree cannot be determined — `git stash`/`git reset --soft` first (`R-safe-git-reset`) |
| `recursive-delete` | block | recursive delete from the shell (`rm -r`, `rmdir /s`, `Remove-Item -Recurse`, `find -delete`) — delete with the language's own means or file by file (`R-safe-no-shell-delete`) |
| `secret-scan` | block | `git commit` while the staged diff holds a key/token pattern, a private key, an `.env` file or a high-entropy assignment; a line carrying `act:allow-secret` is exempt (`R-safe-no-secret-diff`) |
| `security-check` | local | `off` \| `local` \| `deps` \| `full`, not the usual block/warn/off. `off` runs nothing here; `local`/`deps`/`full` run the dangerous-pattern scan (Art A: `eval`/`exec`, `shell=True`, `pickle.loads`, `yaml.load` without a SafeLoader, `v-html`, `innerHTML =`, SQL built by string concatenation, ... — only for a coding rule set the project has checked on in `docs/project/coding_rules.md`) on `git commit`, stopping the first hit once per file and pattern with its location; the repeat goes through, and a line carrying `act:allow-danger` is exempt. A doc file (`.md`, `.txt`, `.rst`) and anything under `.act/` are never scanned (prose and the template's own files, not project code). `deps` and `full` behave like `local` for now — the library-vulnerability lookup (Art B, e.g. `pip-audit`/`npm audit`/`osv-scanner`) and the deep check (Art C, Semgrep/a `reviewer` pass) are not built yet, pending a decision on network access |
| `worker-docs-ai` | block | a worker writing under `docs/ai/` — only the orchestrator writes there (`R-role-worker`) |
| `worker-git-write` | block | a worker running a git command that changes the tree or history (`commit`, `add`, `stash`, `checkout`, `reset`, `restore`, `merge`, `rebase`, `clean`, `push`) (`R-role-worker`) |
| `worker-cap` | block | a worker's tool calls beyond its `Cap: <n>` line (without one: `light` 10, `standard` 40, `elevated` 60, `high`/`expert` 80) — a note at the cap, refused from 1.5 × the cap (`R-cost-delegate`) |
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
metrics, `b` rule and structure changes, `c` tool usage. Every sent payload's full copy stays
local (`.act-local/feedback/sent/`, gitignored) — each send also gets one line in the journal
(date, kind, entry count, schema version, never content). A message you write yourself
(`feedback: <text>`) always goes out, even with `off`. Details: `.act/rules/topics/feedback.md`.

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
