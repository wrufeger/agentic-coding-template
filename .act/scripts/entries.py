#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Create and account for the project's short-lived entry files — tasks, backlog items,
#          journal entries, and docs/ai/inbox/ entries (question | todo | report | note, ADR-9,
#          T75) — one file per entry. A task, backlog item, or question carries a short id ("T12",
#          "B7", "Q5") in an "id:" header line; a todo/report/note never does. *When* an id is
#          written depends on docs/ai/config.md's "mode" key (Q65c/Q66): "solo" gets it right
#          away, from `new`; "team" leaves it out until `assign` runs it on the project's default
#          branch, the same moment a PR number would be handed out — until then, the entry's
#          filename carries the person's identity and a timestamp instead, and `assign` renames it
#          once the id is known (Q100 b: the filename always shows an assigned id up front, never
#          hides it inside the file the way Q62a had it). A journal entry under
#          docs/ai/work/ledger/ never gets an id at all, and is never scanned for one either — see
#          _ID_SCAN_ROOTS.
#          Every docs/ai/inbox/ entry — anything waiting on a person — carries a "kind:" header
#          field (question | todo | report | note, actlib.INBOX_KINDS; missing means "todo",
#          actlib.DEFAULT_INBOX_KIND); "question" is the only one that also carries an id.
#          docs/ai/questions/ no longer exists as its own directory — a question is an inbox entry
#          like the rest, just one with an id (see docs/project/concepts/ai-dev-app/
#          16-inbox-questions-tasks.md).
#          Adoption (stage 6, Q79 a): `new` also takes an entry over from an older structure — its
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
#       [--id <T|B|Q><n>[a-z]]    keep this id (task/backlog/question only; refused if it is taken)
#       [--formerly <old id>]     header line "formerly: <old id>"
#       [--status open|answered]  question/todo/report/note only (default open)
#       [--for <identity>]        todo/report/note only (default all; a question is always "all")
#       [--body-file <path>]      body below the heading, copied verbatim (UTF-8)
#   python .act/scripts/entries.py assign                  # hand out ids still missing (and rename)
#   python .act/scripts/entries.py state <T-id> <text...>   # append a working-state line (Q65a)
#   python .act/scripts/entries.py list [<kind>]            # id/filename + title, per kind
#   python .act/scripts/entries.py check                    # report a duplicate or unreadable entry
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
#   "state": Q65a (2026-09-20) splits a task's versioned goal/check-criteria from its unversioned
#     working state ("State ...: step 3 running, next step ..."), which lives under
#     .act-local/state/ (gitignored — .gitignore already covers .act-local/) instead of inside the
#     task file. Finds the task under docs/ai/work/tasks/ whose header carries "id: <T-id>"
#     (used_ids()-style scan, task kind only), appends one line "State <YYYY-MM-DD HH:MM>: <text>"
#     to .act-local/state/<that task file's name> (creating the directory on first use), and prints
#     "entries: appended state for <id> to .act-local/state/<name>", exit 0. Refuses (exit 2,
#     nothing written) with a reason on stderr if the id is not a task id, no task with that id
#     exists, or the text is empty. board.py reads the same file back and shows its last non-blank
#     line next to the task's title.
#   "list": one "== <kind> ==" heading per kind shown, then one "<id-or-'(unassigned)'>  <file> —
#     <title>" line per entry ("-" instead of the id for ledger/todo/report/note, which never
#     carry one), oldest first (filename order); an inbox entry is listed once, under its own
#     `kind:` section. Exit 0, 2 on an unknown kind.
#   "check": "entries: no duplicate ids found" (stdout, exit 0) if nothing is wrong, else one
#     "entries: duplicate id <id>: <path>, <path>, ..." line per collision and/or one "entries:
#     cannot read <path> (not valid UTF-8)" line per unreadable file (stderr, exit 1 either way).
#     find_duplicate_ids()/find_unreadable_entries() below are the reusable halves doctor.py's own
#     checks call instead of repeating the scan.

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional

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

# No entry for "ledger", "todo", "report" or "note" — only task/backlog/question ever get a short
# id (see header comment); the other three inbox kinds are named from kind+timestamp+slug alone
# (actlib.inbox_entry_filename()).
KIND_PREFIX: dict[str, str] = {"task": "T", "backlog": "B", "question": "Q"}

# Directories scanned for existing ids, both for the next free number and for check(): every kind
# that can carry one (docs/ai/work/tasks/, .../backlog/, the question share of docs/ai/inbox/),
# plus the archive, where an accepted task or backlog item keeps its id
# (docs/ai/work/archive/README.md). docs/ai/work/ledger/ is deliberately absent — a journal entry
# never has an id, and a prose mention of another entry's id in a journal text ("... header was:
# id: T12") must never be read as if it were this file's own header. A todo/report/note entry
# under docs/ai/inbox/ never carries a T/B/Q id, so scanning the whole inbox directory here is
# harmless (used_ids()/_next_id() only count what actually matches the kind's prefix) — same for
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
# B118 (6): an old id whose material the content step (adopt_entries.py) decided not to keep as a
# live entry at all — a `delete` row `--finish` removes for good, never moved to LEGACY_ROOT either
# — would otherwise be free to reuse. adopt_entries.py's "reserved" batch kind writes the id here
# instead of a file; _next_id() reads it back the same way it reads legacy_ids(), so the next id
# still lands above it. A plain {"ids": [...]} list, tolerant of a missing/unreadable file (then
# nothing is reserved — the safer default is the same "not yet known about" as before this fix).
RESERVED_IDS_PATH = Path(".act-local/adopt/reserved-ids.json")
# Q65a: a task's working state ("State ...") lives here, gitignored, never in the versioned task
# file itself — see cmd_state()/board.py's read_task_titles().
STATE_DIR = Path(".act-local/state")

STATUS_VALUES = ("open", "answered")
_HEADER_FIELD_RE = re.compile(r"^[A-Za-z][A-Za-z-]*:\s")

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


def _derive_slug(stem: str) -> str:
    """The slug part of an existing entry filename's stem (no ".md"), for cmd_assign()'s rename:
    strips a leading team-mode prefix ("<P>-<identity>-<YYYYMMDD-HHMM>-") or a leading date prefix
    ("YYYY-MM-DD-"), whichever matches; neither ever occurs together. A trailing "-<n>" counter left
    over from a same-minute name collision (_create_unique) is not a prefix and stays part of the
    slug, exactly as it stood in the old name. A stem that matches neither pattern (already renamed,
    or an old-style name from before this scheme) is returned unchanged."""
    for pattern in (_TEAM_PREFIX_RE, _DATE_PREFIX_RE):
        match = pattern.match(stem)
        if match:
            return stem[match.end():]
    return stem


def _identity_slug(root: Path) -> str:
    """The current checkout's identity (.act-local/identity.json's "identity" field), slugified for
    a team-mode filename awaiting its id — "unknown" if identity.json is missing, unreadable, or
    has no "identity" value (never blocks entry creation on it)."""
    value = (actlib.read_identity() or {}).get("identity")
    return _slugify(value) if isinstance(value, str) and value.strip() else "unknown"


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
    match = _ID_ARG_RE.match(raw)
    if not match:
        return raw.upper()
    letters, digits, sub = match.groups()
    return f"{letters.upper()}{int(digits)}{sub.lower()}"


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
        return path.read_text(encoding="utf-8")
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
    value = actlib.read_config().get("mode", "").strip().lower()
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
    """prefix -> canonical ids from RESERVED_IDS_PATH (see its comment above) — read the same
    tolerant way as legacy_ids(): a missing file, bad JSON, or a value that isn't a T/B/Q id is
    skipped rather than raising, so a stray hand-edit never breaks id assignment."""
    found: dict[str, set[str]] = {prefix: set() for prefix in KIND_PREFIX.values()}
    text = _safe_read(root / RESERVED_IDS_PATH)
    if text is None:
        return found
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return found
    ids = data.get("ids") if isinstance(data, dict) else data
    if not isinstance(ids, list):
        return found
    for value in ids:
        if not isinstance(value, str):
            continue
        match = _ID_ARG_RE.match(value.strip())
        if match and match.group(1).upper() in found:
            found[match.group(1).upper()].add(_canonical_id(value.strip()))
    return found


def used_ids(root: Path, kind: str) -> set[str]:
    """Every canonical id of `kind`'s prefix a "taken" check must refuse: entry-file headers
    anywhere _entry_files() reaches, archive included — never a legacy collection file's own old
    id (legacy_ids()). An id that only survives in legacy is free to adopt with --id (Q79 a); it
    only raises the floor for the *next* id (see _next_id()), it never blocks a kept one."""
    prefix = KIND_PREFIX[kind]
    ids = set()
    for path in _entry_files(root):
        text = _safe_read(path)
        canonical = _entry_id(text) if text is not None else None
        if canonical is not None and _id_number(canonical, prefix) is not None:
            ids.add(canonical)
    return ids


def _next_id(root: Path, kind: str, also_used: tuple = ()) -> str:
    """The next free id for `kind` — one past the highest number already used by that prefix,
    anywhere _entry_files() reaches (including the archive, so an id an accepted task already
    carries is never reused), in the legacy collection files (legacy_ids()), so an adopted
    project's next task comes after its highest old one even when that one only survives in
    legacy, and in reserved_ids() (an old id `--finish` deletes for good instead, never moved to
    legacy — B118 (6)). `also_used`: ids not on disk yet (a batch being planned). Leading zeros and
    sub-letters don't count ("T012" is 12, "Q55a" is 55, via _canonical_id/_id_number)."""
    prefix = KIND_PREFIX[kind]
    numbers = [_id_number(i, prefix) for i in
              (*used_ids(root, kind), *legacy_ids(root)[prefix], *reserved_ids(root)[prefix], *also_used)]
    highest = max((n for n in numbers if n is not None), default=0)
    return f"{prefix}{highest + 1}"


def _insert_id(path: Path, entry_id: str) -> bool:
    """Write `id: <entry_id>` as the file's first line — directly above an existing header field
    (e.g. a question's "status: open"), or with a blank line separating it from the heading when
    there was no header yet. Returns False without writing anything if the file cannot be read as
    UTF-8 (the caller reports that separately, see cmd_assign)."""
    text = _safe_read(path)
    if text is None:
        return False
    first_line = text.splitlines()[0] if text else ""
    if _HEADER_FIELD_RE.match(first_line):
        new_text = f"id: {entry_id}\n{text}"
    else:
        new_text = f"id: {entry_id}\n\n{text}"
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(new_text)
    return True


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

    def __init__(self, root: Path):
        self.path = root / _LOCK_PATH
        self._held = False

    def __enter__(self) -> "_EntriesLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + _LOCK_TIMEOUT
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
        canonical = _entry_id(text)
        if canonical is not None:
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
    if recipient is not None and (kind not in ("todo", "report", "note") or not _single_line(recipient)):
        problems.append("--for: only a todo, report, or note entry takes a recipient "
                        "(one line; a question is always for all)")
    return problems


def create_entry(
    root: Path, kind: str, title: str, entry_id: Optional[str] = None, formerly: Optional[str] = None,
    status: Optional[str] = None, recipient: Optional[str] = None, body: str = "",
) -> tuple[Path, Optional[str]]:
    """Write one entry file, return (path, id written or None). The caller has validated
    (validate_entry()). An explicit `entry_id` is written in either mode — it is an id the entry
    already had (adoption, Q79 a); without one, "solo" hands out the next free id and "team" leaves
    it to `assign`. `body` goes below the heading exactly as given (no newline translation).
    Filename (ADR-9, Q100 b): "ledger" keeps its date-based name; task/backlog/question get
    "<id>-<slug>.md" once an id is assigned, else (team mode, no id yet)
    "<P>-<identity>-<stamp>-<slug>.md" for `assign` to rename later; todo/report/note (which never
    carry an id) get "<kind>-<stamp>-<slug>.md" (actlib.inbox_entry_filename())."""
    kind = _canonical_kind(kind)
    entry_dir = root / KIND_DIR[kind]
    entry_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    created_at = now.isoformat(timespec="seconds")
    team = _mode(root) == "team"

    with _EntriesLock(root):
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
        if kind in actlib.INBOX_KINDS:
            # Q63b: every entry waiting on a person carries "for:" — "all" by default; a question
            # is never filed to just one person's own queue, so it is always "all" regardless of
            # `recipient`.
            header_lines.append(f"kind: {kind}")
            header_lines.append("for: all" if kind == "question" else f"for: {(recipient or 'all').strip()}")
            header_lines.append(f"status: {status or 'open'}")
        header_lines.append(f"created: {created_at}")

        text = "\n".join(header_lines) + "\n\n" + f"# {title.strip()}\n\n" + body
        slug = _slugify(title)
        if kind == "ledger":
            filename = f"{date.today().isoformat()}-{slug}.md"
        elif kind in KIND_PREFIX:
            if assigned_id:
                filename = f"{assigned_id}-{slug}.md"
            else:
                filename = f"{KIND_PREFIX[kind]}-{_identity_slug(root)}-{actlib.entry_stamp(now)}-{slug}.md"
        else:  # todo | report | note — never carry an id
            filename = actlib.inbox_entry_filename(kind, slug, now)
        dest = _create_unique(entry_dir, filename, text)
    return dest, assigned_id


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
    elif kind in ("todo", "report", "note"):
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

    assigned: list[tuple[str, Path]] = []
    unreadable: list[Path] = []
    # KIND_PREFIX is task/backlog/question only — "question" here means the whole of
    # actlib.INBOX_DIR (task/backlog/question don't share a directory with each other), so a
    # todo/report/note file in the same directory is skipped by the kind == "question" check below
    # rather than mistaken for an unassigned question.
    for kind in KIND_PREFIX:
        entry_dir = root / KIND_DIR[kind]
        if not entry_dir.is_dir():
            continue
        for path in sorted(entry_dir.glob("*.md")):
            if path.name.lower() == "readme.md":
                continue
            text = _safe_read(path)
            if text is None:
                unreadable.append(path)
                continue
            if kind == "question" and actlib.inbox_kind(text) != "question":
                continue
            if _entry_id(text) is not None:
                continue
            entry_id = _next_id(root, kind)
            if not _insert_id(path, entry_id):
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


def cmd_state(root: Path, raw_id: str, text_words: list[str]) -> int:
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
        handle.write(f"State {stamp}: {text}\n")
    entry_id = _entry_id(_safe_read(path) or "") or _canonical_id(raw_id.strip())
    print(f"entries: appended state for {entry_id} to {_rel(state_path, root)}")
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
                       help="keep this id (T/B/Q<n>, optional sub-letter); refused if taken or wrong prefix")
    p_new.add_argument("--formerly", metavar="OLD_ID", help='header line "formerly: <old id>"')
    p_new.add_argument("--status", choices=STATUS_VALUES,
                       help="question/todo/report/note entry (default open)")
    p_new.add_argument("--for", dest="recipient", metavar="IDENTITY",
                       help="todo/report/note entry: recipient (default all)")
    p_new.add_argument("--body-file", metavar="PATH", help="body below the heading, copied verbatim (UTF-8)")

    sub.add_parser("assign", help="hand out ids still missing ('team' mode: only on the default branch)")

    state_help = ("append a working-state line for an open task to .act-local/state/ — needs an id "
                  "already assigned; in 'team' mode a task awaiting one (filename only) has no `state` "
                  "target yet")
    p_state = sub.add_parser("state", help=state_help, description=state_help)
    p_state.add_argument("id", metavar="T-ID", help="the task's id, e.g. T12")
    p_state.add_argument("text", nargs="+", help='the state line\'s text, e.g. "step 3 running, next: ..."')

    p_list = sub.add_parser("list", help="list entries, optionally filtered by kind")
    p_list.add_argument("kind", nargs="?", choices=new_kind_choices,
                        help="task | backlog | ledger | question | todo | report | note (inbox: alias for todo)")

    sub.add_parser("check", help="report a duplicate id or an entry file that isn't valid UTF-8")

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
        return cmd_state(root, args.id, args.text)
    if args.command == "list":
        return cmd_list(root, args.kind)
    if args.command == "check":
        return cmd_check(root)
    return 2  # argparse's `required=True` already keeps this unreachable


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
