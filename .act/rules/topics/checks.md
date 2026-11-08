# Mechanically checked rules — details

Detail page for the rules that name `topics/checks.md`. A rule in `.act/rules/` says what is forbidden or required;
this page adds, per check, what it blocks, how it is switched and the limits an owner must know. How a check reads
a command (parser allow-lists, time budgets, failure handling) is documented at its code in `.act/hooks/checks/`
(header comment of the module); the block messages name the syntax and point here. The checks are switched in
`docs/ai/config.md` § Checks (`block`, `warn` or `off`).

**Incident log.** What a check does without stopping the call is noted in `.act-local/incidents.jsonl` (time, kind,
source, role, a short message; never a command or a path): a `warn` message that was printed, a check that crashed or
ran past 8 s of the hook's 10 s limit, a refusal of the main session (a worker's refusals are routine), a refusal that
made the session or a worker switch model, and `usage.py --outcome <role> <tier> escalated`. The next session start
puts the new lines into the inbox report `Incident log <date>` (`kind: report`, `for: all`; an open report of the same
day is extended), counts per kind on top, and is silent when nothing is new. Delivered lines are kept 30 days. It is
written by `session-start-refresh: block`; there is no switch of its own.

**When a check itself fails.** `secret-read` and `outside-root` fail closed for the shell: if the module cannot be
imported or raises on a call, Bash and PowerShell are refused and the failure is named on standard error, so a broken
check does not let `cat .env` through (`off` does not help when the module cannot be imported; `warn` does not soften
it). Read, Write and Edit stay possible; the owner starts `.act/scripts/doctor.py` with the `!` prefix. If the
dispatcher cannot import its own helpers, every tool is refused (PreToolUse). Every other check fails open, but not
silently: the failure goes to standard error, to the human as `systemMessage` and to the model as `additionalContext`
of the call's PostToolUse (see `dispatch.py`). Assumption, not verified: that Claude Code displays the `systemMessage`
of a PreToolUse or PostToolUse hook (a live probe, 2026-11-07, showed it is never displayed for Stop and SubagentStop).

## `R-safe-no-secret-read` — Never read a secret file into the context

Checks: secret-read.

Blocks a Read, Grep or shell reading command (`cat`, `grep`, `Get-Content`, `< file`, `git show HEAD:<file>` …) that
names a secret file; path list and exceptions (`.env.example`, `*.pub` …) in the header of `secret_read.py`. Switch
`secret-read` (`block`, `warn`, `off`); `ACT_SECRET_READ` in the environment for one run. Limits: a program that
opens the file itself (`python script.py`, `docker run --env-file`) is invisible, and so is an MCP tool that takes a
path, unless it is a read tool of the IDE server's known list (`ide-mcp`; each path argument of those is checked as a
Read). A word that merely looks like a secret name (`grep .env README`) is refused as well.

## `R-safe-no-secret-diff` — Check the diff before every commit

Checks: secret-scan (and danger-scan, same commit trigger).

Before a `git commit` (also inside a chain or a nested shell) `secret-scan` scans what the commit would take — the
staged diff, plus unstaged changes or new files where the call stages them itself (`-a`, `git add -A`). Only added
lines count: key/token formats, private keys, an added `.env` file (`.env.example`, `.env.sample`, `.env.template`
excepted) and assignments to a credential-like name with a long, high-entropy value. A match stops the commit and is
reported without the value. Exempt: a line carrying `act:allow-secret`, a value that reads as a placeholder, and for a
file that cannot carry a comment (JSON) a line listed in `docs/ai/local/secret-accepted.md` as `- <path> <hash>:
<reason>` (the hold message prints the finished entry); also a line of `.act-lock.json` at the project root that holds
only a rule ID and a 64-digit hex digest (an override hash). Switch: `secret-scan` (`block`, `warn`, `off`).

Limit: each added line is checked on its own, so a SQL string continued on the next line is not seen by danger-scan.
`danger-scan` (switch `security-check`; `act:allow-danger` exempts a line) holds the first commit per reader, file and
pattern and lets the second attempt through; its patterns, PHP file types and SQL heuristics are in `danger_scan.py`.

Adopted project: `adopt_baseline.py --book` (skill `act-adopt`, step 7b) books the dangerous patterns of the existing
code as backlog entries and lists their keys `file|rule-id` in `.act-local/danger-scan-hints/baseline.json`; a
danger-scan finding with exactly such a key passes without the first hold. Limit: the key has no line number and no
expiry, so a new hit of a booked rule in a booked file passes too, until the owner removes the key from the list or
deletes the file. Secrets are never covered by it.

## `R-safe-outside-root` — Stay inside the project

Checks: outside-root.

Allowed places: the project root, the folders in `permissions.additionalDirectories`, the system temp directory, Claude
Code's own folder for this project, its plan folder `~/.claude/plans/`, read-only its plugin and skill folders
(`~/.claude/plugins/`, `~/.claude/skills/`), and the entries of `outside-root-allow` (`docs/ai/config.md` § Checks;
`(read)` after a path allows reading only). Any other place — a neighbouring repository, another project, the home
directory — only on the owner's word for this case, as an entry in `outside-root-allow` or `additionalDirectories`,
never as a one-off workaround. Applies to every role and tool. Switch `outside-root` (`block`, `warn`, `off`);
`ACT_OUTSIDE_ROOT` in the environment for one run.

Entry forms. A program folder outside the project and the home directory (browser, compiler, SDK) is entered as an
absolute path in either slash style (`D:/Program Files/Browser`, `/opt/browser`); it is read-only with or without
`(read)` and needs the owner's word for this folder. A write the shared write-target scanners recognise is refused
there; one they do not see (a `cd` into the folder followed by a relative write, a clone, `xargs`, `robocopy`,
`chmod`, code behind `-c`/`-e`) passes. An absolute entry with a glob character keeps the glob behaviour and is
writable unless `(read)` stands behind it. An entry that is a drive root, `/` or a folder above the project or the home
directory opens everything below it: name the program folder itself. A `file:` URL entry is ignored. The program word
of a command is no path (`"D:/Program Files/Browser/browser.exe" --headless` needs no entry); a `cd` into the folder,
a path argument or a wrapper (`xvfb-run`, `bash -c`) does.

Two scripts write outside the project, only when the human explicitly asks: `id_links_install.py` to `~/.act/id-links/`
and `act-export-settings --profile` to the user's config folder (`settings.md`; an existing file is first copied to
`settings.md.bak-<stamp>`). `act-adopt` is the one exception: the owner starts the first scan with the `!` prefix,
which opens the target folder for 24 hours or until `--abort` through a marker under `.act-local/outside-allow/` that
only the adopt scripts write.

Limits: the shell check is best effort. A program that opens files itself (`python script.py`, `docker run -v`) is
invisible; an MCP tool that takes a path is checked only if it is a read tool of the IDE server's known list. A command
line with more than 150 `cd`-like statements is refused: split it. A word of only slashes (`//`), and a lone `/` as a
shell word of its own (`ls /`, `du -sh /`), is the file system root and refused; as text, an option value, a
delimiter or the operator of an arithmetic expression it is not (allow-list in `outside_root.py`; in PowerShell
`Get-ChildItem $dir / 2` passes).

## `R-safe-git-reset` — Check before `git reset --hard`

Checks: git-reset-hard (the same module as git-discard; each row keeps its own mode).

The rule text carries everything the check enforces; there is nothing further to add.

## `R-safe-git-discard` — Don't discard work with other git commands either

Checks: git-discard.

Next to `git reset --hard`, these git commands throw work away with no way back: `git clean -f` when `git clean -n`
with the same switches lists something; `git checkout -- <folder>`, `git checkout .`, `git restore <folder>`,
`git checkout -f`, `git switch -f` while the target has uncommitted changes; `git stash drop` and `git stash clear`; a
forced push or a delete of the default branch on the remote; `git branch -D` and `git branch -M`/`-C` over a branch
HEAD does not contain (a branch only cherry-picked into HEAD counts as not contained). A call whose repository cannot
be determined, too long to check in time or whose check fails is refused (run smaller calls), except a `branch` that
only lists and a `reset` without `--hard`. Switches: `git-reset-hard` and `git-discard`. The full table is `_TABLE`
in `git_discard.py`.

## `R-safe-git-metadata` — No writing of hooks, repository config or Claude settings

Checks: git-metadata-guard, protected-watch.

`git-metadata-guard` (switch `git-metadata-guard`) refuses a write to `.git/hooks/**` or `.git/config` (also
`config.worktree` and the git directories of submodules and linked worktrees), also by copying into them, with a file
tool, a shell command, or `git config`, `git -c` or `GIT_CONFIG_KEY_<n>` for a key that starts a program
(`core.hooksPath`, `core.fsmonitor`, `core.sshCommand`, a `!` alias, a filter, textconv or credential helper, an
`ext::` remote URL …; the full list is in `git_metadata_guard.py`); `git init --template` too. A worker also never
writes `.claude/settings*.json`, `.claude/agents`, `.claude/skills`, `.claude/commands`, `.vscode/tasks.json`,
`.devcontainer/**`, `.devcontainer.json`, `.envrc` or `.mcp.json`; nobody adds a `folderOpen` task to
`.vscode/tasks.json` or a `*.code-workspace` with a file tool, or writes `.vscode/tasks.json` with a shell command; the
human writes such a file themselves.

Limits. The checks read the text of a call and run nothing: what a program or script file writes itself
(`pre-commit install`, `python script.py`) is invisible; a Python program handed to `python` (`-c`, heredoc,
here-string) is read for literal paths and literal command lines, not for computed ones (a variable, an f-string).
Code that becomes a script only when the command runs (`bash <<< '…'`, `source /dev/stdin`, `[scriptblock]::Create`)
is not followed, and a target that depends on an earlier command is judged on what the text says — for every shell
check that reads write targets. The checks are a guard rail against mistakes, not a wall against intent.

### The watcher after every call: `protected-watch`

Because the guard cannot see a script file, `protected-watch` compares the protected files with a snapshot (taken at
session start, kept under `.act-local/protected-watch/`) after every tool call of the orchestrator and of workers:
`.git/hooks/**` and `.git/config` (only the keys that start code) of the repository and its linked git directories,
`.claude/settings*.json`, `.claude/agents/**`, `.claude/skills/**`, `.claude/commands/**`, and `.mcp.json`, `.envrc`,
`.devcontainer.json`, `.devcontainer/**`, `.vscode/tasks.json` at the project root. It never follows a link.

Switch `protected-watch`: `block` (default), `warn` (reports every change, restores nothing), `off` (no snapshot, no
comparison); `ACT_PROTECTED_WATCH` in the environment for one run. On a change:

- **A worker's call, `block`:** the file is put back at once from the snapshot (not from git), a new file is removed,
  the changed version is kept under `.act-local/protected-watch/kept/` for 30 days; the worker, the human and the
  orchestrator are told. One exception: a change of `.claude/settings.local.json` that only adds entries to
  `permissions.allow` is Claude Code writing the owner's "always allow" answer; it is reported, not put back (the
  exact form is in `protected_watch.py`; any other change there is put back). Limit: an entry a worker adds to
  `permissions.allow` itself is only reported too; the file does not tell it from the owner's answer.
- **The orchestrator's call, or `warn`:** reported only, with the commands that put the previous version back; the new
  state becomes the reference.

Limits: it reports after the call and prevents nothing. A change made between two calls by someone else (the human,
Claude Code, another session) is attributed to the next call; a worker's change first seen in the orchestrator's call
is reported as the orchestrator's and not put back. A write that leaves size and modification time unchanged is not
seen; a file over 2 MB cannot be restored; at most 4000 files are listed. `~/.claude`, `*.code-workspace` files and a
`.git` file above the project root are not watched. A git directory first seen in a snapshot taken during a worker's
call and not below the project root in fact is reported, not restored. Nothing runs where hooks do not run. The
remaining limits and the rules for links are in the header of `protected_watch.py`.

## `R-work-throwaway` — Throwaway material under `.act-local/tmp/`

Checks: act-local-tidy.

Throwaway material (probes, scratch projects, clones, output files) goes into `.act-local/tmp/<task-id>-<slug>/`, never
into the system temp directory and never directly under `.act-local/`. The orchestrator removes a task's folders when
it commits the task (`python .act/scripts/act_local_tidy.py --task <id>`); whoever made a folder removes it earlier.
Git run in a subfolder that is not a repository of its own acts on the project's repository: set
`GIT_CEILING_DIRECTORIES` to `.act-local/tmp`, or call git only on a repository of its own. A deny entry on Windows can
lock out the owner too (`(RX)` also denies `READ_CONTROL`): deny only the one right the probe needs, such as `(RD)`,
and run `icacls <path> /reset` in the `finally`. A throwaway project below `.act-local/tmp/` carries a `.act/` of its own;
the template's `.act/` write-guard lets a write into it pass (conditions in `write_guard.py`).

`act-local-tidy` (switch `act-local-tidy`; `warn` only reports what would go, `off` skips) runs once a day at session
start in a detached process; the next start reports the result in one line. It removes `.act-local/tmp/` entries older
than 7 days that belong to no open task (name equals the task's id or starts with it and a non-digit), all but the
newest 5 folders in `.act-local/backup/`, stale folders of the compiled cache in `.act-local/pyc/`, and every other
entry directly under `.act-local/` that no template script creates. `act-local-keep` lists patterns relative to
`.act-local/` (`exports, tmp/long-*`) that are never removed. Report first: removal starts only on a calendar day
after a report-only result was shown, so the first result in a project is a report with the date the next start may
remove. `python .act/scripts/act_local_tidy.py` lists the plan without removing anything. Limits: an entry that a
parallel session uses for more than 7 days without an open task id in its name is removed — name it with the task id
or list it in `act-local-keep`; a task file without an `id:` line protects no folder.

## `R-cost-delegate` — Delegate where it pays off; the assignment header

Checks: worker-cap, worker-write-scope, worker-scope-overlap.

The assignment header's mandatory lines are `Write scope:`, `Cap:` and, where something runs, `Tests:`.
The tier follows from the role; a `Tier: <tier>` line is only needed for a deviation (`usage.py --outcome`
records the role's tier otherwise). The estimate (`~<n> min · ~<n> tkn fresh · ~<n> tkn cache`) is given from
`standard` up: `fresh` = input, cache-writing and output tokens, `cache` = cache-read tokens; base it on
`python .act/scripts/usage.py --estimates` where it has measured runs of that role/tier, not on memory.
`Depends on: <whose result>` is only for an assignment that reads another worker's result.
`builder-high` and `reviewer-high` are the same tier one reasoning step further; the other
template roles have no such variant (`docs/ai/config.md` § Roles for a permanent override). About
10–12 units (a verdict per entry or per file) per judgment worker because with more, the verdicts turn shallow while every further tool
call re-reads a growing context. Only the orchestrator starts workers: a worker's proposal to split its
task comes back, and the orchestrator cuts and starts the new assignments.

`Cap:` is recognized either on its own line or right after a `·`/`|`/`;`/`,` further into a line, so
a compact header works too (`Write scope:` and `Tests:` are read only at the start of a line), e.g.

`Tier: standard · Estimate: ~30 min · ~400k tkn fresh · ~8M tkn cache · Cap: 95.` Leaving the line
out falls back to the default of the tier a `Tier:` line names (`light` 10, `standard` 40, `elevated`
60, `high`/`expert` 80), else of the worker's role: `quick-check` `light`, `reviewer` `elevated`,
`expert-solver` `expert`, every other role (`builder`, `explorer`, `doc-writer` …) `standard`; a `-high`
variant counts as its base role. With neither, `standard`.

The worker gets one note on reaching the cap ("cap reached — deliver your current state now") and is
refused from 1.5× the cap onward — wrap up and report rather than push past it.

`Write scope: none` allows no writes at all: not in the project, and not in the system temp directory or
the worker's scratchpad either (only `/dev/null`, `NUL` and the standard streams stay free). A worker with
any `Write scope:` line writes only what that scope allows; the system temp directory and the scratchpad
are no exception. Throwaway material goes under `.act-local/tmp/<task-id>-<slug>/` (`R-work-throwaway`),
and an assignment that needs it names the folder in its scope (`.act-local/tmp/<task-id>-<slug>/**`); the
refusal of a write into the system temp directory or the scratchpad, every refusal under `none`, and the
refusal of a target that starts with a temp variable (`$TEMP`, `${TMPDIR}`, `$env:TEMP` ...) say so. Limit:
`mktemp` (also `-d`, `-p`), PowerShell `New-TemporaryFile` and `tempfile` in inline code create a file in
the system temp directory without a path in the command, so the check does not see it; a later write
through the variable that holds the name is refused. Leaving the `Write scope:` line out means no restriction beyond the
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
made from inside a script file stay invisible to it. There is no cap on the number of write targets in one
command: a target inside the scope costs about 1.4 ms, so the hook's 10 s time limit is reached at roughly
7000 literal targets in one command (about 200 KB of command text), above which the remaining PreToolUse
checks of that call do not run - no realistic command comes close, and a target outside the scope stops the
check at the first hit.

The command text of an `ssh [options] <host> <command>` call counts as remote - only the `$(...)` the
local shell expands (easy to cut out: no `#`, `<<`, line break or `case` inside, no stray `)` around) are
read - exactly when the call has a plain, known form: `ssh` or the ssh of a system directory, in front of
it only a reserved word or the bare name of `sudo`, `env`, `command`, `exec`, `nohup`, `nice`, `timeout`
(with a plain duration), `stdbuf` or `setsid`, no `$`, backtick, `{`, `*`, `?`, `[` or `~` in any word up
to the host, options only from `-4 -6 -a -C -n -q -T -t -v -x` (also combined) and `-p <digits>`,
`-l <name>`, `-i <file>`, a `[user@]host` that is not this machine (`localhost` and its variants, any
`127/8` or `0/8` address in any spelling, the IPv6 loopback, `ip6-*`, this computer's own name), and a
first command word that begins with a plain character other than `-`. Every other form - every `-o`,
`-F`, `-E`, `-J`, `-W`, `-L`, `-R`, `-D`, a wrapper's option, `parallel` or `xargs` in front, an
expansion up to the host or at the start of the command, a `PATH=`, `BASH_ENV`, an alias, a function
`ssh`, `source` or `.`, `enable`, `command_not_found_handle` or the word `hash` in the same command - is
read as a local command, as before. An alias in an ssh configuration that points here cannot be seen;
local redirections behind the call are always checked. The file an `ssh -E <file>` call writes its log to
is a write target. The command text of a call whose destination is this machine, or one the shell still
expands (`ssh localhost 'echo x > f'`), runs here and is read as a local command line; the text for another
machine stays unread. An `rsync` destination on another machine (`host:path`, `host::module`,
`rsync://host/...`) is no local file, as long as every option acts on the remote side alone: plain flags and
flag clusters (`-avz`, `--archive`, `--delete`), pattern options (`--exclude`, `--include`, `--filter`, `-f`),
the value options `--bwlimit`, `--timeout`, `--port`, `--chmod`, `--max-size`, `--min-size`,
`--compress-level`, `--info` and `--debug`, and a remote shell that is only `ssh` (`-e ssh`, `-e 'ssh -p
2222'`, `--rsh=ssh`) - and only when the whole command line is nothing but that one rsync call with plain
words: the first word is `rsync` itself, no other command and no operator (`;`, `&&`, pipe, redirection, `&`,
group, line break) anywhere, no `$` or backtick outside single quotes (in double quotes the shell still
expands them), and no unquoted glob, brace or `~` in any word. rsync reads its own environment variables (`RSYNC_RSH`, `RSYNC_CONNECT_PROG`) and runs a local
program from them, and a line can set one in more spellings than a text search finds - the shell removes
quotes and escapes before `export`, `env` or `declare` see the name (`export RSYNC"_"RSH=...`) - so a line
with a prefix assignment, `export`, `env`, a nested `sh -c` or a PowerShell part (`$env:RSYNC_RSH = ...; bash
-c 'rsync ...'`) keeps the destination a local path; so does a line that holds the text `rsync_` (a plain
name such as `docs/rsync_notes/` counts too). `rsync -a docs/ h2:x && echo done` is such a line as well. Any other
option - another `-e`/`--rsh` program, `--rsync-path`, `--log-file`, `--write-batch`, `--only-write-batch`,
`--backup-dir`, `--partial-dir`, `--temp-dir`, `--link-dest`, an option not on that list - makes the
destination count as a local path again. A drive letter, a path with a `/` before the colon, a variable, a
glob, a tilde and this machine (`localhost:path`) are read as local paths in any case. In PowerShell native
programs such as `ssh` and `rsync` are not read for write targets at all.

In PowerShell, `$name = <program> args` with `py`, `python`, `python3` or `git` and plain arguments (no
sub-expression, script block, escape, `;` or comma-separated array) is read as the program call alone by the
statement handlers: its redirections, and the `git mv`/`git rm` targets. For `write-guard` and
`git-metadata-guard`, every word right of the `=` stays a possible target as before, except two kinds of
word: the script of `py|python|python3 [-3|-u|-B ...] <script>` (never with `-m`, `-c` or an option that takes
a value), and the path and revision words of `git log|diff|show|status|blame|ls-files|rev-parse|grep` without
`-o` or `--output*`. So `$out = py .act/scripts/board.py` and `$log = git log -- .act/scripts` pass, while
`$x = python -m zipfile -e a.zip .act/`, `$x = git clone <url> .act/y`, `$x = git archive -o .act/x.zip HEAD`
and `$x = py x.py, '.act/x'` are judged as before. Any other right side (a cmdlet such as `Join-Path`, a
string, an expression, the call operator) is read as before.

Inline interpreter code is read too, for a worker with a restricted scope (`none` or patterns; a worker
without a `Write scope:` line and the orchestrator are not affected). A Bash or PowerShell call that runs
`python`, `python3`, `python3.N`, `pythonw`, `py` (also `py -3`) or `node` (an `.exe` suffix and a
directory in front are fine, and so are the usual prefixes such as `env`) with code of its own is refused
when the code holds **a write call and a path written out as a literal that lies outside the scope** (the
system temp directory and the worker's scratchpad are not exempt, as for any write). The code comes from `-c`
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
Write/Edit; when the literal was found in the body of a heredoc (or a PowerShell here-string) it adds the way out for a
program fed that way, for the case that the code only reads that path: write the helper script as a file inside the
write scope and run it (`python <file>`), or use Write/Edit instead of a heredoc; a file outside the scope is never
written, not through a script either (`R-role-worker`) (left out for a read-only assignment, which has no place in the scope to write a
script). Only the wording differs; which calls are refused does not change. Code that only reads - no write call -
may name any path, so read outside the scope in a call of its own.

A literal that is only a switch of a Windows tool (`icacls`, `cacls`, `robocopy`, `xcopy`, `takeown`,
`attrib`, `cmd`; `/deny`, `/grant:r`, `/MIR`, `/R:3`, `/c`) is no path in one place only: among the
arguments of the call that starts the tool, when the tool's name is the literal in the tool's position of
that call - the first element of the list `subprocess.run`, `call`, `check_call`, `check_output` or
`Popen` gets, the first argument of Node `spawn`, `spawnSync`, `execFile` or `execFileSync` with the list
as the second, the program of `os.exec*`/`os.spawn*` - and the tool knows the switch; for `cmd` only the
switches up to `/c` or `/k`, as what follows is another program's command line. A command line that is the
first argument of such a call, of `os.system` or of Node `exec`/`execSync` (`'icacls d /deny x'`) is cut
into words when it is one command (no `;`, `&`, `|`, `<`, `>`, `(`, `)`, `^`, `%`, `$`, backtick or line
break in it); the tool and its switches drop out, every other word is judged. Anywhere else - another
call, the same statement, a list built from parts, `args=` - a `/c` or `/deny` stays a path, and so does
a switch that names a file (`/LOG:out.txt`). Limits: a file in the root of a drive named like a switch is
not judged in that list; `from subprocess import run` used bare is not seen as a start.

Python inline code in which that reading finds a write call gets one more step: the target of a write call that
is built from string literals is resolved and judged like a literal. A tightening only: the literals stay judged
as before, and the step runs only where the literal reading already sees a write call (`m = 'w'` and
`open('src/x.py', m)` alone are not read, as before). For the targets it resolves, the write calls are `open` (also
`io.open`, `codecs.open` and `.open(<mode>)` on a path) with a writing mode - a mode held in a name bound once is
read through it, one that is not seen counts as writing -, `os.open` with flags naming `O_WRONLY`, `O_RDWR`,
`O_CREAT`, `O_APPEND` or `O_TRUNC` (or flags that are not seen), `os.remove`, `unlink`, `rmdir`, `removedirs`,
`mkdir`, `makedirs`, `truncate`, `chmod`, `chown`, `utime`, `rename`, `replace`, `symlink`, `link`, `shutil.copy`,
`copy2`, `copyfile`, `copytree`, `move`, `rmtree`, and the `Path` methods `write_text`, `write_bytes`, `touch`,
`mkdir`, `unlink`, `rmdir`, `chmod`, `lchmod`, `rename`, `link_to`, `symlink_to`, `hardlink_to` (for the last two
the receiver is resolved, not the link target; a link target or a read-only `os.open` target written as a literal
is still reported by the literal reading, as before). The target is built with `os.path.join`, `Path(...)` and `/`,
`+`, an f-string, a name bound exactly once (also as the variable of a `for` loop over a list of literals), and
`glob.glob`, `glob.iglob`, `Path(...).glob` and `.rglob`, whose pattern is judged as the target (a loop over
`glob.glob('i18n/*.json')` writes to `i18n/*.json`, which must lie inside the scope). A value the resolver does
not reach - a name bound twice or by a tuple, a parameter, a call, an alias, `getattr` - stays unjudged, as before:
the check does not fail closed on it, and it makes no attempt to follow a program that hides its targets.
Unjudged too is what lies beyond the resolver's limits, which bound its work by the length of the program: a
program longer than 32,768 characters is not resolved at all; an expression standing for more than 256 strings,
a string longer than 1,024 characters, a list of more than 256 items and a nesting deeper than 64 are not
resolved; every string built, and every resolved mode judged once, costs from a work budget of two units per
character of the program (a mode that no longer fits counts as writing); and the targets
reported are at most one per string literal of the program, at most 256, and together at most 8,192 characters
and two per character of the program - past any of these, nothing more is resolved.

Limits of that reading (what stays unseen; it catches the common form, not every form):
- the program is not in the command: a script file run by path (`python /tmp/x.py`), code held in a
  shell variable or read from a file (`cat x.py | python`);
- the path is not a literal that tells it: built at run time and not resolved (`os.environ[...]`, a name
  bound twice, a function parameter, a call such as `p.name`; see the paragraph above); a name without extension and without
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
before. An error of the reader's own program (a bug of the check, not a text it fails to understand) is
different: `worker-write-scope` and `git-metadata-guard` then name the error and, in block mode, refuse the
call (in warn mode they only warn), since inline code that was never judged must not pass as code without a
write call; `.act/scripts/doctor.py` or the owner decides how to go on. Text the reader cannot parse, or a program too large or too deep for it,
stays on the lenient path above.

`worker-scope-overlap` (`docs/ai/config.md` § Checks) refuses a start whose scope overlaps that of a
worker still running: `none` overlaps nothing, a missing `Write scope:` line counts as everything,
and two patterns overlap when some path can match both, compared as the matching reads them (`*`
crosses `/`, `?` is one character, `[` is literal, `dir/**` also names `dir`): `src/lib/alpha/**` and
`src/lib/beta*` do not overlap, `src/lib/**` and `src/lib/beta*` do.

A finished worker, a worker the orchestrator stops with `TaskStop`, and a failed start free their scope at
once; a worker that crashed without any stop does so after three hours. The refusal names `TaskStop` as the
way out. The entry under `.act-local/worker-scopes/` stays after a stop, marked as ended, so that a worker
continued with a message (`SendMessage`) is bound to its own scope again: its restart clears the mark, and
it counts as running once more. A call that cannot be bound to an entry (no `meta.json` of the agent, no
entry under its `toolUseId`) is refused as before while a restricted scope is registered for a running
worker.

Limit: the restart of a continued worker is not checked against the scopes of the workers started
meanwhile, so the orchestrator keeps those apart itself.

**A test run beside a writer: the `Tests:` line.** A test or probe run reads the tree it tests, and a half-written
file there fails the run without saying anything about the code. So no run — the full suite, a worker's own probes,
a review that executes something — goes on while a worker writes in that tree, and no worker starts writing there
while a run goes on. An assignment that runs tests names the tree as its own line `Tests: <glob>[, <glob> ...]`:
the same patterns and normalization as `Write scope:` (project-root-relative, `/` as separator, a trailing `/` read
as `/**`, a sibling checkout as `../name/**` when `additionalDirectories` lists it), on a line of its own with the
same optional bullet, bold key and backticks. Each comma-separated word counts on its own: a word counts only if it
has no white space and holds a `/` or a glob character (`*`, `?`, `[`), or names an existing path below the project
root, so prose after the key (`Tests: run the suite`) is ignored; a word outside the project and the listed
directories is dropped, the valid ones stay; `Tests: none`, or a line with no valid word left, is no `Tests:` line. `worker-scope-overlap` compares a starting worker's `Tests:` patterns with the
`Write scope:` of every running worker, and its `Write scope:` with the `Tests:` of every running worker, with the
overlap test above (`dir/**` also names `dir`, `*` crosses `/`). A running worker without a `Write scope:` line
counts as writing everywhere, so a starting `Tests:` line meets it, and a start without the line meets every
running `Tests:` line; `Write scope: none` writes nothing and never meets a `Tests:` line. Two `Tests:` lines never
meet (two readers), and a worker's own `Tests:` against its own `Write scope:` is no conflict. The `Tests:`
patterns are stored with the worker's entry under `.act-local/worker-scopes/` and freed with it (a stop, a failed
start, the three hours). The refusal names the other worker's line; the way out is to wait until that worker has
ended (or stop it with `TaskStop`), or to test an isolated copy — a clone or a worktree — and name the copy in
`Tests:`.

**The orchestrator only gets a note, never a refusal** (same switch, `worker-scope-overlap`; `off` silences it, a `block`
row counts as `warn` for it, so every note enters the incident log). The note names the worker's line and the way out
(wait until that worker has ended or stop it with `TaskStop`, or work in an isolated copy). It comes when a `Write`,
`Edit`, `MultiEdit` or `NotebookEdit` path of the main session, or a write target of its Bash or PowerShell command
(the scanners `worker-write-scope` uses, inline code included), falls under the `Tests:` of a running worker; and when a
command runs the test command (third entry of `commands` in `docs/ai/config.md`; `(not set)` means none: a simple
command starting with its words, the program by name, quoted text not counted) in a tree a running worker writes in. That
tree is the directory the run starts in (the call's cwd, moved by a literal `cd`) and every word that names an existing
file or folder, such as `--template <dir>`; a worker that writes below `.act-local/tmp/` is an isolated copy and meets
only a tree below `.act-local/tmp/`, a worker without a `Write scope:` line meets every tree. PreToolUse text does not
reach the model, so the note is repeated with the PostToolUse of the same call. Limits: a target still expanded by the
shell (`$VAR`, `~`, a nested `{`) or relative with no known directory cannot be placed, inline code the reader fails
on and an unreadable registry are not looked at, and a target is compared with the `Tests:` pattern only from below: a
write that moves, copies or restores a parent folder of the tested tree (`mv tests tests-old`, `git restore .`) and a
glob class such as `tests/t24[8]/a.py` pass without a note.

What the check cannot see stays with the orchestrator: a run does not start before the reviews are accepted (the
full suite runs once on that state, during rework only the rework's own tests), and a run still going when rework
starts, or when another worker begins writing in the tested tree, is stopped and started again on the new state.
Parallel builders that must test while others build each work in an isolated copy of their own.

Whoever stops a worker and assigns it anew (`R-cost-amend`) needs nothing more than the stop (`TaskStop`).

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
