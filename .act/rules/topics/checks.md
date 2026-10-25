# Mechanically checked rules — details

Detail page for the rules that name `topics/checks.md`. Each rule in `.act/rules/` keeps what is
forbidden or required; what its check recognises, where its limits lie, how it is switched and which
syntax it expects stands here, one section per rule. The block messages of the checks name the
syntax and point here. The checks are switched in `docs/ai/config.md` § Checks (`block`, `warn` or
`off`). The sentences below are the former text of the rules, moved here unchanged.

## `R-safe-no-secret-read` — Never read a secret file into the context

Checks: secret-read.

Checked mechanically by `secret-read` (`docs/ai/config.md` § Checks); the owner may set it to `warn`
or `off` there, or for one run with `ACT_SECRET_READ` in the environment. Limit: a program that
opens the file itself (`python script.py`, `docker run --env-file`) is invisible to the check.

## `R-safe-outside-root` — Stay inside the project

Checks: outside-root.

Read and write only inside the project root and the places allowed for it: the folders in
`permissions.additionalDirectories`, the system temp directory, Claude Code's own folder for this
project, its plan folder `~/.claude/plans/`, read-only its plugin and skill folders
(`~/.claude/plugins/`, `~/.claude/skills/`), and the entries of `outside-root-allow`
(`docs/ai/config.md` § Checks; `(read)` after a path allows reading only). Any other place — a
neighbouring repository, another project, the home directory — only on the owner's word for this
case, and then as an entry in `outside-root-allow` or `additionalDirectories`, never as a one-off
workaround. Applies to every role and tool.

`act-adopt` is the one exception: the owner starts the first scan with the `!` prefix, which opens
the target folder for 24 hours or until `--abort` (also past `--finish`) through a marker under
`.act-local/outside-allow/` that nobody but the adopt scripts writes; `--apply` only refreshes a
valid marker for the same target. Checked mechanically by `outside-root` (`docs/ai/config.md` §
Checks); the owner may set it to `warn` or `off` there, or for one run with `ACT_OUTSIDE_ROOT` in
the environment. Limits: the shell check is best effort, a program that opens files itself (`python
script.py`, `docker run -v`) is invisible to it, and MCP tools that take a path are not checked.

## `R-safe-git-reset` — Check before `git reset --hard`

Checks: git-reset-hard.

The rule text carries everything the check enforces; there is nothing further to add.

## `R-safe-git-discard` — Don't discard work with other git commands either

Checks: git-discard.

Next to `git reset --hard`, these git commands throw work away with no way back: `git clean -f` (or
`git clean` with `clean.requireForce` switched off) when `git clean -n` with the same switches lists
something; `git checkout -- <folder>`, `git checkout .`, `git restore <folder>`, `git checkout -f`,
`git switch -f` while the target has uncommitted changes; `git stash drop` and `git stash clear`; a
forced push (`-f`, `--force-with-lease`, `+refspec`, `--mirror`) to the default branch, or deleting
it on the remote (`git push origin :main`, `--delete`); `git branch -D` of a branch `git branch
--no-merged` lists, and `git branch -M`/`-C` over one. A call too long to check in time, or a check
that fails, is refused — run smaller calls.

## `R-safe-git-metadata` — No writing of hooks, repository config or Claude settings

Checks: git-metadata-guard.

Nobody writes `.git/hooks/**` or `.git/config` (also `config.worktree`, submodule and
linked-worktree git directories), and copies nothing into them — neither with a file tool nor a
shell command, nor with `git config`, `git -c` or `GIT_CONFIG_KEY_<n>` for a key that starts a
program (`core.hooksPath`, `core.fsmonitor`, `core.sshCommand`, a `!` alias, `include.path`, a
filter, textconv or credential helper, an `ext::` remote URL, `protocol.allow=always` …), and
`GIT_CONFIG_GLOBAL`, `GIT_CONFIG_SYSTEM` or `GIT_CONFIG` pointing at `.git/config` counts like
`--file`; `git init --template` is refused the same way. Files that start code when the folder is
opened are covered too: a worker never writes `.vscode/tasks.json`, `.devcontainer/**`,
`.devcontainer.json`, `.envrc` or `.mcp.json` (file tool or shell, also by copying into their
directory), and nobody writes `.vscode/tasks.json` with a shell command, or adds a task that runs on
`folderOpen` to `.vscode/tasks.json` or a `*.code-workspace` with a file tool (judged on the text
the edit produces); the human writes such a file themselves. Limit: what a program or script writes
itself (`pre-commit install`, `python -c "open(...)"`) is invisible to the check.

## `R-cost-delegate` — Name the tier, the estimate, and the cap

Checks: worker-cap, worker-write-scope, worker-scope-overlap.

`Cap:` is recognized either on its own line or right after a `·`/`|`/`;`/`,` further into a line, so
a compact header works too, e.g.

`Tier: standard · Estimate: ~30 min · ~400k tkn fresh · ~8M tkn cache · Cap: 95.` Leaving the line
out falls back to the tier's own default: `light` 10, `standard` 40, `elevated` 60, `high`/`expert`
80; with neither a `Cap:` nor a `Tier:` line, `standard`.

The worker gets one note on reaching the cap ("cap reached — deliver your current state now") and is
refused from 1.5× the cap onward — wrap up and report rather than push past it.

Every assignment also states its write scope as a `Write scope: <glob>[, <glob> ...]` line —
patterns relative to the project root, `/` as the separator, `*` crossing `/` freely (so `src/*`
already reaches any depth under `src/`); a whole directory can also be named as `dir/**` or, as a
shorthand, `dir/` (read the same way); brackets in a path are taken literally, so
`server/api/[id]/**` names the folder called `[id]`, as framework route folders are — a shell
command should quote such a path, and a shell target whose wildcard expansion reaches outside the
scope is refused.

A relative pattern (`src/**`) is the usual case; an absolute path inside the project root
(`D:/dev/x/project/src/**`) is accepted too and read as if it had been written relative — one
outside the project root is refused, unless it lies in a directory listed in
`permissions.additionalDirectories` (a sibling checkout: `../other/.act/**` or its absolute path).

`worker-write-scope` (`docs/ai/config.md` § Checks) checks it mechanically, the same way the cap is
checked mechanically rather than from memory — for a Bash command this is best-effort (it catches
redirection and the common write commands, not a full shell parse), not a complete guarantee: writes
made from inside a program (`python -c "open(...)"`, a script file) stay invisible to it.

`worker-scope-overlap` (`docs/ai/config.md` § Checks) refuses a start whose scope overlaps that of a
worker still running: `none` overlaps nothing, a missing `Write scope:` line counts as everything,
and the overlap is estimated cautiously from the fixed leading directory of the patterns.

A finished worker or a failed start frees its scope; a crashed worker does so after three hours, or
when its file under `.act-local/worker-scopes/` is deleted.

Limit: a worker continued with a message (`SendMessage`) is invisible to the check once it has
ended, so the orchestrator keeps the scopes apart itself.

Whoever stops a worker and assigns it anew (`R-cost-amend`) first deletes its file there, if it
still stands.

The orchestrator starts it only after that worker has ended — only a rule, since a hook can refuse a
start but not wait.

When several workers are to read the same material, the orchestrator reads it once and writes what
it found to `.act-local/notes/brief-<slug>.md` (source, state, `<path>:<line>` references), then
names that file in each assignment.

The workers read the note instead of the sources and look up only what is missing from it.

The note is the orchestrator's own text, not foreign content (`R-safe-foreign-text`): the one-day
rule applies to the sources it rests on, the note itself only to the workers of this one start.

## `R-cost-wait` — Let a started worker finish

Checks: status-poll.

A worker reports back on its own when it is done; polling its status repeatedly does not speed it up
— it costs tokens on every call and clutters the chat (trigger: over forty consecutive idle status
checks in one real case, none of them changing anything). Mechanically refused from the second
status query in a row (`status-poll`, `docs/ai/config.md` § Checks) — any other tool use in between
resets it.
