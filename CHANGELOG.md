<!-- act:template-changelog -->
# Changelog

Changes to the template itself. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html); the sections up to 2.1.0 keep the headings of their
release notes. A project set up from this template keeps its own
changelog: `init` removes this file (step 8, recognized by the marker on its first line, like the template's own
README), and `act-update` and `act-adopt` never bring it into a project.

## [Unreleased]

### Added

- `/act <name>` also finds a template skill without its `act-` prefix: `/act version` shows
  `act-version`. A skill whose name matches exactly still wins.
- `R-work-throwaway`: throwaway material — probes, throwaway projects, scratch files — goes into
  the system temp directory, or, where the tool refuses that to a worker, into
  `.act-local/tmp/<task-id>-<slug>/`, never directly under `.act-local/`. `act-commit` removes a
  task's folders after the commit (`act_local_tidy.py --task <id>`).
- Session-start check `act-local-tidy` keeps `.act-local/` small in every project: once a day, in
  a background process, it removes `tmp/` entries and unknown entries directly under
  `.act-local/` that are older than 7 days and whose name does not start with an open task's id,
  and all but the newest 5 backups of `update`. Entries the template's own scripts create are
  never removed. The next session start reports count, size and names. The first run in a project
  only reports what it would remove; removal starts the day after a session start has shown that
  report. Nothing is removed when `.act-local/` itself is a link. `act-local-keep` in
  `docs/ai/config.md` § Checks protects a project's own entries, `act-local-tidy: warn` only
  reports, `off` skips it. `python .act/scripts/act_local_tidy.py` lists what would go.
- `update` names in its summary what the next session start will remove from `.act-local/`.
- `update` follows a rule that moved to another rule file in an edited `docs/ai/rules.md`: its
  checkbox line moves, mark and reason unchanged, from the block of its old file to the block of
  its new one, so a rule switched off stays off. A rule whose new file the project does not import
  is only reported. An unedited `docs/ai/rules.md` is re-derived from the template as before.
- `init` and `update` keep IDEs from indexing `.act-local/`: an `excludeFolder` in a JetBrains
  `.idea/*.iml`, and `files.watcherExclude` in `.vscode/settings.json` where `.vscode/` exists.

### Changed

- Shorter core rules (`.act/rules/shared/00-core.md`): `R-work-override`, `R-work-language` and
  `R-role-worker` leave details that `.act/bridges/rules.md`, `topics/feedback.md` and the scaffold's
  own inbox entry already state. No rule and no obligation is removed, here and in the six rule files
  below; what moved stands on the topic pages.
- Shorter code rules (`shared/20-code.md`): `R-code-language` names `language-docs` for prose,
  `R-code-tools` and `R-code-version` drop their examples.
- Shorter role rules (`orchestrator/00-role.md`): the role table becomes one sentence on the special
  cases, and `R-role-outcome` leaves the threshold of the tier proposal to `act-doctor`. `act-commit`
  points to `R-role-worker` and `R-code-commit` for who commits.
- Shorter work rules (`orchestrator/10-work.md`): updating `config.md` moves from `R-work-record-now`
  to `R-work-config`, and `R-work-handover` names `act-handover` before `/clear` or a restart.
- Shorter human-facing rules (`orchestrator/20-human.md`): the threshold for a question mid-task
  stands only in `R-human-ask`; `R-human-chat` and `R-human-capture` drop style sentences and the
  hook's field list.
- Shorter cost rules (`orchestrator/30-cost.md`): the estimate basis, `-high`, the reason for 10–12
  units, the temp-directory exception and the brief-note details move to `topics/checks.md`, and
  `R-code-commit` points to the `reviewer` role and `act-commit` for `CONDITIONAL`. `topics/checks.md`
  also gains a section on what `secret-scan` looks for.
- Shorter safety rules (`shared/10-safety.md`): `R-safe-no-secret-diff` points to the `secret-scan`
  check instead of describing a hand check, the git rules name groups of commands instead of every
  form, and `R-safe-git-metadata` and `R-safe-dev-server` drop examples.
- `R-safe-no-secret-diff`, `R-safe-git-reset` and `R-safe-git-discard` move from `shared/10-safety.md`
  to the end of `orchestrator/30-cost.md`, next to `R-code-commit`: only the main session commits or
  changes the working tree, so workers no longer load them (about 1,600 characters less per worker).
  IDs, wording and the checks `secret-scan`, `git-reset-hard` and `git-discard` stay as they were.
- `act-version`, `act-export-settings` and `act-load-settings` start only when typed as a slash
  command (`disable-model-invocation: true`): their descriptions no longer take up room in every
  Claude Code session, and a request in plain words no longer starts them. Usage measured over a
  month showed no call of any of them; the tips name the slash command.
- `rules.py --imports` shows how much every always-loaded instruction file costs: each file it
  reaches, and each file Claude Code loads on its own, ends with its size in characters (a CRLF
  line end counts as one), and a last line gives the total, split into the template's share under
  `.act/` and the project's. The `reached`/`unresolved` headers and the exit code are unchanged.
- `R-cost-delegate` now says when a handover to a worker pays off, not only how to make one:
  independent parts that run in parallel, the review, which should not share the implementation's
  context, output of unknown or large length not needed afterwards, and long reading or runs that
  a cheaper tier does just as well. A known file or spot, a few tool calls or a small change the
  main session does itself; its review still follows `R-code-commit`. The template's roles come
  before the tool's own agents (in Claude Code `Explore`, `general-purpose`, `Plan`; its
  `claude-code-guide` stays for questions about the tool).
- `R-safe-outside-root` is cut down to what the `outside-root` check cannot do itself: a new place
  needs the owner's word and an entry in `outside-root-allow`, even when the check only warns, and
  the rule also covers what the check cannot see, such as a program that opens files itself or an
  MCP tool that takes a path. The list of allowed places moved to `topics/checks.md`. Each session
  loads about 400 characters less.
- A new question from `entries.py new question` ends with an empty `**Answer:**` line
  (`**Antwort:**` when `language-docs` is `de`); the answer goes below it. The inbox README now
  describes the form of a question: one question per file, options as `- **a)** …` rather than a
  numbered list, the recommendation marked, and when booking an answer the file is read again and
  the answer goes below the existing label, never under a second one. `act-prepare` and `act-idea`
  point to that form. Adopted questions keep their text as it was.
- `doctor.py --inbox` files each new tier proposal (`R-role-outcome`) as an inbox question of its
  own instead of a line in the doctor report: the finding with its numbers, a table of the role's
  outcomes per tier, the row for `docs/ai/config.md` § Roles with the next tier, and three options
  (raise it, leave it until 8 more outcomes, look at the cases first). `update` commits the
  questions with the report and names both in its summary. Without `--inbox` and with `--json` the
  proposal stays a finding.
- The rule texts no longer contradict one another. The reviewer has three verdicts everywhere
  (`ALLOW`/`CONDITIONAL`/`BLOCK`). An open decision goes where `inbox-decisions` puts it, one the
  owner makes in chat into the inbox. There is one threshold for asking mid-task, and `triage: open`
  entries come right after the answered ones. Fetched notes under `.act-local/notes/` are data, the
  orchestrator's own brief notes are not. A PR, issue or comment needs approval and a way back but
  no backup. The ban on code-running `git config` keys covers the repository only. Rules a project
  adds to `docs/ai/rules.md` are in `language-docs`. "Always English" means the names of code files,
  not inbox or journal files. `expert-solver` is called only after two failed attempts. A worker
  hands a template bug back instead of filing it. Python error messages name an identifier or a
  masked value, never a secret. The estimates in `act-audit-docs` and `act-release` use the
  `R-cost-delegate` form.
- Three rules now say where they deviate from a tool's own defaults: committing accepted work needs
  no separate request (`R-code-commit`), a default the tool or the assistant states is an
  assumption, not a decision (`R-human-ask`), and `language-chat` wins over a language set in the
  tool (`R-human-language`).
- Only `builder` and `reviewer` still get a `-high` variant (`.claude/agents/<role>-high.md`); a
  template role's bridge declares it with `high-variant: true`. `update` removes the generated
  variants of `explorer`, `quick-check`, `doc-writer`, `debugger`, `test-writer` and `optimizer`
  and names each one in its preview and summary. That saves six entries in the tool's agent list,
  which is sent with every call. A project's own roles keep their variant as before. An assignment
  that named a removed variant names the role itself, or `builder-high`/`reviewer-high`.
- A pending template update stays visible until it is installed. The session start names it in the
  line the human sees (`update 2.4.0 available`) and repeats the note to the assistant at every start,
  the board lists it under Status, and Claude Code's status line shows `update: 2.4.0` on the release
  channel or `update: <date>` on `latest` (the date of the newer commit where it can be read without
  the network, in `DD.MM.YYYY` when `language-docs` is `de`; otherwise its short hash). The note used
  to appear once, only in the assistant's context, and could get lost. Once the lock has moved on
  since the check (an update pulled from another checkout), the old finding is dropped and the next
  check runs at once. Every look at the source refreshes the note, not only the daily check:
  `update.py --versions` (what `act-version` runs), `--plan` and an update run record what they
  found, or clear the note when the project is up to date; `--channel`, `--source` and `--ref` aim
  a single run elsewhere and leave it alone. `act-update` answers a question about the installed
  or newest version with `update.py --versions`.

### Fixed

- On Windows, the board showed umlauts and other non-ASCII characters in the branch name and the
  last commit garbled (`ü` as `Ã¼`), and a commit subject with a character the Windows code page
  does not know made the last commit vanish from the board. Every script and hook of the template
  now reads the output of git and Semgrep as UTF-8, the board, the session start, the feedback
  numbers and the deep security scan included.
- A tier proposal the owner had already decided came back in the next doctor report of the same
  day. A proposal whose question is filed no longer returns, not even on the same day, until 8
  more outcomes are recorded.
- Workers no longer lose part of their rules once the project's rules outgrow six hook entries:
  Claude Code cuts every hook output above 10,000 characters down to a short preview, so the worker
  rules now go out over 12 `SubagentStart` entries instead of 6. If even 12 are not enough, the last
  entry names the files the worker has to read itself, and `rules.py --worker` and `act-doctor`
  warn which rule files to shorten. `act-update` replaces the old six entries and leaves your own
  hooks alone.
- The SQL checks of `security-check` no longer hold a commit for a query builder's tagged template
  literal, where every `${…}` is a bound parameter: ``sql`select … where code = ${code}` `` (Kysely,
  Drizzle, postgres.js, also `sql<T>` and `<name>.sql`), ``Prisma.sql`…` ``, ``$queryRaw`…` `` and
  ``$executeRaw`…` ``. A line with a raw helper (`sql.raw`, `sql.lit`, `sql.literal`, `sql.unsafe`,
  `Prisma.raw`, `$queryRawUnsafe`, a bare `raw(…)`, `sql.__dangerous__rawValue`) is still reported,
  and so are untagged template literals and real `+` concatenation.
- The SQL check of `security-check` no longer holds a commit for a fixed `DELETE … FROM` or
  `INSERT INTO` string without concatenation, such as `"DELETE FROM sessions WHERE expired = 1"` or a
  parameterized `"INSERT INTO t (a) VALUES (?)"`. These two now count as built by concatenation only
  when their line carries a quote and `+` (or `+=`), as far away and past a `;` as before. Python
  `%`-formatting, PHP's `.`, PHP string interpolation and a `+` continued on the next line were never
  covered for SELECT or UPDATE; for DELETE and INSERT they are no longer reported by accident either.
- `secret-scan` no longer holds a commit for the override hashes `doctor --accept` writes into
  `.act-lock.json`: a rule ID with a credential word in its name (`R-safe-no-secret-cli` …) next to a
  64-digit hex value read like a credential. Exempt is only that shape — a rule ID as key, exactly 64
  lowercase hex digits as value, nothing else on the line — and only in the lock file at the project
  root; a known token shape on the line is still caught.

### Security

- `worker-write-scope` reads inline interpreter code: a worker with a restricted `Write scope:` that
  runs `python`, `python3`, `py` or `node` with `-c`/`-e`, or with code from a heredoc, a here-string
  or a pipe, in Bash or PowerShell, is refused when the code holds a write call (`open(…, 'w')`, `write_text`, `shutil.copy`,
  `fs.writeFileSync` …) and a path written out that lies outside the scope, the system temp directory
  and its scratchpad. Workers had written files outside their scope this way, some right after the
  check refused the same write. Best effort: a script file, a path built at run time and writes through
  `subprocess` stay unseen (`topics/checks.md`).
- `R-role-worker`: a write a check refused is never made another way; the worker reports the refusal
  with its result.

## [2.3.0] - 2026-10-25

Reads and writes outside the project root are checked, updates follow either the newest release or the default
branch, worker runs are measured and start with far less rule text, ten new coding rule sets arrive, old archive
entries can be compacted, and the dependency scan no longer passes findings as a clean result on Windows. Projects
on v2.2.0 update with `act-update`.

### Upgrading from v2.2.0

- Run `act-update` (or `python .act/scripts/update.py`), then start a new session so the new hooks and role fields
  take effect. No new migration; the existing ones read headers more exactly.
- `update-channel` decides what the next `act-update` brings. A project without the key in `docs/ai/config.md`
  follows `release`, the newest stable release tag, and gets a one-time note; set `update-channel: latest` to keep
  following the default branch.
- The new check `outside-root` runs as `warn` in a project without the row in `docs/ai/config.md` § Checks; a
  one-time note at session start says how to switch it to `block` and where further allowed places go
  (`outside-root-allow`).
- The template's roles get `omitClaudeMd: true` and `.claude/settings.json` a `SubagentStart` hook. Claude Code
  before 2.1.271 ignores the field, so workers there get the rules twice until Claude Code is updated.

### Added

- **Commit secret scan: accepted false alarms in `docs/ai/local/secret-accepted.md`.** A line that cannot carry the
  `act:allow-secret` comment (for example a JSON script entry whose name looks like a credential) can be accepted as
  `- <path> <hash>: <reason>`; the hold message prints the finished entry. A changed line or another file is held
  again, and a missing, oversized or unreadable list accepts nothing.
- **Reads and writes outside the project root are checked.** The new check `outside-root` (rule
  `R-safe-outside-root`, `docs/ai/config.md` § Checks) refuses Read, Write, Edit, Grep, Glob and shell commands that
  name a path outside the project root, for the orchestrator and workers alike. Allowed without an entry: the folders
  in `permissions.additionalDirectories`, the system temp directory, Claude Code's own folder for the project
  (including `~/.claude/plans/`) and, read-only, `~/.claude/plugins/` and `~/.claude/skills/`.
  Further places go into the new row `outside-root-allow` (comma-separated paths, ` (read)` after a path for
  read-only). New projects start with `block`; an existing project without the row runs the check as `warn` and gets
  a one-time note at session start saying how to switch it to `block`. `ACT_OUTSIDE_ROOT=block|warn|off` overrides
  it for one run. `act-adopt` stays possible: the owner starts the first scan with the `!` prefix, which opens the
  target folder for 24 hours or until `--abort`, also past `--finish`; `--apply` only refreshes a valid marker. Limits: the shell check is best effort, and programs that open files themselves and MCP tools with a
  path are not checked.
- **Worker runs are measured.** When a worker ends, the usage counter reads its transcript and records duration,
  steps and tokens — `fresh` (input, cache writes, output) and `cache` (cache reads) — per role and tier in
  `.act-local/usage.json`, the newest 50 runs each. Numbers only; they are never sent with feedback.
  `usage.py --estimates` shows median and 80th percentile per role and tier with the date of the last measurement;
  `usage.py --backfill` reads a project's existing transcripts once, without counting anything twice. Claude Code only.
- **`docs/project/integrations.md` has a hand-written section** between `act:integrations-own` marks, for
  example for an MCP server of a service other than the repo host. `integrations.py check --write` keeps it and
  rewrites the rest; a begin mark without an end mark stops the command without writing.
- **Path-bound rules under `.claude/rules/` are visible and kept.** `rules.py --list` and `--validate` show
  Claude Code's `.claude/rules/*.md` files with their `paths:` patterns (block list, inline list with braces,
  scalar, trailing comments), warn about a pattern that matches no project file, and note a file without `paths:`
  that loads at every start. `act-adopt` proposes to keep such files instead of merging them, which would lose
  their binding. The `explorer` and `builder` roles note that a path-bound rule loads only once a matching file is
  read or written through a file tool.
- **Ten new coding rule sets:** PowerShell, Docker, CI (GitHub Actions, GitLab CI), Rust, C, C++, Kotlin, CSS (for
  projects without Tailwind), JavaScript (for projects without TypeScript) and React. Each holds what goes beyond
  general knowledge (typical agent mistakes, version-dependent rules, toolchain, tests). `init` switches them on
  from marker files (`Dockerfile`/Compose files, `*.ps1`, workflow files, `Cargo.toml`, a Kotlin Gradle build or
  version catalog, C and C++ sources, stylesheets without Tailwind, `package.json` with JavaScript sources,
  `react`/`next` dependencies); `init-notes` name detected languages that have no set yet (Flutter, Rails, Ruby,
  R, Laravel) with a pointer to `act-feedback`.
- **`act-update` lists new coding sets and groups in `docs/project/coding_rules.md`.** A set the template adds
  appears unchecked, a new group of a checked set appears checked; existing lines, boxes, reasons and own rules
  stay as they are. Before, the update only reported them. The scaffold says right after its introduction that a
  checked set is imported with `@`.
- **`docs/project/glossary.md` in every new project:** a place for the project's own terms, abbreviations and
  turns of phrase, listed in the docs index, checked by `act-audit-docs`, and not loaded every session. It is
  scaffold (`act:default`), so a non-English docs language lists it for translation.
- **`entries.py compact` merges old archive entries into monthly collections.** Archived entries older than a
  week, and journal entries, go into one file per kind and month (`Q-2026-09.md`, `ledger-2026-09.md` …) with
  one anchored section per entry; links in the project are rewritten to the anchors, the head names the commit
  that still holds the full text, `--plan` previews, a second run changes nothing. It refuses while a file to
  merge is uncommitted. `entries.py archive` records the archive date as `archived:`, and the next free id and
  the duplicate check also read collection files.
- **Update channel `release` or `latest`.** The key `update-channel` in `docs/ai/config.md` (or
  `update.py --channel`) chooses what `act-update` brings: `release`, the default, offers only the newest stable
  release tag and never moves a project that is already past it; `latest` follows the default branch. The
  session-start check follows the channel ("template release vX.Y.Z available"), `.act-lock.json` records
  `template.ref`, and a project without the key gets a one-time note. A source without release tags is followed
  at its tip with a note while the channel is the built-in default or `release` in `docs/ai/config.md` (which
  `init` writes); `--channel release` and an invalid value stop.
- **`/act-version` and `update.py --versions`** list the installed version, the channel, the source's releases
  and the tip of its default branch, and what `act-update` would take, without a clone.
- **`init` asks which update channel to follow** (`release` by default, or `latest`), accepts
  `--update-channel` (also through `act-adopt --apply`), writes it to `docs/ai/config.md` § Update, and notes when
  the template clone is already past the newest release. `act-doctor` reports a value other than `release` or
  `latest`. Existing projects keep their `config.md`; without the key they get the one-time note of `act-update`.
- **Archive compaction, part 2: `act-compact` and `compact_check.py`.** After `entries.py compact`, workers may
  shorten only text that is recognisably the assistant's (paragraphs with a bold label and the option list below
  them) and write a monthly topic overview `archive/YYYY-MM.md`. `compact_check.py` compares every section with
  the original in git: ids, hashes, versions, dates, paths, numbers and every line the human wrote, marked or
  not, must survive; a section deleted by hand is reported; `--restore` puts a section back in full length. The
  session start says once a day when compaction is due (`archive-compact: 30d 300`, `archive-shorten: on` in
  `docs/ai/config.md`).

### Changed

- **Estimates in minutes and `tkn`, never person-days.** `act-idea`, `act-prepare`, the task and backlog READMEs and
  `R-cost-delegate` ask for `~<n> min · ~<n> tkn fresh · ~<n> tkn cache` plus the assumption behind it, based on
  `usage.py --estimates` (runs per role times the median, up to the 80th percentile) where measurements exist.
- **A rule that keeps being violated is named as a candidate for a check.** `R-work-override` and `act-feedback`
  say so; the rule's text then shrinks to what the check does not cover. The known limits of the shell checks
  (`topics/safeguards.md`) now list writes from inside a program and the authorship of `feedback.py --direct`.
- **`act-adopt` says the tool copy stays the template's** until the next `act-update`.
- **The `git-metadata-guard` row in `docs/ai/config.md` § Checks names every file the check covers**
  (`.vscode/tasks.json`, `.devcontainer/**`, `.devcontainer.json`, `.envrc`, `.mcp.json`, `folderOpen` tasks).
- **`act-adopt` keeps a `.junie/guidelines.md` that only points to `AGENTS.md` or `CLAUDE.md`** instead of
  proposing to adopt it; Junie still gets no bridge.
- **The doctor's tier proposal is remembered.** `doctor.py --inbox` notes count and day in
  `.act-local/tier-proposals.json` and files the same proposal again only after at least 8 more outcomes for that
  role and tier; a second run on the same day keeps it in the open daily report.
- **`update` checks at the start that Git is 2.25 or newer** and stops with a message naming the version found,
  instead of failing at the commit after all files are written; `--plan` and `--no-commit` are not affected.
- **The `security-check: deps` offer at `init` covers pnpm projects.**
- **`R-human-text` names one exception:** `act-compact` may shorten the assistant's own text in the sections of
  an archive collection file; every line the human wrote stays verbatim.
- **Proposals under `docs/ai/proposals/` carry a frontmatter header** (`---` around `author`, `date`, `target`) like
  every other entry, including those written by the adoption content step, so they keep that form when archived.
  Older proposals with the plain header lines are still read.
- **Workers no longer load the orchestrator rules.** The template's roles carry `omitClaudeMd: true`, and a
  `SubagentStart` hook hands them the rest of what `CLAUDE.md` loads (shared rules, coding rules, your own rules,
  `CLAUDE.local.md`, the user-level `~/.claude/CLAUDE.md`) in up to six parts below Claude Code's 10,000-character
  limit — about 24k characters less in every worker start. `update` adds the field to existing template roles and
  their `-high` variants (your own roles and an explicit `omitClaudeMd: false` stay as they are) and the hook entries
  to `.claude/settings.json`. `rules.py --worker` shows the parts. Claude Code before 2.1.271 ignores the field, so
  workers there get the rules twice; details in `.act/rules/topics/worker-rules.md`.
- **The seven mechanically checked rules are shortened to what they forbid or require**
  (`R-safe-no-secret-read`, `R-safe-outside-root`, `R-safe-git-reset`, `R-safe-git-discard`, `R-safe-git-metadata`,
  `R-cost-delegate`, `R-cost-wait`): recognition details, limits, switches and the `Write scope:`/`Cap:` syntax moved
  word for word to the new `.act/rules/topics/checks.md`, about 4.3k characters less in every session and worker.
  The block messages of the write-scope, cap and scope-overlap checks name the syntax themselves and point there.

### Fixed

- **`act-release` keeps Markdown headings in the tag message.** The tag is created with `--cleanup=verbatim`,
  and the stored message is compared with the release notes before anything is pushed.
- **Feedback metrics count only the project's files.** `files` and `size_mb` come from `git ls-files -co
  --exclude-standard` in a git checkout, so a vendor, IDE or media folder that git ignores no longer inflates them.
- **Skills started by typing their slash command count in feedback usage.** Before, only skills the model invoked
  itself were counted; built-in and own commands stay out, as before.
- **The board no longer drops tasks silently.** Open tasks list the most recently worked task first, show the task
  id before the title, and end with `… +N more` when there are more than five; the session-start excerpt does the same.
- **The daily dependency scan skips lock files git ignores** and nested checkouts with their own `.git`. The
  session-start note groups findings per lock file, states the age of the scan, and drops a result once a scanned
  lock file has changed or disappeared.
- **The PowerShell write guard accepts the call operator with a literal program.** `& 'python3' .act/scripts/x.py …`
  or `& "C:\…\python.exe" … > <temp file>` is checked like a direct call. Variables, script blocks and `iex` after
  `&` stay refused, and `& 'pwsh' -Command …` is now scanned.
- **The shell scanner behind the write guards is fast on long `cd` chains.** 800 statements took 21 s before and
  take well under a second now; the targets it finds are unchanged.
- **The frontmatter migrations read headers exactly like the readers** (line breaks at LF only, a non-breaking
  space counts as whitespace), write each file through a temporary file and an atomic replace, skip symbolic
  links, and leave out `archive/legacy` whatever its letter case.
- **`init` in a clone with a detached HEAD commits the removal of the template's own files** (such as
  `CHANGELOG.md` and the `.github` community files) instead of leaving them as unstaged deletions; a file the
  user deleted before `init` stays out of the commit.
- **`init --target` run from a set-up project records the template, not the project.** Address and commit come
  as a pair from that project's `.act-lock.json`, so the new project's update source is the template and its
  first update no longer stops with a downgrade warning.
- **`init` commits a kept `.github/README.md` in the first commit** and names the other unmarked files under
  `.github/` that it left out; files the clone already tracks are not named.
- **A translated scaffold README is no longer reported as a hand change** by the one-inbox migration unless the
  scaffold itself changed since the project's last commit; this also holds for a project in a subfolder of a
  larger repository.
- **The SQL checks of `security-check` no longer hold commits for "update" or "select" in prose, URL paths or
  hyphenated words.** `sql-fstring` and `sql-concat` require a statement structure (`SELECT … FROM`, `INSERT
  INTO`/`VALUES`, `UPDATE … SET`, `DELETE … FROM`); aliases, placeholders, optimizer hints and statements split
  across concatenated literals are still caught.
- **A project's own coding set, or a local override of a template set, under `docs/ai/local/coding/` works.** It
  can be switched on in `docs/project/coding_rules.md`; the import names the file actually loaded (local before
  template), and `rules.py --validate` and the doctor accept it.
- **A hand-edited usage store with non-numeric outcome counts no longer breaks the doctor's tier check.**
- **Worker run measurement is sturdier.** Idle gaps over 30 minutes are left out, so a worker continued hours
  later no longer inflates its minutes; a damaged `usage.json` (wrong types, non-numeric counts) is reported per
  field instead of a traceback; roles with measured runs but no counted start no longer show as `0x`; `Tier:`
  values in backticks, bold or underscores are read as the bare tier.
- **The Nuxt coding set no longer breaks the typecheck on Nuxt 4 and later.** Path aliases go into
  `nuxt.config.ts` only, the root `tsconfig.json` holds just `references`; test files outside the generated
  contexts are added through Nuxt's TypeScript options (including `nitro.typescript.tsConfig` for the server)
  and proven with one deliberate type error per context.
- **The Tailwind coding set is version-bound for source detection:** `content` paths on v3, automatic detection
  with `@source` for additions from v4 on.
- **A pnpm project is scanned without osv-scanner.** The dependency scan falls back to `pnpm audit --json` for
  `pnpm-lock.yaml` (pnpm 9 or newer); an older or missing pnpm is reported as a missing tool as before, and
  output in an unexpected shape counts as a failed scan, never as a clean one. `act-deps` notes that
  accepted-finding ids differ between `npm audit` and osv-scanner or `pnpm audit`.
- **Bridges are no longer reported as modified with `core.autocrlf=true`.** The `.gitattributes` block marks
  `CLAUDE.md`, `AGENTS.md` and `docs/ai/rules.md` with `text eol=lf`. An update replaces the template's earlier
  `merge=ours` lines in place; a line of the project's own for the same file is kept and reported as a conflict.
  A project that had deleted one of the earlier lines gets it back in the new wording, as with any reworded line.
- **A skill copy is no longer stuck as "kept (edited locally)" because of line endings.** A lock hash taken over
  CRLF or LF matches the copy in either form, the lock records the hash over LF, and a really edited copy is
  still kept.
- **`update` reads file lists from git without path quoting,** so files with non-ASCII names are recognised and a
  deleted one reaches the update commit.
- **A Kotlin project no longer gets the Java set** unless it also has Java sources; Android layouts and
  multi-module builds are recognised.
- **The free-text `stack` value switches a set on only for a whole name** (`python3`, `Vue3`, `PHP8` count, `C#`
  and `objective-c` no longer switch on `c`); PostgreSQL, MySQL, SQLite and MariaDB switch on the SQL set.
- **The summary of the `.gitattributes`/`.gitignore` block names replaced lines** separately from added ones.
- **Copies recorded by `act-load-settings` and for own skills are hashed over their LF form,** like all other
  copies.
- **A read-only or narrowly scoped worker can use the system temp directory as documented.** A glob in the last
  path segment under the temp directory (`rm -f /tmp/x/*_ran`) and an extraction with `tar -C`, `--directory` or
  `unzip -d` into a literal temp folder pass the write-scope check, as long as every entry of that folder, hidden
  ones and links included, lies inside the temp directory; globs earlier in the path, `..`, leading-dot globs and
  variables stay refused.
- **A quoted here-doc for a program that is not a shell is no longer read as commands** when its opening line
  also holds `[`, `${`, a backtick or `((`; a body fed to a shell (`bash <<'EOF'`, `sh -s`, `| bash`) is still
  scanned. This also ends the recursive-delete false alarm on prose in such a body.

### Security

- **The dependency scan no longer passes findings as a clean result.** On Windows with a non-UTF-8 code page
  (cp1252), `security_scan.py` read the scanner's UTF-8 report in that code page; one unknown byte emptied the
  output, and a tool that exited 1 *because* it found something ended as "no known vulnerability found" with exit 0.
  Tool output is now read as UTF-8. A tool that exits with its findings code but leaves no readable report (for
  pip-audit, whose own fatal errors also exit 1, only a non-empty one) holds
  the commit, makes `security_scan.py --deps` exit 1 with an `UNREAD FINDINGS` line, and shows up in the
  session-start note and the report after a merge. Any other tool error prints "scan incomplete" instead of the
  clean line; a timeout or a tool that will not start still only notes, so a machine without network can commit.
- **`secret-scan` catches a literal fallback after an environment lookup in more spellings:** Laravel
  `env('X', 'v')`, keyword defaults (`default=`), `os.environ.pop`, `import.meta.env`, `Deno.env.get`, Ruby
  `ENV[...]` and `ENV.fetch`, Python string prefixes and triple quotes, nested defaults, and lookup chains of more
  than six names. An f-string that interpolates a value is not read as a literal.
- **`sql-fstring` also catches a template literal whose interpolation follows the SQL text.**
- **`git-metadata-guard` sees what a recursive copy brings along.** A copy whose source directory or glob holds
  a protected file (`cp -r payload/. .` with a `.vscode/tasks.json`, `.git/config` or `.claude/settings.json`
  below it, `cp payload/* .vscode/`, `Copy-Item -Recurse`) is refused; the files below the source (at most
  2,000) are mapped onto where they land and checked one by one.
- **Credentials in a template source URL are masked** in `update.py` output, plan, version list and fetch errors,
  also with an `@` in the password.

## [2.2.0] - 2026-10-20

Quick capture from the chat, entries with YAML frontmatter, a one-step archive that takes pasted images along, four
new safety checks and a shell scanner that reads bash the way bash does. Projects on v2.1.0 update with `act-update`.

### Upgrading from v2.1.0

- Run `act-update` (or `python .act/scripts/update.py`). Migration `003` moves the header of every inbox entry into
  YAML frontmatter, migration `004` does the same for tasks, backlog, journal and the archive under `docs/ai/work/`
  (`archive/legacy/` and every `README.md` stay as they are). Both rewrite each file once and leave it alone after.
- Updating now needs Git 2.25 or newer.
- Claude Code's `Artifact` tool is off after the update; `artifacts: on` in `docs/ai/config.md` keeps it.

### Added

- **Quick capture from chat** — a message that begins with `todo:`, `note:` or `idea:` (any letter case) is filed by
  the `UserPromptSubmit` hook without a model turn and never reaches the model, so it costs no tokens and does not
  interrupt a running task. `todo:` and `note:` become inbox entries marked `triage: open`; `idea:` becomes a new
  section at the end of your `docs/ai/concept/ideas-<identity>.md`, text unchanged. The assistant then processes
  each `triage: open` entry right after the answered inbox entries: it decides whom a todo is for (or turns it into
  a backlog entry), or replies below a note. The board and the session-start excerpt list such entries under
  "Answered — the assistant processes these", and an answered note waits under "Waiting for you". Switch with
  `quick-capture: on|off` in `docs/ai/config.md` (a missing key counts as `on`); new rule `R-human-capture` covers
  tools without the hook, where the assistant files the entry itself.

- **Coding rule set `nuxt5`** — rules for Nuxt 5 and its nightly channel on top of `nuxt`: versions and channel,
  modules, Nitro 3/h3 v2 server code, typed `$fetch` and route targets, Unhead 3, and the checks after every Nuxt
  update. `init` checks it when `package.json` names `nuxt` at major 5 (`^5.0.0`, `npm:nuxt-nightly@5x`) or the
  `stack` value says "Nuxt 5"; `nuxt.md` points an existing project to it.

- **New rule `R-safe-dev-server`** — a server the assistant starts for tests, a browser check or a screenshot runs on
  a port of its own, never on one of the project's default ports; the owner's running server may be reused, but is
  stopped, restarted or moved only after asking, and processes are never ended by name.

- **`act-teach`** — short Markdown lessons on a topic, ideally on the project's own code, with exercises and a
  learning record. New config key `teach-lessons: local | docs` (`.act-local/learn/` or versioned under `docs/learn/`,
  which `act-audit-docs` then covers).
- **Board excerpt at session start** — open tasks with their last state, waiting and answered inbox entries, about
  2,000 characters, so a bare "continue" works from it. New config key `board-at-start: on | off`.
- **New rule `R-code-checks-intact`** — a failing test, lint or type check is fixed in the code, never by deleting,
  skipping, loosening or silencing the check; a check that is itself wrong is changed as its own step.
- **Reviewer verdict `CONDITIONAL`** next to `ALLOW` and `BLOCK`: committed with its one condition filed in the inbox;
  a known bug is always `BLOCK`.
- **Four new safety checks:** `secret-read` (no secret file such as `.env`, private keys or cloud credentials read
  into the context; `.env.example` and `*.pub` stay free), `git-metadata-guard` (no write to `.git/hooks`,
  `.git/config` or a git config key that runs code; workers also not to `.claude/` settings, roles and skills),
  `git-discard` (no `git clean -f`, folder checkout/restore over changes, `stash drop/clear`, force push to the default
  branch or `branch -D` of an unmerged branch), `worker-scope-overlap` (no worker start whose `Write scope:` overlaps a
  running worker's). `R-cost-delegate` gains `Depends on:` and a shared read note for several workers.
- **Learning step** — `act-bug`, `act-perf` and `act-refactor` end by asking whether the finished code carries what
  was learned; if not, a short note goes under `docs/project/learnings/`, which `act-prepare` and `act-bug` read first.
  `act-commit` asks the same after two or more rework rounds.
- `context_size.py --report` (and `--json`): base load of the first call, cache hit rate and cache breaks, read from
  the transcript.
- `doctor.py` checks skill and role frontmatter (YAML pitfalls, required fields, name vs. folder, known values) and
  reports an expired or invalid `revisit:` date under a decision.
- `act-audit-docs` can run as a Claude Code workflow script (one explorer and one doc-writer per doc area, in
  parallel), only on explicit request.
- Feedback: the project id is created with the first payload, so a direct message is never anonymous;
  `--direct --contact <email>` adds an optional reply address.
- This `CHANGELOG.md`, filled back to `0.1.0-beta` from the release notes. `init` removes it from a new project in
  step 8 like the template's own README; an edited copy is kept with an inbox note.
- Community files for the template's GitHub repository under `.github/`: code of conduct, contributing guide,
  security policy, an accessibility statement (every environment "not tested", known barriers listed), issue forms
  and a pull request template. They recommend `/act-feedback` as the first way to report a problem.
- **`entries.py archive <id|file>`** archives a finished task, backlog item or inbox entry to
  `docs/ai/work/archive/` in one step; an inbox entry gets `status: done`. Images and other files it links beside
  itself (a pasted `img.png`, `image (1).png` …) move along: generic or already taken names get the entry id in front
  (`Q<n>-img.png`), links are rewritten, and a file another Markdown file under `docs/` still links is copied instead
  of moved. Everything is planned before the first write, so a failure leaves nothing half-done. `act-commit`,
  `act-idea`, the chat rule and the inbox and concept READMEs point to it.
- `doctor` reports files under `docs/ai/inbox/` and `docs/ai/concept/` that no Markdown file under `docs/` links
  (kind `orphan-file`), such as a pasted picture left behind when its entry was archived by hand.

### Changed

- **Entries open with YAML frontmatter** — the header fields of every inbox entry, task, backlog item and journal
  entry (`id`, `kind`, `for`, `status`, `created` …) now stand between two `---` lines, so GitHub, GitLab and Markdown
  editors show them as metadata instead of running them together into one paragraph. `entries.py`, quick capture and
  the reports of `doctor --inbox` and `act-adopt` write the new form; every reader accepts both forms, so hand-written
  entries in the old form keep working. `act-update` rewrites the existing entries once: migration
  `003-inbox-frontmatter` the inbox, migration `004-work-frontmatter` the tasks, backlog, journal and the archive under
  `docs/ai/work/` (archived inbox entries included). `docs/ai/work/archive/legacy/` and every `README.md` stay as they
  are.

- **Claude Code's `Artifact` tool is switched off by default** to save about 13,700 tokens at every session start.
  New config key `artifacts: on | off` (default `off`): `off` sets `"enableArtifact": false` in
  `.claude/settings.json` at session start, `init` and `update`; the tool is gone from the next session on. Existing
  projects lose it after their next update — `artifacts: on` in `docs/ai/config.md` keeps it. `on` only removes an
  entry the template set itself; a value the project set itself is never overwritten, a contradicting one is reported
  once.
- **Feedback to the template author defaults to `confirm` in new projects** instead of `off`: `init` writes
  `feedback: confirm` whenever nobody chooses — a run without a terminal (as `act-setup` and `act-adopt` run it), an
  empty answer, or three invalid ones. `confirm` shows every payload and asks before each send, so nothing leaves
  without a yes; `off` stays one edit away in `docs/ai/config.md` § Feedback. Existing projects keep their value, and
  a `config.md` without the key still counts as `off`. A project that has never sent counts the feedback cadence from
  its first session with sending on, so it is no longer shown "feedback due" from the very start.
- **`act-setup` and `act-adopt` translate the docs scaffold in the same run** when `language-docs` is not English,
  and close the `translate-scaffold` todo themselves; it is left for later only by an `init` run without either skill.
- **`doctor.py` no longer proposes a lower tier** for a role whose workers' results were all accepted; it
  proposes only a higher one, once 8+ outcomes show 40%+ reworked or escalated (`R-role-outcome`). An
  accepted result does not show that a cheaper tier would have done as well.
- **Nuxt coding rules, stuck dev server on Windows:** no longer advise ending the process on port 3000; they end only a
  server the assistant started itself, found by its listening PID (`Get-NetTCPConnection … -State Listen`, or
  `findstr /C:` with `LISTENING`, since plain `findstr ":<port> "` also matches longer ports and client connections).
- `init` removes these community files from a new project in step 8, like the template's own README; an edited
  copy is kept with an inbox note, and `.github/` goes once nothing else is left in it.
- `R-work-evidence` counts a CI run, a log excerpt or a screenshot of the running application as evidence, and every
  reachable feedback loop runs before the human's.
- Workers mark every assumption; an accepted one is confirmed, asked in the inbox or recorded with the task's state.
- `R-work-idea-first` and `act-idea`: the recommended option names its failure modes and its way back; a throwaway
  prototype and an existing dependency or service count as options, and a `revisit:` date is set when the use is
  uncertain. `act-prepare` sets a first checkpoint after the first runnable slice.
- New projects get `dependency-check: regularly`; existing values stay.
- `context-hint` defaults to 180000 tokens, just below where Claude Code compacts on its own after an idle hour.
- `worker-write-scope` refuses fewer harmless commands: every worker may write into the system temp directory, even
  with `Write scope: none`, when the path is written out (`/tmp/...` in Bash, or the directory's absolute path in
  any tool) and the project itself does not lie inside it; the resolved path counts, so `..` or a link back into the
  project is judged as a project target. A target with a variable such as `$TEMP` stays refused, and so does a
  temp or scratchpad path with a glob character (`.*` can match `..`); `R-cost-delegate` says what
  `Write scope: none` now allows. An unquoted brace
  list in Bash (`app/{css,js}`) is checked as every path it expands to and as its literal name. A refusal names the
  way out for a target with a variable or command substitution and for a relative target after a `cd` on an earlier
  line.
- `secret-read` no longer reads the search pattern of `grep`, `egrep`, `fgrep`, `rg` or `git grep` as a file name,
  so a secret scan such as `git diff --cached | grep -E '\.env|id_rsa'` runs; files named as operands, `-f` pattern
  files and anything after `-e` stay checked.

### Security

- **The Bash write checks read a backslash-newline the way bash does.** They no longer join it in a comment, in
  single quotes or in the body of a heredoc with a quoted delimiter (including a mixed one such as `<<'E'$x`, where
  bash expands nothing in the delimiter), and they follow comments, quotes and heredocs inside `$(...)` within double
  quotes; an escaped backslash before the pair is kept. Before, a write or delete after such a comment or heredoc
  could slip past the `.act/` guard, the worker write scope and the delete/reset checks.
- **A heredoc fed to a shell is scanned as a script** — `bash <<EOF`, `sh -s <<EOF`, `cat <<EOF | bash`,
  `{ bash; } <<EOF`, `(bash) <<EOF` — and the `$(...)` in any unquoted heredoc body counts on its own, since bash
  expands it before the shell reads the body. A `-c` after `--`, `-` or a script name is no longer taken as the
  shell's own option, and a `<<` bit shift in arithmetic no longer counts as a heredoc.
- **A crafted command with very many heredocs or pipe stages is scanned in linear time**, so it can no longer stall
  the `PreToolUse` hook past its timeout, which would have let the call through.
- `git-metadata-guard` also covers files that start code when the folder is opened: workers may not write
  `.vscode/tasks.json`, `.devcontainer/`, `.envrc` or `.mcp.json`, and nobody adds a `folderOpen` task. A copy or
  move into a directory (`cp`, `mv`, `Copy-Item`, `Move-Item`) is checked as `<dir>/<source name>`, which also closes
  `cp -r x/.claude .` for workers.
- Agents started by a Claude Code workflow script are bound to their `Write scope:` and `Cap:` like any other worker.
- The `git reset --hard` guard no longer lets the command through when `git status` prints a file name it cannot
  decode (`core.quotePath=false`).
- The recursive-delete check covers more forms: `rm --rec` prefixes, glued `rd/s/q` and `rd/q /s` switches,
  `del`/`erase`, wrappers such as `busybox` or `setsid`, `$SHELL`/`$0` as shell names, `iex`/`Invoke-Expression` like
  `eval`, and every `find -exec` block.

### Fixed

- **A template update that touches many files no longer fails on Windows** with "WinError 206" (command line too
  long) at its commit step, as a migration rewriting several hundred entries would. The paths now reach git on
  standard input instead of the command line, the commit still covers exactly those paths, and the read-only path
  queries run in chunks; `init`'s first commit does the same. This needs Git 2.25 or newer.
- **Session start no longer rewrites unchanged bridges.** `CLAUDE.md`, `AGENTS.md` and `docs/ai/rules.md` are written
  only when their content differs from the source apart from line endings. On a Windows checkout with
  `core.autocrlf=true`, the LF rewrite used to leave the files listed as modified with an empty `git diff`, which
  blocked `act-update` and `act-commit` until they were added again. `act-update` skips identical bridges the same way.
- **`update.py --plan` says "nothing to update" when there is nothing to update.** When the project is already at the
  source's commit and no migration is due, the plan used to describe steps 5 to 10 anyway, so `act-update` asked for
  consent to an update that did not exist. Plan and real run now end the same way.
- **Hidden files on Windows can be overwritten.** Writing an existing file with the Hidden attribute (a `.gitignore`
  set hidden by an editor, for example) used to abort `init` and `act-adopt` with `PermissionError` 13 and leave the
  adoption in `init-failed`. `init` and `act-adopt` now overwrite such a file in place and keep its attributes; where
  that is impossible, the error names the file and the way out (`attrib -R -H`).
- The worker write scope reads a timestamp without a time zone as UTC.
- Feedback documentation: the reply address stays in the local copy of its one payload and is never reused for a
  later message (it said "never stored" before).

## [2.1.0] - 2026-10-09

Six new skills, a status line that says when a fresh session pays off, and safety checks that hold more and block
less. Projects on v2.0.0 update with `act-update`.

### New skills

- **`act-integrations`, `act-pr`, `act-issue`** — work with GitHub or GitLab, self-hosted included: check which
  access exists (REST token, MCP servers) and record it in `docs/project/integrations.md`; prepare a pull or merge
  request from the diff; read, create, comment on, close and start work on issues. Every write shows a preview and
  waits for your yes. New config section **Git hosting** (`target-branch`, `forge`, `forge-host`); a token goes only
  to github.com, gitlab.com or a host you named, never over plain http.
- **`act-handover`** — before you close a session or `/clear`: uncommitted changes, started tasks without a state
  line, answered inbox entries, and the sentence to type into the new session.
- **`act-check-translations`, `act-seo`** — code-only checks of translation files (missing, extra and empty keys,
  placeholders, keys used but not defined) and of on-page basics for search engines (title, description, headings,
  canonical, Open Graph, alt text, robots.txt, sitemap).

### Sessions, status line, board

- The status line shows the context size (`ctx 127k`) and splits tasks into `run`, `wait` and `new`. A started task
  waits when you mark it (`entries.py state <id> --wait`), when it has been quiet longer than `task-wait-hours`, or
  when an open question or todo names it. What waits for you appears by id — questions `Q<n>`, todos now `U<n>` —
  and every other kind as a count.
- Once the context reaches `context-hint` (default 150000 tokens), the assistant suggests `/clear` or a new session
  at the next task boundary: a fresh session after a finished task is the largest token saving there is. New config
  section **Session length**.
- Tasks get a `started:` header. Each person gets an ideas file under `docs/ai/concept/`; new entries are reported
  at session start.
- The board's place is a setting (`board: docs | shared | local`), and it is regenerated after git merge, pull,
  rebase, switch and similar commands.

### Rules and settings

- New rules: `R-cost-amend` (an addition to a running worker's assignment goes to it at once, or the worker is
  restarted when that is cheaper), `R-safe-no-personal-data` (no real personal or customer data in what the model
  sees), `R-work-bounded-output` (output of unknown length stays out of the context).
- `R-human-chat` makes compact chat a token-saving goal, with `output-depth` levels `normal`, `sparse` and `verbose`.
- `inbox-decisions: immediate | at-start` decides whether an open decision goes to the inbox at once or waits until
  work on its backlog entry starts.
- Reasoning per skill (`reasoning:` in a skill becomes `effort:` in the Claude Code copy, overridable in
  `config.md` § Roles); a `run` key for the start command; active environment overrides named at session start;
  promised replies kept as todos.
- Skill descriptions are trigger-first and linted (`skills.py --check`, `act-doctor`); long skills load in stages
  from `references/`.
- Your own skills and roles under `docs/ai/local/` get their tool copies automatically at session start and on
  update.

### Safety checks

- `secret-scan` now also holds credentials in URL query strings, single-quoted keys, PHP array entries, literal
  fallbacks after an environment lookup and credential pairs inside a quoted value — and no longer holds a commit
  over plain code expressions in source files. Every finding is named.
- After `git merge`, `pull` or `cherry-pick`, the lock files that came in get a dependency scan; findings become an
  inbox report, never a block.
- The Bash write scanners read backtick and `$(…)` spans, combined with the previous scanner so a check can only get
  stricter; they no longer block on `$'` inside quoted patterns or heredoc text, and fail closed beyond their nesting
  limit.
- Worker write scope: brackets are literal (`server/api/[id]/**`), and a wildcard that reaches outside the scope is
  refused.

### Update and adoption

- `update.py` refuses a downgrade unless `--allow-downgrade`; `--catch-up` keeps the recorded template commit; a
  failed fetch says what failed. `session-start-refresh: warn | off` is honoured by `update.py` too.
- `act-adopt` keeps the chosen languages, turns adopted rules into overrides or own rules, and asks before applying
  rows without a target.
- On Windows, a file held for a moment by a virus scanner or IDE no longer makes a write fail; the security scans
  print UTF-8.
- Documentation site in English and German: <https://wrufeger.github.io/agentic-coding-template-docs/>, linked from
  the README.

### Upgrading from v2.0.0

- Run `act-update` (or `python .act/scripts/update.py`). In `solo` mode, migration `002` gives every inbox todo a
  `U<n>` id and renames it to `U<n>-<slug>.md`; in `team` mode, `entries.py assign` on the default branch does the
  same. The archive is never rewritten.

## [2.0.0] - 2026-09-28

The rebuild. This release replaces the template's previous generation on `main`. The previous generation stays
available, frozen, on the branch `v1`.

### What changed

- **One layer under `.act/`**, in English, stdlib-only Python 3.9+. A project's own documentation stays in its
  own language (`language-docs`); the chat language is remembered per person and machine.
- **Setup from a fresh clone:** open it in your AI assistant and say what you want (`act-setup`) — a new project
  right in the clone, a new project elsewhere, or an existing codebase taken over with `act-adopt`.
- **Staying current:** `act-update` shows the diff first, tells local changes from template changes by a
  manifest, runs migrations, and a daily check at session start says when a newer template exists.
  `act-doctor` reports drift between project and template.
- **Rules in layers** — shared, orchestrator, topics — switched on and off per project in `docs/ai/rules.md`;
  coding rule sets per language in `docs/project/coding_rules.md`, preselected from the detected stack.
- **Roles and skills:** 9 worker roles with model tiers instead of model names, 23 skills. Claude Code gets
  the full bridge (hooks, skills, role bridges); Codex, GitHub Copilot, Cursor and Gemini CLI read `AGENTS.md`
  (Gemini CLI: `GEMINI.md`) and the skills under `.agents/skills/`.
- **Mechanical checks through hooks:** secret and danger scans before a commit, worker caps and write scopes,
  a guard before `git reset --hard`, a status-poll guard, and an optional security check (dependency scan;
  a deep scan before a release).
- **Work records as single files:** one inbox (questions, todos, reports, notes), tasks, backlog and journal
  under `docs/ai/`; the board is generated under `.act-local/`.
- **Settings export and import** between projects; opt-in feedback to the template author.

### Moving a project from the previous generation

- Do **not** merge or pull the new `main` into a project built on the previous generation — the layouts differ
  (`.claude/` there, `.act/` here). `update-template.py --apply` from the last state of `v1` refuses on its own.
- Instead run `act-adopt` from a checkout of this release. It moves board, tasks, questions, journal, backlog
  and the project's own docs into the new layout, on a branch of its own; the old state stays reachable.
  Details (German): `UMZUG.md` on `v1`.

### Notes

- A project set up from a pre-release state of the rebuild whose `.act-lock.json` has no
  `template.manifest_sha256` yet shows `.act/ was pulled in without update.py` at session start. Run
  `python .act/scripts/update.py` (or `--catch-up`) once; the lock then records it and the note stops.

## [0.1.0-beta] - 2026-09-13

First public pre-release of the previous generation (today the branch `v1`), documentation in German only.

- Rules in two layers: a tool-neutral `AGENTS.md` (roles, done only with evidence, commits by pathspec, live systems)
  and `CLAUDE.md` as the Claude Code addition, with pointer files for Cursor, Copilot, Aider and Gemini CLI.
- 8 sub-agents under `.claude/agents/` with a fixed model each, 6 skills (`/create-project`, `/apply-template`,
  `/update-template`, `/audit-docs`, `/commit`, `/run-maintenance`) and 9 stdlib-only scripts.
- Working folder `docs/ai/` (board, tasks, questions, ledger, backlog, checklists) and a `docs/project/` skeleton with
  coding rule modules for 10 languages and stacks; `AI-CONFIG.md` steers the collaboration.
- Optional live log `ai.log` through hooks.

[Unreleased]: https://github.com/wrufeger/agentic-coding-template/compare/v2.3.0...HEAD
[2.3.0]: https://github.com/wrufeger/agentic-coding-template/compare/v2.2.0...v2.3.0
[2.2.0]: https://github.com/wrufeger/agentic-coding-template/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/wrufeger/agentic-coding-template/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/wrufeger/agentic-coding-template/releases/tag/v2.0.0
[0.1.0-beta]: https://github.com/wrufeger/agentic-coding-template/releases/tag/v0.1.0-beta
