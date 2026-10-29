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

## `R-safe-no-secret-diff` — Check the diff before every commit

Checks: secret-scan.

Before a `git commit` (also inside a chain or a nested shell), `secret-scan` scans what the commit
would take — the staged diff, plus unstaged changes or new files where the call stages them itself
(`-a`, `git add -A`). Only added lines count. It looks for key/token formats, private keys, an added
`.env` file (`.env.example`, `.env.sample`, `.env.template` excepted) and assignments to a
credential-like name with a long, high-entropy value. A match stops the commit and is reported
without the value, never silently stripped. A line carrying `act:allow-secret`, or a value that reads
as a placeholder, is not reported; for a file that cannot carry a comment (JSON), list the line in
`docs/ai/local/secret-accepted.md` as `- <path> <hash>: <reason>` (the hold message prints the
finished entry). The one exemption by shape: a line of `.act-lock.json` at the project root that holds
only a rule ID and a 64-digit lowercase hex digest (an override hash). Switch: `secret-scan` in
`docs/ai/config.md` § Checks (`block`, `warn` or `off`).

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
--no-merged` lists, and `git branch -M`/`-C` over one. `git branch -D` is let through for a branch
taken over by cherry-pick: `git cherry HEAD <branch>` shows only `-` lines, the branch has no merge
and no empty commit of its own, and merging it into HEAD would change nothing (`git merge-tree
--write-tree`, git 2.38 or later). A branch HEAD has edited further after the pick stays refused. A
call too long to check in time, or a check that fails, is refused — run smaller calls.

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

## `R-work-throwaway` — Throwaway material under `.act-local/tmp/`

Checks: act-local-tidy.

Throwaway material (probes, scratch projects, clones, output files, scratch files) goes into
`.act-local/tmp/<task-id>-<slug>/`, never into the system temp directory and never directly under
`.act-local/`. The orchestrator removes a task's folders when it commits the task
(`python .act/scripts/act_local_tidy.py --task <id>`); whoever made a folder removes it earlier, once
it has served. The template's own scripts keep to the same place: their short-lived folders are
`.act-local/tmp/act-<purpose>-*`, removed when the script ends (outside a project they use the system
temp directory), and the hooks' compiled-module cache is `.act-local/pyc/`. Such a folder lies inside the project's work tree: git run in a subfolder that is not a
repository of its own finds the project's repository and acts on it, so set `GIT_CEILING_DIRECTORIES`
to the folder above it, `.act-local/tmp` (git never climbs into a ceiling folder, so a throwaway
repository still finds itself), or call git only on a repository of its own. A deny entry on Windows can
lock out the owner too (`(RX)` also denies `READ_CONTROL` and `SYNCHRONIZE`): deny only the one right
the probe needs, such as `(RD)`, and run `icacls <path> /reset` in the `finally`.

Checked mechanically by `act-local-tidy` (`docs/ai/config.md` § Checks), once a day at session start in a
detached process; the next start reports the result in one line. It removes: `.act-local/tmp/` entries
older than 7 days that belong to no open task; all but the newest 5 folders in `.act-local/backup/`; every
other entry directly under `.act-local/` that no template script creates. Age is the newest change of
anything inside an entry, so an entry still written to stays. An entry belongs to an open task when its
name equals the task's id or starts with it followed by a non-digit (`<id>-x` belongs to the task,
`<id>0-x` does not). Links are removed as links, never followed; if `.act-local` itself is a link, nothing is touched.
`act-local-keep` lists patterns relative to `.act-local/` (`exports, tmp/long-*`) that are never removed;
a pattern naming a folder keeps its contents (`tmp` keeps `tmp/x`), and one naming something inside an
entry keeps that whole entry (`mydata/important` keeps `mydata`). `act-local-tidy: warn` only reports
what would go, `off` skips the check. Report first: removal starts only on a calendar day after the day a
report-only result was shown (by the session start, or by `--apply` on a hand run), so the first result in
a project is a report with the date the next start may remove; until a report was shown a run only reports.
`python .act/scripts/act_local_tidy.py` lists the plan without removing anything. Limits: an entry that a
parallel session uses for more than 7 days without an open task id in its name is removed - name it with the
task id or list it in `act-local-keep`; a task file without an `id:` line (team mode before `assign`)
protects no folder.

## `R-cost-delegate` — Name the tier, the estimate, and the cap

Checks: worker-cap, worker-write-scope, worker-scope-overlap.

In the estimate, `fresh` = input, cache-writing and output tokens, `cache` = cache-read tokens; base
it on `python .act/scripts/usage.py --estimates` where it has measured runs of that role/tier, not on
memory. `builder-high` and `reviewer-high` are the same tier one reasoning step further; the other
template roles have no such variant (`docs/ai/config.md` § Roles for a permanent override). About
10–12 units (a verdict per entry or per file) per judgment worker because with more, the verdicts turn shallow while every further tool
call re-reads a growing context. Only the orchestrator starts workers: a worker's proposal to split its
task comes back, and the orchestrator cuts and starts the new assignments.

`Cap:` is recognized either on its own line or right after a `·`/`|`/`;`/`,` further into a line, so
a compact header works too, e.g.

`Tier: standard · Estimate: ~30 min · ~400k tkn fresh · ~8M tkn cache · Cap: 95.` Leaving the line
out falls back to the tier's own default: `light` 10, `standard` 40, `elevated` 60, `high`/`expert`
80; with neither a `Cap:` nor a `Tier:` line, `standard`.

The worker gets one note on reaching the cap ("cap reached — deliver your current state now") and is
refused from 1.5× the cap onward — wrap up and report rather than push past it.

`Write scope: none` allows no writes in the project, only into the system temp directory as a path
written out (`/tmp/...` in Bash, or its absolute path) — every worker may write there, unless the
project itself lies inside it. That opening does not make the system temp directory a place for
throwaway material: that goes under `.act-local/tmp/<task-id>-<slug>/` (`R-work-throwaway`), and an
assignment that needs it names the folder in its scope. Leaving the `Write scope:` line out means no restriction beyond the
template's own `.act/` write-guard. Patterns are relative to the project root, `/` as the separator,
`*` crossing `/` freely (so `src/*` already reaches any depth under `src/`); a whole directory can also be named as `dir/**` or, as a
shorthand, `dir/` (read the same way); brackets in a path are taken literally, so
`server/api/[id]/**` names the folder called `[id]`, as framework route folders are — a shell
command should quote such a path, and a shell target whose wildcard expansion reaches outside the
scope is refused.

A relative pattern (`src/**`) is the usual case; an absolute path inside the project root
(`D:/dev/x/project/src/**`) is accepted too and read as if it had been written relative — one
outside the project root is refused, unless it lies in a directory listed in
`permissions.additionalDirectories` (a sibling checkout: `../other/.act/**` or its absolute path).

`worker-write-scope` (`docs/ai/config.md` § Checks) checks it; for a Bash command this is
best-effort (it catches redirection and the common write commands, not a full shell parse): writes
made from inside a script file stay invisible to it.

Inline interpreter code is read too, for a worker with a restricted scope (`none` or patterns; a worker
without a `Write scope:` line and the orchestrator are not affected). A Bash or PowerShell call that runs
`python`, `python3`, `python3.N`, `pythonw`, `py` (also `py -3`) or `node` (an `.exe` suffix and a
directory in front are fine, and so are the usual prefixes such as `env`) with code of its own is refused
when the code holds **a write call and a path written out as a literal that lies outside the scope** (the
system temp directory and the worker's scratchpad stay open, as for any write). The code comes from `-c`
(also a cluster such as `-Ic`, with options like `-X utf8` before it) or `node -e`/`--eval`/`-p`/`--print`
(also after `-i`/`--interactive`, which still runs the code); or from standard input - `-` or no script argument, with a heredoc (`python - <<'EOF'`), a here-string, or
a literal piped in (`cat <<'EOF' | python -`, `{ cat <<'EOF'; } | python -`, `cat <<'EOF' | (python -)`,
`echo '...' | python3`, `printf '%s' '...' | node`, in PowerShell a string or here-string piped into
`python -`); `<<-` counts with or without a blank before the delimiter, and a `$'...'` elsewhere in the
command does not hide the heredoc. Write calls: Python `open(...)` with a literal
write mode (`w`, `a`, `x` or `+`), `.write_text`, `.write_bytes`, `.touch`, `.mkdir`, `.unlink`, `.rmdir`,
`.rename`, `.symlink_to`, `.hardlink_to`, `shutil.copy*`/`move`/`rmtree`, and `os.remove`, `rename`,
`replace`, `makedirs`, `mkdir`, `rmdir`, `symlink`, `link`, `truncate`, `open`; Node `writeFile`,
`appendFile`, `createWriteStream`, `copyFile`, `cp`, `rename`, `unlink`, `rm`, `rmdir`, `mkdir`,
`symlink`, `truncate` (and their `Sync` forms). A string counts as a path when it contains `/` or `\`, or
is a bare file name with an extension (`out.txt`; not a number like `1.0`), is not a URL and holds none of
`*?[]^|()<>`; its escapes are decoded the way the language does before that test (`'caf\u00e9'` is text,
`'a\x2fb'` is a path; a raw Python literal stays as written); an f-string or template literal is judged
by the part before its first interpolation, up to the last separator. Every such literal is judged like a
shell target, against the directory the call runs in (a `cd` before it counts), but as written: no
`/tmp` mapping, no brace or tilde expansion, and no Git-Bash drive form - on Windows a literal such as
`/d/work/x` is the folder `d` on the drive of the directory the call runs in, as the interpreter sees it,
not drive D. A literal holding `$` or a backtick counts as unknown and is refused. The refusal says to write the file with
Write/Edit; code that only reads - no write call - may name any path, so read outside the scope in a call
of its own.

Limits of that reading (what stays unseen; it catches the common form, not every form):
- the program is not in the command: a script file run by path (`python /tmp/x.py`), code held in a
  shell variable or read from a file (`cat x.py | python`);
- the path is not a literal that tells it: built at run time (`Path(a) / b`, `os.path.join('out', name)`
  whose parts hold no separator, `os.environ[...]`, a variable); a name without extension and without
  separator (`open('out', 'w')`), which includes dotfiles such as `.envrc` (a leading dot is no extension:
  `open('.envrc', 'w')` is not judged); a glob- or regex-looking literal (`*?[]^|()<>`);
- the write is not in the list: writes through `subprocess`, `os.system` or `child_process`; a bare
  `.write(` such as `sys.stdout.write`, `str.replace` and `Path.replace`, `print(..., file=...)`,
  `fs.openSync`; a name imported under another one;
- the code is another interpreter's: perl, ruby, php, deno, bun;
- the shell scan does not reach the code: a heredoc after a line that does not tokenize on its own (a
  string spanning lines, an unterminated quote) or after a `$'...'` the scan misreads (`$'it\'s'`); a
  pipe into a group counts only for the group's first command (`cat <<'EOF' | (true; python -)`); a
  heredoc given to a group or subshell (`( python - ) <<'EOF'`);
- the code text is misread: a JavaScript regular expression after `)`, `]` or `}` (taken for a division,
  so a `//` in it starts a comment that hides the rest of its line), a string nested in an f-string
  field that reuses the quote of the f-string;
- PowerShell: the directory is followed through `Set-Location`, `cd` and `Push-Location` only (not
  `Pop-Location`, not a script block), as for every PowerShell write target.

When the reading meets text it cannot read, the call is not refused for it and
`[act] inline interpreter code not read (...)` goes to standard error; the rest of the check runs as
before.

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

The brief note `.act-local/notes/brief-<slug>.md` holds what the orchestrator found once (source,
state, `<path>:<line>` references); the workers read it instead of the sources and look up only what is
missing from it. The note is the orchestrator's own text, not foreign content (`R-safe-foreign-text`):
the one-day rule applies to the sources it rests on, the note itself only to the workers of this one
start.

## `R-cost-wait` — Let a started worker finish

Checks: status-poll.

A worker reports back on its own when it is done; polling its status repeatedly does not speed it up
— it costs tokens on every call and clutters the chat (trigger: over forty consecutive idle status
checks in one real case, none of them changing anything). Mechanically refused from the second
status query in a row (`status-poll`, `docs/ai/config.md` § Checks) — any other tool use in between
resets it.
