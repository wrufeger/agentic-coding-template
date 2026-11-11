# Mechanically checked rules — details

Detail page for the rules that name `topics/checks.md`. A rule in `.act/rules/` says what is forbidden or required;
this page adds, per check, what it blocks, how it is switched and the limits an owner must know. How a check reads
a command (parser allow-lists, time budgets, failure handling) is documented at its code in `.act/hooks/checks/`
(header comment of the module); the block messages name the syntax and point here. The checks are switched in
`docs/ai/config.md` § Checks (`block`, `warn` or `off`).

**Incident log.** Only real faults are noted in `.act-local/incidents.jsonl` (time, kind, source, role, a short message;
never a command or a path):

- `restored` / `restore-failed`: `protected-watch` put a worker's change to a protected file back, or could not (tool,
  kinds of file such as `git-hook`, their number);
- `check-error` / `check-slow`: a check crashed (exception class only) or ran past 8 s of the hook's 10 s limit;
- `warn`: a check in `warn` mode let a call through that wrote, deleted or read a secret file, with a reason class and a
  masked target class (`outside-write other/d3`, `secret-file project/d1`; never a name) and the tool and the first word
  of the command (a class such as `(assign)` or `(path)` when there is no plain word). A read outside the project
  (`outside-root`), a note of `ide-mcp` and a hint to the main session (`worker-scope-overlap`) are not logged. The
  environment overrides `ACT_OUTSIDE_ROOT` and `ACT_SECRET_READ` count like the config row; `encoding-hint: warn`
  counts although it prints nothing;
- `escalated` (`usage.py --outcome <role> <tier> escalated`) and `model-switch` (a refusal that made the session or a
  worker switch model).

A check's refusal is not logged: whoever made the call sees it at once; it is counted instead (below). The next session
start puts the new lines into the inbox report `Incident log <date>` (`kind: report`, `for: all`; an open report of the
same day is extended, text a person added to it stays), equal lines as one row with a count, counts per kind on top, and
is silent when nothing is new. Delivered lines are kept 30 days. It is written by `session-start-refresh: block`; with
`warn` the start only says how many events wait. There is no config row of its own, but `ACT_INCIDENT_LOG=off` in the
environment writes, counts and delivers nothing for one run (a test suite that drives the hooks). Limits: two appends at
the same instant are serialised by a short lock file (`.act-local/incidents.lock`), also held while a delivery cuts old
lines out; a wait for it is given up after half a second and the event is appended anyway, so an event is lost only
when a delivery's rewrite takes longer than that; when the offset cannot be written after a delivery, the same events
come again.

**Refusals counted.** Every refusal of a check is counted silently in `.act-local/usage.json` (`checks.<check>.refusals`,
per day and role, `main` for the main session; the check's module name and the role name only, never a command or a
path; days older than 30 are dropped). Counting never changes a check's verdict, also when it fails. `doctor.py --inbox`
files one question when the same check refused workers at least 3 times within 7 days, not again while one is open and
not within 7 days of the last one. Its proposal never loosens the check: it proposes one sentence for the worker's role
file or the assignment header that tells the worker beforehand what the check does not allow, with the options adopt,
reword, do nothing. The sentences are these (one per check; a check without one gets a generic sentence):

- `write_guard`: Never write under `.act/` (the template's own files); a project-specific version goes into `docs/ai/local/<same path>`.
- `git_metadata_guard`: Never write `.git/hooks`, `.git/config` or a git config key that starts a program, nor Claude settings, agents, skills or commands, `.vscode/tasks.json`, `.devcontainer`, `.envrc` or `.mcp.json`; name the change you need in your result.
- `write_scope`: Write only inside the `Write scope:` of your assignment, also through a script, an interpreter or a redirect; name any other file and the change it needs in your result.
- `worker_docs_ai`: Never write under `docs/ai/`; the orchestrator records it, return your result instead.
- `worker_git_write`: Git is read-only for you (`status`, `diff`, `log`, `show`, `stash list`, `stash show`): never stage, commit, stash, reset or check out.
- `nesting_guard`: Never start another worker; name a better split in your result.
- `mcp_ide`: Do not use IDE tools that write, run a shell or run a program; use the standard tools inside your `Write scope:`.
- `commit_pathspec`: Never stage with `git add -A`, `git add .` or `git commit -a`; name each path.
- `git_discard`: Never run a git command that discards work (`reset --hard`, `clean -f`, a folder checkout or restore, `stash drop`, `branch -D`).
- `recursive_delete`: Never delete recursively with a shell command (`rm -rf`); use the language's own means on a literal path under your throwaway folder.
- `secret_read`: Never read `.env`, private keys or credential files with any read, grep or command; read `.env.example` or ask for the non-secret values in your result.
- `outside_root`: Read and write only inside the project and the places your assignment names; a path outside, also in a `cd`, is refused, so name it in your result instead.
- `encoding_hint`: Before writing to an existing file that is not UTF-8, keep its encoding; the first write to such a file is refused once.
- `worker_cap`: Keep to the `Cap:` of your assignment: past it you are refused, so report what is done and what is left.

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

Inline code of a JavaScript runtime (`node -e`, `deno eval`, `bun -e`): a string literal that is the direct argument of
`new URL(`, `URL(`, `url.resolve(`, `path.normalize(` or `path.posix.normalize(` (also behind `require('path')`) is no
read. Any other literal, one inside a call nested in such an argument, and a `file:` URL are still paths, and the whole
exception is off when the command line names a file API (`fs`, `open(`, `readFile`, `fetch`, `import.meta`, a `file:`
...).
A file API the list does not know makes a literal look harmless.

A URL route handed to a script is no read either: a word with a leading `/` behind the script file of `python`, `node`,
`deno run`, `bun`, `tsx`, `ts-node`, `ruby`, `php`, `perl`, `lua`, `bash`/`sh`/`zsh`/`dash`/`ksh`, behind the package of
`npx`, `bunx`, `npm exec`/`x`, `pnpm exec`/`dlx` or `yarn exec`/`dlx`, or behind a relative program (`./run.sh`,
`./.venv/bin/python`) is left out of the read scan when its first segment names nothing (`python scripts/replace.py
"/api/users" "/api/v2/users"`). It stays a path when its first segment exists (`/etc`, `/usr`, `/home`), when it holds
`..`, `~`, a variable, `%` or an expanding brace group (`{a,b}`), is a drive, `file:` or UNC form, follows a file option
(`-o`, `-vo`, `--output`, `--file`, `--config`, `--out-dir`, `--save-to` ...), is the script itself, or belongs to inline
code (`-c`, `-e`); a known file command (`cat "/api/users"`) is judged as ever, and so is everything inside `wsl`
(the check cannot see the distribution's folders). On Windows the first segment counts as existing when any reading of
it does: the drive form (`/q/x` as `Q:`), a folder of the working drive, a name every POSIX root has, or a folder of a
Git for Windows root (looked up in its usual install places only). A script that opens such a path itself is not seen:
the exception trades some safety for comfort and holds only while nothing lies at the first segment.

More generally a read names nothing, and is left out, where the command text does not show a place: a path that does not exist on the disk (`cat /contacts.json`,
`grep x /de/link-collection`, `C:/nothing/x`, a mistyped file `D:/dev/proj/tests/x.ts` under an existing folder; on
Windows a POSIX-rooted word counts as existing when one reading of its first segment does), and a shell word with a
variable or substitution (`cat /etc/$f`). A write is never left out this way: it can create the place. Limit: a file
created between the check and the read is read unseen.

Two scripts write outside the project, only when the human explicitly asks: `id_links_install.py` to `~/.act/id-links/`
and `act-export-settings --profile` to the user's config folder (`settings.md`; an existing file is first copied to
`settings.md.bak-<stamp>`). `act-adopt` is the one exception: the owner starts the first scan with the `!` prefix,
which opens the target folder for 24 hours or until `--abort` through a marker under `.act-local/outside-allow/` that
only the adopt scripts write.
The write-target scanners shared by the write guard, the worker write scope and `outside-root` see a `cd`/`pushd`
into a folder before a relative write (a folder an earlier top-level `mkdir`/`New-Item -ItemType Directory` with a
literal path makes counts as existing), `git clone` and the other git commands that write a target (also `git diff|log|show --output=<file>`, `--output <file>`
and an abbreviation from `--ou`), `robocopy`, the
source of a PowerShell move, `perl`/`ruby -i`, `chmod`/`chown`, `xargs` with literal input and the literal file names
a `-c`/`-e` interpreter argument opens for writing; not a path built at run time, archives `tar`/`zip` create, or
`find -exec`. A relative write behind more than 24 possible folders, or past the work bound of one command, is
refused by all three as a write they cannot place (any mode short of `off`): split the command. A folder made again
after something took it away (`mv build old; mkdir build; cd build`, `Remove-Item build; New-Item -ItemType Directory
build; Set-Location build`) counts as existing again, what lies below it does not, and a removal or move after the
creation wins. A name a command made a file at (a move or copy to it, `ln`, `touch`, a redirection, `Set-Content`)
does not count so: the `mkdir` fails there, the `cd` after it stays where it was, and the write is also placed in the
old folder (`mv a.txt out; mkdir out; cd out; touch .act/x`). The shell may be in two places after `cd .act && ls && cd ..; echo x > out.txt` (and with `pushd`/`popd`): a
failing `ls` skips the `cd ..` while the `;` goes on, so the write is also placed in `.act`, and the guard refuses it. That
is a limit, not a bug: write the command with `;` between the steps, or as two calls. A list that ends in `&` runs as
one background job, so what follows the `&` is placed where the list began, not in the folder of a `cd` inside it
(`cd out && A & B`: B runs in the starting folder); `--output` is read from the words before `--`, and a value that
`git` takes for another option is not told apart.

Limits: the shell check is best effort. A program that opens files itself (`python script.py`, `docker run -v`) is
invisible; an MCP tool that takes a path is checked only if it is a read tool of the IDE server's known list. A command
line with more than 150 `cd`-like statements, one that may run in more than 8 directories, or a path of more than
200 segments is refused as unknown: split it. A word of only slashes (`//`), and a lone `/` as a
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
  state becomes the reference. One exception, the orchestrator's call only: a file under `.claude/skills/` that the
  copy step (`init`, `act-update`, session start) writes for this project (exact path, not removed by you) and whose
  bytes equal what it writes is not reported; a deleted file, any other path and any difference is. Limit: a skill
  changed through its source (`.act/skills/`, `docs/ai/local/skills/`) is not reported, the source is versioned.

Limits: it reports after the call and prevents nothing. A change made between two calls by someone else (the human,
Claude Code, another session) is attributed to the next call; a worker's change first seen in the orchestrator's call
is reported as the orchestrator's and not put back. A write that leaves size and modification time unchanged is not
seen; a file over 2 MB cannot be restored; at most 4000 files are listed. `~/.claude`, `*.code-workspace` files and a
`.git` file above the project root are not watched. A git directory first seen in a snapshot taken during a worker's
call and not below the project root in fact is reported, not restored. Nothing runs where hooks do not run. The
remaining limits and the rules for links are in the header of `protected_watch.py`.

## `R-work-throwaway` — Throwaway material under `.act-local/tmp/`

Checks: act-local-tidy, throwaway-place.

Throwaway material (probes, scratch projects, clones, output files) goes into `.act-local/tmp/<task-id>-<slug>/`, never
into the system temp directory and never directly under `.act-local/`. Work with no task (a skill run, a doctor
report, feedback intake) takes `.act-local/tmp/<YYYYMMDD>-<slug>/` (date in digits, no hyphens); `act-local-tidy`
clears it after 7 days like any entry whose name does not start with an open task's id. The orchestrator removes a task's folders when
it commits the task (`python .act/scripts/act_local_tidy.py --task <id>`); whoever made a folder removes it earlier.
Git run in a subfolder that is not a repository of its own acts on the project's repository: set
`GIT_CEILING_DIRECTORIES` to `.act-local/tmp`, or call git only on a repository of its own. A deny entry on Windows can
lock out the owner too (`(RX)` also denies `READ_CONTROL`): deny only the one right the probe needs, such as `(RD)`,
and run `icacls <path> /reset` in the `finally`. A throwaway project below `.act-local/tmp/` carries a `.act/` of its own;
the template's `.act/` write-guard lets a write into it pass (conditions in `write_guard.py`); a `shutil.rmtree` of the
project root or of a folder that holds it is refused. Limit: a relative
`.act/` target after `cd $VAR/...` (a variable, `P=<dir> cd $P/x` too) is judged against the project root and
refused; `cd <literal folder> && cp ... .act/...` into such a project passes, so write the folder out.

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

`throwaway-place` (switch in `docs/ai/config.md` § Checks; `warn`, the default and the value of a missing row, notes;
`off` says nothing; `block` counts as `warn`) notes, never refuses, when the main session writes into the wrong
place: a shell redirection or write target, or the path of a Write/Edit call, in the system temp directory
(`/tmp`, `$TEMP`, `$TMP`, `$TMPDIR`, `%TEMP%`, `$env:TEMP`, the directory `tempfile.gettempdir()` names) or a file
directly under `.act-local/` (not one the template creates there itself). The note names
`.act-local/tmp/<task-id>-<slug>/` or `.act-local/tmp/<YYYYMMDD>-<slug>/` and reaches the model with the call's
result. A worker's call is not looked at (with a restricted `Write scope:`, `worker-write-scope` refuses it). Limits: only targets the write-scope
reader sees; `mktemp`, `tempfile` in inline code and a script file's own writes stay unseen.

## `R-work-evidence` — Done only with evidence

Checks: commit-hashes.

A commit hash counts as evidence, so `commit-hashes` (switch in `docs/ai/config.md` § Checks; `warn`, the default and
the value of a missing row, notes; `off` says nothing; `block` counts as `warn`) notes, never refuses, a hash in a
`git commit` that no repository knows. It reads the lines the commit adds to staged journal files
(`docs/ai/work/ledger/`) and the message as the command shows it: `-m`, a heredoc behind `-F -`, a literal `-F <file>`.
A hash is a word in backticks of 7 to 40 hex characters with a digit and a letter (`` `3e2901a` ``); a bare number, a
hex word without a digit and a word without backticks are not looked at. Each is looked up with
`git cat-file -e <hash>^{commit}` in this repository and in the repositories the row `commit-hashes-repos` lists
(comma-separated, relative to the project root or absolute; default `none`; a folder that is no repository is skipped),
because a journal can name commits of another repository. A hash none of them knows still counts as known when it
starts (any case) a template commit that `.act-lock.json` records, in the working tree, staged or in its history; a
template commit never recorded there is noted. The note names the unknown hashes and reaches the model with the call's
result. A worker's call is not looked at. Limits: a message file written in the same call, hashes inside a
program's own text and an ambiguous abbreviation (counts as unknown) are not handled; a lookup that runs past about
4 seconds, or a missing git, gives no note.

## `cd-git` — `cd` and `git` in one call (no rule of its own)

Claude Code asks the owner for approval each time for a Bash call that holds `cd` (or `pushd`) and `git`, in auto mode
too; `git -C <folder> <command>` with the folder written out does not. `cd-git` (switch in `docs/ai/config.md`
§ Checks; `block`, the default, refuses; `warn` names the way and lets the call pass; `off`) refuses such a call, for the
main session and for workers, and names `git -C <folder> …` in a call of its own as the way. It runs only when the
`tools` row holds `claude-code`; for another tool or a project without the row it does nothing. A `cd` into the folder
the call runs in (the project root, `cd .`, `cd sub/..`) does not count; a `cd` to a variable or substitution counts as a
`cd` elsewhere. Subshells and the text of `bash -c` are read. Limits: Bash calls only (not PowerShell), a `cd` or `git`
made inside a program is not seen; an exception lets the call pass.

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
variant counts as its base role. A tier set for the role in `docs/ai/config.md` § Roles replaces that
role default, and an unknown `Tier:` word falls back to the role default too. With neither, `standard`.

The worker gets one note on reaching the cap ("cap reached — deliver your current state now") and is
refused from 1.5× the cap onward — wrap up and report rather than push past it.

`Write scope: none` allows no writes at all, except into the throwaway place (below): not in the project, and not
in the system temp directory or the worker's scratchpad either (`/dev/null`, `NUL` and the standard streams stay
free). A worker with any `Write scope:` line writes only what that scope allows; the system temp directory and the
scratchpad are no exception. Every target under `.act-local/tmp/` of the project root is free for every worker,
whatever its scope says (`R-work-throwaway`: throwaway material goes under `.act-local/tmp/<task-id>-<slug>/`);
a `..` that leaves it is judged as the path it reaches, and the refusal of a write into the system temp
directory or the scratchpad names that place. Limit:
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
check at the first hit. Advice for a relative target behind a `cd`: in a real shell the `cd` holds only for the parts
behind `&&` (behind `&` it ran in the background shell, after `;` it may have failed), so chain the parts with `&&`
or put the `cd` and the parts that need it into one group (`cd d && (a > ../x & b > ../y; wait)`).

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
only when **a write call of the code names a path written out as a literal that lies outside the scope**. The
code comes from `-c` (also a cluster such as `-Ic`) or `node -e`/`--eval`/`-p`/`--print`, or from standard
input (`-` or no script argument): a heredoc (`python - <<'EOF'`), a here-string, or a literal piped in
(`cat <<'EOF' | python -`, `echo '...' | python3`, in PowerShell a string or here-string piped into
`python -`).

What counts is only what the text shows, nothing else (a check refuses what the command text shows to be wrong; an
unknown target passes): a string that is merely mentioned (an import line, a comment, a message, a path the code
only reads, the system temp folder in a text) is no target, and neither is a path the text does not show - a name
bound twice, a loop variable, a parameter, `sys.argv`, a join or f-string with a variable part, a call's result -, a
literal that holds a `$` or a backtick, or code that cannot be read as Python (or a program
larger than the reader takes). Shown is: a string literal; `Path(...)`, `os.path.join(...)` (Node `path.join(...)`) of
such parts; a name bound exactly once, by a plain assignment (Node `const NAME = "literal"`), to such a value and used
unchanged (not where the program calls `exec`, `eval`, `getattr`, `setattr`, `__import__` ... or stores an attribute on
a module); and the files of `<folder>.glob('<literal>')`, `.rglob(...)`, `glob.glob('<literal>')` with a literal folder
(the folder is judged; the worker scope allows it only where the scope covers all of it). The text of an
`exec`/`eval` written out is read again.

The write calls are Python `open` (also `io.open`, `codecs.open`) with a writing mode or one that is not seen, `.open`
with a writing mode written out, `os.open`, `os.remove`, `unlink`, `rmdir`, `removedirs`, `mkdir`, `makedirs`,
`truncate`, `chmod`, `chown`, `utime`, `rename`, `replace`, `symlink`, `link`, `shutil.copy`, `copy2`, `copyfile`,
`copytree`, `move`, `rmtree`, and the `Path` methods `write_text`, `write_bytes`, `touch`, `mkdir`, `unlink`, `rmdir`,
`chmod`, `lchmod`, `rename`, `link_to`, `symlink_to`, `hardlink_to`; Node `writeFile`, `appendFile`,
`createWriteStream`, `copyFile`, `cp`, `rename`, `unlink`, `rm`, `rmdir`, `mkdir`, `symlink`, `truncate` (and their
`Sync` forms). A literal counts as a path when it holds `/` or `\`, or is a bare file name with an extension
(`out.txt`), is no URL; its escapes are decoded the way the language does. A literal is judged like
a shell target, against the directory the call runs in (a `cd` before it counts), but as written: no `/tmp` mapping,
no brace or tilde expansion, and no Git-Bash drive form - on Windows a literal such as `/d/work/x` is the folder `d`
on the drive of the directory the call runs in. The refusal says to write the file with Write/Edit.

Limits of that reading (what stays unseen; it catches the common form, not every form):
- the program is not in the command: a script file run by path (`python /tmp/x.py`), code held in a
  shell variable or read from a file (`cat x.py | python`);
- the path is not a literal that tells it (see above), a name without extension and without separator in a path
  literal (`open('out', 'w')`), a glob- or regex-looking literal (`*?[]^|()<>`);
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
write call; `.act/scripts/doctor.py` or the owner decides how to go on.

A shell target with a variable is unknown and passes, unless the same command assigns the variable once as a simple
literal (`f=server/x.ts && sed -i ... $f`, `d="out"; echo x > ${d}/y`): then the value is judged like any target. So
does a command substitution, a brace list of unknown quoting, a target behind a `cd` the scan cannot follow, a target
the scan could not place and a command it cannot read (too deeply nested, too large). A `~` start is the home
directory and is refused (it is never in the scope); a `$` after a shown folder (`other/$x`) passes.

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
row counts as `warn` for it; the notes are hints and not entries of the incident log). The note names the worker's line and the way out
(wait until that worker has ended or stop it with `TaskStop`, or work in an isolated copy). It comes when a `Write`,
`Edit`, `MultiEdit` or `NotebookEdit` path of the main session, or a write target of its Bash or PowerShell command
(the scanners `worker-write-scope` uses, inline code included), falls under the `Tests:` of a running worker; and when a
command runs the test command or the full suite (third and fourth entry of `commands` in `docs/ai/config.md`; `(not set)`
means none: a simple command starting with its words, the program by name, quoted text not counted) in a tree a running worker writes in. That
tree is the directory the run starts in (the call's cwd, moved by a literal `cd`) and every word that names an existing
file or folder, such as `--template <dir>`; a worker that writes below `.act-local/tmp/` is an isolated copy and meets
only a tree below `.act-local/tmp/`, a worker without a `Write scope:` line meets every tree. PreToolUse text does not
reach the model, so the note is repeated with the PostToolUse of the same call. Limits: a target still expanded by the
shell (`$VAR`, `~`, a nested `{`) or relative with no known directory cannot be placed, inline code the reader fails
on and an unreadable registry are not looked at, and a target is compared with the `Tests:` pattern only from below: a
write that moves, copies or restores a parent folder of the tested tree (`mv tests tests-old`, `git restore .`) and a
glob class such as `tests/t24[8]/a.py` pass without a note.

What the check cannot see stays with the orchestrator: a run does not start before the reviews are accepted (the
commit's checks run once on that state, during rework only the rework's own tests), and a run still going when rework
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
resets it. Limit (also for `worker-cap`, which counts a worker's tool calls the same way): both keep their count in
a file below `.act-local/`, and where `.act-local` or its `status-poll` / `worker-caps` folder is a link or junction out
of the project they write nothing and track nothing, so neither refuses a call there (they fail open: cost checks, no
safety); the session start names the link.
