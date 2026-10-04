#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Gives every todo in docs/ai/inbox/ its own short id. A todo (a task for a human) used to
#          carry none and was named "todo-<YYYYMMDD-HHMM>-<slug>.md"; from now on it carries
#          "U<n>" ("U" for "user"), the same way a question carries "Q<n>".
#          What this does depends on docs/ai/config.md's `mode` key (a missing or unrecognized value
#          counts as "solo", like entries.py):
#            - "solo": every inbox entry that is a todo (a "kind: todo" header, or no "kind:" header at
#              all, which counts as todo) and has no "id:" header line yet gets the next free U<n> as
#              the file's first header line and is renamed "U<n>-<slug>.md" (the slug is the old name
#              without its "todo-<stamp>-" start). Whatever its status (open, answered, done). Several
#              todos are numbered in the order of their "created:" header, then by file name.
#              "Next free" is one past the highest U number found in the inbox, in the archive
#              (docs/ai/work/archive/, its legacy/ subtree read for ids only), in the task and backlog
#              directories, and in the reserved-id list entries.py reads
#              (docs/ai/work/reserved-ids.json, and the old .act-local/adopt/ place) — an archived U id is never handed out again.
#              A file with a UTF-8 BOM loses the BOM when its header is rewritten (the id must be the
#              first thing on the first line, or the header readers would not see it).
#              apply() holds .act-local/entries.lock while it numbers, with the same create-exclusive,
#              5 s wait, 30 s stale rule as entries.py (reimplemented here, stdlib only), so a
#              parallel `entries.py new` cannot take the same number; on timeout it goes on without
#              the lock, like entries.py does.
#            - "team": nothing is changed. `entries.py assign`, run on the default branch, numbers the
#              todos without an id, the same way it numbers questions; the description says so. A
#              team project that later switches to "solo" numbers its todos still in the old form
#              with `entries.py assign` (this migration does not run again).
#          Reports and notes keep their names and never get an id; the archive is never rewritten.
#          A rename happens on the filesystem (Path.rename), never "git mv" — update.py's step_commit
#          stages old and new path from the touched-paths list this module returns. A rename target
#          that already exists is reported and the file left as it was (Path.rename() silently
#          replaces a target on POSIX, so the check must happen on our side).
#          Re-running apply() changes nothing (a numbered todo is not a candidate any more); plan()
#          only reads, never writes.
#
# Contract (.act/scripts/update.py step 8): plan(root) -> str, apply(root) -> (str, list[str]) of
# project-relative paths (posix separators) touched — old and new path for every rename. Stdlib
# only, no `actlib` import: a migration must not depend on the *project's* possibly-older copy of
# it — the small pieces of entries.py's id scan and slugging this needs are reimplemented below.

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Optional

INBOX_DIR = "docs/ai/inbox"
ARCHIVE_DIR = "docs/ai/work/archive"
LEGACY_DIR = f"{ARCHIVE_DIR}/legacy"
ID_SCAN_DIRS = ("docs/ai/work/tasks", "docs/ai/work/backlog", ARCHIVE_DIR, INBOX_DIR)
RESERVED_FILES = ("docs/ai/work/reserved-ids.json", ".act-local/adopt/reserved-ids.json")  # the lists entries.reserved_ids() reads
LOCK_FILE = ".act-local/entries.lock"  # the lock entries.py's _EntriesLock takes
LOCK_TIMEOUT = 5.0
LOCK_STALE_AFTER = 30.0
CONFIG_FILE = "docs/ai/config.md"
PREFIX = "U"
INBOX_KINDS = ("question", "todo", "report", "note")

_BOM = b"\xef\xbb\xbf"
_KEY_RE = re.compile(rb"^([A-Za-z][A-Za-z-]*):")
_ID_RE = re.compile(rb"(?im)^id:\s*(\S+)\s*$")
_KIND_RE = re.compile(rb"(?im)^kind:\s*(\S+)\s*$")
_CREATED_RE = re.compile(rb"(?im)^created:\s*(\S+)\s*$")
_ID_PARTS_RE = re.compile(r"^([A-Za-z]+)0*(\d+)([a-z]?)$")
_MODE_RE = re.compile(r"^\|\s*`?mode`?\s*\|\s*([^|]*?)\s*\|", re.MULTILINE)
_KIND_STAMP_RE = re.compile(r"^(?:question|todo|report|note)-\d{8}-\d{4}-")
_TEAM_PREFIX_RE = re.compile(r"^[A-Za-z]+-[a-z0-9]+(?:-[a-z0-9]+)*?-\d{8}-\d{4}-")
_DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")
# The forms an old collection file under legacy/ names an entry in (same set entries.py reads).
_LEGACY_PATTERNS = (
    r"\*\*U(\d+)[a-z]?\s*[·:—–]",
    r"\*\*U(\d+)[a-z]?\*\*\s*[·:—–]",
    r"\|\s*U(\d+)[a-z]?\s*\|",
    r"(?m)^id:\s*U(\d+)[a-z]?\s*$",
)


def _is_readme(name: str) -> bool:
    return name.lower() == "readme.md"


def _mode(root: Path) -> str:
    """"solo" | "team" from docs/ai/config.md's `mode` row; anything else (or no file) is "solo"."""
    path = root / CONFIG_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "solo"
    match = _MODE_RE.search(text)
    value = match.group(1).strip().lower() if match else ""
    return value if value in ("solo", "team") else "solo"


def _split_bom(data: bytes) -> tuple[bytes, bytes]:
    if data.startswith(_BOM):
        return _BOM, data[len(_BOM):]
    return b"", data


def _header(data: bytes) -> bytes:
    """The file's leading run of "key: value" lines (a leading BOM ignored), as bytes."""
    _, body = _split_bom(data)
    kept: list[bytes] = []
    for line in body.splitlines(keepends=True):
        if not line.strip() or not _KEY_RE.match(line):
            break
        kept.append(line)
    return b"".join(kept)


def _newline(data: bytes) -> bytes:
    """The line ending the file already uses, "\\n" for a file without any."""
    match = re.search(rb"\r\n|\n|\r", data)
    return match.group(0) if match else b"\n"


def _entry_number(data: bytes) -> Optional[int]:
    """The number of a "U<n>" id in the header, else None (another prefix, or no id)."""
    match = _ID_RE.search(_header(data))
    if not match:
        return None
    parts = _ID_PARTS_RE.match(match.group(1).decode("ascii", "replace"))
    if parts and parts.group(1).upper() == PREFIX:
        return int(parts.group(2))
    return None


def _is_todo(data: bytes) -> bool:
    """True for an inbox entry of kind todo — a missing, empty or unknown `kind:` counts as todo."""
    match = _KIND_RE.search(_header(data))
    value = match.group(1).decode("ascii", "replace").strip().lower() if match else ""
    return value not in INBOX_KINDS or value == "todo"


def _derive_slug(stem: str) -> str:
    for pattern in (_KIND_STAMP_RE, _TEAM_PREFIX_RE, _DATE_PREFIX_RE):
        match = pattern.match(stem)
        if match:
            return stem[match.end():]
    return stem


def _used_numbers(root: Path) -> set[int]:
    """Every U number already taken: file headers under ID_SCAN_DIRS (the legacy subtree skipped
    there, read separately below), old collection files under legacy/, the reserved-id lists."""
    legacy = root / LEGACY_DIR
    numbers: set[int] = set()
    for rel in ID_SCAN_DIRS:
        base = root / rel
        if not base.is_dir():
            continue
        for path in base.rglob("*.md"):
            if not path.is_file() or _is_readme(path.name) or legacy in path.parents:
                continue
            try:
                number = _entry_number(path.read_bytes())
            except OSError:
                continue
            if number is not None:
                numbers.add(number)
    if legacy.is_dir():
        patterns = [re.compile(p) for p in _LEGACY_PATTERNS]
        for path in legacy.rglob("*"):
            if not path.is_file():
                continue
            try:
                data = path.read_bytes()
            except OSError:
                continue
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = data.decode("cp1252", errors="replace")
            for pattern in patterns:
                numbers.update(int(m.group(1)) for m in pattern.finditer(text))
    for rel in RESERVED_FILES:
        try:
            data = json.loads((root / rel).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        ids = data.get("ids") if isinstance(data, dict) else data
        if not isinstance(ids, list):
            continue
        for value in ids:
            parts = _ID_PARTS_RE.match(value.strip()) if isinstance(value, str) else None
            if parts and parts.group(1).upper() == PREFIX:
                numbers.add(int(parts.group(2)))
    return numbers


def _with_id(data: bytes, entry_id: str) -> bytes:
    """`data` with "id: <entry_id>" as the first header line — above an existing header, or followed
    by a blank line when the file has no header; line ending kept, a leading BOM dropped."""
    _bom, body = _split_bom(data)  # the BOM is dropped: "id:" must start the first line
    newline = _newline(body)
    line = f"id: {entry_id}".encode("ascii") + newline
    first = body.splitlines()[0] if body.strip() else b""
    if _KEY_RE.match(first):
        return line + body
    return line + newline + body


def _candidates(root: Path) -> list[tuple[bytes, Path, bytes]]:
    """(created, file, content) of every inbox todo without an id, in numbering order."""
    inbox = root / INBOX_DIR
    found: list[tuple[bytes, Path, bytes]] = []
    if not inbox.is_dir():
        return found
    for path in inbox.glob("*.md"):
        if not path.is_file() or _is_readme(path.name):
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if not _is_todo(data) or _ID_RE.search(_header(data)):
            continue
        created = _CREATED_RE.search(_header(data))
        found.append((created.group(1) if created else b"", path, data))
    return sorted(found, key=lambda item: (item[0], item[1].name))


def _plan_renames(root: Path) -> tuple[list[tuple[Path, Path, bytes, str]], list[str]]:
    """(src, dest, new content, id) for every todo to number, and a line per target name that is
    already taken (that todo is left as it is)."""
    renames: list[tuple[Path, Path, bytes, str]] = []
    conflicts: list[str] = []
    used = _used_numbers(root)
    taken_names = {p.name for p in (root / INBOX_DIR).glob("*.md")} if (root / INBOX_DIR).is_dir() else set()
    for _created, path, data in _candidates(root):
        number = max(used, default=0) + 1
        entry_id = f"{PREFIX}{number}"
        dest_name = f"{entry_id}-{_derive_slug(path.stem)}.md"
        if dest_name in taken_names:
            conflicts.append(f"{path.name} (target {dest_name} already exists)")
            continue
        used.add(number)
        taken_names.add(dest_name)
        renames.append((path, path.with_name(dest_name), _with_id(data, entry_id), entry_id))
    return renames, conflicts


def plan(root: Path) -> str:
    """Describes what apply() would do, writes nothing."""
    renames, conflicts = _plan_renames(root)
    if _mode(root) == "team":
        count = len(_candidates(root))
        if not count:
            return "mode is team, no todo without an id — nothing to do"
        return (f"mode is team: {count} todo(s) without an id stay as they are — "
                "`entries.py assign` on the default branch numbers them")
    if not renames and not conflicts:
        return "no todo without an id — nothing to do"
    parts = [f"would number {len(renames)} todo(s): "
             + ", ".join(f"{src.name} -> {dest.name}" for src, dest, _data, _id in renames)] if renames else []
    if conflicts:
        parts.append("would skip " + ", ".join(conflicts))
    return "; ".join(parts)


class _Lock:
    """entries.py's cooperative lock (same file, same rules), stdlib only; best-effort."""

    def __init__(self, root: Path) -> None:
        self.path = root / LOCK_FILE
        self.held = False

    def __enter__(self) -> "_Lock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + LOCK_TIMEOUT
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode("ascii", "replace"))
                os.close(fd)
                self.held = True
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > LOCK_STALE_AFTER:
                        self.path.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    return self
                time.sleep(0.05)

    def __exit__(self, *exc_info: object) -> None:
        if self.held:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass


def apply(root: Path) -> tuple[str, list[str]]:
    """Numbers the todos as described above. Returns (description, touched project-relative paths,
    old and new name of every rename)."""
    if _mode(root) == "team":
        return plan(root), []
    with _Lock(root):
        return _apply_solo(root)


def _apply_solo(root: Path) -> tuple[str, list[str]]:
    renames, conflicts = _plan_renames(root)
    touched: list[Path] = []
    done: list[str] = []
    for src, dest, new_data, entry_id in renames:
        if dest.exists():
            conflicts.append(f"{src.name} (target {dest.name} already exists)")
            continue  # planned a moment ago; re-check right before touching the filesystem
        src.write_bytes(new_data)
        src.rename(dest)
        touched.extend([src, dest])
        done.append(f"{src.name} -> {dest.name}")
    parts: list[str] = []
    if done:
        parts.append(f"numbered {len(done)} todo(s): " + ", ".join(done))
    if conflicts:
        parts.append("left alone: " + ", ".join(conflicts))
    description = "; ".join(parts) if parts else "no todo without an id — nothing to do"
    return description, [p.relative_to(root).as_posix() for p in touched]
