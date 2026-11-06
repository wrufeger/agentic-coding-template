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
`docs/ai/config.md` § Checks (`block`, `warn` or `off`). Limits: each added line is checked on its own,
so a SQL string built with `+`, `.` or `%` that continues on the next line is not seen by danger-scan;
secret-scan joins only an environment lookup and its literal fallback split at an operator. A `%` that
opens a short literal of its own (`strftime('%Y', d)`) is a date format, not the operator. The PHP
patterns (`sql-php-concat`, `sql-php-interpolation`) run only on `.php`, `.phtml`, `.inc` and `.module`
files. `sql-format` and `sql-php-concat` skip a line that is a single raise/print/log call (Python) or
echo/error_log/throw/logger call (PHP) holding only string literals and simple operands, as long as no
literal opens with a SQL keyword; anything else on the line is checked as before. `sql-php-interpolation`
also covers `${name}`, and the PHP patterns cover `.php3/.php4/.php5/.php7/.php8/.pht`. Names that git quotes
in the diff header are read unquoted. A rename or copy to a `.env` name counts as a new `.env` file. A `$'`
in the commit command that is only text no longer forces the over-inclusive fallback; a live ANSI-C quote
does.

Adopted project: `adopt_baseline.py --book` (skill `act-adopt`, step 7b) books the dangerous patterns found in the
existing code as backlog entries and lists their keys `file|rule-id` in `.act-local/danger-scan-hints/baseline.json`.
A danger-scan finding with exactly such a key passes without the first hold. The list is an allow-list of exact keys
(no prefix, glob, other case, `./` prefix or path normalisation) for the whole project; the check reads it and never
writes it or copies it into the per-reader hints. A missing, malformed, oversized or linked (symlink or junction, also
one of its folders) list, or one holding anything but strings, counts as empty. Booked rules are taken out of a file's
pattern list before a line is matched, so they never count toward the limit of five findings and cannot hide an
unbooked rule on the same line. Only an open entry directly in `docs/ai/work/backlog/` that carries the line
`baseline: <key>` counts as booked. Limit: the key has no line number and no expiry, so after the first commit a new
hit of a booked rule in a booked file passes too, until the owner removes the key from the list or deletes the file
(the booked entry says so). A new rule in a booked file, the booked rule in another file and every other new pattern
hold as before. Secrets are not covered: secret-scan keeps holding until the value is removed, the line carries
`act:allow-secret` or is listed in `docs/ai/local/secret-accepted.md`.

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
script.py`, `docker run -v`) is invisible to it, and MCP tools that take a path are not checked. A word
of only slashes (`//`) is never a path where it is text (inline code behind `-c`/`-e`, a text option, a
heredoc); on its own (`ls //`, `cp x //`) it is the file system root and stays refused. A single `/` is
read the same way when it is a shell word of its own (`ls /`, `find / -name x`, `du -sh /`), in Bash and in
PowerShell; it is not a place where it is text (inline code behind `-c`/`-e`, a text option), the value of
an option (`--grep=/`), the delimiter of `cut -d`, `paste -d`, `sort -t`, `join -t`, `awk -F` or `column -s`
(`cut -d / -f1 file`), or the operator between two operands (`expr 6 / 2`, `$((6 / 2))`, PowerShell
`$size / 1MB`). Limit: the operator is told by its neighbours alone - a lone `/` with any argument before it
and a number, variable or parenthesis after it counts as one wherever it stands, so `ls -la / 2`, `ls -d / 1`
and `du -sh / $X` pass.

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
--write-tree`, git 2.38 or later). A branch HEAD has edited further after the pick stays refused.
`@{-N}` is resolved to its branch before the unmerged check; a name with two case-different refs is not
released as taken over. A call too long to check in time, or a check that fails, is refused — run
smaller calls.

## `R-safe-git-metadata` — No writing of hooks, repository config or Claude settings

Checks: git-metadata-guard, protected-watch.

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
itself (`pre-commit install`, `python -c "open(...)"`) is invisible to the check. Inline Python
narrows that limit: a Python program a Bash command hands to `python` behind `-c`, as a heredoc, a
here-string or a literal piped in is also read as Python, so that very `python -c "open(...)"` is
judged, while a script file (`python script.py`) stays invisible. A call that runs a command or writes
a file (`os.system`, `subprocess`, `os.exec*`, `open(..., 'w')`, `shutil.copy`, `Path(...).write_text` …)
is judged by its literal value — the command line like a shell command, the path (a string, or
`Path(...)` of strings) like a write target —, and `exec`/`eval` of a literal is read again, one level
deep (a literal `exec` inside that one is not followed). An `open` of a literal path counts as a write
also when its mode is no literal. A value that is no literal is not seen: a variable, a name bound
earlier, `os.path.join`, `Path(...) / x`, an f-string, a glob result, a loop over a list. That is the
same limit as for a script file: the reading catches a literal path typed by mistake, it does not work
out what a program computes. On top of that, a program is taken out of the shell reading of the command
only when it is harmless — every call a plain builtin that computes or prints (`print`, `len`, `sorted`,
`str` …), a method on a literal, `sys.exit`; no `key=`, no decorator, no class, no dunder name but
`__name__` and `__file__`, no attribute read beyond those calls and `sys.argv`/`sys.stdout`/`sys.stderr`,
no store on an attribute or an item, no rebinding of such a name — and only at the place
it stands: the one word behind `-c` or the body of a quoted heredoc, on the top level of the command.
So a string such as `"cp x .git/hooks/y"` in a list the program only prints is free, while the same
text behind `git -c` or `bash -c` next to it still counts. Everything else is read as before, its text
as shell commands: a program that calls anything off that list (`open`, `subprocess`, a function of
its own), a program that does not parse as Python, a here-string, a pipe, an unquoted heredoc, a
program inside `sh -c`, `eval` or a wsl line, and PowerShell. Not read: a callee reached through
`getattr` or a subscript, a function bound to a variable, `str.replace` and `Path.replace`, a name
without an import the reading knows, writing calls outside the families it knows (`io.FileIO`,
`urllib.request.urlretrieve`, `extractall` of a zip or tar archive), other interpreters.

A single-quoted or ANSI-C quoted `$(...)` among the words of `echo` or `printf` is printed text, not a command
substitution, and is not read as one - but only on a command line that prints and does nothing else.
Allow-list over the whole line: every command of the line is a bare `echo` or `printf` (the word itself, not
`./echo`, no prefix, no keyword before it; `printf` without `-v`), the commands are joined by nothing but `;`,
`&&`, `||` or a line break, and every word is plain - a `$` or backtick only inside single quotes or as the
`$'` of ANSI-C quoting. Anything else on the line - a pipe, a redirection (also `>&2`), `&`, a group,
subshell or process substitution, a compound command (`for`, `if`, `{ ...; }`), `exec`, `trap`, an alias,
function or variable definition, `eval`, a nested shell, `$_`, `printf -v`, any other command, in PowerShell
also `Set-Alias`, `New-Alias` and `iex` - makes the whole line one that is judged as before (`echo '$(cmd)' |
sh`, `echo '$(cmd)'; sh -c "$_"`, `for i in 1; do echo '$(cmd)'; done | sh`, `echo '$(cmd)' > x.sh`,
`echo '$(cmd)' && git status`). A double-quoted or unquoted `$(...)` is always judged.

Text that a pipeline hands to a shell as its script is read as a command line of its own, like the text behind
`eval`: `echo 'cmd' | bash`, `printf '%s\n' 'cmd' | sh -s`, a bare `cat` in between (`echo 'cmd' | cat | bash`),
and in PowerShell a string or here-string, `Write-Output`/`Write-Host` with literal arguments, piped into
`powershell`/`pwsh` that reads standard input (`-`, `-Command -`, `-File -`, only options) or into
`Invoke-Expression`/`iex` without an argument. A `$'...'` word behind `eval`, `bash -c`, `sh -c` or
`powershell -c` has its escapes resolved first (the plain lexer does not know ANSI-C quoting and read
`eval $'git config x'` as the command `$git`). Where a command line cannot be tokenized (a live ANSI-C quote the
lexer misreads) and the raw-text fallback decides, the word after a redirection operator is reported whole -
quotes taken off, a quoted or escaped blank kept, at most 1,024 characters - as well as its beginning up to the
first blank (`> "src/a b/../../x"` is `src/a b/../../x` and `src/a`). Limit: a `$'...'` word with a backslash
inside a double-quoted `bash -c "eval ..."` text is not read: the lexer keeps the backslash of the outer quotes,
so the inner ANSI-C text is not decoded.

Two boundaries hold for every shell check that reads write targets from the command text (write-guard,
worker-write-scope, git-metadata-guard, outside-root), since the checks read the text and run nothing:
**runtime code** — code that becomes a script only when the command runs (`bash <<< '…'`, `source
/dev/stdin`, `$CMD <<'EOF'`, `eval "$(cat <<'EOF' …)"`, `[scriptblock]::Create`, `Start-Process`) is
not followed into; and **state** — a target that depends on an earlier command or on an alternative
(`ln -s <project>/src l && echo x > l/f`, `cd a || cd b` many times over) is judged on what the text
says, not on what the file system will hold. The checks are a guard rail against mistakes, not a wall
against intent: whoever routes a write around them already acts against their own assignment.

Redirections behind a copy command are not operands. A copy source is read whole: there is no
file-count limit, links and junctions inside it are followed once each, and a source that cannot be
read within the time budget (about 4 s) is refused. Below a copy destination that is no protected
place, only source files that can land on a protected path are mapped: a protected name, a path
through a link already below the destination, a Windows short name (`~1`). The body of a quoted
heredoc is not scanned as commands only when the whole command is one text reader that stores it
(`cat`, `tee [-a] <file>`, `git commit -F -`, `git tag -F -`) with nothing before or after it.

### The watcher after every call: `protected-watch`

`git-metadata-guard` reads the text of a call before it runs, so a script file, inline code or a program that
writes a protected file itself stays invisible to it. `protected-watch` looks at the files afterwards, whatever
wrote them. After every tool call (PostToolUse and PostToolUseFailure, orchestrator and workers) it compares
these files with a snapshot kept under `.act-local/protected-watch/` (taken at session start, after the session
handler has refreshed the bridges): `.git/hooks/**` and `.git/config` / `.git/config.worktree` of the repository,
of a `.git` file's git directory and its `commondir`, and of submodule and linked-worktree git directories, plus the
pointer files themselves - the `.git` file at the project root (`gitdir: ...`) and a git directory's `commondir`;
`.claude/settings*.json`, `.claude/agents/**`, `.claude/skills/**`, `.claude/commands/**` of the project;
`.mcp.json`, `.envrc`, `.devcontainer.json`, `.devcontainer/**` and `.vscode/tasks.json` at the project root.
`.git/config` is compared only on the keys that start code (the list above, the one `git-metadata-guard` uses):
git rewrites the file for `push -u` or `remote add`, and that is no change; without a usable `git` the whole
file is compared. For a key whose danger depends on the value (`alias.*`, `remote.*.url` and `pushurl`,
`protocol.*.allow`) every value is kept, harmless or not, so a harmless value that is changed to a dangerous one
is put back as well.

The watcher never follows a link. A watched folder or file that is a symbolic link, a Windows junction or another
reparse point (the `modules/` and `worktrees/` folders of a git directory and the
entries below them included) is listed as one entry of its own and never entered or read. Before it removes or restores a file it
checks that no folder between the project root (or the git directory) and the file is such a link and that the real
path of the folder is the expected one; a path that goes through a link is reported as "not restored (path goes
through a link)" and left alone, and a link a worker put in place of a watched folder or file is removed (the link
itself, never what it points at). The same check guards every write below `.act-local/protected-watch/`; if
`.act-local` or that folder is a link, the watcher stops with one line on stderr.

Everything the watcher may delete, create, replace or write lies below places fixed when the snapshot was taken: the
project root, the git directories found then (each with the real path it had, both kept in the snapshot) and
`.act-local/protected-watch/`. Nothing read from the working tree at restore time can add a place. The `.git` file at
the root and a git directory's `commondir` are watched as files like any other, so a pointer a worker rewrites is a
change that is put back (a worker) or reported (the orchestrator) - but the scan keeps listing the git directories
of the snapshot, never the new target, and a file below a git directory the snapshot did not have is reported and never
removed. A restore also stops when the recorded git directory is now a link, no longer a directory, or no longer
resolves to the real path it had. The temp file of a restore is created exclusively and never follows a link, so a
hard link or symlink standing at its name is not written through.

Whether a git directory may be restored at all is decided from real paths. A snapshot taken at session start, or in
an orchestrator's call that found none, is trusted, so the git directories it finds (also one outside the project
root, such as a linked worktree's directory below the main repository's `.git`) are restorable. A snapshot taken
during a worker's call (the snapshot was missing or deleted) is not: there a git directory is restorable only when it
lies below the project root in fact - written below it, no link on the way from the root down to it, and its real
path below the root's real path. A `.git` file that names a path inside the root which reaches outside through a
linked folder therefore makes nothing outside a place the watcher may delete or write; the directory is watched and
its changes are reported "not restored" until a session start takes a trusted snapshot.

It is cheap: one directory listing of the project root and the watched folders, one stat per file, and a file is
read and hashed (sha256) only when its size or modification time differs from the snapshot. A call that changed
nothing costs a few milliseconds on top of the interpreter start (about 3 ms for 76 files, measured).

What happens when a file really changed (its hash differs; for `.git/config` a code-starting key):

- **A worker's call** (the payload carries `agent_id`), key `block`: the file is put back at once from the
  snapshot taken before the call, not blindly from git — a versioned file can carry the orchestrator's wanted,
  uncommitted edit, and `.git/hooks` and `.git/config` are never versioned. A file that appeared is removed, a
  file that vanished is restored. For `.git/config` only the changed keys are reset with `git config --file`; the
  rest of the file stays as git left it. The changed version is kept as a file under
  `.act-local/protected-watch/kept/` (30 days). The worker gets the report as `additionalContext`, the human a
  `systemMessage` that starts with the warning sign, and the orchestrator a note with its next tool call.
- **The orchestrator's call**, or key `warn`: reported only, to the model and to the human, with the commands that
  put the previous version back (the previous version is kept under `kept/` so the command stays valid; the
  assistant's own writes to hooks and git config are refused, so the human runs them). The new state becomes the
  reference, so the next call is quiet. The commands name the file (`git config --file <path> ...`, also for
  `config.worktree` and a submodule's config), end git's options with `--` before the key and value (a value that
  begins with `-` is a value, not an option), and are written so that no shell expands anything in a key, a value
  or a path: an argument with a character other than letters, digits, space, comma and `_./:@+=-` is given as a
  Python string literal with `\xNN` escapes, in one `python -c` call, and an argument that begins with `@`
  (splatting in PowerShell) or `-`, or that holds a comma (PowerShell reads a bare `a,b` as an array), is put in
  double quotes.
- **A restore that fails** (a read-only file, a path through a link, no copy of the old version): the snapshot entry
  stays the reference, so the next call reports the change again, and a temp file the write left behind is removed.

Switch: `protected-watch` in `docs/ai/config.md` § Checks — `block` (default; restores a worker's change), `warn`
(reports every change, restores nothing), `off` (no snapshot, no comparison); `ACT_PROTECTED_WATCH` in the
environment overrides the value for one run.

Limits:

- It reports after the call and prevents nothing; a hook runs at the next git command, which can be the next call
  of another worker.
- A change made between two calls by someone else — the human in an editor, Claude Code writing
  `.claude/settings.local.json` when a permission is granted, another session in the same project (it shares the
  snapshot) — is attributed to the next call. A worker call that ends just after the orchestrator changed a
  protected file is attributed to the worker and the change is put back: the kept copy and the command in the
  message undo that. The same holds for a permission the human grants in a prompt during a worker's call.
- Stat first: a write that leaves size and modification time as they were is not seen (a file modified within two
  seconds before the snapshot is hashed once more at the next call, so a write in the same clock tick is not
  missed). A file over 2 MB is hashed but has no copy and cannot be restored. At most 4000 files are listed.
  `*.sample` files in a hooks folder are left out; git never runs them.
- A worker that deletes the snapshot itself makes the next call take a new one; its write scope normally keeps it
  out of `.act-local/`. Two sessions in one project share the snapshot.
- A `.git` file above the project root (the project lies inside a linked worktree or a separate git directory whose
  pointer is outside the root) is outside the root and not watched: the git directories it named at snapshot time
  stay watched, but a rewrite of that pointer is not seen.
- A git directory that is first seen in a snapshot taken during a worker's call (the snapshot was missing or deleted)
  and does not lie below the project root in fact - by its real path, with no link between the root and it - is
  watched and its changes are reported, but not restored, because that snapshot cannot be trusted as a reference for
  it; the next session start takes a trusted one. A pointer that names a path inside the root which reaches outside
  through a linked folder is such a case.
- Who is blamed: a worker's change that is first seen in the orchestrator's own call — calls that run in
  parallel, a background command that ends late, a worker call that finds the lock taken and returns — is reported
  as the orchestrator's, is not put back, and becomes the reference. The report names the call it was seen in, not
  who wrote.
- A watched folder that was a link when the snapshot was taken (a shared `.claude/skills` linked in on purpose) is
  watched as that link only, not what lies behind it. A link is checked at the moment of the write, not held: one
  planted between the check and the write by a process running at that very instant is not caught.
- Not watched: `~/.claude` (other projects share it and Claude Code writes there itself; it stays with the static
  check), `*.code-workspace` files.
- Nothing runs where hooks do not run (other tools stay with the static check). An error in the watcher is one line
  on stderr and never blocks a call.

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

A throwaway project below `.act-local/tmp/` carries a `.act/` of its own, which is no part of the project's
template tree: the template's `.act/` write-guard lets a write into it pass, also where the text of the target
cannot be resolved (a variable in front of it, `$ROOT/.act-local/tmp/job/proj/.act/x`). Allow-list: the
project root is known and does not itself lie below `.act-local/tmp/`, the text holds `.act-local/tmp/` as
whole segments with no `.act` segment before them, the part before them is empty or made of plain segments
with at most one variable, written `$NAME`, `${NAME}` or `$env:NAME` and standing alone as the very first
segment, and every segment behind them is plain too. A plain segment holds no `..`, variable (`$NAME`, cmd's `%NAME%`), command
substitution, backtick, glob, brace, `~`, parenthesis, quote or white space. `$ROOT/.act/x`,
`.act-local/tmp/$job/.act/x`, `$ROOT/.act-local/tmp/../../.act/x`, `$ROOT/.act-local-tmp/job/.act/x`,
`$A$B/.act-local/tmp/job/.act/x`, a substitution that begins before the marker and ends behind it
(`$(cd $ROOT/.act-local/tmp/job; cd ...)/x`) and a segment with a space or a quote stay refused. For a
project that itself lies below `.act-local/tmp/` (a throwaway project run as a project; the root is compared
without regard to case, `.ACT-LOCAL/TMP/` counts) every text naming
`.act/` stays refused, since its own `.act/` can then be spelled through `.act-local/tmp/` behind a variable
or an administrative share (`${U}//localhost/D$/.../.act-local/tmp/job/.act/x`). Limit: a leading variable is
trusted to stand for a place outside `.act/`; one that holds `.act` itself (`D=.act; echo x >
$D/.act-local/tmp/a/.act/b`, `$PWD` from inside `.act/`) reaches only new files below
`.act/.act-local/tmp/`, no file of the template. `.act` is recognised in any spelling of case in the text of a target that cannot be placed
(`$D/.ACT/x`, `.Act`): Windows and macOS do not tell the spellings apart, so the file is the same. The marker
`.act-local/tmp/` in that text only counts as typed in lower case, so `$ROOT/.ACT-LOCAL/TMP/job/.act/x` stays
refused. A target that can be placed is resolved: on Windows the comparison already ignored case, on macOS it now
does too (a lower-cased comparison, not run on a Mac in the build), on Linux a differently spelled name is a
different file.

Checked mechanically by `act-local-tidy` (`docs/ai/config.md` § Checks), once a day at session start in a
detached process; the next start reports the result in one line. It removes: `.act-local/tmp/` entries
older than 7 days that belong to no open task; all but the newest 5 folders in `.act-local/backup/`;
folders of the compiled cache in `.act-local/pyc/` whose source folder no longer exists (a moved project, a
replaced Python) and that hold nothing newer than 7 days; every other entry directly under `.act-local/`
that no template script creates. Age is the newest change of
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
Write/Edit; code that only reads - no write call - may name any path, so read outside the scope in a call
of its own.

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
