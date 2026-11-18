# Package format

summary: the folder layout, header and sections of a package, how its units are named, the zip and its signature, installing and removing it

A package brings rules, coding sets, skills, roles, topics, scripts and check modules into a project on the
template, plus an `install.py` and an AI-guided setup `install.md`. `python .act/scripts/packages.py plan <zip|folder>`
reads a package, checks it against this file and prints what installing it would do; it writes nothing and runs no
package code. `add` and `remove` (below) make a package active or inactive, always after a plan, a diff of every
project file and an explicit yes. This file is a kind of its own, like `documents/`: no switch, no project override.

## Folder layout

```
<package>/
  package.md          required: header and sections (below)
  install.py          optional: code that runs once at install (needs `contains-code: yes`)
  install.md          optional: the AI-guided setup, read after the install
  pre-template/       units that come before the template's own
  post-template/      units that come after the template's own
```

Each side holds any of `rules/`, `coding/`, `skills/`, `agents/`, `topics/`, `scripts/`, `hooks/checks/`;
nothing else. Anything else at the package root or in a side, and any symbolic link or junction anywhere, makes
the package refused, as does a name that cannot be written on every system: a `:` in any part (an NTFS stream) or a
Windows device name (`con`, `prn`, `aux`, `nul`, `com1`-`com9`, `lpt1`-`lpt9`, with or without an extension, in any
case) in any part. What goes where:

| Folder | Holds | One unit is |
| :--- | :--- | :--- |
| `rules/` | `.md` files with `## \`R-<area>-<name>\` — Title` headings | one rule id |
| `coding/` | `<name>.md` | one coding set |
| `skills/` | `<name>/SKILL.md` and what belongs to it | one skill folder |
| `agents/` | `<name>.md` | one role |
| `topics/` | `<name>.md` | one topic file |
| `scripts/` | `<module>.py` | one script |
| `hooks/checks/` | `<module>.py` | one check module |

## package.md

A header between two `---` lines, one `key: value` per line, then sections.

| Header field | Value |
| :--- | :--- |
| `id` | `^[a-z][a-z0-9-]{1,30}$`; the prefix of every new unit; `act` and any id starting with `act-` are refused (the template's namespace) |
| `version` | `X.Y.Z` |
| `requires-template` | `>=X.Y.Z`, no other form; refused when the installed template (`.act/VERSION`) is older or its version cannot be read |
| `tools` | comma list; each a tool the template knows (`claude-code`, `codex`, `copilot`, `gemini`, `cursor`, `aider`, `cline`, `ollama`) |
| `license` | non-empty |
| `contains-code` | `yes` or `no`; `no` with an `install.py`, a file in `scripts/` or in `hooks/checks/` is refused |

A missing or invalid field is refused with the field named. Other header fields are ignored by the plan; a package
repository may read one more, optional field into its index: `stack`, a comma list of the stacks the package is for
(free words such as `python` or `nuxt`; nothing checks it).

| Section | Lines | Plan line |
| :--- | :--- | :--- |
| `## Contents` | free text, shown at the head of the plan | head |
| `## disables` | `- R-<area>-<name>`: a rule id of the template | `disables rule …` |
| `## settings` | `- <key>: <question>`, key `<id>-<key>` (any other key is refused with the expected name; so is a key that equals a key of the template's `docs/ai/config.md`) | `asks <key>: <question>` |
| `## checks` | `- <check>: block\|warn\|off` (the template's own modes, nothing else): a check with a block/warn/off row in the template's `config.md` § Checks | ``config line `<check>: <value>` (from package <id>)`` |

Any other `##` section, a line in `disables`, `settings` or `checks` that is not a list line, and a repeated entry or
section are refused.

## Units and names

A unit whose name equals a template unit of the same kind:

- in `pre-template/` it **replaces** that unit; in `post-template/` it **extends** it (the text is appended).
  This holds for skills, roles and topics.
- A **coding set** is only extended: a coding set in `pre-template/` with the name of a template set is refused,
  because nothing can take the template's set out yet; put the text in `post-template/` instead.
- A **rule** is matched by id. A template rule id in `pre-template/` is always refused, with or without a `disables`
  line: the row of that id is the one `disables` switches off, so the package's own rule would be off itself. To
  replace a rule, list it under `## disables` and bring a rule of the package's own id `R-<id>-<name>`. In
  `post-template/` a template rule id extends that rule and its row stays checked.

A new unit must be named `<id>-<name>` (rule ids `R-<id>-<name>`; scripts and check modules `<id>_<name>.py`, the
id's hyphens written as underscores). The only exceptions are template units that moved into a package and keep their
name: `act-teach` and `act-slides` (`OUTSOURCED_UNITS` in `packages.py`). Anything else is refused with the expected
name. A unit may come from one side only; a skill folder needs its `SKILL.md`.

A script or check module with the name of a template one is refused: a package does not replace template code. A unit
name or rule id that another package in the lock already brings is refused, naming that package (the package's own
earlier entry does not count). The one exception: two packages may both **extend** the same template unit or template
rule (their text is appended in install order). A replacement collides with anything: replace against replace and
replace against extend of the same template unit are refused, naming the other package.

Load order: a package's `pre-template/` comes first, then the template's own files, then `post-template/`, then the
project's own overrides and rules.

### Skills and roles

A skill is a folder: `SKILL.md` and whatever belongs to it. A new skill gets its own copy where the project keeps its
skills. A skill in `pre-template/` with a template skill's name replaces that skill's copy (template files the package
lacks are not copied). A skill in `post-template/` with a template skill's name extends it: the package's `SKILL.md`
text without its frontmatter is appended to the template's, other files of the same name as a template file have their
text appended, and further files are added.

A role is one `.md` file: frontmatter (`name`, `description`, and the tier fields the template's roles use) and the role's
text. A new role is copied as a role file; a role in `pre-template/` with a template role's name replaces it; a role in
`post-template/` extends it: its text is added after the template role's body between two marks
`<!-- act:package <id> -->` and `<!-- /act:package <id> -->`. The role's `-high` variant follows its base role. A copy
that a person edited is never overwritten or deleted, and the plan names it.

Limit: roles reach Claude Code only (`.claude/agents/`). Role files for Copilot (`.github/agents/`) are not made from a
package yet.

### Check modules

A check module in `hooks/checks/` is a PreToolUse check of the package. It defines `check_<module>(payload) -> int`
(module `demo_guard.py` gives `check_demo_guard`): `0` lets the call pass, `2` refuses it, and what it prints to
stderr is the reason. It runs after the template's own checks on a deep copy of the payload, with a time limit of
two seconds, and its refusal is named with the package and the module. Before it runs, its file is compared with the
hash in the lock; a module that differs, a missing folder, a module that raises or runs past its limit refuses the call
with the fix named (`packages.py remove <id>`, or `add <id>` again). A module can only make a call stricter: it cannot
let through what a template check refuses, and changing its own payload copy changes nothing for the others.

A check module is code the owner installed, trusted like `install.py`: the template guards its verdict against the
module's return value and payload changes, not against what code can do. The guarantee comes before the install: the
plan names the module, `package_scan.py` lists it, and a signature says who made the zip.

The dispatcher refuses every call while `.act-lock.json` exists but cannot be read (or its `packages` is no object) and
`.act-local/packages/` holds a package folder: the owner fixes the lock (for example `! git checkout -- .act-lock.json`)
or moves the folders out. Without a package folder there is one note per session and nothing is refused.

### The config mark

A `## checks` line sets the value of a row in `docs/ai/config.md`. The row is marked at the end of its third column with
`<!-- act:package <id> was=<value before> now=<value set> -->`. One package marks a row at a time: a row another
package marks refuses the install, naming that package. Removing the package gives the row its old value back when the
row still holds `now=`; a value the owner wrote since stays. The mark goes either way. A `secret-read-allow` row is
written by the owner only, a package cannot set it.

## The plan

`packages.py plan <zip|folder>` prints, for a valid package: a head (package and version, license, tools, `contains-code`,
`requires-template`, the package hash, Contents), the origin and whether it is admitted (below), one line per file
`pre|post|root <path> -> <effect>` (`adds skill …`, `replaces role …`, `extends rule …`), then one line per config line.
A refused package prints every reason, not only the first, and exits 1.

## Zip, signature and fetch

A zip has `package.md` at its root or in exactly one top folder. Refused are an absolute path, a drive letter, a
`..` part, a backslash, an empty part, a symbolic link or other entry that is no plain file, an encrypted entry, two
names equal ignoring case, an entry below a file, more than 2,000 entries and more than 50 MB uncompressed. A folder
source gets the same limits, counted on the bytes copied. A UNC path (`\\host\share`, `//host/share`) is refused as a
source before anything is opened. Zip and folder are first copied into a fresh folder below
`.act-local/packages/.staging/`; every check, the signature check and the unpacking read that one copy.

The signature is `<zip>.sig`, made with `ssh-keygen -Y sign -n act-package` and checked with `ssh-keygen -Y verify -I
act-packages -n act-package` against the keys in `.act/package-signers` and, if it exists, in the project's own
`docs/ai/local/package-signers` (the same allowed-signers form, one line per key:
`act-packages namespaces="act-package" <key type> <key>`); a key line of either file may verify. A project that trusts
a key of its own adds it to its own file and never edits `.act/`. `ssh-keygen` is looked for in the absolute entries of
`PATH` only. The origin is one of:

| State | When |
| :--- | :--- |
| `verified` | the signature verifies |
| `unverified` | no `.sig`, no key line in either signers file, no `ssh-keygen`, a time-out, or a folder (a folder has no signature) |
| `bad` | a `.sig` exists and does not verify: refused in every mode |

The config key `packages-unverified` decides about `unverified`: `block` (default) refuses it, `scan` admits it and
`add` prints the findings of `package_scan.py` first (marked `RED`), `allow` admits it with a warning. An unknown value
counts as `block`.

`packages.py fetch <id> [--source <place>]` looks for the package in `packages-sources`, in order. A source is an
`https://` address or a local folder holding `index.json`:

```json
{"packages": {"<id>": {"version": "X.Y.Z", "zip": "<file name>", "sig": "<file name>"}}}
```

File names are plain names without a path part. Fetch writes `.act-local/packages/<id>-<version>.zip` and its `.sig`,
prints the origin, and never unpacks or activates anything.

An entry may also carry optional fields that only inform a reader and are never used to fetch: `contents` (the text
of the package's `## Contents` section), `tools` and `stack` (a comma list or a list of strings; `tools` as in the
header, `stack` from the optional header field) and `red` (a non-empty reason: the repository's maintainers mark the
package as one to stay away from). A field that is missing is missing; none of them is a reason to trust or refuse
the package, the plan of the zip itself decides.

`packages.py index [--source <place>] [--json]` reads that `index.json` from the first source that answers, with the
rules of `fetch` (an `https://` address or a local folder, no UNC path, the time and size limits; a source whose index
is refused or does not answer is skipped with a line on stderr, a time-out aborts) and prints one line per package: id,
version, a mark when the lock records it (`active <version>`, `broken`, `newer in the index`) or a folder of it rests
in `.act-local/packages/`, and where the index has them the first line of `contents`, `tools`, `stack` and
`RED <reason>`. A file is refused as a whole when it is no JSON, has no `packages` object, lists an id that is no
package id, or an entry has a version, a file name or an optional field of the wrong kind. `--json` prints the same
fields as JSON. It writes nothing.

## Installing and removing

`packages.py add <zip|folder|id>` takes a zip (with its `.sig` next to it), a package folder, or a package id: then the
newest `.act-local/packages/<id>-<version>.zip`, else the resting folder `.act-local/packages/<id>/` (read as a folder,
so unverified), else it refuses and names `fetch`. An id-shaped argument is always an id; write a folder of that name
as `./<name>`. What a bare id picks up must be what its name says: a zip or folder whose `package.md` carries another
id is refused, and so is a zip `<id>-<version>.zip` whose `package.md` carries another version.

Without `--yes` it writes nothing. It prints the plan, the origin and admission (with `scan` the findings), `install`,
`update <old> → <new>` or `downgrade <old> → <new>` (the same id again is an update, a lower version a downgrade,
allowed after the yes like an update; the units the new version drops go), what happens to the folder
`.act-local/packages/<id>/` (a resting folder that another source replaces is said to be replaced and deleted), the list of project
files that change and a unified diff of each (`docs/ai/rules.md`, skill and role copies, `docs/ai/config.md`,
`.act-lock.json`), and the line `install exactly this: python .act/scripts/packages.py add <source> --yes <code>`. The
code is the first 12 hex digits of a package hash computed over the raw bytes of every package file, with no
line-ending folding: any byte that changes after the plan was shown changes the code, and `--yes` with the old code is
refused. (The lock's `sha256` below stays over the LF form.) The yes itself is the owner's: it is given in chat to the
plan shown, and `--yes <code>` only carries it out; a plan is never shown and carried out in one step. The diff does not show an import line that the cut of a rule file takes out when the package disables all
of its rules.

With `--yes <code>` the staged folder moves to `.act-local/packages/<id>/` (an old one is moved aside first), the check
rows are set, the lock entry is written and the package is loaded. A failure on the way, also a file the loading cannot
write, puts everything back from the bytes saved before (the lock, the config, every file the loading writes) and exits
1 with the path and the kind of error, never a file's content. Then, for `contains-code: yes` with an `install.py`,
it runs once (argument list, the project root as working folder, no input, its output written to a file in the staging
folder and shown afterwards, cut at 20 000 bytes, a limit of 300 seconds). At the limit the process and everything it
started are ended, also on Windows and also when it left a child process that keeps the output open. On a time-out or
an exit other than 0 the package stays installed, the message names `remove`, and the exit is 1. A process that
`install.py` left running after it exited normally is not ended; if it still holds the output file, the staging folder
stays and the message names it. Then, with an `install.md`, one line tells the AI agent to follow it now: the
`install.md` of a package the owner said yes to, after the plan, counts as the owner's instruction for that installation
only. Neither runs in a dry run or from any session-start or check path.

`packages.py remove <id> [--keep]` shows the same plan and diff for taking the package out and the folder that goes;
`--yes <id>` gives the check rows back, drops the lock entry, unloads the package and deletes
`.act-local/packages/<id>/` (never following a link), unless `--keep`, which leaves the folder resting: nothing loads
from a folder the lock does not record. It works when the folder is already missing, and a resting folder with no lock
entry is deleted the same way. `add` followed by `remove` leaves the project byte for byte as it was. `packages.py list`
shows the lock's packages and the resting folders and names a broken package (its folder is missing or a file differs
from the lock) with the fix: `add <id>` again, or `remove <id>`.

## Settings

The questions of a package's `## settings` section are answered after the install, in one go, and kept in
`docs/ai/config.md`, section Packages, in a block of their own below the section's table, one table row per key:

```
<!-- act:package-settings <id> -->
| Key | Value |
| :--- | :--- |
| `<id>-<key>` | the answer |
<!-- /act:package-settings <id> -->
```

`packages.py settings <id>` shows the keys the package declares with their question and answer (`(not set)` when there
is no row); `settings <id> <key>=<value> …` writes them. Only keys the package's own `## settings` declares are taken
(read from the hash-checked `package.md` of an intact active package), a value is one line without `|` and is stored
stripped, and one refused pair writes nothing. The rows are read like any other row of the file (`actlib.read_config`),
`config.py` shows them as settings of the package and never checks them against the template's own settings, and
`doctor.py` does not check their values; it names only a block whose package has no entry in the lock, with the fix
(remove the block by hand, or `packages.py add <id>`). An update that no longer declares a key drops its row; `remove --yes` drops the block
(and the one blank line in front of it), so `add`, `settings` and `remove` leave `docs/ai/config.md` byte for byte as it
was. A package's settings are not secrets: the file is versioned.

## Lock

The lock (`.act-lock.json`) records installed packages under `packages`, per id:

```json
{"<id>": {"version": "1.0.0", "source": "...", "sha256": "...", "check": "verified",
          "files": {"<path in the package>": "<sha256>"}, "units": ["skill:<id>-x", "rule:R-<id>-y"],
          "extends": ["role:reviewer"], "config": ["<check>: <value>"]}}
```

`source` names the zip file or folder it came from, `check` the origin at install time. `sha256` is the SHA-256 over the
sorted lines `<path>`, a NUL byte, `<file sha256>`, a newline, one per file of the package (the file hash is the one the
lock uses everywhere, over the LF form). `units` lets a later install see which names a package already brings (rule
ids cannot be read from a path); `extends` lists the part of `units` that only extends a template unit or rule, so two
extensions of the same one do not collide. The copies a package made are recorded under `package_copies`, never under
`copies`.

A package is **active** when it has a lock entry; a folder without one is **resting** and nothing loads from it. The
lock is versioned, the folder is not: on a second machine the lock is there and the folder may not be. What derives from
the lock alone (the import lines and the marked rows) stays, what needs the folder (copies, check modules) is left as it
is and reported, and a package whose folder is missing or whose files differ from the lock is **broken**: its modules
are not loaded and its copies not rewritten until `add` or `remove` is run.
