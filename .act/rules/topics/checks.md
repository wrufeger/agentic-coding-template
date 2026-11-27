# Mechanically checked rules — details

Detail page for the rules that name `topics/checks.md`. A rule in `.act/rules/` says what is forbidden or required;
this page adds, per check, what it blocks, how it is switched and the limits an owner must know. How a check reads
a command (parser allow-lists, time budgets, failure handling) is documented at its code in `.act/hooks/checks/`
(header comment of the module); the block messages name the syntax and point here. The checks are switched in
`docs/ai/config.md` § Checks (`block`, `warn` or `off`).

**Hook command.** Each hook entry in `.claude/settings.json` has a `command` in Bash form that starts
`.act/hooks/dispatch.py` and also a `powershell` form for GitHub Copilot on Windows (for `UserPromptSubmit` it
starts nothing). The dispatcher always reads Copilot's keys (`path`, `file_text`, `old_str`, `new_str`) where
Claude Code's are missing; the `powershell` form sets `ACT_HOOK_HOST=copilot`, and then Copilot's key wins over a
Claude Code key, its shell tool reported as `Bash` is judged as `PowerShell`, and a denial reason goes to standard
output as well.

**Incident log.** Only real faults are noted in `.act-local/incidents.jsonl` (time, kind, source, role, a short message,
and an origin mark when `ACT_INCIDENT_ORIGIN` is set; never a command or a path):

- `restored` / `restore-failed`: `protected-watch` put a worker's change to a protected file back, or could not (tool,
  kinds of file such as `git-hook`, their number);
- `check-error` / `check-slow`: a check crashed (exception class only) or ran past 8 s of the hook's 10 s limit
  (past 8 s no further check starts, see "When a check itself fails" below);
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
environment writes, counts and delivers nothing for one run (a test suite that drives the hooks).
`ACT_INCIDENT_ORIGIN=<mark>` adds the field `origin` to each line written in that run (a test runner marks its own
probes' lines with it; delivery ignores it). Limits: two appends at
the same instant are serialised by a short lock file (`.act-local/incidents.lock`), also held while a delivery cuts old
lines out; an event is appended only while the lock is held, waiting up to two seconds for it; when the lock cannot
be taken in that time the event is not written (never an unlocked append, which could mix two lines), and a stale lock is
broken. A hook passes a shorter wait, down to none, so that its own time limit holds; when the offset cannot be written
after a delivery, the same events come again.

**Refusals counted.** Every refusal of a check is counted silently in `.act-local/usage.json` (`checks.<check>.refusals`,
per day and role, `main` for the main session; the check's module name and the role name only, never a command or a
path; days older than 30 are dropped). Next to it a class per refusal is counted (`checks.<check>.classes`, per day): a
word of a fixed set the check names itself (`protected-path`, `outside-scope`, `inline-code`, `read-only-scope`,
`scope-unbound`; a check that names none is counted without one), never text of the call. Counting never changes a check's verdict, also when it fails. `doctor.py --inbox`
files one question when the same check refused workers at least 3 times within 7 days, not again while one is open and
not within 7 days of the last one. Its proposal never loosens the check: it proposes one sentence for the body of the
role's bridge (`.claude/agents/<role>.md`, which an update never replaces; a `<role>-high.md` the role's row no longer
calls for is removed with a backup; a file `docs/ai/local/agents/<role>.md` with a template role's name is not read,
it is the place of an own role) or the assignment header that tells the worker beforehand what the check does not allow, with the options adopt,
reword, do nothing. The sentence follows the most frequent class of the window where one is listed below as
`<check> (<class>)`, else it is the check's own; a check without one gets a generic sentence. When a file the worker
reads already carries that sentence (the role's bridge, `docs/ai/local/rules.md`, `docs/project/coding_rules.md` or a rule file
the workers load; compared without backticks, emphasis and line breaks), the options become report to the template,
adopt anyway, reword, do nothing, the question names those files, and only the blocks after the last commit of the
carrying file (without a commit, its modification date) count, from the day after it.
The sentences are these:

- `write_guard`: Never write under `.act/` of this project (the template's own files); a project-specific version goes into `docs/ai/local/<same path>`. In a throwaway copy under `.act-local/tmp/`, show the place in the command: the path written out, or a variable set once to a literal before its first use; `cd` only to a folder written out.
- `write_scope` (`inline-code`): Write a file with the Write or Edit tool inside your `Write scope:`, not through inline interpreter code; name any other file and the change it needs in your result.
- `write_scope` (`read-only-scope`): Your assignment is read-only (`Write scope: none`): write no file; return the content or the change in your result.
- `write_scope` (`scope-unbound`): If a write is refused because no write scope is bound to you, do not retry another way; say so in your result and name the file and the change it needs.
- `git_metadata_guard`: Never write `.git/hooks`, `.git/config` or a git config key that starts a program, nor Claude settings, agents, skills or commands, Copilot roles under `.github/agents/`, `.vscode/tasks.json`, `.devcontainer`, `.envrc` or `.mcp.json`; name the change you need in your result.
- `write_scope`: Write only inside the `Write scope:` of your assignment, also through a script, an interpreter or a redirect; name any other file and the change it needs in your result.
- `worker_docs_ai`: Never write under `docs/ai/`; the orchestrator records it, return your result instead.
- `worker_git_write`: Git is read-only for you (`status`, `diff`, `log`, `show`, `stash list`, `stash show`, `tag -l`, `config --get`, `notes list`, `remote -v`, `reflog`, `worktree list`, `apply --check` (also with `--index`, `--cached` or `--whitespace=nowarn`), `submodule status`, `lfs ls-files` with no option before the subcommand): never stage, commit, stash, reset or check out, never run `update-ref`, write `symbolic-ref`, create or delete a tag or write `config`, never run a maintenance, plumbing or notes/remote/worktree/reflog command that writes (`gc`, `prune`, `notes add`, `remote add`, `worktree add`, `hash-object -w` …), leave `fetch`, `clone`, `backfill`, `fetch-pack`, `send-pack`, `submodule--helper` and the writing forms of `submodule` and `lfs` to the orchestrator, and never `clone`, `init` or a `worktree` command into a folder of the project from a `-C` or `cd` outside it; every program `git-<name>` counts as `git <name>`, and `update-git-for-windows` is never yours.
- `nesting_guard`: Never start another worker; name a better split in your result.
- `mcp_ide`: Do not use IDE tools that write, run a shell or run a program; use the standard tools inside your `Write scope:`.
- `commit_pathspec`: Never stage with `git add -A`, `git add .` or `git commit -a`; name each path.
- `git_discard`: Never run a git command that discards work (`reset --hard`, `clean -f`, a folder checkout or restore, `stash drop`, `branch -D`).
- `recursive_delete`: Never delete recursively with a shell command (`rm -rf`); use the language's own means on a literal path under your throwaway folder.
- `secret_read`: Never read `.env`, private keys or credential files with any read, grep or command; read `.env.example` or ask for the non-secret values in your result.
- `outside_root`: Read and write only inside the project and the places your assignment names; a path outside, also in a `cd`, is refused, so name it in your result instead.
- `encoding_hint`: Before writing to an existing file that is not UTF-8, keep its encoding; the first write to such a file is refused once.
- `worker_cap`: Keep to the `Cap:` of your assignment: past it you are refused, so report what is done and what is left.

**When a check itself fails.** `secret-read` and `outside-root` fail closed: if the module cannot be imported or
raises on a call, every tool they otherwise look at is refused (`secret-read`: Read, Grep, Bash and PowerShell;
`outside-root`: the path tools Read, Grep, Glob, Write and Edit, Bash and PowerShell) and the failure is named on
standard error, so a broken check does not let `cat .env` or `Read .env` through (`off` does not help when the module
cannot be imported; `warn` does not soften it). A tool they never look at stays possible, so the cause can be looked
into; the owner starts `.act/scripts/doctor.py` with the `!` prefix. If the
dispatcher cannot import its own helpers, every tool is refused (PreToolUse). Every other check that can refuse
(`secret-scan`, the danger and dependency scans of `security-check`, `git-discard`, `commit-hashes`, `cd-git`,
`commit-pathspec`, `recursive-delete`, the `worker-*` checks, `status-poll`) refuses the call it was to look at as well:
the tools and callers it judges are listed in `_REFUSING_SCOPE` of `dispatch.py` (the shell checks only Bash and
PowerShell; `commit-hashes` only a `git commit` of the main session; `worker-cap` every call of a worker but its
`SubagentHandback`, which always goes through). The text names the check, the exception class, the row that switches
it off (`<row>: off` in `docs/ai/config.md` § Checks, which helps only while the check can be loaded) and
`.act/scripts/doctor.py`; for `commit-hashes` that means a crash refuses the commit although the check otherwise only
notes. `security-check` also refuses when the coding rule sets cannot be read (a broken `rules.py`); a missing
`docs/project/coding_rules.md` is an empty list and free. Only a check that never refuses (`encoding-hint`,
`throwaway-place`, the notes) fails open, but not silently: the failure goes to standard error, to the human as
`systemMessage` and to the model as `additionalContext` of the call's PostToolUse (see `dispatch.py`).

**When a check runs out of time.** A spent time limit is never a pass. `secret-scan` and the danger and dependency
scans of `security-check` repeat a git call that ran past its limit once, for its own limit or what is left of the
check's deadline, when at least half a second is left (`secret-scan`, `danger-scan`: 4.5 s, shortened by what the hook
has used; the hook as a whole has 8 s of the harness' 10). `git-discard` does not repeat: one git call may take its
whole budget. Otherwise, and when a loop stops at the deadline with work open or a git alias cannot be looked up for
want of time, the call is refused (exit 2): `[act] <check>: time budget used up, not finished after <n> s, so the call
is refused unchecked. Run the command again; to switch this check off, set `<row>: off` in docs/ai/config.md §
Checks.` (`security-check` for the danger and dependency scans; in `warn` mode the text is a note and the commit goes
ahead). "Not a repository" and "nothing to check" are no time-out and stay free; the size limit of `secret-scan` (a
file over 2 MB) stays a note. A check or hook that only notes says `[act] <name> incomplete (time limit <n> s);
<what is missing>` instead of staying silent (`commit-hashes`, the board refresh and the git lookups of the session
start, `tips`, `protected-watch`; the template update lookup runs detached and reports it at the next start). Those
lines are in the JSON the hook prints, which Claude Code shows: `systemMessage` for the human and `additionalContext`
for the model (PostToolUse; the session start's JSON for `tips`), never only on standard error, which nobody sees on
exit 0. The dispatcher starts no further check once 8 s of the hook are used: if one that can refuse and judges this
call is left, the call is refused `[act] hook time limit 8 s used up before these checks ran: <checks>; the <tool>
call is refused unchecked. Run the command again. ... Timing: <e> s since the hook started, the first check began at
<f> s.` (or `... before any check began.`). What a check judges is the table above, not wider and not
narrower: `secret-read` a Read, a Grep and the shell, `outside-root` every tool with a path and the shell, `ide-mcp` an
`mcp__` call of a write, shell or exec tool of an IDE server and a read tool that takes a path (`read_file`, which
`ide-mcp` hands to `secret-read` and `outside-root` as a Read). Otherwise
(only notes are left, or a call none of them judges) one line `[act] <checks> not run (hook time limit 8 s) -- <e> s
since the hook started, the first check began at <f> s` (or `... before any check began`) goes
to the human as `systemMessage` and to the model as `additionalContext` of the call's PostToolUse, and the call goes
ahead. Assumption, not verified: that Claude Code displays the `systemMessage` of a PreToolUse or PostToolUse hook (a
live probe, 2026-11-07, showed it is never displayed for Stop and SubagentStop).

## `R-safe-no-secret-read` — Never read a secret file into the context

Checks: secret-read.

Blocks a Read, Grep or shell reading command (`cat`, `grep`, `Get-Content`, `< file`, `git show HEAD:<file>` …) that
names a secret file; path list and exceptions (`.env.example`, `*.pub` …) in the header of `secret_read.py`. For a `git`
call, git's global options that take a value (`-C`, `-c`, `--git-dir`, `--work-tree`,
`--namespace`, `--exec-path`, `--config-env`, `--attr-source`; the list is shared with the other git checks) are skipped
before the subcommand is read, so `git --attr-source HEAD show HEAD:.env` is a `show` of `.env`. Switch
`secret-read` (`block`, `warn`, `off`); `ACT_SECRET_READ` in the environment for one run. Limits: a program that
opens the file itself (`python script.py`, `docker run --env-file`) is invisible, and so is an MCP tool that takes a
path, unless it is a read tool of the IDE server's known list (`ide-mcp`; each path argument of those is checked as a
Read). A word that merely looks like a secret name (`grep .env README`) is refused as well.

**`secret-read-allow`** (§ Checks, default `none`) lists files that may be read although they look like secrets: a
comma-separated list, each entry a file relative to the project root, starting with `~`, or absolute. A `*` is allowed
only in the last part of the path (`config/.env.*`). An entry is ignored, so it allows nothing, when it holds `**`, `?`,
`[`, `{`, a `*` before the last part, a last part that is only `*`, a trailing slash, or when it names a folder. A target
equal to an entry, read the way every target is (relative paths against the call's working directory, `~`, `..`, either
slash style; the case is folded on Windows and macOS only), is not refused; every other secret file stays refused, also
one next to a listed file or below it. A Grep `glob` is never matched against the list, and neither is the value of
grep's `--include` or of rg's `-g`, `--glob`, `--iglob` (any spelling: `=`, a separate argument, the glued short form):
it names files by pattern anywhere below the search path, so `grep -r KEY . --include=.env` stays refused with `.env`
listed. The real path counts too: a target that reaches another file through a link (`link/../.env` with `link`
leading elsewhere, a listed name that is itself a link to another secret file) is refused, a listed real file is read,
and so is a listed name that links to a file that is no secret. Only the owner writes this row in `docs/ai/config.md`:
a package cannot set it (its `## checks` line is refused).

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
created between the check and the read is read unseen. A brace expansion in a read word (`cat /x/{a,b}.txt`,
`{1..3}`) is judged as every word it stands for, up to 63 words; a range is counted before it is built, and a larger
one stays an unexpanded word. A word with a quoted or escaped brace, a value cut out of such a word
(`--in='/x/{a,b}'`) and a string literal of inline code (`python -c "open('/x/{a,b}')"`) are not expanded. The
refusal names the word as typed and the expanded word.

Two scripts write outside the project, only when the human explicitly asks: `id_links_install.py` to `~/.act/id-links/`
and `act-export-settings --profile` to the user's config folder (`settings.md`; an existing file is first copied to
`settings.md.bak-<stamp>`). `act-adopt` is the one exception: the owner starts the first scan with the `!` prefix,
which opens the target folder for 24 hours or until `--abort` through a marker under `.act-local/outside-allow/` that
only the adopt scripts write.
The write-target scanners shared by the write guard, the worker write scope and `outside-root` see a `cd`/`pushd`
into a folder before a relative write (a folder an earlier top-level `mkdir`/`New-Item -ItemType Directory` with a
literal path makes counts as existing), `git clone` and the other git commands that write a target (also `git diff|log|show|diff-tree|diff-index|diff-files|whatchanged|stash show --output=<file>`,
`--output <file>` and an abbreviation from `--ou`, and `git format-patch --output=<file>`, where any `--ou...`
abbreviation counts as a target), `robocopy`, the
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
(`cd out && A & B`: B runs in the starting folder). When the list holds a `{ }` group, a loop, an `if` or a
`case` with an inner `;` (`cd out && { A; } & B`), B is judged in the starting folder and, to be safe, in the
folder of the `cd` too; `--output` is read from the words before `--`, and a value that
`git` takes for another option is not told apart.

Write-guard lists. A write whose files come from a list (loop, `read`, `mapfile`/`readarray` array, array assignment,
assignment, `find -exec`, PowerShell pipeline) is refused unless the list names fixed folders. A Bash scalar
`X=$(...)` or an array `a=($(...))` (an assignment is recognized only as a command of its own, never inside `[[ ...
]]` or as an argument) is a list only when a substitution in it lists files. Its pipeline must start with a lister in
name mode and go on only with `head`, `tail`, `sort`, `uniq` or `grep`. The listers are `find`, `ls`, `fd`, `locate`;
`git ls-files` without `-s`/`--stage`; `grep`, `rg` and `git grep` with `-l`/`-L` (also in a cluster such as `-rl`),
`--files-with-matches`, `--files-without-match`, `--files` or `--name-only`; and `git diff
--name-only`/`--name-status`. A git list command is found behind any global option (`-C`, `-c`, `--git-dir`,
`--work-tree`, `--namespace`, `--exec-path`, `--config-env`, `--attr-source`, `--no-pager` ... are skipped before the
subcommand), in Bash and in PowerShell (`git -C . ls-files .act | ForEach-Object { Remove-Item $_ }` is a list that
names `.act`). The folders it names count as shown only when every option in front of it is one that changes neither
the folder nor what is printed nor how the operands match: `-C .`, `-C ./`, `--no-pager`, `-P`, `--attr-source <tree>`
and `--attr-source=<tree>`, each word matched on its own; behind any other (`-C sub`, `-c core.worktree=…`,
`--git-dir`, `--work-tree`, `--*-pathspecs`, `--namespace` ...) the list is not shown and the write is refused, also
for `git rev-parse`, whose printed folder is read the same way. The command word is matched whole, so
`./find-version.sh` is no `find`. An `ls` whose
path operands are all name-only globs that cannot match `.act` (`f=$(ls -t *.log | head -1)`; no `/` or backslash,
`[!…]` counting as a match) lists names of the current folder and binds nothing, in a scalar and in an array
assignment; a `for` loop over such a substitution keeps its list. Anything else (`grep -m1 ... | cut`, `ls | wc -l`,
`git diff | sha256sum`, `basename "$f"`) prints text and binds nothing; so does a lister behind another first stage
(`cat x | grep -rl y .`, a limit). A `mapfile -C <callback>` runs per line like `find -exec`; a variable-only callback
is unknown. In PowerShell the literal destination of `MoveTo`/`CopyTo` and the destination and backup of an item's
`Replace` are write targets; `Open` is free only as mode `Open` plus access `Read`. A name-only wildcard that cannot
match `.act` (`gi *.log | Remove-Item`) is relieved only for a write on the item itself, never
`MoveTo`/`CopyTo`/`Replace`, and only when the command holds no location change (`location`, `cd`, `sl`, `chdir`,
`pushd`, `popd`), no `iex`, no `&` or `.` call operator (literal names too), no word ending `.ps1`, no
`[scriptblock]`, no `Invoke-Command`/`icm` and no `.Invoke(`. A write target unrelated to the item (`Move-Item $_ $d`)
is judged as anywhere else. Limits: a junction or link matched by name, compound assignment operators, symbolic-link
and handle calls, casts and typed variables, item objects built with `-ArgumentList (,'x')`; `[IO.File]::Copy`/`Move`
written `.Invoke(` is missed by the literal reader, not by the list reader.

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
be determined, too long to check in time (the text says "time budget used up") or whose check fails is refused (run
smaller calls), except a `branch` that
only lists and a `reset` without `--hard`. Switches: `git-reset-hard` and `git-discard`. The full table is `_TABLE`
in `git_discard.py`.

## `R-safe-git-metadata` — No writing of hooks, repository config or Claude settings

Checks: git-metadata-guard, protected-watch.

`git-metadata-guard` (switch `git-metadata-guard`) refuses a write to `.git/hooks/**` or `.git/config` (also
`config.worktree` and the git directories of submodules and linked worktrees), also by copying into them, with a file
tool, a shell command, or `git config`, `git -c` or `GIT_CONFIG_KEY_<n>` for a key that starts a program
(`core.hooksPath`, `core.fsmonitor`, `core.sshCommand`, a `!` alias, a filter, textconv or credential helper, an
`ext::` remote URL …; the full list is in `git_metadata_guard.py`); `git init --template` too. A worker also never
writes `.claude/settings*.json`, `.claude/agents`, `.claude/skills`, `.claude/commands`, the Copilot role files
`.github/agents/**` of the project (only that folder; there is no home counterpart), `.vscode/tasks.json`,
`.devcontainer/**`, `.devcontainer.json`, `.envrc` or `.mcp.json`; nobody adds a `folderOpen` task to
`.vscode/tasks.json` or a `*.code-workspace` with a file tool, or writes `.vscode/tasks.json` with a shell command; the
human writes such a file themselves.

The body of a quoted heredoc is read as commands (a line `cp x .git/hooks/p` is a copy) unless the whole command only
stores it as text; `cat > <note>` into a plain relative `.md`, `.txt`, `.json`, `.log` or `.csv` file outside every
protected place counts as storing even behind a `mkdir -p <paths> &&` or before further commands, as long as those do
not name or glob that file (they stay read as commands). A copy source is read from disk for at most 4 s; one that
cannot be read in that time refuses the call and names the source, since a copy whose landing places are unknown is
not let through. Text for a note or another file is better written with the Write tool than with a heredoc.

Limits. The checks read the text of a call and run nothing: what a program or script file writes itself
(`pre-commit install`, `python script.py`) is invisible; a Python program handed to `python` (`-c`, heredoc,
here-string) is read for literal paths and literal command lines, not for computed ones (a variable, an f-string).
Code that becomes a script only when the command runs (`bash <<< '…'`, `source /dev/stdin`, `[scriptblock]::Create`)
is not followed, and a target that depends on an earlier command is judged on what the text says — for every shell
check that reads write targets. An unquoted `$(…)` or `@(…)` in a call (`git -C $(pwd) commit`) is one word of that
call with the words glued to it, a value no check can determine, and the commands inside it are read as commands of
their own, in front of the call for `secret-scan` (a `cd` inside moves no directory outside it), behind it for the
other checks; without a closing `)`, or with a `case` block inside that has no `esac`, the call is cut at the `$` as
before. The checks are a guard rail against mistakes, not a wall against intent.

### The watcher after every call: `protected-watch`

Because the guard cannot see a script file, `protected-watch` compares the protected files with a snapshot (taken at
session start, kept under `.act-local/protected-watch/`) after every tool call of the orchestrator and of workers:
`.git/hooks/**` and `.git/config` (only the keys that start code) of the repository and its linked git directories,
`.claude/settings*.json`, `.claude/agents/**`, `.claude/skills/**`, `.claude/commands/**`, `.github/agents/**`, and
`.mcp.json`, `.envrc`, `.devcontainer.json`, `.devcontainer/**`, `.vscode/tasks.json` at the project root. It never follows a link.
`.act-lock.json` is watched on two keys only, `packages` and `package_copies` (what the installed packages are and what
they copied); the rest of the lock is never touched. A worker's change of those keys is put back, the orchestrator's is
reported with the way to restore the previous state, and a lock that cannot be read is skipped.

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
  changed through its source (`.act/skills/`, `docs/ai/local/skills/`) is not reported, the source is versioned. The
  same exception covers the copies the active packages make (skill and role files under `.claude/`): the orchestrator's
  call passes one only when its bytes equal what the lock and the package folders give, worked out afresh and never
  from a note some script left behind; a deleted file is passed only where the packages give none. A worker gets no
  such exception: its change of a package copy is put back like any other.

Limits: it reports after the call and prevents nothing. A change made between two calls by someone else (the human,
Claude Code, another session) is attributed to the next call; a worker's change first seen in the orchestrator's call
is reported as the orchestrator's and not put back. A write that leaves size and modification time unchanged is not
seen; a file over 2 MB cannot be restored; at most 4000 files are listed. `~/.claude`, `*.code-workspace` files and a
`.git` file above the project root are not watched. A git directory first seen in a snapshot taken during a worker's
call and not below the project root in fact is reported, not restored. Nothing runs where hooks do not run. The
remaining limits and the rules for links are in the header of `protected_watch.py`.

## `R-role-worker` — Git and scripts of a worker

Checks: worker-git-write, worker-run-watch.

`worker-git-write` (`block` default, `warn`, `off`) refuses a worker's git command that changes the tree or history:
`commit`, `add`, `stash` (but `stash list` / `stash show`), `checkout`, `switch`, `reset`, `restore`, `merge`, `rebase`,
`clean`, `push`, `pull`, `cherry-pick`, `revert`, `am`, `apply`, `rm`, `mv`, `init`, `branch` (but listing), and the
forms that change refs and configuration: `update-ref` in every form, `symbolic-ref` with two names, `-d` or `-m`, `tag`
that creates, changes or deletes a tag (a name without `-l`/`--list`/`-v`/`--verify`, `-d`, `-a`, `-s`, `-u`, `-f`, `-m`,
`-F`, `-e`, `--create-reflog`) and `config` that writes (`--add`, `--unset`, `--unset-all`, `--replace-all`,
`--rename-section`, `--remove-section`, `-e`, the new syntax `set`, `unset`, `rename-section`, `remove-section`, `edit`,
or a key with a value). Reading stays free: `symbolic-ref <name>`, `tag`, `tag -l`, `tag -v`, `config <key>`, `--get*`,
`--list`, `config get`. Git run against a folder outside the project (`git -C <folder>`, a leading `cd <folder>`) is
exempt (a `-C` after a leading `cd` counts from the folder of that `cd`, inside the project too, so
`cd src && git -C .. commit` is refused; a `-C` that leads back into the project, or cannot be resolved, ends the
exemption, and so does a `-C` chain without an absolute value when the folder the call runs in is not determinable: a leading `cd` to a
variable, a substitution, a leading `~` or with no operand, a later `cd`, `Set-Location`, `Push-Location` or
`Pop-Location`, a group such as `(cd $X) && git …`, or a `cd` inside the text of `pwsh -c '…'`, `powershell -Command
"…"` or `bash -c '…'`, which counts like a later `cd`). A `-C` chain with an absolute value does not depend on that
folder: it is decided from the last absolute `-C` on, whatever literal value came before it and wherever the call runs,
and is free only when it ends outside the project (`cd $X && git -C sub -C <absolute folder outside> commit` is free,
`git -C <absolute folder outside> -C ../project commit` is refused); a variable or a substitution before the last
absolute `-C` (`git -C $D -C <absolute folder outside> commit`) takes that away and the call is refused. Two limits
stay on purpose. A directory change that is not
determinable counts also behind the git call (`git -C ../x commit -m y && cd src` is refused): a loop may run the `cd`
before the next git call, and the check knows no loops; a `-C` chain with an absolute value keeps the exemption there. And `/tmp/x`
as a `-C` value is no absolute path on Windows, where it names a folder of the current drive and not the system temp:
behind such a directory change it counts as relative and is refused (without one it counts from the working folder and
stays free); throwaway material belongs under `.act-local/tmp/`. A `config` write with `--global`, `--system` or
`--file` is refused there too: it writes the user's, the machine's or a named file, not that repository, and so is
`update-git-for-windows` in every form (it replaces the Git installation of the machine, also with `-C`, a leading `cd`
or as the program `git-update-git-for-windows`).

It also refuses the typed writing forms of further commands. Refused in every form, because they have no reading form:
`gc`, `repack`, `pack-refs`, `maintenance`, `filter-branch`, `fast-import`, `update-index`, `read-tree`, `write-tree`,
`commit-tree`, `mktag`, `mktree`, `checkout-index`, `receive-pack`, `index-pack`, `unpack-objects` (also with `-n`) and
`http-fetch` (they write objects, an index file or a ref); `upload-pack` only reads and stays free. Refused except for
the reading forms named here (any other form is a write): `notes` (free: bare, `list`, `show`, `get-ref`), `replace`
(bare, `-l`/`--list`, `--format`), `worktree` (`list`), `remote` (bare, `-v`, `show`, `get-url`, and `prune` with
`-n`/`--dry-run`), `reflog` (every form except `expire`, `delete`, `drop` and `write`; `expire` and `delete` are free
as a dry run), `prune` (only as a dry run), `hash-object` (only without `-w`; in a bundle `-wt` sets it, `-tw` is the
type `w`), `history` (bare, `-h`, or a form with `--dry-run`; it has no `-n`), `sparse-checkout` (`list`), `bisect`
(bare, `log`, `visualize`/`view`, `terms`, `help`), `rerere` (`status`, `diff`, `remaining`). `apply` is free when it
only analyses a patch: one of `--check`, `--stat`, `--numstat` or `--summary`, and every other word is
`-v`/`--verbose`, `-q`/`--quiet`, `-z`, `-R`/`--reverse`, `--recount`, `--allow-empty`, `--unidiff-zero`, `--index`,
`--cached`, `--ignore-whitespace`, `--ignore-space-change`, `--whitespace=<action>` (`nowarn`, `warn`, `fix`, `error`
or `error-all`, glued with `=`; a separate value is refused like `-p 1`), `-p<n>`, `-C<n>`, `--include=`, `--exclude=`,
`--directory=`, `-` or a patch file; `--apply`, `--reject`, `--build-fake-ancestor`, `--3way`, any `--no-…` word or an
abbreviation keeps it refused. `git apply -h` with no other word prints the usage and is free; a bare `apply` is not.
A dry run is a word exactly `-n` or `--dry-run` before any `--` or `--end-of-options`, with no word that starts with
`--no-` (git reads `--no-dry-run` as the write); an abbreviation such as `--dry` is refused, and so is a `-n` that is
the value of `--expire`. Options before the subcommand (`git notes --ref=x add`, `git -C <folder> …`,
`git --attr-source <tree> …`) are skipped when the subcommand is found; `--attr-source` takes the next word as its
value, so `git --attr-source commit status` is a `status`. The commands that work with a remote are refused too:
`fetch`, `clone`, `backfill`, `fetch-pack` and `send-pack` in every form (the orchestrator provides a remote's state),
`submodule` except bare, `status` and `summary` (`submodule--helper`, git's internal helper, in every form), and `lfs`
except `ls-files`, `status`, `env`, `version` and `locks` as the very first word after `lfs` (a bare `git lfs` and an
option before the subcommand, `git lfs -X ls-files pull`, are refused); every program `git-<name>` (also with `.exe`,
a directory in front, in any case, and in PowerShell wherever a command can stand, read the way PowerShell reads it
(see the end of this section): `.\git-lfs.exe`, `& ..\bin\git-lfs.exe`, behind a variable assignment or the dot operator
(`. .\git-lfs.exe pull`), inside a script block (`ForEach-Object { .\git-lfs.exe pull }`) or a group `( )`, behind
`cmd /c`) is judged exactly like `git <name>`, without global options: `git-lfs pull` is `git lfs pull`, `git-commit -m x` is `git commit -m x`,
`git-receive-pack` is `git receive-pack`, and a `-C` after it is that command's own option, not a folder; programs
that name no write subcommand (`git-credential-manager`, `git-askpass`, `git-upload-pack`) stay free.
`update-git-for-windows` (as `git update-git-for-windows` or `git-update-git-for-windows`) is refused in every form, a
folder outside the project included, because it changes the Git installation of the machine and no repository.
The exemption for a folder outside the project
does not cover a `clone` or `init` whose target folder or `--separate-git-dir` value, resolved against the `-C`/`cd`
folder, lies inside the project or holds a variable or a leading `~`; without a target (the folder comes from the URL,
a bare `init`) it stays. The same holds for `worktree add`, `move` and `remove`: every path word (for `add`
only the first positional, not the commit-ish behind it, and without the values of `-b`, `-B` and `--reason`) is
resolved the same way; `worktree lock`, `unlock` and `prune` stay exempt. Two more cases refuse there. git reads the
`<worktree>` word of `remove` and the first word of `move` (`git worktree remove <worktree>`, `move <worktree>
<new-path>`; the second word of `move` is a path) also as the last path components
of any worktree of the repository (`ghi` names `/abc/def/ghi`), so a bare relative word may reach a worktree inside
the project: those words keep the exemption only when they are absolute or start with `./` or `../` (in PowerShell also
`.\` and `..\`, which that reading keeps; in Bash a backslash form is no anchor, since the shell consumes the backslash,
so write `./`) and lead outside the project; `.` and `..` alone
and every other relative word are refused. And every `worktree repair` is refused there, with or without a path: besides
the paths named it repairs the `.git` file of every linked worktree, wherever it lies (a probe in a repository of its own
rewrote the broken file of a third worktree when run for another one), so it also writes into a worktree inside the
project. `lock`, `unlock`, `prune` and `list` keep the rules above. The check reads the words typed: an alias
from the repository's or the user's git configuration (`alias.zz = commit`, then `git zz`) is invisible to it, as is a
variable that expands to an option, and a dynamic word (`$(…)`, a variable) where the subcommand stands hides the
subcommand behind it (`git $(…) commit` passes: the check refuses only what the text shows); only a `-c alias.<name>=…`
on the call itself is refused.

Git in a PowerShell call is read with PowerShell's own reader, not the Bash one, by every check that looks at a git
call (`worker-git-write`, `git-discard`, `git-metadata-guard`, `commit-pathspec`, `commit-hashes`, the board refresh): a
backslash stays in a word (`git -C ..\proj commit` names the folder `..\proj`, and `Set-Location ..\proj` is followed
the same way), a backtick at the end of a line continues the command and a backtick in a word escapes one character
(``..\p`roj`` is `..\proj`), `--%` is not handed to git and the words behind it are still cut at `;` and `|` (stricter
than PowerShell), `&` and the dot operator in front of a command are taken off, and a call counts wherever a command
can stand: at the start, behind `;`, `|`, `&&`, `||`, behind a variable assignment, after `{`, `(`, `$(` and `@(` (a
group that holds git leaves one dynamic word in the call around it, so `git -C $(Get-Location) commit` is refused like
any folder that cannot be resolved), and inside the double-quoted text `"$(git commit)"`. `cmd /c`, `cmd /k` and
`cmd /r` (also `cmd.exe`, any spelling) hand the words behind them on as a call, a single text behind them read as
PowerShell; `Invoke-Expression`/`iex` read their text the same way; `bash -c '…'` and `find -exec` keep their reading.
Besides this, every git call the Bash reader finds is kept (a string piped into `powershell -` or `iex`, which the
PowerShell reading does not read), unless a PowerShell call is the same call: the words are compared with every
backslash and backtick taken off, and a PowerShell call stands for one Bash call only. So a call the Bash reader saw
is never lost, and one that both readers see is read as PowerShell reads it. A line that does not tokenize is read by
the Bash reader alone. Unchanged: a dynamic word in place of the
subcommand, and `deps-scan`, `secret-scan` and `danger-scan`, which read a PowerShell call as Bash.

Git behind `wsl` (`wsl`/`wsl.exe`, any case, a path in front; Bash and PowerShell) is read by the same checks as a git
call of its own: `wsl git commit -m x`, `wsl -d Ubuntu -- git …`, `wsl "git commit -m x"`, `wsl bash -c "git commit -m
x"`, `wsl --exec git …`. The options are the ones the outside-root and write checks read (`-d`/`--distribution`,
`-u`/`--user`, `--cd`, `--shell-type` with a value, `-e`/`--exec`, `--system`, `--` ends them); a management command
(`wsl --list`, `-l -v`, `--shutdown`) or no word behind the options is no call. Without `--exec` wsl hands the words,
joined with blanks, to the distribution's shell, so the line is read anew like the text of an `eval` (one nesting
level), in Bash rules also for a PowerShell call: `\` is an escape there, `wsl git -C ..\x commit` names `..x`, a folder
inside the project. A word that holds a blank is read once more as the one word it was, so `wsl bash -c "git commit -m
x"` is seen as that commit. With `--exec` the words are the call as they stand. In the git words `/mnt/<x>/…` is the
drive `<X>:` (on Windows). The wsl words stand in the prefix of the git call. `worker-git-write` never exempts a call
whose prefix holds `wsl --cd <dir>` or `env -C`/`--chdir <dir>`: the folder it runs in is not followed (`git -C
<literal folder>` is the way); the `--cd` folder never holds for a command after the wsl call. `git-discard` refuses
a `reset --hard` or `clean` behind `wsl --cd <dir>` as not determinable, like `env -C`, and a `cd`, `pushd` or `chdir` inside
the wsl line counts as `--cd` for the git calls of that line. Limits: `git-<name>` behind `wsl` is not read; only the readers of a git call look into a wsl line; every other check reads it as before (`outside-root` and
`write-guard` read it themselves, `secret-scan`, `danger-scan` and `deps-scan` do not follow it).

`worker-run-watch` (`warn` default, `off` skips it, `block` counts as `warn`; it never refuses and never resets)
reports what a worker's script or program changed, because the other checks read the text of a call and cannot see what
a program does. A call is watched when a worker runs an interpreter with a script file or a module (`python x.py`,
`py -3 x.py`, `python -m <module>`, `node x.js`, `node --test`, `bash x.sh`, `pwsh -File x.ps1`; behind `uv run`,
`poetry run`, `pipenv run`, `pdm run`, `hatch run` or `conda run` the wrapped command counts), a path run directly
(`./x.sh`, `./gradlew`, `.\x.ps1`, `& .\x.ps1`), or inline code that starts a process (Python `subprocess`/`os.system`,
Node `child_process`). `python --version`, `python -c "print(1)"`, `py -0p`, `bash -n x.sh`, `source .venv/bin/activate`,
`git status` and `ls` are not watched and cost nothing. Before such a call it
takes a snapshot of the project's repository and of the repositories named by the worker's `Write scope:` outside the
project (at most 3): HEAD, every ref, and the changed paths with size and modification time
(`.act-local/worker-run-watch/`). After the call, a failed one too, it compares, and the worker gets a note headed
`worker-run-watch:` among its next notes when it finds a `new commit` (HEAD's branch unchanged, the new id on top of
the old one), a `ref changed` (a switch of HEAD's branch, a branch added, moved elsewhere or removed, a tag) or a file
`outside every running worker's Write scope` (paths under `.act-local/` and paths that match the `Write scope:` of any
running worker are left out). The orchestrator gets the same facts with the worker's id and, for a `new commit` in the
project repository, the way back (`git reset --soft <old id>` after looking at what the commit holds); for a `ref
changed` it gets the old targets and ids and no such command. The incident log gets identifiers only. The worker must
not undo a commit or ref change itself and names it in its result. Time: the git calls of one event, and the loops that
read the changed paths, share 3 s and never more than the hook has left; a time-out, a git error or a call whose
snapshot is missing is reported as `comparison not possible` with the reason, never passed silently.

Limits: paths ignored by git and paths under `.act-local/` are not seen; a background process that writes after the
call has ended is not seen; a program outside the selection (an unknown binary, `npm run`, `make`) is not watched;
when another worker runs, or the main session wrote meanwhile, the note says `author uncertain`, but a main-session
call that starts before the snapshot and ends after the comparison is not counted for it; staging inside a scope is not
reported; a call that a package check refuses after this check leaves a snapshot, pruned after 24 h; a project inside a
larger repository is compared as that repository; at most 2000 changed paths and 5000 refs are compared (more: the part
says so once per session and repository, the rest still runs).

## `R-work-throwaway` — Throwaway material under `.act-local/tmp/`

Checks: act-local-tidy, throwaway-place.

Throwaway material (probes, scratch projects, clones, output files) goes into `.act-local/tmp/<task-id>-<slug>/`, never
into the system temp directory and never directly under `.act-local/`. Work with no task (a skill run, a doctor
report, feedback intake) takes `.act-local/tmp/<YYYYMMDD>-<slug>/` (date in digits, no hyphens); `act-local-tidy`
clears it after 7 days like any entry whose name does not start with an open task's id. The orchestrator removes a task's folders when
it commits the task (`python .act/scripts/act_local_tidy.py --task <id>`); whoever made a folder removes it earlier.
Git run in a subfolder that is not a repository of its own acts on the project's repository: set
`GIT_CEILING_DIRECTORIES` to the throwaway folder (`.act-local/tmp/<name>`), or call git only on a repository of its
own; a worker's git probe follows `R-role-worker` (`git init` first, stop unless `git rev-parse --show-toplevel`
names the throwaway folder). A deny entry on Windows can
lock out the owner too (`(RX)` also denies `READ_CONTROL`): deny only the one right the probe needs, such as `(RD)`,
and run `icacls <path> /reset` in the `finally`. A throwaway project below `.act-local/tmp/` carries a `.act/` of its own;
the template's `.act/` write-guard lets a write into it pass (conditions in `write_guard.py`); a `shutil.rmtree` of the
project root or of a folder that holds it is refused. Limit: a relative
`.act/` target after `cd $VAR/...` (a variable, `P=<dir> cd $P/x` too) is judged against the project root and
refused (the verdict is the same as for the project's own `.act/`), with the message that says its folder is not
known, because the scan yields that target with no known folder as well; `cd <literal folder> && cp ...
.act/...` into such a project passes, so write the folder out.

`template-write-guard` also protects the project's own `.act-local/packages/` (the packages the lock records, resting
folders, staging): a write there is refused, naming `python .act/scripts/packages.py` (fetch, add, remove) as the way;
`packages.py` itself is no write the guard sees. It refuses moving, renaming or removing `.act-local` itself, the
folder that holds `packages/`, in the same way (a `mv`, `Rename-Item` or `Remove-Item` of it, a `rmdir`, a `mkdir`, a
redirect or the Write tool onto it; a recursive removal of it is refused by the guard before `recursive-delete` sees
it), and a mirroring copy into it (`rsync --delete*`, `robocopy /MIR` or `/PURGE`), which deletes what is there. A copy
INTO it passes this rule: `cp`, `cp -t`, `mv`, `install -t`, `rsync`, `robocopy`, `tar -C`, `unzip -d`, `Copy-Item`,
`Move-Item` and `Expand-Archive` with `.act-local` as the destination folder; `outside-root` and the other checks judge
it as before (a recursive copy into it is refused there, because of `outside-allow/`). Where the guard cannot tell the
destination from a removal (a wrapper such as `sudo`, `xargs` or `bash -c`, `cp -T`, inline code, a location change
before a PowerShell copy), it keeps refusing. Moves and writes inside `.act-local`, reads, a throwaway project's own
`.act-local` under `.act-local/tmp/` and `.act-local/packages-old/` stay free: only the project's own folder counts. A
list over `.act-local` is refused like one over the project root. Limit: a loop word naming the folder is not seen.

The write-guard reads shell names the same way: a target made of a name that the command assigns exactly once, as
a literal, before its first use (`f=.act/x && echo y > $f`, also `local`/`declare`/`export`/`readonly f=...`) is
judged only as the text with the value in place, in both directions: refused like the written-out path (the refusal
names the target as typed and the value it was read as), or passed like it (`T=.act-local/tmp/job/tpl; cp a
$T/.act/x`; any value counts, `T=.` refuses like `./.act/x`). A name assigned more than once, also with literals
only, assigned after its first use, or bound any other way stays unknown: its value can only refuse, and the raw
target is judged as it stands. A target naming `.act/` whose folder is not known is refused with a message of its
own that shows the two ways out: the path written out, or a variable set once to a literal before its first use.
Limit, for both checks: the assignment is read wherever it stands in the text, so one that bash does not run before
the write (inside `( … )`, a later pipeline stage, a branch that does not run, after `unset`, a heredoc body or
quoted string, `local` outside a function, a name only a child `bash -c` sees, a quoted `'$f'` target) can be taken
as the value; for the write-guard's pass direction such an assignment, an `unset` between the assignment and the
write, an assignment in a heredoc body or a quoted string, a function body that is never called, a name that is not
exported and is used inside the text of a child shell, and a rebinding the count does not see (`printf -v`,
`eval "…"`, `source`) are constructed commands, not accidental ones. A value with white space or a glob character
(`*`, `?`, `[`), and the names `PWD` and `OLDPWD` (bash resets them on `cd`), never count as written out: such a
target is judged as before, the value only refusing.

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
the value of a missing row, notes; `off` says nothing; `block` counts as `warn`) notes, and never refuses for, a hash in
a `git commit` that no repository knows. It reads the lines the commit adds to staged journal files
(`docs/ai/work/ledger/`) and the message as the command shows it: `-m`, a heredoc behind `-F -`, a literal `-F <file>`.
A hash is a word in backticks of 7 to 40 hex characters with a digit and a letter (`` `3e2901a` ``); a bare number, a
hex word without a digit and a word without backticks are not looked at. Each is looked up with
`git cat-file -e <hash>^{commit}` in this repository and in the repositories the row `commit-hashes-repos` lists
(comma-separated, relative to the project root or absolute; default `none`; a folder that is no repository is skipped),
because a journal can name commits of another repository. A hash none of them knows still counts as known when it
starts (any case) a template commit that `.act-lock.json` records, in the working tree, staged or in its history; a
template commit never recorded there is noted. The note names the unknown hashes and reaches the model with the call's
result. A worker's call is not looked at. Limits: a message file written in the same call, hashes inside a
program's own text and an ambiguous abbreviation (counts as unknown) are not handled; a missing git gives no note, and
a lookup that runs past about 4 seconds gives the line `[act] commit-hashes incomplete (time limit <n> s) …`, no refusal.
A crash of the check (an exception, not a hash that is unknown) refuses a `git commit` of the main session, by the
dispatcher, naming the check, the exception class, `commit-hashes: off` and `.act/scripts/doctor.py`.

## Packages — check modules, the source switch and the scan (no rule of its own)

A package installed with `packages.py add` (an entry in `.act-lock.json` § packages, its folder
`.act-local/packages/<id>/`; format: `.act/formats/package.md`) may bring PreToolUse check modules,
`hooks/checks/<module>.py` on its `pre-template/` or `post-template/` side. Claude Code only; the other tools have no
dispatcher.

- **Loading.** The dispatcher reads the files the lock lists, once, compares each file's hash with the lock's and
  compiles and runs exactly the bytes it hashed, as module `actpkg_<id>_<module>` (never importable as a template
  module). A folder without a lock entry, a package that only rests there, is never read. A package check module is
  code the owner installed and is trusted like `install.py`.
- **Interface and order.** A module defines `check_<module>(payload: dict) -> int` (0 allows, anything else refuses;
  the reason goes to stderr before a refusal, text on stdout is a note), the same as a template check; it gets a deep
  copy of the hook payload. Modules of `pre-template/` run before every template check, those of `post-template/` after
  them; the first refusal ends the call. A package check can only refuse or note. The template guards its verdict
  against the module's return value (a 0 overrules no template check) and against changes to the payload copy; it does
  not guard against what code can do: a module can end the process, replace another module or set the environment.
  The guarantee that comes before is the plan, the static scan and the signature of the package (`packages.py`, below).
- **Broken.** A module that is missing, differs from the lock, or whose package folder is gone is not loaded, and the
  calls it would have judged are not checked by it. One note per module, at the first call of each session, names the
  package, the module and the fix; on a refused call the note goes to stderr with the refusal. The fix is a command
  the owner types himself with the `!` prefix, which still runs while every tool call of the session is refused:
  `! python .act/scripts/packages.py remove <id>` (or `add <id>` again).
- **Crash.** An exception, a missing function or a return value that is no int refuses the call; the message names the
  package, the module and the exception class, never a value of the call or of the exception.
  A crash of the loader itself refuses every call the same way (the exception class only, an incident log entry).
  A lock that exists but cannot be read (a merge conflict, invalid JSON), or whose `packages` entry is no object, hides
  which packages are active: while `.act-local/packages/` holds a package folder (a folder whose name does not start with
  a dot) every call is refused, naming the folders and the fix the owner runs with `!`; with no package folder the call
  goes ahead with one note per session. A lock without a `packages` entry (or no lock) passes the loader and is never
  refused by it.
- **Time limit.** A module runs in a daemon thread with its own limit (2 s, never past the hook's budget); past it the
  call is refused with "timed out" and the dispatcher returns at once without waiting for the module. A package check
  that could not run is never a pass.
- **`packages-unverified`** (§ Packages, `block` default): what `packages.py add` does with a package that carries no
  valid signature of the template author. `block` refuses it, `scan` shows the findings of the static scan in red before
  it asks, `allow` asks with a warning only. A package with a valid signature of the template author passes in every
  mode; a signature that does not match is refused in every mode; the plan, the diff and the human's yes apply in every
  mode.
- **The static scan** (`python .act/scripts/package_scan.py <folder>`, exit 1 when it finds something) reads the folder
  and never runs anything in it. Each finding starts with `RED `: every `## disables` line, every `## checks` line weaker
  than the template's default (`off` < `warn` < `block`), every file under `scripts/` and `hooks/checks/`, an
  `install.py`, an `install.md` (an AI-guided setup will follow it), every MCP server (a `.mcp.json` or `mcp.json`,
  `mcpServers` in any file, `mcp add` in `install.md`, `install.py` or a script), a link and a file too large to read.
  A package's `## checks` lines set rows of § Checks in `docs/ai/config.md`, each marked in its Guards cell with the
  package and the value before; the owner's later change of a value is never undone by removing the package.

## `cd-git` — `cd` and `git` in one call (no rule of its own)

Claude Code asks the owner for approval each time for a Bash call that holds `cd` (or `pushd`) and `git`, in auto mode
too; `git -C <folder> <command>` with the folder written out does not. `cd-git` (switch in `docs/ai/config.md`
§ Checks; `block`, the default, refuses; `warn` names the way and lets the call pass; `off`) refuses such a call, for the
main session and for workers, and names `git -C <folder> …` in a call of its own as the way. It runs only when the
`tools` row holds `claude-code`; for another tool or a project without the row it does nothing. A `cd` into the folder
the call runs in (the project root, `cd .`, `cd sub/..`) does not count; a `cd` to a variable or substitution counts as a
`cd` elsewhere. Subshells and the text of `bash -c` are read. Limits: Bash calls only (not PowerShell), a `cd` or `git`
made inside a program is not seen. A crash of the check refuses the Bash call it was to look at, by the dispatcher,
naming the check, the exception class, `cd-git: off` and `.act/scripts/doctor.py`.

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
to the host (except the value of `-i`, which may also be `~/` and plain characters), options only from
`-4 -6 -a -C -n -q -T -t -v -x` (also combined), `-p <digits>`, `-l <name>`, `-i <file>` and `-o Key=Value` as
one word with one of the keys `StrictHostKeyChecking` (`yes|no|ask|accept-new|off`), `BatchMode`,
`IdentitiesOnly`, `PasswordAuthentication`, `PubkeyAuthentication`, `Compression` (`yes|no`),
`ConnectTimeout`, `ServerAliveInterval`, `ServerAliveCountMax`, `ConnectionAttempts`, `Port` (digits),
`LogLevel`, `User`, `UserKnownHostsFile` and `GlobalKnownHostsFile` (only `/dev/null`) or `IdentityFile` (as
`-i`), a `[user@]host` that is not this machine (`localhost` and its variants, any
`127/8` or `0/8` address in any spelling, the IPv6 loopback, `ip6-*`, this computer's own name), and a
first command word that begins with a plain character other than `-`. Every other form - every other `-o` key or value (`ProxyCommand`, `LocalCommand`, `Hostname`, the `Key Value`
form ...),
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
a value), and the path and revision words of `git log|diff|show|status|blame|ls-files|rev-parse|grep|diff-tree|diff-index|
diff-files|whatchanged|stash show` without `-o` or an option starting with `--ou`. So `$out = py .act/scripts/board.py` and `$log = git log -- .act/scripts` pass, while
`$x = python -m zipfile -e a.zip .act/`, `$x = git clone <url> .act/y`, `$x = git archive -o .act/x.zip HEAD`
and `$x = py x.py, '.act/x'` are judged as before. Any other right side (a cmdlet such as `Join-Path`, a
string, an expression, the call operator) is read as before.

The PowerShell reader cuts a command into words the way PowerShell does, as far as the text shows it: a `#` starts a
comment only at the start of a word (`a#b` is one word), a block comment `<# ... #>` is skipped (one that is never
closed counts like an open quote: the command cannot be told apart, and with `.act/` in its text it is refused), a
carriage return alone is a line break, and the typographic quotes (U+2018 to U+201E) open and close a string like
`'` and `"`; inside a string the quotes of the other kind are plain text. `${C:\dir\file} = value` (also `+=`, a glued
`=`, a type literal in front) writes the file on a drive of one letter and counts as a write to it; `$env:X`,
`${env:X}` and `$function:f` are no files. An alias that a statement defines (`Set-Alias`, `sal`, `New-Alias`,
`nal`, also with `-Name`/`-Value`) counts for the statements after it, behind `$x =` and `&` too, by one rule for
every name: a statement whose command word has been given an alias is read as written and once with each value the
name has had so far in the command (none is replaced; an alias of an alias is followed for each value). The text does
not show whether a definition takes effect (`-WhatIf`, `sl` and other read-only names, a name that exists, a definer
that another alias took over), so each reading counts, for the write targets, a script piped into a shell, inline
interpreter code, further definitions, directory moves (the directories the shell may be in are the union of what the
readings lead to) and the literal text piped on. What a command is refused for as written stays refused:
`Set-Alias Set-Content Get-Content; Set-Content .act/x y`, `Set-Alias git Get-Content -WhatIf; git rm .act/x`,
`New-Alias cd Get-Content; cd .act; Set-Content x y`, `Set-Alias cat Set-Content; New-Alias cat Get-Content; cat .act/x
y`; so is a call of the value (`Set-Alias cat Set-Content; cat .act/x y`, `Set-Alias git Set-Content; git .act/x y`),
while `Set-Alias ll Get-ChildItem; ll .act` and a call before the definition stay free. A large or branching set of
aliases ends in the scan's budget (the command is then the one target no check may place). `saps`, `start` and `icm`
are read like `Start-Process` and `Invoke-Command`. The program text behind a code flag of `perl` or `ruby` (`-e`,
`-ne` ...) is judged by its path-like pieces (those with a `/` or `\` or starting with `.`), each a possible target
like any other path, for `write-guard` and for `git-metadata-guard` alike: `ruby -e "File.write('.act/x','y')"` is
refused, `perl -ne "print" .act/hooks/a.py` is free, and so is a program that names no path; for
`git-metadata-guard`, `perl -e 'print ".git/config"'` is refused as well (the text is judged, not what the code does;
code glued to the flag, `perl -e'...'`, is not read). Limits: a drive made with `New-PSDrive` is not seen (a name with
its letter is read as that drive letter); an alias counts within the same command only, from the statement that
defines it on: an alias defined inside a script block, and a nested `pwsh -c` (it starts without the aliases of the
text around it) do not see it.

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
larger than the reader takes, 32 KB; it passes with a note "inline program over 32 KB not checked", once per call). Shown is: a string literal; `Path(...)`, `os.path.join(...)` (Node `path.join(...)`, read the way Node joins: a later
part with a leading `/` stays a part, on Windows `\` splits as well) of such parts; a name bound exactly once, by a plain assignment (Node `const NAME = "literal"`), to such a value and used
unchanged (not where the program calls `exec`, `eval`, `getattr`, `setattr`, `__import__` ... or stores an attribute on
a module); and the files of `<folder>.glob('<literal>')`, `.rglob(...)`, `glob.glob('<literal>')` with a literal folder
(the folder is judged; the worker scope allows it only where the scope covers all of it; a glob that can reach a
protected place below the folder - `.act/`, the git and Claude settings files, a worker's `docs/ai/` - is judged
there too). After the program's one `os.chdir('<literal>')`, a statement of the module body (no other `chdir`, no
`getattr` or `exec`, no write call inside a `def`, `lambda` or `class`), a relative path lies below that folder;
any other `chdir` leaves names unknown. The text of an `exec`/`eval` written out is read again.

The write calls are Python `open` (also `io.open`, `codecs.open`) with a writing mode or one that is not seen, `.open`
with a writing mode written out, `os.open`, `os.remove`, `unlink`, `rmdir`, `removedirs`, `mkdir`, `makedirs`,
`truncate`, `chmod`, `chown`, `utime`, `rename`, `replace`, `symlink`, `link`, `shutil.copy`, `copy2`, `copyfile`,
`copytree`, `move`, `rmtree`, `tarfile.open` and `zipfile.ZipFile` with a literal mode starting with `w`, `x` or
`a`, and the `Path` methods `write_text`, `write_bytes`, `touch`, `mkdir`, `unlink`, `rmdir`,
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
  string spanning lines, an unterminated quote) or after a `$'` the quote pass cannot place (in a comment
  with a quote, in arithmetic, in a `${...}` with an operator); a
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

A Python program larger than 32 KB is not read, is not refused and passes with a note to the model, once per call
(`inline program over 32 KB not checked`): what it writes is not judged. Node and PowerShell inline code have no such limit.

A shell target with a variable is unknown and passes, unless the same command assigns the name exactly once, as a
simple literal: `f=v`, `export|local|declare|typeset|readonly [-r -x -g] f=v`, or several names in one
assignment-only command (`f=a g=b; ...`; `f=server/x.ts && sed -i ... $f`, `d="out"; echo x > ${d}/y`). Then the
value is judged like any target. A name assigned more than once (also with literals only), a prefix assignment of a
command (`g=x cmd $g`), `read`/`mapfile`, a loop variable, `+=`, other flags (`declare -i`) and a non-literal value
keep the name unknown. So does a command substitution, a brace list of unknown quoting, a target behind a `cd` the scan cannot follow, a target
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

An entry stores the session of its start. A worker of an earlier session (its session ended, so the worker did
with it) no longer counts once its entry is older than 15 minutes and its transcript below the project's Claude Code
folder is missing or has not grown for 15 minutes (a transcript counts as grown no earlier than the entry's time). In
its first 15 minutes it always counts as running: its transcript appears seconds after the entry. A missing session
folder counts as ended only when that session's own transcript exists in the project folder. One whose transcript,
folder or `meta.json` cannot be read or parsed counts as running, and the refusal says so. An entry without a stored
session counts for three hours as before.

A start that names a `Write scope:` or `Tests:` line while `.act-local` is a link out of the project cannot record
it, so the scope would go unenforced: `worker-write-scope` and `worker-scope-overlap` refuse that start in `block`
mode (remove the link, or switch the row off for one run) and give one note line in `warn` mode.

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
