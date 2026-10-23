#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Create and account for the project's short-lived entry files — tasks, backlog items,
#          journal entries, and docs/ai/inbox/ entries (question | todo | report | note)
#          — one file per entry. A task, backlog item, or question carries a short id ("T12",
#          "B7", "Q5") in an "id:" header line, and so does a todo ("U4", U for "user": a task
#          for a human); a report/note never does. *When* an id is
#          written depends on docs/ai/config.md's "mode" key ("solo" or "team"): "solo" gets it
#          right away, from `new`; "team" leaves it out until `assign` runs it on the project's default
#          branch, the same moment a PR number would be handed out — until then, the entry's
#          filename carries the person's identity and a timestamp instead, and `assign` renames it
#          once the id is known (the filename always shows an assigned id up front, never
#          hides it inside the file). A journal entry under
#          docs/ai/work/ledger/ never gets an id at all, and is never scanned for one either — see
#          _ID_SCAN_ROOTS.
#          Every docs/ai/inbox/ entry — anything waiting on a person — carries a "kind:" header
#          field (question | todo | report | note, actlib.INBOX_KINDS; missing means "todo",
#          actlib.DEFAULT_INBOX_KIND); "question" and "todo" also carry an id (Q<n> / U<n>).
#          docs/ai/questions/ no longer exists as its own directory — a question is an inbox entry
#          like the rest, just one with an id.
#          Adoption: `new` also takes an entry over from an older structure — its
#          old id kept (--id, in either mode), or a new id plus "formerly: <old id>" for another
#          numbering scheme, the body copied byte for byte from --body-file. The next free id also
#          counts the ids of old collection files moved to docs/ai/work/archive/legacy/ (see
#          legacy_ids()), so a new entry never reuses an old number. adopt_entries.py writes whole
#          batches through the same create_entry().
#
# Usage:
#   python .act/scripts/entries.py new <kind> <title...>
#       # kind: task | backlog | ledger | question | todo | report | note ("inbox" is an alias
#       # for "todo", kept for existing callers such as update.py/adopt_entries.py)
#       [--id <T|B|Q|U><n>[a-z]]  keep this id (task/backlog/question/todo only; refused if it is taken)
#       [--formerly <old id>]     header line "formerly: <old id>"
#       [--status open|answered]  question/todo/report/note only (default open)
#       [--for <identity>]        task/todo/report/note only (todo/report/note default all; a task
#                                 defaults to this checkout's identity, `all` = shared; a question
#                                 is always "all")
#       [--body-file <path>]      body below the heading, copied verbatim (UTF-8)
#   python .act/scripts/entries.py assign                  # hand out ids still missing (and rename; an
#                                                          # old "todo-<stamp>-<slug>.md" becomes "U<n>-<slug>.md")
#   python .act/scripts/entries.py state <T-id> <text...>   # append a working-state line
#   python .act/scripts/entries.py list [<kind>]            # id/filename + title, per kind
#   python .act/scripts/entries.py check                    # report a duplicate or unreadable entry
#   python .act/scripts/entries.py archive <id|file>        # move a finished entry (and its pasted images) to the archive
#   python .act/scripts/entries.py compact [--plan]          # merge old archived entries into one file per kind and month
#
# Output format:
#   "new": one line, "entries: created <path> [<id or explanation>]", exit 0 (2 on a bad kind, an
#     empty title, or a refused option — an id taken or with the wrong prefix, an option the kind
#     does not take, an unreadable body file; the reason goes to stderr, nothing is written).
#   "assign": one "entries: assigned <id>: <old path> -> <new path>" line per entry given an id (so
#     a commit made by pathspec can stage both the old and the new name of the same rename — the
#     skill act-commit reads this line), one "entries: cannot read <path> ..." line per file
#     skipped for not being valid UTF-8,
#     or one line saying there was nothing to do (including "team" mode + wrong/undetermined
#     default branch) — never touches a file that already has one. Exit 0 always; assigning ids is
#     never a failure.
#   "state": splits a task's versioned goal/check-criteria from its unversioned
#     working state ("State ...: step 3 running, next step ..."), which lives under
#     .act-local/state/ (gitignored — .gitignore already covers .act-local/) instead of inside the
#     task file. Finds the task under docs/ai/work/tasks/ whose header carries "id: <T-id>"
#     (used_ids()-style scan, task kind only), appends one line "State <YYYY-MM-DD HH:MM>: <text>"
#     to .act-local/state/<that task file's name> (creating the directory on first use), and prints
#     "entries: appended state for <id> to .act-local/state/<name>", exit 0. Refuses (exit 2,
#     nothing written) with a reason on stderr if the id is not a task id, no task with that id
#     exists, or the text is empty. board.py reads the same file back and shows its last non-blank
#     line next to the task's title. The first state for a task also writes "started: <timestamp>"
#     into the task file's versioned header (the line then ends "— task marked started"), which is
#     what board.py and the status line count as a running task; a note on a task not begun yet
#     belongs in the task file itself, not in `state`. With `--wait` the line reads "State
#     <YYYY-MM-DD HH:MM> (wait): <text>": the task is then shown as waiting (board, status line)
#     until the next plain `state` line; lines without the marker keep reading as before.
#   "start": writes "started: <timestamp>" into the task's header without a state line —
#     "entries: <id> marked started" or "entries: <id> already started (<value>)", exit 0; the same
#     refusals as "state" (exit 2).
#   "list": one "== <kind> ==" heading per kind shown, then one "<id-or-'(unassigned)'>  <file> —
#     <title>" line per entry ("-" instead of the id for ledger/report/note, which never
#     carry one), oldest first (filename order); an inbox entry is listed once, under its own
#     `kind:` section. Exit 0, 2 on an unknown kind.
#   "check": "entries: no duplicate ids found" (stdout, exit 0) if nothing is wrong, else one
#     "entries: duplicate id <id>: <path>, <path>, ..." line per collision and/or one "entries:
#     cannot read <path> (not valid UTF-8)" line per unreadable file (stderr, exit 1 either way).
#     find_duplicate_ids()/find_unreadable_entries() below are the reusable halves doctor.py's own
#     checks call instead of repeating the scan.
#   "archive": for a task, a backlog item or an inbox entry (found by id or path; directly in its
#     folder). Moves the file to docs/ai/work/archive/; an inbox entry gets `status: done` in its
#     header (either header form), a task or backlog item keeps its header as it is. Non-Markdown
#     files the entry links by a relative path from its own folder (Markdown image or link, `<img
#     src>`, also `<...>` and %20 forms) move along; an IDE's generic name (img.png, image_1.png,
#     "Pasted image ...", screenshot ...) or a name already taken in the archive gets the entry's id in
#     front ("Q<n>-img.png"), and the links in the moved file are rewritten. A file another remaining
#     Markdown file under docs/ (the archive included) still links is copied instead of moved; a link
#     that leads out of the entry's folder through a symlink is left in place and reported. Relative
#     links to files that stay are rewritten so they still resolve from the archive; links inside
#     fenced blocks or inline code are not touched. Prints one "entries: archived|moved|copied|
#     relinked|left ..." line per change, so a commit by pathspec can stage every path; exit 2 with
#     the reason on stderr, nothing changed, for an unknown id, a name already in the archive, an
#     unreadable file, or an entry that cannot be deleted (what was written is removed again); exit 1
#     when an original could not be removed after the copy. The moved file gets the header field
#     `archived: <date>` (an existing one is replaced).
#   "compact": folds the single files in docs/ai/work/archive/ (and the journal files in
#     docs/ai/work/ledger/) that were archived more than 7 days ago into collection files in the archive
#     folder, one per kind and calendar month of the archive date: Q-2026-09.md, T-, B-, U- by id prefix,
#     other- for entries without an id, ledger- for journal entries (the date is the file name's). A
#     collection opens with actlib.COLLECTION_MARK, names the commit that still holds the single files
#     ("full text: git show <hash>:<folder>/<file>") and has one section per entry: an anchor line
#     `<a id="<id>"></a>`, the heading `## <id> — <title>`, the header fields in one inline-code line
#     (with `archived:` and the original `file:`), then the body. Every id in a collection is found by
#     actlib.entry_ids(), so the next free id and the duplicate check still see it. The archive date is the
#     header field `archived:`, else the day Git first saw the file in the archive, else `created:`.
#     Links to a merged file in any Markdown file of the project (not legacy/, not .act/) are rewritten to
#     the collection plus anchor. The newest week, a subfolder (legacy/, proposals/), a README, an
#     unreadable file, an entry whose id is carried twice and a monthly topic overview (`YYYY-MM.md`) stay as they are. Refuses (exit 2, nothing
#     changed) when the project is not a Git repository with a commit or a file to merge is not committed.
#     `--plan` lists what would be merged and writes nothing. A second run changes nothing. Prints one
#     "entries: compacted|would compact <id>: <old path> -> <collection>#<anchor>" line per entry, one
#     "entries: relinked ..." line per rewritten file and a closing "entries: wrote ..." line.

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.parse
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Optional, Union

import actlib
import board


# ---------------------------------------------------------------------------
# Where each kind lives, and what its id looks like
# ---------------------------------------------------------------------------

# "inbox" is a legacy alias for "todo" (existing callers such as update.py/adopt_entries.py) — see
# _canonical_kind(). All four inbox kinds (question/todo/report/note) share actlib.INBOX_DIR.
KIND_ALIASES: dict[str, str] = {"inbox": "todo"}

KIND_DIR: dict[str, Path] = {
    "task": Path("docs/ai/work/tasks"),
    "backlog": Path("docs/ai/work/backlog"),
    "ledger": Path("docs/ai/work/ledger"),
    "question": actlib.INBOX_DIR,
    "todo": actlib.INBOX_DIR,
    "report": actlib.INBOX_DIR,
    "note": actlib.INBOX_DIR,
}

# No entry for "ledger", "report" or "note" — only task/backlog/question/todo ever get a short id
# (see header comment; "U" for "user", a todo being a task for a human); the other two inbox kinds
# are named from kind+timestamp+slug alone (actlib.inbox_entry_filename()).
KIND_PREFIX: dict[str, str] = {"task": "T", "backlog": "B", "question": "Q", "todo": "U"}

# Directories scanned for existing ids, both for the next free number and for check(): every kind
# that can carry one (docs/ai/work/tasks/, .../backlog/, the question and todo share of docs/ai/inbox/),
# plus the archive, where an accepted task or backlog item keeps its id
# (docs/ai/work/archive/README.md). docs/ai/work/ledger/ is deliberately absent — a journal entry
# never has an id, and a prose mention of another entry's id in a journal text ("... header was:
# id: T12") must never be read as if it were this file's own header. An inbox entry
# carries only its own kind's id (Q for a question, U for a todo, none for a report/note), so
# scanning the whole inbox directory here is harmless (used_ids()/_next_id() only count what
# actually matches the kind's prefix) — same for
# docs/ai/work/archive/proposals/, except docs/ai/work/archive/legacy/, which _entry_files() skips
# (see legacy_ids()).
_ID_SCAN_ROOTS = (
    Path("docs/ai/work/tasks"),
    Path("docs/ai/work/backlog"),
    Path("docs/ai/work/archive"),
    actlib.INBOX_DIR,
)

# An id is the kind's prefix, a number, and at most one sub-letter ("Q55a" — a part of a question
# asked together with its siblings, kept as it was when adopted).
ID_FIELD_RE = re.compile(r"(?im)^id:\s*([A-Za-z]+\d+[a-z]?)\s*$")
_ID_ARG_RE = re.compile(r"^([A-Za-z]+)0*(\d+)([A-Za-z]?)$")

# Where adopt.py puts old material byte-identical (docs/ai/work/archive/legacy/<old path>), and how
# an old collection file there names its entries: "**T47 ·", "- **Q55a** ·", "| B114 |" (the
# separator may also be ":", "—" or "–"). Only these definition forms count — a prose mention such
# as a journal heading "### T5 step 10" is not an entry of its own. The letter group has to be
# exactly the kind's prefix; a sub-letter is kept for the "taken" check and ignored for the number.
LEGACY_ROOT = Path("docs/ai/work/archive/legacy")
_LEGACY_PATTERNS = (
    r"\*\*({p})(\d+)([a-z]?)\s*[·:—–]",
    r"\*\*({p})(\d+)([a-z]?)\*\*\s*[·:—–]",
    r"\|\s*({p})(\d+)([a-z]?)\s*\|",
    r"(?m)^id:\s*({p})(\d+)([a-z]?)\s*$",  # an old per-entry file's own header (_entry_files() skips legacy)
)
# An old id whose material the content step (adopt_entries.py) decided not to keep as a
# live entry at all — a `delete` row `--finish` removes for good, never moved to LEGACY_ROOT either
# — would otherwise be free to reuse. adopt_entries.py's "reserved" batch kind writes the id here
# instead of a file; _next_id() reads it back the same way it reads legacy_ids(), so the next id
# still lands above it. A plain {"ids": [...]} list, tolerant of a missing/unreadable file (then
# nothing is reserved — the safer default is the same "not yet known about" as before this fix).
# The list is versioned (a fresh clone keeps it); the old gitignored place is still read during the
# transition.
RESERVED_IDS_PATH = Path("docs/ai/work/reserved-ids.json")
RESERVED_IDS_OLD_PATH = Path(".act-local/adopt/reserved-ids.json")
# A task's working state ("State ...") lives here, gitignored, never in the versioned task
# file itself — see cmd_state()/board.py's read_task_titles().
STATE_DIR = Path(".act-local/state")

STATUS_VALUES = ("open", "answered")
# A task's versioned "started:" header field (entries.py state / start) — board.py and the status
# line count a task carrying it as running, one without it as new.
STARTED_RE = re.compile(r"(?im)^started:\s*(\S+)\s*$")

# Solo-mode id assignment (cmd_new) is guarded by a short-lived lock file under .act-local/, so two
# processes started at the same instant never compute the same "next free id" from the same disk
# snapshot. _LOCK_TIMEOUT is how long a waiter tries before giving up and proceeding anyway (a
# collision at that point is exceedingly unlikely — the critical section is a handful of file
# reads plus one exclusive create — and entries.py check/doctor.py catch it either way, see
# find_duplicate_ids()). _LOCK_STALE_AFTER reclaims a lock file left behind by a process that died
# inside the critical section instead of blocking every future `new` forever.
_LOCK_PATH = Path(".act-local/entries.lock")
_LOCK_TIMEOUT = 5.0
_LOCK_STALE_AFTER = 30.0
_LOCK_POLL = 0.05


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


_UMLAUT_MAP = str.maketrans({
    "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
    "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
})


def _slugify(title: str) -> str:
    """A filesystem- and URL-safe slug: German umlauts spelled out first (ä/ö/ü/ß, both cases) so
    they survive as letters rather than vanishing with the rest of the non-ASCII text, then
    Unicode-normalized (NFKD) and stripped to plain ASCII, then everything but [a-z0-9] collapsed
    to a single "-". Capped at 60 characters so a long title doesn't produce an unwieldy filename;
    falls back to "entry" if nothing alphanumeric survives (e.g. a title in a non-Latin script)."""
    text = title.strip().translate(_UMLAUT_MAP)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    slug = slug[:60].strip("-")
    return slug or "entry"


def _canonical_kind(kind: str) -> str:
    """`kind` with a legacy alias resolved (KIND_ALIASES) — the one place every command and helper
    below normalizes it before touching KIND_DIR/KIND_PREFIX, so "inbox" (an older caller's spelling
    for "todo") works everywhere without a second copy of every kind check."""
    return KIND_ALIASES.get(kind, kind)


_DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")
# Non-greedy "(?:-[a-z0-9]+)*?": the identity slug itself may contain digits, and so may the title
# slug that follows the timestamp — a greedy quantifier here would consume as much as possible and
# then backtrack onto the *last* "-YYYYMMDD-HHMM-" run it can still find, mistaking a timestamp-
# shaped fragment inside the title for the real one (e.g. a title slug "release-20260101-1200-
# notes" swallowed whole, leaving just "notes"). Non-greedy stops at the first "-YYYYMMDD-HHMM-" it
# meets right after the identity, which is always the real one.
_TEAM_PREFIX_RE = re.compile(r"^[A-Za-z]+-[a-z0-9]+(?:-[a-z0-9]+)*?-\d{8}-\d{4}-")
# An inbox entry's old id-less name, "<kind>-<YYYYMMDD-HHMM>-<slug>" (actlib.inbox_entry_filename()) —
# what a todo was called before it carried an id. Tried first: its "<kind>-<digits>" start would
# otherwise be misread as a team prefix with an identity named after the kind.
_KIND_STAMP_RE = re.compile(r"^(?:question|todo|report|note)-\d{8}-\d{4}-")


def _derive_slug(stem: str) -> str:
    """The slug part of an existing entry filename's stem (no ".md"), for cmd_assign()'s rename:
    strips a leading kind+timestamp prefix ("todo-<YYYYMMDD-HHMM>-", an old id-less inbox name), a
    team-mode prefix ("<P>-<identity>-<YYYYMMDD-HHMM>-") or a date prefix ("YYYY-MM-DD-"), whichever
    matches; none ever occurs together. A trailing "-<n>" counter left
    over from a same-minute name collision (_create_unique) is not a prefix and stays part of the
    slug, exactly as it stood in the old name. A stem that matches neither pattern (already renamed,
    or an old-style name from before this scheme) is returned unchanged."""
    for pattern in (_KIND_STAMP_RE, _TEAM_PREFIX_RE, _DATE_PREFIX_RE):
        match = pattern.match(stem)
        if match:
            return stem[match.end():]
    return stem


def _identity_slug(root: Path) -> str:
    """The current checkout's identity (.act-local/identity.json's "identity" field), slugified for
    a team-mode filename awaiting its id — "unknown" if identity.json is missing, unreadable, or
    has no "identity" value (never blocks entry creation on it)."""
    value = (actlib.read_identity(root) or {}).get("identity")
    return _slugify(value) if isinstance(value, str) and value.strip() else "unknown"


def _own_identity(root: Optional[Path] = None) -> Optional[str]:
    """`root`'s identity in short form (.act-local/identity.json; default: the project found from
    the working directory), or None if there is none."""
    value = (actlib.read_identity(root) or {}).get("identity")
    return actlib.recipient_slug(value) if isinstance(value, str) and value.strip() else None


def _recipient_value(recipient: Optional[str]) -> str:
    """The `for:` header value for `--for`: "all" (also the default) stays, anything else in the
    identity's short form (`--for "Wolfgang Rufeger"` writes `wolfgang-rufeger`)."""
    text = (recipient or "all").strip() or "all"
    return "all" if text.lower() == "all" else actlib.recipient_slug(text)


def _rename_with_id(path: Path, entry_id: str) -> Path:
    """Rename `path` to "<entry_id>-<slug>.md" in the same directory (cmd_assign()'s second half,
    after _insert_id() has written the header) — slug via _derive_slug(path.stem). A name collision
    gets a numeric suffix, never an overwrite; returns `path` unchanged if it already has the exact
    target name. Returns the new (or unchanged) path."""
    slug = _derive_slug(path.stem)
    directory = path.parent
    n = 1
    while True:
        name = f"{entry_id}-{slug}.md" if n == 1 else f"{entry_id}-{slug}-{n}.md"
        dest = directory / name
        if dest == path:
            return path
        if dest.exists():
            n += 1
            continue
        path.rename(dest)
        return dest


def _canonical_id(raw: str) -> str:
    """Normalize an id's number so "T012" and "T12" compare equal (leading zeros carry no
    meaning) — the form every comparison and every duplicate-id report below uses. Falls back to
    the raw value, upper-cased, for anything that does not parse as letters+digits (defensive
    only; ID_FIELD_RE already restricts what reaches this function)."""
    return actlib.canonical_id(raw)


def _id_number(canonical: str, prefix: str) -> Optional[int]:
    """The number of a canonical id whose letter group is exactly `prefix` ("Q55a" -> 55 for "Q"),
    else None — a sub-letter never counts towards the next free number."""
    match = _ID_ARG_RE.match(canonical)
    if not match or match.group(1).upper() != prefix:
        return None
    return int(match.group(2))


def _safe_read(path: Path) -> Optional[str]:
    """UTF-8 text of `path`, or None if it cannot be opened or is not valid UTF-8 — the one place
    every entry-file read in this module goes through, so a stray Latin-1/cp1252 file is skipped
    consistently everywhere instead of crashing whichever command happened to touch it first."""
    try:
        return path.read_text(encoding="utf-8-sig")  # a hand-saved BOM is dropped, not content
    except (OSError, UnicodeDecodeError):
        return None


def _entry_id(text: str) -> Optional[str]:
    """The canonical id from `text`'s header block, or None — reads only the leading run of
    "key: value" lines (actlib.header_block), never the body, so an id can't be spoofed by an
    example, a fenced code block, or another file's header merely quoted in prose."""
    match = ID_FIELD_RE.search(actlib.header_block(text))
    return _canonical_id(match.group(1)) if match else None


def _first_heading(path: Path) -> Optional[str]:
    text = _safe_read(path)
    if text is None:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return None


def _mode(root: Path) -> str:
    """docs/ai/config.md's "mode" key ("solo" | "team"), defaulting to "solo" for a missing or
    unrecognized value — the safer default, since it just means ids keep being handed out right
    away instead of waiting for a default-branch commit that may never come."""
    value = actlib.read_config(root).get("mode", "").strip().lower()
    return value if value in ("solo", "team") else "solo"


def _default_branch(root: Path) -> Optional[str]:
    """The project's own default branch — "origin/HEAD"'s target if that symref is set, else
    "main" or "master" if either exists as a remote-tracking branch, else None. Never the current
    branch: in "team" mode, falling back to whatever happens to be checked out would silently let
    a feature branch assign ids meant for the default branch only (the bug `assign` had before —
    see cmd_assign's message for the fix: `git remote set-head origin --auto`, once there is a
    real "origin" to ask). "origin/<name>" is turned into "<name>" by stripping the literal
    "origin/" prefix, not by taking the last "/"-segment — a branch named "release/2" must stay
    "release/2", not become "2"."""
    output = board.run_git(["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], root)
    if output and output.strip():
        ref = output.strip()
        return ref[len("origin/"):] if ref.startswith("origin/") else ref
    for candidate in ("main", "master"):
        if board.run_git(["rev-parse", "--verify", "-q", f"refs/remotes/origin/{candidate}"], root) is not None:
            return candidate
    return None


def _entry_files(root: Path) -> list[Path]:
    """Every entry file that could carry an id — see _ID_SCAN_ROOTS above. The legacy tree is left
    out: its files are old material kept byte for byte (possibly Latin-1, possibly with an "id:"
    header of their own) and are read only by legacy_ids(), never as entries of this project."""
    legacy = root / LEGACY_ROOT
    out: list[Path] = []
    for rel in _ID_SCAN_ROOTS:
        base = root / rel
        if not base.is_dir():
            continue
        out.extend(p for p in base.rglob("*.md")
                   if p.is_file() and p.name.lower() != "readme.md" and legacy not in p.parents)
    return out


def legacy_ids(root: Path) -> dict[str, set[str]]:
    """prefix -> canonical ids named by the old collection files under LEGACY_ROOT (every file,
    any depth; see _LEGACY_PATTERNS). Read as UTF-8, else as cp1252, so an old Latin-1 file still
    yields its ASCII ids instead of being skipped."""
    found: dict[str, set[str]] = {prefix: set() for prefix in KIND_PREFIX.values()}
    base = root / LEGACY_ROOT
    if not base.is_dir():
        return found
    patterns = [(prefix, re.compile(pattern.format(p=prefix)))
                for prefix in found for pattern in _LEGACY_PATTERNS]
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            # An old Windows-1252/Latin-1 file: its "·", "—", "–" separators are single bytes there.
            text = data.decode("cp1252", errors="replace")
        for prefix, pattern in patterns:
            for match in pattern.finditer(text):
                found[prefix].add(f"{prefix}{int(match.group(2))}{match.group(3)}")
    return found


def reserved_ids(root: Path) -> dict[str, set[str]]:
    """prefix -> canonical ids from RESERVED_IDS_PATH and the old place (see the comment above) — read the same
    tolerant way as legacy_ids(): a missing file, bad JSON, or a value that isn't a T/B/Q id is
    skipped rather than raising, so a stray hand-edit never breaks id assignment."""
    found: dict[str, set[str]] = {prefix: set() for prefix in KIND_PREFIX.values()}
    for rel in (RESERVED_IDS_PATH, RESERVED_IDS_OLD_PATH):
        _collect_reserved(_safe_read(root / rel), found)
    return found


def _collect_reserved(text: str | None, found: dict[str, set[str]]) -> None:
    """Add the valid ids of one reserved-ids file's text to `found`; unreadable text adds nothing."""
    if text is None:
        return
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return
    ids = data.get("ids") if isinstance(data, dict) else data
    if not isinstance(ids, list):
        return
    for value in ids:
        if not isinstance(value, str):
            continue
        match = _ID_ARG_RE.match(value.strip())
        if match and match.group(1).upper() in found:
            found[match.group(1).upper()].add(_canonical_id(value.strip()))


def used_ids(root: Path, kind: str) -> set[str]:
    """Every canonical id of `kind`'s prefix a "taken" check must refuse: entry-file headers
    anywhere _entry_files() reaches, archive included — never a legacy collection file's own old
    id (legacy_ids()). An id that only survives in legacy is free to adopt with --id; it
    only raises the floor for the *next* id (see _next_id()), it never blocks a kept one."""
    prefix = KIND_PREFIX[kind]
    ids = set()
    for path in _entry_files(root):
        text = _safe_read(path)
        for canonical in (actlib.entry_ids(text) if text is not None else []):
            if _id_number(canonical, prefix) is not None:
                ids.add(canonical)
    return ids


def _next_id(root: Path, kind: str, also_used: tuple = ()) -> str:
    """The next free id for `kind` — one past the highest number already used by that prefix,
    anywhere _entry_files() reaches (including the archive, so an id an accepted task already
    carries is never reused), in the legacy collection files (legacy_ids()), so an adopted
    project's next task comes after its highest old one even when that one only survives in
    legacy, and in reserved_ids() (an old id `--finish` deletes for good instead, never moved to
    legacy). `also_used`: ids not on disk yet (a batch being planned). Leading zeros and
    sub-letters don't count ("T012" is 12, "Q55a" is 55, via _canonical_id/_id_number)."""
    prefix = KIND_PREFIX[kind]
    numbers = [_id_number(i, prefix) for i in
              (*used_ids(root, kind), *legacy_ids(root)[prefix], *reserved_ids(root)[prefix], *also_used)]
    highest = max((n for n in numbers if n is not None), default=0)
    return f"{prefix}{highest + 1}"


def _insert_id(path: Path, entry_id: str, frontmatter: bool = False) -> bool:
    """Write `id: <entry_id>` as the header's first field: directly above an existing header field
    (e.g. a question's "status: open"), inside the frontmatter when the header is one, or, when
    there was no header yet, as a new header above the heading, separated from it by a blank
    line, as frontmatter if `frontmatter` says the entry's kind is written that way
    (actlib.writes_frontmatter()). Returns False without writing anything if the file cannot be
    read as UTF-8 (the caller reports that separately, see cmd_assign)."""
    text = _safe_read(path)
    if text is None:
        return False
    head = actlib.split_header(text)[0]
    if actlib.is_frontmatter(head):
        first_line, _, rest = text.partition("\n")
        new_text = f"{first_line}\nid: {entry_id}\n{rest}"
    elif head:
        new_text = f"id: {entry_id}\n{text}"
    else:
        new_text = actlib.format_header([f"id: {entry_id}"], frontmatter) + f"\n{text}"
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(new_text)
    return True


def _started_value(text: str) -> Optional[str]:
    """The `started:` value in a task's header block, or None if the task has not started."""
    match = STARTED_RE.search(actlib.header_block(text))
    return match.group(1) if match else None


def _mark_started(path: Path) -> Optional[str]:
    """Write `started: <now>` into the task's header — right below `created:`, else below the last
    header field, else as a new header above the heading. Returns the value written, or None when
    the task already carries one or the file cannot be read as UTF-8 (nothing written then)."""
    text = _safe_read(path)
    if text is None or _started_value(text) is not None:
        return None
    value = datetime.now().isoformat(timespec="seconds")
    lines = text.split("\n")
    head = actlib.split_header(text)[0]
    head_count = head.count("\n") + (1 if head and not head.endswith("\n") else 0)
    # the field lines are lines[first:last]: all header lines, or those between the `---` delimiters
    framed = actlib.is_frontmatter(head)
    first, last = (1, head_count - 1) if framed else (0, head_count)
    if head_count == 0:
        lines[0:0] = [f"started: {value}", ""]
    else:
        created = [i for i in range(first, last) if lines[i].lower().startswith("created:")]
        lines.insert((created[-1] + 1) if created else last, f"started: {value}")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))
    return value


def _create_unique(entry_dir: Path, filename: str, text: str) -> Path:
    """Exclusively create `filename` (already the full "*.md" name a caller wants — a date-based,
    id-based, team-mode, or kind+timestamp name, see create_entry()) under entry_dir, writing `text`
    with "\\n" line endings regardless of platform default. On a name collision, retries with a
    numeric suffix inserted before the ".md" extension. Uses open(..., "x") — no check-then-write
    race — so two processes racing to create the same name never overwrite one another."""
    stem = filename[:-3] if filename.endswith(".md") else filename
    n = 1
    while True:
        name = f"{stem}.md" if n == 1 else f"{stem}-{n}.md"
        dest = entry_dir / name
        try:
            handle = open(dest, "x", encoding="utf-8", newline="\n")
        except FileExistsError:
            n += 1
            continue
        try:
            with handle:
                handle.write(text)
        except BaseException:
            dest.unlink(missing_ok=True)  # never leave an empty or half-written entry behind
            raise
        return dest


class _EntriesLock:
    """A short-lived, cooperative lock at .act-local/entries.lock — wraps id assignment plus file
    creation in cmd_new() so two `entries.py new` processes started at (nearly) the same instant
    never read the same "highest id so far" and hand out the same number. Best-effort: on a
    timeout it proceeds without the lock rather than hanging or failing outright — a collision at
    that point is still caught by check()/doctor.py, just not prevented."""

    def __init__(self, root: Path, timeout: Optional[float] = None):
        self.path = root / _LOCK_PATH
        self._held = False
        self._timeout = _LOCK_TIMEOUT if timeout is None else timeout

    def __enter__(self) -> "_EntriesLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode("ascii", "replace"))
                os.close(fd)
                self._held = True
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > _LOCK_STALE_AFTER:
                        self.path.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    return self  # proceed without the lock — see class docstring
                time.sleep(_LOCK_POLL)

    def __exit__(self, *exc_info: object) -> None:
        if self._held:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# find_duplicate_ids() / find_unreadable_entries() — reused by doctor.py, not just entries.py's
# own "check"
# ---------------------------------------------------------------------------

def find_duplicate_ids(root: Path) -> list[tuple[str, list[Path]]]:
    """(canonical id, files) for every id assigned to more than one entry file, sorted by id.
    Empty when every assigned id is unique (the common case). A file that cannot be read as UTF-8
    is silently skipped here — see find_unreadable_entries() for that, reported separately so one
    bad file doesn't hide a real duplicate among the readable ones."""
    by_id: dict[str, list[Path]] = defaultdict(list)
    for path in _entry_files(root):
        text = _safe_read(path)
        if text is None:
            continue
        for canonical in actlib.entry_ids(text):  # a collection file lists one id per section
            by_id[canonical].append(path)
    return sorted((entry_id, paths) for entry_id, paths in by_id.items() if len(paths) > 1)


def find_unreadable_entries(root: Path) -> list[Path]:
    """Entry files under _ID_SCAN_ROOTS that cannot be read as UTF-8 — surfaced as their own
    finding (entries.py check, doctor.py) instead of silently vanishing from the id scan without a
    trace."""
    return [path for path in _entry_files(root) if _safe_read(path) is None]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _single_line(value: str) -> bool:
    return bool(value.strip()) and "\n" not in value and "\r" not in value


def validate_entry(
    root: Optional[Path], kind: str, title: str, entry_id: Optional[str] = None,
    formerly: Optional[str] = None, status: Optional[str] = None, recipient: Optional[str] = None,
) -> list[str]:
    """Every reason `new` would refuse this entry, one line each (empty: fine). With `root`, an
    explicit id is also checked against used_ids() (an entry file or the archive, never a legacy
    collection file — see used_ids()); adopt_entries.py passes root=None and checks ids once for
    its whole batch instead."""
    problems: list[str] = []
    kind = _canonical_kind(kind)
    if kind not in KIND_DIR:
        return [f"unknown kind {kind!r} (task | backlog | ledger | question | todo | report | note)"]
    if not _single_line(title):
        problems.append("a one-line, non-empty title is required")
    if entry_id is not None:
        prefix = KIND_PREFIX.get(kind)
        match = _ID_ARG_RE.match(entry_id.strip())
        if prefix is None:
            problems.append(f"--id: a {kind} entry never carries an id (use --formerly for the old one)")
        elif not match or match.group(1).upper() != prefix:
            problems.append(f"--id {entry_id!r}: a {kind} id is {prefix}<n> (optionally one sub-letter, e.g. {prefix}12a)")
        elif root is not None and _canonical_id(entry_id.strip()) in used_ids(root, kind):
            problems.append(f"--id {_canonical_id(entry_id.strip())}: already taken (an entry or the archive)")
    if formerly is not None and not _single_line(formerly):
        problems.append("--formerly: a one-line, non-empty value is required")
    if status is not None and (kind not in actlib.INBOX_KINDS or status not in STATUS_VALUES):
        problems.append(f"--status {status!r}: only a question, todo, report, or note entry takes one, "
                        f"and only {' | '.join(STATUS_VALUES)}")
    if recipient is not None and (kind not in ("task", "todo", "report", "note") or not _single_line(recipient)):
        problems.append("--for: only a task, todo, report, or note entry takes a recipient "
                        "(one line; a question is always for all)")
    return problems


def create_entry(
    root: Path, kind: str, title: str, entry_id: Optional[str] = None, formerly: Optional[str] = None,
    status: Optional[str] = None, recipient: Optional[str] = None, body: str = "",
    slug: Optional[str] = None, extra_header: Optional[list[tuple[str, str]]] = None,
    lock_timeout: Optional[float] = None,
) -> tuple[Path, Optional[str]]:
    """Write one entry file, return (path, id written or None). `extra_header` adds (key, value)
    header lines of an inbox entry directly after `status:` (the quick capture writes `triage: open`).
    `lock_timeout` shortens the wait for entries.lock (seconds; default _LOCK_TIMEOUT) for a caller
    with a hard time limit. The caller has validated
    (validate_entry()). An explicit `entry_id` is written in either mode — it is an id the entry
    already had (adoption); without one, "solo" hands out the next free id and "team" leaves
    it to `assign`. `body` goes below the heading exactly as given (no newline translation).
    `slug` fixes the filename's slug (slugified) instead of deriving it from `title` — for a tool
    whose entry is found again by its name's ending (e.g. "translate-scaffold").
    Filename: "ledger" keeps its date-based name; task/backlog/question/todo get
    "<id>-<slug>.md" once an id is assigned, else (team mode, no id yet)
    "<P>-<identity>-<stamp>-<slug>.md" for `assign` to rename later; report/note (which never
    carry an id) get "<kind>-<stamp>-<slug>.md" (actlib.inbox_entry_filename())."""
    kind = _canonical_kind(kind)
    entry_dir = root / KIND_DIR[kind]
    entry_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    created_at = actlib.created_stamp(now)
    team = _mode(root) == "team"

    with _EntriesLock(root, lock_timeout):
        assigned_id: Optional[str] = None
        if entry_id is not None:
            assigned_id = _canonical_id(entry_id.strip())
        elif not team and kind in KIND_PREFIX:
            assigned_id = _next_id(root, kind)

        header_lines: list[str] = []
        if assigned_id:
            header_lines.append(f"id: {assigned_id}")
        if formerly is not None:
            header_lines.append(f"formerly: {formerly.strip()}")
        if kind == "task":
            # a task says whose work it is — the current workspace identity unless --for names
            # someone else ("all" = shared). Without an identity (no identity.json) no field is
            # written; the board counts such a task as shared.
            task_for = _recipient_value(recipient) if recipient is not None else _own_identity(root)
            if task_for:
                header_lines.append(f"for: {task_for}")
        if kind in actlib.INBOX_KINDS:
            # Every entry waiting on a person carries "for:" — "all" by default; a question
            # is never filed to just one person's own queue, so it is always "all" regardless of
            # `recipient`.
            header_lines.append(f"kind: {kind}")
            header_lines.append("for: all" if kind == "question" else f"for: {_recipient_value(recipient)}")
            header_lines.append(f"status: {status or 'open'}")
            for extra_key, extra_value in extra_header or []:
                header_lines.append(f"{extra_key}: {extra_value}")
        header_lines.append(f"created: {created_at}")

        text = (actlib.format_header(header_lines, actlib.writes_frontmatter(kind))
                + "\n" + f"# {title.strip()}\n\n" + body)
        slug = _slugify(slug if slug else title)
        if kind == "ledger":
            filename = f"{date.today().isoformat()}-{slug}.md"
        elif kind in KIND_PREFIX:
            if assigned_id:
                filename = f"{assigned_id}-{slug}.md"
            else:
                filename = f"{KIND_PREFIX[kind]}-{_identity_slug(root)}-{actlib.entry_stamp(now)}-{slug}.md"
        else:  # report | note — never carry an id
            filename = actlib.inbox_entry_filename(kind, slug, now)
        dest = _create_unique(entry_dir, filename, text)
    return dest, assigned_id


def create_todo(
    root: Path, title: str, body: str = "", slug: Optional[str] = None,
    recipient: Optional[str] = None, status: Optional[str] = None,
) -> tuple[Path, Optional[str]]:
    """The one way a tool files a todo (a task for a human) in docs/ai/inbox/ — same id handling as
    `entries.py new todo` (solo: U<n> now; team: a name awaiting `assign`), `body` below the heading.
    Returns (path, id or None)."""
    return create_entry(root, "todo", title, status=status, recipient=recipient, body=body, slug=slug)


def _inbox_has_entry_ending(root: Path, suffix: str) -> bool:
    """True when docs/ai/inbox/ holds a file ending in `suffix` — any name form (an id, an old
    timestamp, a team-mode name awaiting its id), open or answered."""
    inbox = root / actlib.INBOX_DIR
    return inbox.is_dir() and any(inbox.glob(f"*{suffix}"))


def _planned_todo_path(root: Path, slug: str) -> Path:
    """The path create_todo(root, ..., slug=slug) would write now, for a plan-mode run: solo
    "U<next>-<slug>.md", team "U-<identity>-<stamp>-<slug>.md" (the name awaiting `assign`).
    Reads only; the stamp may differ by a minute from a later real run, as the number may if
    something else is filed in between."""
    slug = _slugify(slug)
    if _mode(root) == "team":
        name = f"{KIND_PREFIX['todo']}-{_identity_slug(root)}-{actlib.entry_stamp()}-{slug}.md"
    else:
        name = f"{_next_id(root, 'todo')}-{slug}.md"
    return root / actlib.INBOX_DIR / name


def write_translate_note(root: Path, language: str, plan: bool = False) -> Optional[Path]:
    """File the one-time scaffold-translation todo (slug "translate-scaffold") unless the docs
    language is English, no file carries `act:default`, or such an entry already exists. Returns
    the path that was (plan: would be) written, else None."""
    if actlib.is_english(language):
        return None
    files = actlib.scaffold_default_files(root)
    if not files or _inbox_has_entry_ending(root, actlib.TRANSLATE_NOTE_SUFFIX):
        return None
    title, body = actlib.translate_note_parts(language, files, root)
    if plan:
        return _planned_todo_path(root, "translate-scaffold")
    return create_todo(root, title, body, slug="translate-scaffold")[0]


def write_dependency_check_note(root: Path, dependency_check: str, plan: bool = False) -> Optional[Path]:
    """File the one-time dependency-check todo (slug "dependency-check") when `dependency-check`
    (read from the config.md this run just wrote/kept) is `once` and no such entry exists yet — a
    second `init` run must not add a second one. Returns the path that was (plan: would be)
    written, else None."""
    if dependency_check.strip().lower() != "once":
        return None
    if _inbox_has_entry_ending(root, actlib.DEPENDENCY_CHECK_NOTE_SUFFIX):
        return None
    title, body = actlib.dependency_check_note_parts(actlib.docs_language(root))
    if plan:
        return _planned_todo_path(root, "dependency-check")
    return create_todo(root, title, body, slug="dependency-check")[0]


def cmd_new(
    root: Path, kind: str, title_words: list[str], entry_id: Optional[str] = None,
    formerly: Optional[str] = None, status: Optional[str] = None, recipient: Optional[str] = None,
    body_file: Optional[str] = None,
) -> int:
    kind = _canonical_kind(kind)
    title = " ".join(title_words).strip()
    problems = validate_entry(root, kind, title, entry_id, formerly, status, recipient)
    body = ""
    if body_file is not None:
        try:
            # Bytes, decoded strictly: no newline translation, so the human's text lands byte for byte.
            body = Path(body_file).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            problems.append(f"--body-file {body_file}: cannot read as UTF-8 ({exc.__class__.__name__})")
    if problems:
        for problem in problems:
            print(f"entries: {problem} — nothing written", file=sys.stderr)
        return 2

    dest, assigned_id = create_entry(root, kind, title, entry_id, formerly, status, recipient, body)
    if kind == "ledger":
        label = "no id — journal entries aren't numbered"
    elif kind in ("report", "note"):
        label = "no id — inbox entries carry kind:/for:/status:"
    elif assigned_id:
        label = assigned_id
    else:
        label = "id assigned by `entries.py assign` on the default branch"
    print(f"entries: created {_rel(dest, root)} [{label}]")
    return 0


def cmd_assign(root: Path) -> int:
    if _mode(root) == "team":
        default = _default_branch(root)
        if default is None:
            print(
                "entries: mode is 'team' but the default branch could not be determined "
                "(no origin/HEAD, no origin/main, no origin/master) — run `git remote set-head "
                "origin --auto` once there is a real 'origin' remote; no ids assigned"
            )
            return 0
        current = board.get_branch(root)
        if not current or current != default:
            print(
                "entries: mode is 'team' and the current branch "
                f"({current or 'unknown'!r}) is not the default branch ({default!r}) "
                "— no ids assigned"
            )
            return 0
        behind = board.run_git(["rev-list", "--count", f"{current}..origin/{current}"], root)
        if behind is not None and behind.strip().isdigit() and int(behind.strip()) > 0:
            print(
                f"entries: warning — local '{current}' is {behind.strip()} commit(s) behind "
                f"'origin/{current}' — assigning anyway, `git pull` afterward"
            )

    assigned: list[tuple[str, Path, Path]] = []
    unreadable: list[Path] = []
    # "question" and "todo" share actlib.INBOX_DIR (task and backlog have a directory each), so a
    # file there is only handed an id of its own kind (actlib.inbox_kind()) — a report or note never
    # gets one, and a todo is never mistaken for a question.
    for kind in KIND_PREFIX:
        entry_dir = root / KIND_DIR[kind]
        if not entry_dir.is_dir():
            continue
        candidates: list[tuple[str, str, Path]] = []
        for path in sorted(entry_dir.glob("*.md")):
            if path.name.lower() == "readme.md":
                continue
            text = _safe_read(path)
            if text is None:
                unreadable.append(path)
                continue
            if kind in actlib.INBOX_KINDS and actlib.inbox_kind(text) != kind:
                continue
            if _entry_id(text) is not None:
                continue
            created = board.CREATED_RE.search(actlib.header_block(text))
            candidates.append((created.group(1).strip() if created else "", path.name, path))
        # several entries awaiting a number get it in the order they were created, then by name
        for _created, _name, path in sorted(candidates):
            entry_id = _next_id(root, kind)
            if not _insert_id(path, entry_id, actlib.writes_frontmatter(kind)):
                continue
            new_path = _rename_with_id(path, entry_id)
            assigned.append((entry_id, path, new_path))

    for path in unreadable:
        print(f"entries: cannot read {_rel(path, root)} (not valid UTF-8) — skipped", file=sys.stderr)
    if not assigned:
        if not unreadable:
            print("entries: no missing ids")
        return 0
    for entry_id, old_path, new_path in assigned:
        print(f"entries: assigned {entry_id}: {_rel(old_path, root)} -> {_rel(new_path, root)}")
    return 0


def _task_path_for_id(root: Path, raw_id: str) -> tuple[Optional[Path], Optional[str]]:
    """(task file path, canonical id) for `raw_id`, or (None, None) with a reason string as the
    third element consumed by the caller — see cmd_state(). Scans docs/ai/work/tasks/ only (not
    the archive, not the other kinds sharing a prefix table): a task's working state is only ever
    written while the task is still open."""
    match = _ID_ARG_RE.match(raw_id.strip())
    if not match or match.group(1).upper() != KIND_PREFIX["task"]:
        return None, f"{raw_id!r}: not a task id (a task id is T<n>, optionally one sub-letter)"
    canonical = _canonical_id(raw_id.strip())
    task_dir = root / KIND_DIR["task"]
    if task_dir.is_dir():
        for path in sorted(task_dir.glob("*.md")):
            if path.name.lower() == "readme.md":
                continue
            text = _safe_read(path)
            if text is not None and _entry_id(text) == canonical:
                return path, None
    return None, f"{canonical}: no open task with this id under {KIND_DIR['task'].as_posix()}"


def cmd_state(root: Path, raw_id: str, text_words: list[str], wait: bool = False) -> int:
    text = " ".join(text_words).strip()
    if not text:
        print("entries: state text must not be empty — nothing written", file=sys.stderr)
        return 2
    result = _task_path_for_id(root, raw_id)
    path, problem = result
    if path is None:
        print(f"entries: {problem} — nothing written", file=sys.stderr)
        return 2
    state_dir = root / STATE_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / path.name
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(state_path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"State {stamp}{' (wait)' if wait else ''}: {text}\n")
    started = _mark_started(path)
    entry_id = _entry_id(_safe_read(path) or "") or _canonical_id(raw_id.strip())
    suffix = " — task marked started" if started else ""
    print(f"entries: appended state for {entry_id} to {_rel(state_path, root)}{suffix}")
    return 0


def cmd_start(root: Path, raw_id: str) -> int:
    path, problem = _task_path_for_id(root, raw_id)
    if path is None:
        print(f"entries: {problem} — nothing written", file=sys.stderr)
        return 2
    started = _mark_started(path)
    text = _safe_read(path) or ""
    entry_id = _entry_id(text) or _canonical_id(raw_id.strip())
    if started:
        print(f"entries: {entry_id} marked started")
    else:
        print(f"entries: {entry_id} already started ({_started_value(text) or 'unreadable'})")
    return 0


def cmd_list(root: Path, kind: Optional[str]) -> int:
    # actlib.INBOX_DIR is shared by four kinds (question/todo/report/note): a section here lists
    # only the entries whose own actlib.inbox_kind() matches it, so each inbox file is shown once,
    # under its own kind — never once per kind that happens to share the directory.
    kind = _canonical_kind(kind) if kind else None
    kinds = [kind] if kind else list(KIND_DIR)
    for one_kind in kinds:
        entry_dir = root / KIND_DIR[one_kind]
        if not entry_dir.is_dir():
            continue
        print(f"== {one_kind} ==")
        for entry_path in sorted(entry_dir.glob("*.md")):
            if entry_path.name.lower() == "readme.md":
                continue
            text = _safe_read(entry_path)
            if text is None:
                print(f"  {'(unreadable)':<10} {entry_path.name} — cannot read as UTF-8")
                continue
            if one_kind in actlib.INBOX_KINDS and actlib.inbox_kind(text) != one_kind:
                continue
            entry_id = (_entry_id(text) or "(unassigned)") if one_kind in KIND_PREFIX else "-"
            title = _first_heading(entry_path) or entry_path.stem
            print(f"  {entry_id:<10} {entry_path.name} — {title}")
    return 0


def cmd_check(root: Path) -> int:
    problem = False
    for path in find_unreadable_entries(root):
        print(f"entries: cannot read {_rel(path, root)} (not valid UTF-8)", file=sys.stderr)
        problem = True
    for entry_id, paths in find_duplicate_ids(root):
        names = ", ".join(_rel(p, root) for p in paths)
        print(f"entries: duplicate id {entry_id}: {names}", file=sys.stderr)
        problem = True
    if not problem:
        print("entries: no duplicate ids found")
        return 0
    return 1


# ---------------------------------------------------------------------------
# archive — move a finished entry and the local files it links
# ---------------------------------------------------------------------------

ARCHIVE_DIR = Path("docs/ai/work/archive")
CONCEPT_DIR = Path("docs/ai/concept")

# A Markdown inline link or image: `[text](target "title")` / `![alt](<target with spaces>)`. Groups:
# opener `[` or `![`, the text (which may hold one nested `[...]`, as in `[![a](x.png)](x.png)`), `](`,
# the target, and the optional title with the closing bracket. The target is `<...>` or the shortest run
# up to an optional title (`"..."`, `'...'` or `(...)`) and the closing bracket, so a raw target with
# spaces (an IDE pasting "Pasted image 1.png") is one target, and balanced brackets in it
# ("image (1).png") stay part of it.
_MD_LINK_RE = re.compile(
    r"(!?\[)((?:[^\[\]\n]|\[[^\]\n]*\])*)(\]\(\s*)"
    r"(<[^>\n]*>|(?:[^()\n]|\([^()\n]*\))+?)"
    r"""((?:\s+(?:"[^"\n]*"|'[^'\n]*'|\([^()\n]*\)))?\s*\))""")
_CODE_SPAN_RE = re.compile(r"(`+)(?!`).+?(?<!`)\1(?!`)")
_HTML_SRC_RE = re.compile(r"""(<img\b[^>]*?\bsrc\s*=\s*)(["'])(.*?)\2""", re.IGNORECASE)
_URL_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]+:|^[A-Za-z]:[\\/]")  # a URL or a drive path
# Names an IDE or screenshot tool hands out again and again; two entries would both own an "img.png".
_GENERIC_STEM_RE = re.compile(r"^(?:(?:img|image|bild|foto|photo|clipboard|untitled|unbenannt)[ _-]?\d*"
                              r"|(?:pasted image|screenshot|screen shot|bildschirmfoto).*)$", re.IGNORECASE)


class ArchiveError(Exception):
    """A refusal of `archive` that is raised before anything is written."""


def _split_target(raw: str) -> Optional[tuple[str, str]]:
    """(decoded path, suffix with fragment/query) for a link target that names a local relative
    file, else None (empty, anchor-only, URL, absolute path)."""
    text = raw.strip()
    if text.startswith("<") and text.endswith(">"):
        text = text[1:-1].strip()
    if not text or text.startswith(("#", "/", "\\")) or _URL_SCHEME_RE.match(text):
        return None
    cut = min((i for i in (text.find("#"), text.find("?")) if i >= 0), default=len(text))
    path, suffix = text[:cut], text[cut:]
    return (urllib.parse.unquote(path), suffix) if path else None


def _format_target(raw: str, path: str, suffix: str, html: bool) -> str:
    """The new link target for `path`, written in the style `raw` used (angle brackets, percent
    encoding, or plain); a space always gets escaped or bracketed so the link keeps working."""
    if html:
        return urllib.parse.quote(path, safe="/.-_~()") + suffix
    if raw.strip().startswith("<"):
        return f"<{path}{suffix}>"
    if "%" in raw:
        return urllib.parse.quote(path, safe="/.-_~()") + suffix
    return f"<{path}{suffix}>" if " " in path else path + suffix


# A mapper returns the new link path, or (path, fragment) to also replace the fragment, or None to keep the link.
LinkMapper = Callable[[str, Path], Union[None, str, tuple[str, str]]]


def _rewrite_segment(segment: str, base: Path, mapper: LinkMapper) -> str:
    """`segment` (a piece of one line outside inline code) with every local link target mapped."""

    def new_target(raw: str) -> Optional[tuple[str, str]]:
        parts = _split_target(raw)
        if parts is None:
            return None
        path, suffix = parts
        new = mapper(path, Path(os.path.normpath(base / path)))
        if new is None:
            return None
        if isinstance(new, tuple):  # the target was merged: its old fragment names nothing in the new file
            query = suffix[:suffix.find("#")] if "#" in suffix else suffix
            return (new[0], f"{query}#{new[1]}")
        return (new, suffix)

    def fix_markdown(match: "re.Match[str]") -> str:
        opener, text, middle, raw, tail = match.groups()
        text = _MD_LINK_RE.sub(fix_markdown, text)  # `[![alt](a.png)](a.png)`: the inner image too
        mapped = new_target(raw)
        target = raw if mapped is None else _format_target(raw, mapped[0], mapped[1], False)
        return f"{opener}{text}{middle}{target}{tail}"

    def fix_html(match: "re.Match[str]") -> str:
        mapped = new_target(match.group(3))
        if mapped is None:
            return match.group(0)
        return f"{match.group(1)}{match.group(2)}{_format_target(match.group(3), mapped[0], mapped[1], True)}{match.group(2)}"

    return _HTML_SRC_RE.sub(fix_html, _MD_LINK_RE.sub(fix_markdown, segment))


def _rewrite_links(text: str, base: Path, mapper: LinkMapper) -> str:
    """Apply `mapper(target path, resolved path)` to every local link outside a fenced code block
    and inline code; it returns the new link path (relative, "/" separators) or None to keep the
    link. The resolved path is `base` + the link target, normalised (symlinks untouched)."""
    out: list[str] = []
    fence: actlib.FenceState = None
    for line in text.split("\n"):
        was_fenced, fence = fence is not None, actlib.fence_step(fence, line)
        if was_fenced or fence is not None:  # a fence line or a line inside a fenced block
            out.append(line)
            continue
        pieces: list[str] = []
        position = 0
        for code in _CODE_SPAN_RE.finditer(line):
            pieces.append(_rewrite_segment(line[position:code.start()], base, mapper))
            pieces.append(code.group(0))
            position = code.end()
        pieces.append(_rewrite_segment(line[position:], base, mapper))
        out.append("".join(pieces))
    return "\n".join(out)


def linked_local_files(text: str, base: Path) -> set[Path]:
    """Every existing file `text` links by a relative path (Markdown link or image, `<img src>`),
    resolved against `base`. doctor.py uses it to find files nothing links to."""
    found: set[Path] = set()

    def collect(_path: str, resolved: Path) -> None:
        if resolved.is_file():
            found.add(resolved)

    _rewrite_links(text, base, lambda p, r: collect(p, r))
    return found


def _set_status_done(text: str) -> str:
    """`text` with `status: done` in its header — an existing status replaced, else the field added
    at the end of the header (a new frontmatter if the file has no header at all)."""
    return _set_header_field(text, "status", "done")


def _set_header_field(text: str, key: str, value: str) -> str:
    """`text` with `<key>: <value>` in its header: an existing field replaced, else the field added
    at the end of the header (a new frontmatter if the file has no header at all)."""
    head, body = actlib.split_header(text)
    if not head.strip():
        return actlib.format_header([f"{key}: {value}"], True) + f"\n{text}"
    lines = head.split("\n")
    framed = actlib.is_frontmatter(head)
    end = len(lines)
    if framed:
        end = max(i for i, line in enumerate(lines) if line.rstrip() == actlib.FRONTMATTER_DELIMITER)
    for index, line in enumerate(lines[:end]):
        if re.match(rf"(?i){re.escape(key)}:", line):
            lines[index] = f"{key}: {value}"
            return "\n".join(lines) + body
    while end > 0 and not lines[end - 1].strip() and not framed:
        end -= 1
    lines.insert(end, f"{key}: {value}")
    return "\n".join(lines) + body


def _find_archivable(root: Path, ref: str) -> Path:
    """The entry file for an id ("Q<n>") or a path, which must sit directly in the tasks, backlog or
    inbox folder."""
    folders = [root / KIND_DIR["task"], root / KIND_DIR["backlog"], root / actlib.INBOX_DIR]
    candidate = Path(ref)
    if candidate.suffix.lower() == ".md" or candidate.exists():
        for option in ([candidate] if candidate.is_absolute() else [Path.cwd() / candidate, root / candidate]):
            if option.is_file():
                resolved = Path(os.path.normpath(option.resolve()))
                if any(resolved.parent == folder.resolve() for folder in folders):
                    return resolved
                raise ArchiveError(f"{ref}: not directly in docs/ai/work/tasks, docs/ai/work/backlog or "
                                   f"{actlib.INBOX_DIR.as_posix()} — only those entries are archived")
        raise ArchiveError(f"{ref}: no such file")
    if not _ID_ARG_RE.match(ref.strip()):
        raise ArchiveError(f"{ref!r}: neither an existing file nor an id (T<n>, B<n>, Q<n>, U<n>)")
    wanted = _canonical_id(ref.strip())
    hits: list[Path] = []
    for folder in folders:
        if folder.is_dir():
            for path in sorted(folder.glob("*.md")):
                text = _safe_read(path)
                if path.name.lower() != "readme.md" and text is not None and _entry_id(text) == wanted:
                    hits.append(path)
    if not hits:
        raise ArchiveError(f"{wanted}: no entry with this id under tasks, backlog or inbox")
    if len(hits) > 1:
        raise ArchiveError(f"{wanted}: more than one entry carries this id: "
                           + ", ".join(_rel(p, root) for p in hits))
    return hits[0]


def _attachment_label(entry: Path, entry_id: Optional[str]) -> str:
    """The prefix for a renamed attachment: the entry's id, else the "<kind>-<stamp>" start of its
    file name, else its file stem."""
    if entry_id:
        return entry_id
    match = re.match(r"^([A-Za-z]+-\d{8}-\d{4})", entry.stem)
    return match.group(1) if match else entry.stem


@dataclass
class ArchivePlan:
    """What `archive` is going to do for one entry."""

    text: str  # the entry's new text
    dest: Path  # where the entry goes
    entry_id: Optional[str]
    inbox: bool  # an inbox entry also gets `status: done`
    names: dict[Path, str] = field(default_factory=dict)  # attachment -> its file name in the archive
    shared: set[Path] = field(default_factory=set)  # attachments a staying file still links: copied
    relinked: list[tuple[str, str]] = field(default_factory=list)  # (old, new) link targets
    outside: list[tuple[Path, Path]] = field(default_factory=list)  # (link, real file) left in place


def _is_inside(path: Path, folder: Path) -> bool:
    return folder == path or folder in path.parents


def plan_archive(root: Path, entry: Path, today: Optional[date] = None) -> ArchivePlan:
    """Everything `archive` is going to do for `entry`, computed without touching a file: the new
    text, the destination, and the attachments to move or copy. Raises ArchiveError on a refusal."""
    text = _safe_read(entry)
    if text is None:
        raise ArchiveError(f"{_rel(entry, root)}: cannot be read as UTF-8")
    archive = root / ARCHIVE_DIR
    dest = archive / entry.name
    if dest.exists():
        raise ArchiveError(f"{_rel(dest, root)} already exists")
    entry_id = _entry_id(text)
    is_inbox = entry.parent == (root / actlib.INBOX_DIR).resolve()
    entry_dir = entry.parent
    plan = ArchivePlan(text=text, dest=dest, entry_id=entry_id, inbox=is_inbox)

    # which linked files travel: non-Markdown files inside the entry's own folder. A link that leads
    # out of the folder through a symlink is left alone and reported.
    movable: list[Path] = []

    def scan(_path: str, resolved: Path) -> None:
        if not (resolved.is_file() and resolved.suffix.lower() != ".md" and entry_dir in resolved.parents):
            return
        real = Path(os.path.normpath(resolved.resolve()))
        if not _is_inside(real, entry_dir):
            if (resolved, real) not in plan.outside:
                plan.outside.append((resolved, real))
        elif resolved not in movable:
            movable.append(resolved)

    _rewrite_links(text, entry_dir, scan)

    # a file any other Markdown file under docs/ still links is copied, not moved (the archive itself
    # included: an archived entry may share the picture)
    if movable:
        docs = root / "docs"
        seen: set[Path] = set()
        for other in docs.rglob("*.md") if docs.is_dir() else []:
            other = Path(os.path.normpath(other))
            if other == entry or other in seen:
                continue
            seen.add(other)
            other_text = _safe_read(other)
            if other_text is not None:
                plan.shared |= linked_local_files(other_text, other.parent) & set(movable)

    label = _attachment_label(entry, entry_id)
    # names are compared case-insensitively: the archive may sit on a case-insensitive file system
    taken = {p.name.casefold() for p in archive.iterdir()} if archive.is_dir() else set()
    for source in movable:
        name = source.name
        if _GENERIC_STEM_RE.match(source.stem) or name.casefold() in taken:
            name = name if name.startswith(f"{label}-") else f"{label}-{name}"
        base_name = name
        counter = 2
        while name.casefold() in taken:
            name = f"{Path(base_name).stem}-{counter}{Path(base_name).suffix}"
            counter += 1
        taken.add(name.casefold())
        plan.names[source] = name

    def remap(path: str, resolved: Path) -> Optional[str]:
        if resolved in plan.names:
            new = plan.names[resolved]
        elif resolved.exists():
            try:
                new = Path(os.path.relpath(resolved, archive)).as_posix()
            except ValueError:  # another drive: no relative path exists, keep the link as written
                return None
        else:
            return None
        if new != path:
            plan.relinked.append((path, new))
            return new
        return None

    plan.text = _rewrite_links(text, entry_dir, remap)
    if is_inbox:
        plan.text = _set_status_done(plan.text)
    plan.text = _set_header_field(plan.text, "archived", (today or date.today()).isoformat())
    return plan


def cmd_archive(root: Path, ref: str) -> int:
    try:
        entry = _find_archivable(root, ref)
        plan = plan_archive(root, entry)
    except ArchiveError as exc:
        print(f"entries: {exc} — nothing changed", file=sys.stderr)
        return 2
    archive = root / ARCHIVE_DIR
    dest = plan.dest
    created: list[Path] = []
    try:
        archive.mkdir(parents=True, exist_ok=True)
        with open(dest, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(plan.text)
        created.append(dest)
        for source, name in plan.names.items():
            target = archive / name
            shutil.copy2(source, target)
            created.append(target)
        entry.unlink()  # last step that can fail the whole run; the rollback below covers it
    except OSError as exc:
        stuck: list[str] = []
        for path in created:
            try:
                path.unlink()
            except OSError as undo_exc:
                stuck.append(f"{_rel(path, root)} ({undo_exc!r})")
        print(f"entries: archiving {_rel(entry, root)} failed ({exc!r}) — the entry stays where it is",
              file=sys.stderr)
        if stuck:
            print("entries: could not remove what was already written, delete it by hand: "
                  + ", ".join(stuck), file=sys.stderr)
        return 2
    label = plan.entry_id or entry.stem
    print(f"entries: archived {label}: {_rel(entry, root)} -> {_rel(dest, root)}"
          + (" (status: done)" if plan.inbox else ""))
    status = 0
    for source, name in plan.names.items():
        if source in plan.shared:
            print(f"entries: copied {_rel(source, root)} -> {_rel(archive / name, root)} (still linked elsewhere)")
            continue
        try:
            source.unlink()
        except OSError as exc:
            print(f"entries: copied {_rel(source, root)} -> {_rel(archive / name, root)}, but could not remove "
                  f"the original ({exc!r}) — delete it by hand", file=sys.stderr)
            status = 1
            continue
        print(f"entries: moved {_rel(source, root)} -> {_rel(archive / name, root)}")
    for link, real in plan.outside:
        print(f"entries: left {_rel(link, root)} in place — it leads to {real}, outside the entry's folder")
    for old, new in plan.relinked:
        print(f"entries: relinked {old} -> {new} in {_rel(dest, root)}")
    return status


# ---------------------------------------------------------------------------
# compact — merge old archived entries into one collection file per kind and month
# ---------------------------------------------------------------------------

LEDGER_DIR = Path("docs/ai/work/ledger")
COMPACT_KEEP_DAYS = 7  # the newest week stays as single files: it is still linked to and looked up
_LEDGER_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-")
_OVERVIEW_NAME_RE = re.compile(r"^\d{4}-\d{2}\.md$")  # the monthly topic overview: written by hand, never folded
_ANY_ANCHOR_RE = re.compile(r'^<a id="[^"\n]+"></a>\s*$')
_SKIP_WALK_DIRS = {".git", ".act", ".act-local", "node_modules", ".venv", "venv", "__pycache__"}


class CompactError(Exception):
    """A refusal of `compact` that is raised before anything is written."""


@dataclass
class CompactItem:
    """One single file `compact` is going to fold into a collection."""

    path: Path
    origin: str  # project-relative folder the file lives in (archive or journal)
    group: str  # "Q" | "T" | "B" | "U" | "other" | "ledger"
    day: date  # the archive date (a journal entry: its file name's date)
    anchor: str
    section: str  # the section text; links are still relative to the original folder

    @property
    def month(self) -> str:
        return self.day.strftime("%Y-%m")

    @property
    def collection_name(self) -> str:
        return f"{self.group}-{self.month}.md"


def _git_text(args: list[str], root: Path) -> Optional[str]:
    """stdout of `git <args>` decoded as UTF-8 with paths left unquoted (`core.quotePath=false`), or
    None if git fails; board.run_git decodes with the console code page, which garbles file names."""
    try:
        result = subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=root, capture_output=True,
                                check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.decode("utf-8", errors="replace")


def _git_added_days(root: Path, folder: Path) -> dict[str, date]:
    """posix path (relative to `root`) -> the day the file was first added under `folder`, from one
    `git log`; a move into the archive counts as an add there (rename detection off)."""
    output = _git_text(["log", "--no-renames", "--diff-filter=A", "--name-only", "--format=@@%as", "--",
                       folder.as_posix()], root)
    found: dict[str, date] = {}
    current: Optional[date] = None
    for line in (output or "").splitlines():
        line = line.strip()
        if line.startswith("@@"):
            try:
                current = date.fromisoformat(line[2:])
            except ValueError:
                current = None
        elif line and current is not None and (line not in found or current < found[line]):
            found[line] = current
    return found


def _field_day(header: str, key: str) -> Optional[date]:
    """The date a header field starts with (`created: 2026-10-08T10:00:00` -> 2026-10-08), or None."""
    match = re.search(rf"(?im)^{key}:\s*(\d{{4}}-\d{{2}}-\d{{2}})", header)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _heading_split(text: str) -> tuple[str, str]:
    """(title, body) of an entry: a Markdown heading (`#` to `######` and a space) that comes before the
    first running text, outside a fenced code block, is the title and is taken out of the body, which is
    everything below the header without that line. Any other text, a `#` line in a code block included,
    stays in the body whole."""
    lines = actlib.split_header(text)[1].split("\n")
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if re.match(r"^#{1,6}\s", line):
            return line.lstrip("#").strip(), "\n".join(lines[:index] + lines[index + 1:]).strip("\n")
        break
    return "", "\n".join(lines).strip("\n")


def _inline_code(content: str) -> str:
    """`content` as one inline-code span: the delimiter is one backtick longer than the longest run
    inside, with a padding space where the content starts or ends with a backtick."""
    longest = max((len(run) for run in re.findall(r"`+", content)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if content.startswith("`") or content.endswith("`") else ""
    return f"{fence}{pad}{content}{pad}{fence}"


def _build_section(path: Path, text: str, entry_id: Optional[str], day: date) -> tuple[str, str]:
    """(anchor, section text) for one single entry: anchor line, heading, the header fields in one
    inline-code line (with `archived:` and the original `file:`), then the body."""
    title, body = _heading_split(text)
    fields = [line for line in actlib.header_block(text).split("\n")
              if line.strip() and not re.match(r"(?i)id:", line)]
    if not any(re.match(r"(?i)archived:", line) for line in fields):
        fields.append(f"archived: {day.isoformat()}")
    fields.append(f"file: {path.name}")
    anchor = entry_id if entry_id else path.stem
    heading = f"## {entry_id} — {title or path.stem}" if entry_id else f"## {title or path.stem}"
    parts = [f'<a id="{anchor}"></a>', heading, _inline_code(" · ".join(fields))]
    if body:
        parts += ["", body]
        fence: actlib.FenceState = None
        for line in body.split("\n"):
            fence = actlib.fence_step(fence, line)
        if fence is not None:  # an unclosed fence would swallow the next section
            parts.append(actlib.fence_closer(fence))
    return anchor, "\n".join(parts) + "\n"


def _id_sort_number(anchor: str) -> int:
    match = _ID_ARG_RE.match(anchor)
    return int(match.group(2)) if match else 0


def plan_compact(root: Path, today: date) -> tuple[list[CompactItem], list[str], int]:
    """(items to fold, notes on files left alone, number of single files kept because they are
    newer than the keep window), computed without touching a file. A collection file, a README,
    a subfolder (legacy/, proposals/) and an entry whose id is carried twice are never folded."""
    archive = root / ARCHIVE_DIR
    ledger = root / LEDGER_DIR
    sources: list[tuple[Path, bool]] = []  # (file, lives in the journal folder)
    for folder, journal in ((archive, False), (ledger, True)):
        if folder.is_dir():
            sources += [(p, journal) for p in sorted(folder.glob("*.md"))
                        if p.is_file() and p.name.lower() != "readme.md"]
    duplicated = {entry_id for entry_id, _paths in find_duplicate_ids(root)}
    cutoff = today - timedelta(days=COMPACT_KEEP_DAYS)
    git_days: Optional[dict[str, date]] = None
    items: list[CompactItem] = []
    notes: list[str] = []
    kept = 0
    for path, journal in sources:
        text = _safe_read(path)
        if text is None:
            notes.append(f"left {_rel(path, root)} - not valid UTF-8")
            continue
        if actlib.is_collection(text) or (not journal and _OVERVIEW_NAME_RE.match(path.name)):
            continue
        header = actlib.header_block(text)
        ids = actlib.entry_ids(text)
        entry_id = ids[0] if ids else None
        if entry_id in duplicated:
            notes.append(f"left {_rel(path, root)} - id {entry_id} is carried by more than one entry")
            continue
        named = _LEDGER_NAME_RE.match(path.name)
        as_journal = journal or (named is not None and entry_id is None)
        day = None
        if as_journal and named:
            try:
                day = date.fromisoformat(named.group(1))
            except ValueError:
                notes.append(f"left {_rel(path, root)} - {named.group(1)} in the file name is not a valid date")
                continue
        if day is None:
            day = _field_day(header, "archived")
        if day is None and not journal:
            if git_days is None:
                git_days = _git_added_days(root, ARCHIVE_DIR)
            day = git_days.get(_rel(path, root))
        if day is None:
            day = _field_day(header, "created") or date.fromtimestamp(path.stat().st_mtime)
        if day >= cutoff:
            kept += 1
            continue
        prefix = entry_id[0] if entry_id and entry_id[0] in "QTBU" and entry_id[1:2].isdigit() else None
        group = prefix or ("ledger" if as_journal else "other")
        anchor, section = _build_section(path, text, entry_id, day)
        items.append(CompactItem(path=path, origin=_rel(path.parent, root), group=group, day=day,
                                 anchor=anchor, section=section))
    items.sort(key=lambda item: (item.group, item.day, _id_sort_number(item.anchor), item.path.name))
    return items, notes, kept


def _walk_markdown(root: Path) -> list[Path]:
    """Every Markdown file of the project that may link to an archived entry: not the tool and
    dependency folders, not the legacy archive."""
    legacy = os.path.normcase(os.path.normpath(root / LEGACY_ROOT))
    found: list[Path] = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_WALK_DIRS
                   and os.path.normcase(os.path.normpath(os.path.join(folder, d))) != legacy]
        found += [Path(folder) / name for name in files if name.lower().endswith(".md")]
    return sorted(found)


def _collection_text(existing: Optional[str], members: list[CompactItem], sections: list[str],
                     commit: str, today: date) -> str:
    """The new text of a collection file: a fresh one, or `existing` with one more line in its head
    naming the commit that still holds the full text, and the new sections appended."""
    bullets = [f"- {today.isoformat()}, full text: `git show {commit}:{origin}/<file>` "
               "(`<file>` is the `file:` value in the second line of a section)"
               for origin in sorted({item.origin for item in members})]
    if existing is None:
        head = [actlib.COLLECTION_MARK, f"# {members[0].group} — {members[0].month}", "",
                "Archived entries of one kind and month, merged by `entries.py compact`, one section per entry. "
                "The single files stay in Git:", ""] + bullets + [""]
        return "\n".join(head) + "\n" + "\n".join(sections)
    lines = existing.replace("\r\n", "\n").split("\n")
    first = next((i for i in range(len(lines) - 1)
                  if _ANY_ANCHOR_RE.match(lines[i]) and lines[i + 1].startswith("## ")), len(lines))
    head = lines[:first]
    while head and not head[-1].strip():
        head.pop()
    rest = "\n".join(lines[first:]).rstrip("\n")
    return "\n".join(head + bullets + [""]) + "\n" + (rest + "\n\n" if rest else "") + "\n".join(sections)


def _porcelain_paths(output: str) -> set[str]:
    """Every path named in `git status --porcelain -z` output; a rename or copy entry names two."""
    names: set[str] = set()
    parts = output.split("\0")
    index = 0
    while index < len(parts):
        entry = parts[index]
        index += 1
        if len(entry) < 4:
            continue
        names.add(entry[3:])
        if entry[0] in "RC" or entry[1] in "RC":
            if index < len(parts):
                names.add(parts[index])
            index += 1
    return names


def cmd_compact(root: Path, plan_only: bool, today: Optional[date] = None) -> int:
    today = today or date.today()
    items, notes, kept = plan_compact(root, today)
    for note in notes:
        print(f"entries: {note}")
    if not items:
        print(f"entries: nothing to compact ({kept} single file(s) newer than {COMPACT_KEEP_DAYS} days stay)")
        return 0
    archive = root / ARCHIVE_DIR
    groups: dict[str, list[CompactItem]] = defaultdict(list)
    for item in items:
        groups[item.collection_name].append(item)
    targets = {os.path.normcase(os.path.normpath(item.path)): (item.collection_name, item.anchor) for item in items}
    for name in groups:
        if (archive / name).is_file() and _safe_read(archive / name) is None:
            raise CompactError(f"{_rel(archive / name, root)} exists but is not valid UTF-8: it would be "
                               "replaced instead of extended")

    commit = (board.run_git(["rev-parse", "--short=12", "HEAD"], root) or "").strip()
    pending = _git_text(["status", "--porcelain", "-z", "--untracked-files=all", "--", ARCHIVE_DIR.as_posix(),
                         LEDGER_DIR.as_posix()], root)
    wanted = {_rel(item.path, root) for item in items}
    dirty = sorted(name for name in _porcelain_paths(pending or "") if name in wanted)
    if not plan_only:
        if not commit or pending is None:
            raise CompactError("needs a Git repository with a commit: the full text of every merged entry has "
                               "to stay recoverable from Git")
        if dirty:
            raise CompactError("commit these first, their full text is not in Git yet: " + ", ".join(dirty))

    verb = "would compact" if plan_only else "compacted"
    for item in items:
        print(f"entries: {verb} {item.anchor}: {_rel(item.path, root)} -> "
              f"{_rel(archive / item.collection_name, root)}#{item.anchor}")
    if plan_only:
        print(f"entries: plan - {len(items)} entr(ies) into {len(groups)} collection file(s), {kept} newer single "
              f"file(s) stay; nothing written" + (f"; not committed yet: {', '.join(dirty)}" if dirty else ""))
        return 0

    def mapper_for(dest_base: Path, everything: bool) -> LinkMapper:
        """Link mapper for text that ends up in `dest_base`: a link to a merged entry becomes the
        collection plus anchor; with `everything`, any other existing target is re-based as well
        (a journal entry moves to another folder)."""
        def mapper(path: str, resolved: Path) -> Optional[str]:
            key = os.path.normcase(os.path.normpath(resolved))
            try:
                if key in targets:
                    name, anchor = targets[key]
                    return Path(os.path.relpath(archive / name, dest_base)).as_posix(), anchor
                if everything and resolved.exists():
                    new = Path(os.path.relpath(resolved, dest_base)).as_posix()
                    return None if new == path else new
            except ValueError:  # another drive: keep the link as written
                return None
            return None
        return mapper

    writes: dict[Path, str] = {}
    for name, members in groups.items():
        sections = []
        for item in members:
            if "](" in item.section or "src=" in item.section:
                sections.append(_rewrite_links(item.section, item.path.parent,
                                               mapper_for(archive, item.path.parent != archive)))
            else:
                sections.append(item.section)
        target = archive / name
        existing = _safe_read(target)
        if existing is not None:  # older sections may link to an entry merged by this run
            existing = _rewrite_links(existing, archive, mapper_for(archive, False))
        writes[target] = _collection_text(existing, members, sections, commit, today)

    skip = {os.path.normcase(os.path.normpath(item.path)) for item in items}
    skip |= {os.path.normcase(os.path.normpath(path)) for path in writes}
    names = [item.path.name for item in items]
    relinked: list[Path] = []
    for md in _walk_markdown(root):
        if os.path.normcase(os.path.normpath(md)) in skip:
            continue
        try:
            raw = md.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not any(name in raw for name in names):
            continue
        new = _rewrite_links(raw, md.parent, mapper_for(md.parent, False))
        if new != raw:
            writes[md] = new
            relinked.append(md)

    for path, text in writes.items():
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
    for item in items:
        item.path.unlink()
    for path in relinked:
        print(f"entries: relinked links to merged entries in {_rel(path, root)}")
    written = [_rel(path, root) for path in writes if path not in relinked]
    print(f"entries: wrote {', '.join(written)}; {len(items)} single file(s) removed, full text in Git at {commit}")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="entries.py",
        description="Create and account for docs/ai/'s per-entry task/backlog/ledger/inbox files "
                     "(inbox: question | todo | report | note).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    # "inbox" is accepted as a legacy alias for "todo" everywhere a kind is a CLI argument
    # (KIND_ALIASES/_canonical_kind) — existing callers keep working unchanged.
    new_kind_choices = sorted({*KIND_DIR, *KIND_ALIASES})

    p_new = sub.add_parser("new", help="create a new entry file")
    p_new.add_argument("kind", choices=new_kind_choices,
                       help="task | backlog | ledger | question | todo | report | note (inbox: alias for todo)")
    p_new.add_argument("title", nargs="+", help="entry title — becomes the file's heading")
    p_new.add_argument("--id", dest="entry_id", metavar="ID",
                       help="keep this id (T/B/Q/U<n>, optional sub-letter); refused if taken or wrong prefix")
    p_new.add_argument("--formerly", metavar="OLD_ID", help='header line "formerly: <old id>"')
    p_new.add_argument("--status", choices=STATUS_VALUES,
                       help="question/todo/report/note entry (default open)")
    p_new.add_argument("--for", dest="recipient", metavar="IDENTITY",
                       help="task/todo/report/note entry: recipient (todo/report/note default all, "
                            "task default this identity; all = shared)")
    p_new.add_argument("--body-file", metavar="PATH", help="body below the heading, copied verbatim (UTF-8)")

    sub.add_parser("assign", help="hand out ids still missing ('team' mode: only on the default branch)")

    state_help = ("append a working-state line for an open task to .act-local/state/ — needs an id "
                  "already assigned; in 'team' mode a task awaiting one (filename only) has no `state` "
                  "target yet. With --wait the line marks the task as waiting (for the human, a "
                  "review, an outside party) until the next plain state line")
    p_state = sub.add_parser("state", help=state_help, description=state_help)
    p_state.add_argument("--wait", action="store_true",
                         help="mark the task as waiting; a later plain `state` line ends the waiting")
    p_state.add_argument("id", metavar="T-ID", help="the task's id, e.g. T12")
    p_state.add_argument("text", nargs="+", help='the state line\'s text, e.g. "step 3 running, next: ..."')

    start_help = ("mark an open task as started (versioned `started:` header) without a state line; "
                  "`state` does the same on its first call")
    p_start = sub.add_parser("start", help=start_help, description=start_help)
    p_start.add_argument("id", metavar="T-ID", help="the task's id, e.g. T12")

    p_list = sub.add_parser("list", help="list entries, optionally filtered by kind")
    p_list.add_argument("kind", nargs="?", choices=new_kind_choices,
                        help="task | backlog | ledger | question | todo | report | note (inbox: alias for todo)")

    sub.add_parser("check", help="report a duplicate id or an entry file that isn't valid UTF-8")

    archive_help = ("archive a finished task, backlog item or inbox entry to docs/ai/work/archive/ — an inbox "
                    "entry gets `status: done`; files it links beside itself (pasted images) move along, "
                    "generic or colliding names get the entry's id in front, links are rewritten")
    p_archive = sub.add_parser("archive", help=archive_help, description=archive_help)
    p_archive.add_argument("entry", metavar="ID-OR-FILE", help="an id such as Q<n> or T<n>, or the entry file's path")

    compact_help = ("merge archived entries older than 7 days (and journal entries) into one collection file per "
                    "kind and month in docs/ai/work/archive/ (Q-2026-09.md, T-, B-, U-, other-, ledger-), one "
                    "section per entry with an anchor such as #<id>; links in the project are rewritten, the "
                    "head of each collection names the commit that holds the full text; needs the entries "
                    "committed; running it twice changes nothing")
    p_compact = sub.add_parser("compact", help=compact_help, description=compact_help)
    p_compact.add_argument("--plan", action="store_true", help="show what would be merged, write nothing")
    p_compact.add_argument("--today", metavar="YYYY-MM-DD", help="count the keep window from this day (tests)")

    return parser


def main(argv: list[str]) -> int:
    # Output can carry an em dash; on Windows, stdout/stderr otherwise default to the console's
    # legacy code page instead of UTF-8, which would corrupt it. Same fix as .act/scripts/rules.py.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    args = build_parser().parse_args(argv)
    root = actlib.repo_root()

    if args.command == "new":
        return cmd_new(root, args.kind, args.title, args.entry_id, args.formerly, args.status,
                       args.recipient, args.body_file)
    if args.command == "assign":
        return cmd_assign(root)
    if args.command == "state":
        return cmd_state(root, args.id, args.text, args.wait)
    if args.command == "start":
        return cmd_start(root, args.id)
    if args.command == "list":
        return cmd_list(root, args.kind)
    if args.command == "check":
        return cmd_check(root)
    if args.command == "archive":
        return cmd_archive(root.resolve(), args.entry)
    if args.command == "compact":
        try:
            return cmd_compact(root.resolve(), args.plan, date.fromisoformat(args.today) if args.today else None)
        except ValueError as exc:
            print(f"entries: --today {args.today!r}: {exc}", file=sys.stderr)
            return 2
        except CompactError as exc:
            print(f"entries: {exc} - nothing changed", file=sys.stderr)
            return 2
    return 2  # argparse's `required=True` already keeps this unreachable


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
