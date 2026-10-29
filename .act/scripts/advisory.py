#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Warnings from the template author to projects running an affected template version
#          ("advisories"). The template source carries an orphan branch `advisories` with one file,
#          `advisories.json`. The daily background check of the session start asks the source for that
#          branch and, when its commit changed, fetches only that branch into a bare repository of its
#          own (`.act-local/advisories.git`, never the project's `.git`), validates the file and keeps
#          the accepted entries in `.act-local/advisories.json`. Everything that shows an advisory (the
#          session start, the status line, the board, the chat acknowledgement) reads only that cache,
#          the installed version (`.act/VERSION`) and the lock: files, no git, no network. An
#          acknowledgement then runs board.py once, as the session start does, so the board drops the
#          line at once (board.py reads local git state, never the network).
#
#          The file is data, never code: it is read as JSON, every field is checked, only the known
#          fields are kept, and nothing from it is executed, imported, formatted into a format string
#          or passed to a shell. The only paths taken from it are the `files` paths, and only after
#          check_files() accepted them: they are read as bytes and never executed. A link is shown as
#          plain text and never opened.
#
#          An entry may carry `files`: paths under .act/ with a literal snippet only the faulty version
#          holds. When every listed file (the project override under docs/ai/local/ if there is one,
#          else the .act/ file) is missing or no longer holds its snippet, the project fixed the problem
#          another way: the entry counts as `fixed`, shows one line at the next start (recorded in
#          advisories-seen.json) and is silent after. A bad `files` field is dropped; the entry then
#          works by version range alone. The files are read as bytes, never executed.
#
#          Library part (used by hooks/checks/session.py, hooks/statusline.py, board.py and
#          hooks/checks/advisory_ack.py): validate_document(), load_cache(), active_advisories(),
#          session_report(), acknowledge(), refresh(). The command line part is below.
#
# Usage:   python .act/scripts/advisory.py [--status]        (default) what applies to this project
#          python .act/scripts/advisory.py --ack [ID ...]    acknowledge (no id = every active one)
#          python .act/scripts/advisory.py --check-file PATH validate a file; works outside a project
#          python .act/scripts/advisory.py --refresh         run the fetch now (5 s limit per git call)
# Writes:  only under .act-local/ (advisories.json, advisories-state.json, advisories-seen.json,
#          advisories-ack.json, advisories.git/); --ack and the session start (inbox todo) also write
#          the acknowledgement / seen records and, once per critical advisory, one inbox todo; an
#          acknowledgement also rewrites the board view (docs/ai/board.md or .act-local/board-<branch>.md).
# Exit:    0 normally; 1 when --check-file rejects something or --ack names an unknown id;
#          2 outside a project (except --check-file) or on a usage error.

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import actlib  # noqa: E402

SCHEMA = 1
MAX_FILE_BYTES = 64 * 1024
MAX_ENTRIES = 100
MAX_TEXT = 300
MAX_LINK = 200
MAX_AFFECTED = 60
MAX_COMMITS = 50
SEVERITIES = ("critical", "warning")
REPEATS = ("once", "every-start")
BRANCH_REF = "refs/heads/advisories"
BRANCH_FILE = "advisories.json"
GIT_TIMEOUT = 5
BOARD_TIMEOUT = 5  # the board rewrite after an acknowledgement; the chat hook itself has 10 s
_STATE_READ_LIMIT = 1024 * 1024
# Characters no field may contain: control, format (bidi overrides, zero width), private use,
# surrogates and the line/paragraph separators.
_FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs", "Zl", "Zp"})
_ID_RE = re.compile(r"A[1-9][0-9]{0,3}")
# Windows device names, with or without an extension (`NUL`, `nul.txt`): opening one reaches the device
_RESERVED_NAME_RE = re.compile(r"(?:CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\..*)?", re.IGNORECASE)
# text ends up in the board and the inbox, where a renderer could fetch an image: no link or code syntax,
# no tag start (`<` + letter, `/`, `!` or `?`); a plain `<2.2.0` stays fine
_MARKUP_RE = re.compile(r"[\[\]`]|<[A-Za-z/!?]")
_COMPARATOR_RE = re.compile(r"(>=|>|<=|<|=)?([0-9]+)\.([0-9]+)\.([0-9]+)")
_VERSION_RE = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)")
_COMMIT_RE = re.compile(r"[0-9a-f]{7,40}")
_SHA_RE = re.compile(r"[0-9a-f]{40,64}")
_PRESENT_VERSION_RE = re.compile(r"v?([0-9]+)\.([0-9]+)\.([0-9]+)")

# Field names the file may carry. Everything else is ignored: never shown, never used, never
# evaluated. `files` (below) is checked on its own: a bad one is dropped, never the entry.
KNOWN_FIELDS = ("id", "severity", "affected", "commits", "fixed-in", "repeat", "text", "link")

# `files`: {path relative to the project root under .act/: literal snippet only the faulty version holds}.
# When every listed file is missing or no longer holds its snippet, the project fixed the problem another
# way and the warning ends. A path is at most 120 characters (the longest path under .act/ is far shorter),
# a snippet 200 (enough to be unique, short enough to stay one line and cheap to compare), at most 5
# files (a fault rarely sits in more places; a long list is more likely a mistake). The snippet is a
# single line: a control character, a line break included, is not allowed, so line endings never matter.
MAX_FILES = 5
MAX_FILE_PATH = 120
MAX_SNIPPET = 200
PROJECT_FILE_LIMIT = 1024 * 1024  # a project file read for the snippet check; larger counts as "still there"

Version = tuple[int, int, int]


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Advisory:
    """One validated entry. Only these fields exist; nothing else of the file is kept."""
    id: str
    severity: str
    affected: str
    text: str
    commits: tuple[str, ...] = ()
    fixed_in: Optional[str] = None
    repeat: str = "once"
    link: Optional[str] = None
    files: tuple[tuple[str, str], ...] = ()

    @property
    def critical(self) -> bool:
        return self.severity == "critical"

    @property
    def every_start(self) -> bool:
        """A critical advisory shows at every start; a warning as its `repeat` says."""
        return self.critical or self.repeat == "every-start"

    def to_json(self) -> dict:
        data: dict = {"id": self.id, "severity": self.severity, "affected": self.affected, "text": self.text}
        if self.commits:
            data["commits"] = list(self.commits)
        if self.fixed_in:
            data["fixed-in"] = self.fixed_in
        if self.repeat != "once":
            data["repeat"] = self.repeat
        if self.link:
            data["link"] = self.link
        if self.files:
            data["files"] = dict(self.files)
        return data


@dataclass(frozen=True)
class Rejection:
    """An entry (or the whole file, `id` None) that failed validation, with the reason."""
    id: Optional[str]
    reason: str

    def to_json(self) -> dict:
        return {"id": self.id, "reason": self.reason}

    def __str__(self) -> str:
        return f"{self.id or 'file'}: {self.reason}"


@dataclass
class Validation:
    """Result of validate_document(): the accepted entries, the rejections, and `invalid` set when the
    whole file was rejected (then `advisories` is empty)."""
    advisories: list[Advisory] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)
    invalid: Optional[str] = None
    notes: list[str] = field(default_factory=list)  # accepted entries whose `files` field was dropped


@dataclass
class Standing:
    """An advisory judged against this project: `state` is active, acked, fixed (the project's own files no
    longer hold the faulty code) or not-affected."""
    advisory: Advisory
    state: str


@dataclass
class SessionReport:
    """What the session start shows: `lines` for the visible message (critical first), `notes` for the model."""
    lines: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class RefreshResult:
    """Outcome of refresh(): `status` is one of disabled, no-source, unreachable, unchanged, updated, cleared,
    rejected, error."""
    status: str
    detail: str = ""
    accepted: int = 0
    rejected: list[Rejection] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _bad_char(value: str) -> Optional[str]:
    """The first forbidden character of `value` as `U+XXXX`, else None."""
    for char in value:
        if unicodedata.category(char) in _FORBIDDEN_CATEGORIES:
            return f"U+{ord(char):04X}"
    return None


def parse_version(text: str) -> Optional[Version]:
    """`MAJOR.MINOR.PATCH` (an optional leading `v`) as a tuple; None for anything else, a pre-release too."""
    match = _PRESENT_VERSION_RE.fullmatch(text.strip())
    return (int(match.group(1)), int(match.group(2)), int(match.group(3))) if match else None


def _check_affected(value: object) -> Optional[str]:
    """The reason `value` is not a valid `affected` range, None when it is one."""
    if not isinstance(value, str):
        return "affected must be a string"
    if not value or len(value) > MAX_AFFECTED:
        return f"affected must be 1 to {MAX_AFFECTED} characters"
    parts = value.split(" ")
    if not 1 <= len(parts) <= 4:
        return "affected must hold 1 to 4 comparators separated by single spaces"
    for part in parts:
        if _COMPARATOR_RE.fullmatch(part) is None:
            return "affected holds a comparator that is not (>=|>|<=|<|=)MAJOR.MINOR.PATCH"
    return None


def version_satisfies(version: Version, affected: str) -> bool:
    """True when every comparator of a validated `affected` range holds for `version`."""
    for part in affected.split(" "):
        match = _COMPARATOR_RE.fullmatch(part)
        if match is None:
            return False
        operator = match.group(1) or "="
        bound = (int(match.group(2)), int(match.group(3)), int(match.group(4)))
        holds = {">=": version >= bound, ">": version > bound, "<=": version <= bound,
                 "<": version < bound, "=": version == bound}[operator]
        if not holds:
            return False
    return True


def check_files(value: object) -> tuple[tuple[tuple[str, str], ...], Optional[str]]:
    """Judge a `files` field: (pairs, None) when valid, ((), reason) when not. Valid means a non-empty object of
    at most MAX_FILES entries; each key a relative path of `/`-separated parts under `.act/` (no `..`, `.`,
    empty part, backslash, drive letter or leading slash, at most MAX_FILE_PATH characters, no control
    character); each value a non-empty string of at most MAX_SNIPPET characters without a control character."""
    if not isinstance(value, dict) or not value:
        return (), "files must be a non-empty object of path: snippet"
    if len(value) > MAX_FILES:
        return (), f"files holds more than {MAX_FILES} entries"
    pairs: list[tuple[str, str]] = []
    for path, snippet in value.items():
        if not isinstance(path, str) or not 1 <= len(path) <= MAX_FILE_PATH:
            return (), f"a files path must be 1 to {MAX_FILE_PATH} characters"
        if _bad_char(path) or "\\" in path or ":" in path or path.startswith("/"):
            return (), f"files path {path[:40]!r} is not a relative path with / separators"
        parts = path.split("/")
        if len(parts) < 2 or parts[0] != ".act" or any(part in ("", ".", "..") for part in parts):
            return (), f"files path {path[:40]!r} must be a file under .act/ without .. or empty parts"
        if any(part.endswith((".", " ")) or _RESERVED_NAME_RE.fullmatch(part) for part in parts):
            return (), f"files path {path[:40]!r} has a part Windows treats as a device or strips (reserved name, trailing dot or space)"
        if not isinstance(snippet, str) or not 1 <= len(snippet) <= MAX_SNIPPET:
            return (), f"the files snippet of {path} must be 1 to {MAX_SNIPPET} characters"
        if _bad_char(snippet):
            return (), f"the files snippet of {path} contains a control or format character"
        pairs.append((path, snippet))
    return tuple(pairs), None


def _validate_entry(raw: dict) -> tuple[Optional[Advisory], Optional[str], Optional[str]]:
    """(advisory, None, note) for a valid entry (`note` names a dropped `files` field), (None, reason, None)
    otherwise. Unknown fields are not looked at."""
    advisory, reason = _validate_core(raw)
    if advisory is None or "files" not in raw:
        return advisory, reason, None
    pairs, bad = check_files(raw["files"])
    if bad:
        return advisory, None, f"{advisory.id}: files ignored ({bad}); the warning works by version range alone"
    return Advisory(**{**advisory.__dict__, "files": pairs}), None, None


def _validate_core(raw: dict) -> tuple[Optional[Advisory], Optional[str]]:
    """(advisory, None) for a valid entry without looking at `files`, (None, reason) otherwise."""
    for name in KNOWN_FIELDS:
        value = raw.get(name)
        strings = value if isinstance(value, list) and name == "commits" else [value]
        for item in strings:
            if isinstance(item, str):
                bad = _bad_char(item)
                if bad:
                    return None, f"{name} contains a control or format character ({bad})"
    adv_id = raw.get("id")
    if not isinstance(adv_id, str) or _ID_RE.fullmatch(adv_id) is None:
        return None, "id must be A followed by 1 to 4 digits, not starting with 0"
    severity = raw.get("severity")
    if severity not in SEVERITIES:
        return None, "severity must be critical or warning"
    reason = _check_affected(raw.get("affected"))
    if reason:
        return None, reason
    commits: tuple[str, ...] = ()
    if "commits" in raw:
        value = raw["commits"]
        if (not isinstance(value, list) or len(value) > MAX_COMMITS
                or not all(isinstance(item, str) and _COMMIT_RE.fullmatch(item) for item in value)):
            return None, f"commits must be a list of at most {MAX_COMMITS} lowercase hex strings of 7 to 40 characters"
        commits = tuple(value)
    fixed_in: Optional[str] = None
    if "fixed-in" in raw:
        value = raw["fixed-in"]
        if not isinstance(value, str) or _VERSION_RE.fullmatch(value) is None:
            return None, "fixed-in must be MAJOR.MINOR.PATCH"
        fixed_in = value
    repeat = "once"
    if "repeat" in raw:
        value = raw["repeat"]
        if value not in REPEATS:
            return None, "repeat must be once or every-start"
        repeat = value
    text = raw.get("text")
    if not isinstance(text, str) or not 1 <= len(text) <= MAX_TEXT:
        return None, f"text must be 1 to {MAX_TEXT} characters (longer than {MAX_TEXT} or missing)"
    if _MARKUP_RE.search(text):
        return None, "text contains Markdown or HTML markup"
    link: Optional[str] = None
    if "link" in raw:
        value = raw["link"]
        if (not isinstance(value, str) or len(value) > MAX_LINK or not value.startswith("https://")
                or any(char.isspace() for char in value)):
            return None, f"link must start with https://, hold no whitespace and have at most {MAX_LINK} characters"
        link = value
    return Advisory(id=adv_id, severity=severity, affected=raw["affected"], text=text, commits=commits,
                    fixed_in=fixed_in, repeat=repeat, link=link), None


def validate_document(data: bytes) -> Validation:
    """The one validation every reader uses (the cache reader, `--check-file`, the maintenance script).
    A file that is too large, not UTF-8, not a JSON object or without an integer `schema` >= 1 is rejected
    whole (`invalid` set). Otherwise each entry is judged alone: a failing one is skipped and counted with
    its id when that is readable, the others still count. A higher `schema` is read the same way."""
    result = Validation()
    if len(data) > MAX_FILE_BYTES:
        result.invalid = f"file is larger than 64 KiB ({len(data)} bytes)"
        return result
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        result.invalid = "file is not valid UTF-8 text"
        return result
    try:
        document = json.loads(text)
    except (ValueError, RecursionError):
        result.invalid = "file is not valid JSON"
        return result
    if not isinstance(document, dict):
        result.invalid = "file is not a JSON object"
        return result
    schema = document.get("schema")
    if not isinstance(schema, int) or isinstance(schema, bool) or schema < 1:
        result.invalid = "schema must be an integer of at least 1"
        return result
    entries = document.get("advisories")
    if not isinstance(entries, list):
        result.invalid = "advisories must be a list"
        return result
    seen: set[str] = set()
    for index, raw in enumerate(entries[:MAX_ENTRIES], start=1):
        label = f"entry {index}"
        if isinstance(raw, dict):
            raw_id = raw.get("id")
            if isinstance(raw_id, str) and _ID_RE.fullmatch(raw_id):
                label = raw_id
        if not isinstance(raw, dict):
            result.rejected.append(Rejection(label, "entry is not an object"))
            continue
        advisory, reason, note = _validate_entry(raw)
        if note:
            result.notes.append(note)
        if advisory is None:
            result.rejected.append(Rejection(label, reason or "invalid entry"))
        elif advisory.id in seen:
            result.rejected.append(Rejection(advisory.id, "duplicate id"))
        else:
            seen.add(advisory.id)
            result.advisories.append(advisory)
    if len(entries) > MAX_ENTRIES:
        result.rejected.append(Rejection(None, f"{len(entries) - MAX_ENTRIES} entries beyond the first "
                                                f"{MAX_ENTRIES} ignored"))
    return result


def read_limited(path: Path, limit: int = MAX_FILE_BYTES) -> bytes:
    """At most limit + 1 bytes of `path` (one more than allowed, so a caller can tell it was too large)."""
    with open(path, "rb") as handle:
        return handle.read(limit + 1)


def validate_file(path: Path) -> Validation:
    """validate_document() of a file on disk; an unreadable file is rejected whole."""
    try:
        return validate_document(read_limited(path))
    except OSError as exc:
        result = Validation()
        result.invalid = f"cannot read the file ({exc.__class__.__name__})"
        return result


def serialize(advisories: list[Advisory]) -> bytes:
    """The cache file's bytes: the known fields of the accepted entries only."""
    document = {"schema": SCHEMA, "advisories": [advisory.to_json() for advisory in advisories]}
    return (json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Files under .act-local/ (all small, all written atomically)
# ---------------------------------------------------------------------------

def _local(root: Path, name: str) -> Path:
    return root / ".act-local" / name


def cache_path(root: Path) -> Path:
    return _local(root, "advisories.json")


def state_path(root: Path) -> Path:
    return _local(root, "advisories-state.json")


def seen_path(root: Path) -> Path:
    return _local(root, "advisories-seen.json")


def ack_path(root: Path) -> Path:
    return _local(root, "advisories-ack.json")


def store_path(root: Path) -> Path:
    return _local(root, "advisories.git")


def _read_state_file(path: Path) -> dict:
    """A small JSON object from `path`; {} for a missing, oversized or unreadable one."""
    try:
        if path.stat().st_size > _STATE_READ_LIMIT:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_atomic(path: Path, data: bytes) -> bool:
    """Write `data` to `path` through a temp file and a rename. False when it could not be written."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(data)
        actlib.replace_file(tmp, path)
        return True
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False


def _write_json(path: Path, data: dict) -> bool:
    return _write_atomic(path, (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def enabled(root: Path) -> bool:
    """`advisory-check` in docs/ai/config.md: on unless it says off (a missing or unusable value is on)."""
    return actlib.read_config(root).get("advisory-check", "").strip().strip("`").lower() != "off"


def load_cache(root: Path) -> Validation:
    """The cached entries, validated again on every read -- the cache is a file like any other. Missing: none."""
    path = cache_path(root)
    if not path.is_file():
        return Validation()
    return validate_file(path)


def installed_version(root: Path) -> str:
    """`version=` of `.act/VERSION`, else the lock's template version, else ''."""
    try:
        for line in (root / ".act" / "VERSION").read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() == "version" and value.strip():
                return value.strip()
    except OSError:
        pass
    return str(_lock_template(root).get("version") or "")


def _lock_template(root: Path) -> dict:
    lock = _read_state_file(root / ".act-lock.json")
    template = lock.get("template")
    return template if isinstance(template, dict) else {}


_CODE_PREFIXES = (".act/scripts/", ".act/hooks/")  # code always runs from .act/, never from an override


def _project_file(root: Path, rel: str) -> Path:
    """The file that takes effect for a `.act/<x>` path: the project override `docs/ai/local/<x>` if it
    exists, else the `.act/` file (the rule of actlib.resolve(), which works from the working directory, not a
    root). Scripts and hooks are never taken from an override: they run from `.act/` whatever is in
    docs/ai/local/, so for them the `.act/` file is the effective one."""
    if not rel.startswith(_CODE_PREFIXES):
        local = root / "docs" / "ai" / "local" / rel[len(".act/"):]
        if local.is_file():
            return local
    return root / rel


def still_holds(root: Path, rel: str, snippet: str) -> bool:
    """True when the effective file of `rel` contains `snippet` -- or cannot be judged: doubt keeps the
    warning. False only for a file that is missing (FileNotFoundError / NotADirectoryError on stat) or read
    in full without the snippet. Anything else counts as still there: another OS error, a file that is not
    a regular file (device, FIFO, directory: never opened), a path that resolves outside the project (a
    symlink or junction), a file larger than PROJECT_FILE_LIMIT. Read as bytes, never executed."""
    path = _project_file(root, rel)
    try:
        info = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except (OSError, ValueError):
        return True
    if not stat.S_ISREG(info.st_mode) or info.st_size > PROJECT_FILE_LIMIT:
        return True
    try:
        resolved = path.resolve()
        resolved.relative_to(root.resolve())
    except (OSError, ValueError, RuntimeError):
        return True
    try:
        with open(resolved, "rb") as handle:
            data = handle.read(PROJECT_FILE_LIMIT + 1)
    except OSError:
        return True
    if len(data) > PROJECT_FILE_LIMIT:
        return True
    return snippet.encode("utf-8") in data


def fixed_otherwise(root: Path, advisory: Advisory) -> bool:
    """True when the advisory lists `files` and every one is missing or no longer holds its snippet."""
    return bool(advisory.files) and not any(still_holds(root, rel, snippet) for rel, snippet in advisory.files)


def evaluate(root: Path) -> list[Standing]:
    """Each cached advisory judged against the installed version and the lock commit, acknowledgements
    and the `files` check applied. Files only: no git, no network. Empty while `advisory-check` is off.
    An entry is active when (the version satisfies `affected` OR the lock commit starts with one of `commits`)
    AND it is not acknowledged AND it is not fixed otherwise (state `fixed`: its `files` all lost the faulty
    snippet). Every reader goes through here, so all follow."""
    if not enabled(root):
        return []
    version = parse_version(installed_version(root))
    lock_commit = str(_lock_template(root).get("commit") or "").lower()
    acked = _read_state_file(ack_path(root))
    standings: list[Standing] = []
    for advisory in load_cache(root).advisories:
        affected = ((version is not None and version_satisfies(version, advisory.affected))
                    or (bool(lock_commit) and any(lock_commit.startswith(item) for item in advisory.commits)))
        if not affected:
            standings.append(Standing(advisory, "not-affected"))
        elif advisory.id in acked:
            standings.append(Standing(advisory, "acked"))
        elif fixed_otherwise(root, advisory):
            standings.append(Standing(advisory, "fixed"))
        else:
            standings.append(Standing(advisory, "active"))
    return sorted(standings, key=lambda item: (not item.advisory.critical, int(item.advisory.id[1:])))


def active_advisories(root: Path) -> list[Advisory]:
    """The advisories that apply to this project and are not acknowledged: critical first, then by number."""
    return [item.advisory for item in evaluate(root) if item.state == "active"]


# ---------------------------------------------------------------------------
# Display texts
# ---------------------------------------------------------------------------

def _sentence(text: str) -> str:
    return text if text.endswith((".", "!", "?")) else text + "."


def critical_line(advisory: Advisory, version: str) -> str:
    """The session-start line of a critical advisory."""
    parts = [f"⚠ CRITICAL {advisory.id} (template {version or 'unknown'}): {_sentence(advisory.text)}"]
    if advisory.fixed_in:
        parts.append(f"Fixed in {advisory.fixed_in} — run act-update.")
    parts.append('Say "Warnung quittiert" to acknowledge.')
    line = " ".join(parts)
    return f"{line} {advisory.link}" if advisory.link else line


def warning_line(advisory: Advisory, version: str) -> str:
    """The session-start line of a warning."""
    line = f"⚠ {advisory.id} (template {version or 'unknown'}): {advisory.text}"
    return f"{line} {advisory.link}" if advisory.link else line


def fixed_line(advisory: Advisory, version: str) -> str:
    """The one-time session-start line when the project's own files no longer hold the faulty code."""
    return f"✓ {advisory.id} (template {version or 'unknown'}): affected code changed, treated as fixed."


def model_note(advisory: Advisory) -> str:
    """The note for the model at session start (critical only)."""
    return (f"[act] advisory {advisory.id} (critical) applies to this project: {advisory.text} — tell the human "
            f"at once; it is acknowledged only when the human says so (python .act/scripts/advisory.py --ack "
            f"{advisory.id}).")


def status_segment(root: Path) -> Optional[str]:
    """`⚠ A1 A3` for the status line: the active critical advisories, else None."""
    ids = [advisory.id for advisory in active_advisories(root) if advisory.critical]
    return "⚠ " + " ".join(ids) if ids else None


def board_lines(root: Path) -> list[str]:
    """One board line per active critical advisory."""
    version = installed_version(root) or "unknown"
    lines: list[str] = []
    for advisory in active_advisories(root):
        if not advisory.critical:
            continue
        detail = f"template {version}; fixed in {advisory.fixed_in}" if advisory.fixed_in else f"template {version}"
        lines.append(f"> ⚠ **CRITICAL {advisory.id}** — {advisory.text} ({detail}). "
                     'Acknowledge: say "Warnung quittiert".')
    return lines


def _todo_body(advisory: Advisory, version: str) -> str:
    lines = [f"> {advisory.text}", "", f"- Affected: {advisory.affected} (installed: {version or 'unknown'})"]
    if advisory.fixed_in:
        lines.append(f"- Fixed in: {advisory.fixed_in}")
    if advisory.link:
        lines.append(f"- Link: {advisory.link}")
    lines += ["", "The warning stops when act-update brings in a fixed version or when you acknowledge it "
                  '(say "Warnung quittiert"). Close this todo yourself.', ""]
    return "\n".join(lines)


def _existing_todo(root: Path, advisory: Advisory) -> Optional[str]:
    """The file name of a todo of this advisory that the project already has (in the inbox or archived,
    filed from any workstation), found by its heading; None when there is none."""
    heading = re.compile(rf"^# Template advisory {advisory.id}:", re.MULTILINE)
    folders = ((root / "docs" / "ai" / "inbox", "*.md"), (root / "docs" / "ai" / "work" / "archive", "U*.md"))
    for folder, pattern in folders:
        try:
            for path in sorted(folder.glob(pattern)):
                with open(path, "rb") as handle:
                    head = handle.read(4096).decode("utf-8", errors="replace")
                if heading.search(head):
                    return path.name
        except OSError:
            continue
    return None


def _file_todo(root: Path, advisory: Advisory, version: str) -> Optional[str]:
    """File the inbox todo of a critical advisory; its file name, None when it could not be written."""
    try:
        import entries
        path, _entry_id = entries.create_entry(
            root, "todo", f"Template advisory {advisory.id}: critical problem in this template version",
            recipient="all", body=_todo_body(advisory, version), slug=f"advisory-{advisory.id.lower()}",
            lock_timeout=1.5)
        return path.name
    except Exception:  # noqa: BLE001 -- a todo that cannot be filed is retried at the next start
        return None


def session_report(root: Path, file_todos: bool = True) -> SessionReport:
    """What the session start shows for the active advisories, from files only: critical ones at every
    start with a note for the model and, once per id, an inbox todo (`file_todos`); warnings by `repeat`.
    An advisory judged fixed (its `files` lost the faulty snippet) adds one line "affected code changed,
    treated as fixed", once per id, and nothing else. Nothing is raised. The seen record
    (.act-local/advisories-seen.json) keeps the todos, the warnings and the fixed notes already shown, so
    none is filed or shown twice."""
    report = SessionReport()
    standings = evaluate(root)
    active = [item.advisory for item in standings if item.state == "active"]
    fixed = [item.advisory for item in standings if item.state == "fixed"]
    if not active and not fixed:
        return report
    version = installed_version(root)
    seen = _read_state_file(seen_path(root))
    changed = False
    for advisory in active:
        record = seen.get(advisory.id)
        record = dict(record) if isinstance(record, dict) else {}
        if advisory.critical:
            report.lines.append(critical_line(advisory, version))
            report.notes.append(model_note(advisory))
            if file_todos and not record.get("todo"):
                name = _existing_todo(root, advisory) or _file_todo(root, advisory, version)
                if name:
                    record["todo"] = name
        elif advisory.every_start or not record.get("shown"):
            report.lines.append(warning_line(advisory, version))
            if not advisory.every_start:
                record["shown"] = datetime.now().replace(microsecond=0).isoformat()
        if record != seen.get(advisory.id) and record:
            seen[advisory.id] = record
            changed = True
    for advisory in fixed:  # once per id, then silent everywhere
        record = seen.get(advisory.id)
        record = dict(record) if isinstance(record, dict) else {}
        if not record.get("fixed"):
            report.lines.append(fixed_line(advisory, version))
            record["fixed"] = datetime.now().replace(microsecond=0).isoformat()
            seen[advisory.id] = record
            changed = True
    if changed:
        _write_json(seen_path(root), seen)
    return report


# ---------------------------------------------------------------------------
# Acknowledge
# ---------------------------------------------------------------------------

def _refresh_board(root: Path) -> None:
    """Rewrite the board view with board.py, as the session start does, so a board generated before the
    acknowledgement drops its line at once. A subprocess, not an import: board.py imports this module. A
    missing board.py, an error or a timeout leaves the board to the next session start."""
    board_script = root / ".act" / "scripts" / "board.py"
    if not board_script.is_file():
        return
    try:
        subprocess.run([sys.executable, str(board_script)], cwd=root, timeout=BOARD_TIMEOUT, capture_output=True)
    except (OSError, subprocess.TimeoutExpired):
        pass


def acknowledge(root: Path, ids: list[str]) -> tuple[list[str], list[str]]:
    """Acknowledge the named advisories (no id: every active one) in .act-local/advisories-ack.json, then
    rewrite the board view. Returns (acknowledged ids, ids that name no cached advisory); raises OSError when
    the record cannot be written."""
    known = {standing.advisory.id: standing for standing in evaluate(root)}
    wanted = [item.upper() for item in ids] or [adv_id for adv_id, item in known.items() if item.state == "active"]
    done: list[str] = []
    unknown: list[str] = []
    record = _read_state_file(ack_path(root))
    version = installed_version(root)
    now = datetime.now().replace(microsecond=0).isoformat()
    for adv_id in wanted:
        if adv_id not in known:
            unknown.append(adv_id)
        elif adv_id not in done:
            record[adv_id] = {"acked": now, "version": version}
            done.append(adv_id)
    if done and not _write_json(ack_path(root), record):
        raise OSError("cannot write .act-local/advisories-ack.json")
    if done:
        _refresh_board(root)
    return done, unknown


# ---------------------------------------------------------------------------
# Reader: ls-remote, fetch into the bare store, validate, cache
# ---------------------------------------------------------------------------

def _git_env() -> dict[str, str]:
    """The environment of every git call here: never a prompt, a short ssh handshake, and always (a user
    value is overridden) only the protocols a template source can reasonably use -- so a source such as
    `ext::...` can never start a program."""
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o ConnectTimeout=3")
    env["GIT_ALLOW_PROTOCOL"] = "file:git:http:https:ssh"  # also over a user value: no `ext::` program
    return env


def run_git(args: list[str], cwd: Path, timeout: int = GIT_TIMEOUT) -> Optional[tuple[int, bytes]]:
    """`git <args>` (a list: no shell) with a time limit; (return code, stdout bytes), None when git could
    not be run or took too long. stdout goes to a real temp file, not a pipe, so a grandchild that keeps a
    pipe open (an ssh transport) cannot hold the call past its timeout."""
    tmp_dir = tempfile.mkdtemp(prefix="act-advisory-")
    try:
        out_path = Path(tmp_dir) / "git.out"
        try:
            with open(out_path, "wb") as out_file:
                result = subprocess.run(
                    ["git", *args], cwd=cwd, stdin=subprocess.DEVNULL, stdout=out_file,
                    stderr=subprocess.DEVNULL, timeout=timeout, env=_git_env(),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return result.returncode, out_path.read_bytes()
        except (OSError, subprocess.TimeoutExpired):
            return None
    finally:
        for _attempt in range(8):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            if not os.path.isdir(tmp_dir):
                break
            time.sleep(0.25)


def ls_remote(root: Path, source: str, patterns: list[str]) -> Optional[str]:
    """`git ls-remote -- <source> <patterns>` as text; None when it failed, timed out or the source is not
    a git remote or repository. (The session start's worker passes its own helper with the same limits.)"""
    outcome = run_git(["ls-remote", "--", source, *patterns], root)
    if outcome is None or outcome[0] != 0:
        return None
    return outcome[1].decode("utf-8", errors="replace").strip()


def resolve_source(root: Path, source: str) -> str:
    """A source that is a folder (relative to the project, as the lock records it) as its absolute path;
    anything else (a URL, scp-like address) unchanged."""
    if "://" not in source:
        candidate = Path(root, source)
        if candidate.is_dir():
            return str(candidate.resolve())
    return source


def _is_plain_folder(path: Path) -> bool:
    """A local folder that is not a git repository (no .git, not a bare repository)."""
    if not path.is_dir() or (path / ".git").exists():
        return False
    return not ((path / "HEAD").is_file() and (path / "objects").is_dir())


def _read_state(root: Path) -> dict:
    return _read_state_file(state_path(root))


def _record(root: Path, ref_commit: Optional[str], rejected: list[Rejection], error: Optional[str],
            keep_ref: bool = False) -> None:
    previous = _read_state(root)
    _write_json(state_path(root), {
        "ref_commit": previous.get("ref_commit") if keep_ref else ref_commit,
        "checked": datetime.now().date().isoformat(),
        "rejected": [item.to_json() for item in rejected],
        "error": error,
    })


def _install(root: Path, data: bytes, ref_commit: str) -> RefreshResult:
    """Validate `data` and make it the cache: the accepted entries (known fields only) or, when the whole
    file is bad, nothing -- with the reason in the state file."""
    result = validate_document(data)
    if result.invalid:
        try:
            cache_path(root).unlink(missing_ok=True)
        except OSError:
            pass
        _record(root, ref_commit, [], result.invalid)
        return RefreshResult("rejected", result.invalid)
    if result.advisories:
        if not _write_atomic(cache_path(root), serialize(result.advisories)):
            _record(root, None, result.rejected, "cannot write the cache")
            return RefreshResult("error", "cannot write the cache")
    else:
        try:
            cache_path(root).unlink(missing_ok=True)
        except OSError:
            pass
    _record(root, ref_commit, result.rejected, None)
    return RefreshResult("updated", f"{len(result.advisories)} accepted", len(result.advisories), result.rejected)


def _clear(root: Path) -> RefreshResult:
    try:
        cache_path(root).unlink(missing_ok=True)
    except OSError:
        pass
    _record(root, None, [], None)
    return RefreshResult("cleared", "the source has no advisories branch")


def _make_writable(func: Callable, path: str, _exc: object) -> None:
    """rmtree error handler: read-only git objects (Windows) are made writable and removed again."""
    os.chmod(path, 0o700)
    func(path)


def _fetch_branch(root: Path, source: str) -> Optional[bytes]:
    """Fetch only the branch `advisories` of `source` into the bare store under .act-local/ (never the
    project's .git) and return the bytes of its file; None when any step failed. Raises ValueError when the
    file is larger than the limit (decided by `cat-file -s`, before the content is read)."""
    store = store_path(root)
    cwd = store.parent
    cwd.mkdir(parents=True, exist_ok=True)
    git_dir = f"--git-dir={store}"  # explicit on every call: git never searches upward into the project's .git
    healthy = store.is_dir() and (run_git([git_dir, "rev-parse", "--git-dir"], cwd) or (1,))[0] == 0
    if not healthy:
        try:
            if store.is_dir() and not store.is_symlink():
                if sys.version_info >= (3, 12):
                    shutil.rmtree(store, onexc=_make_writable)
                else:
                    shutil.rmtree(store, onerror=_make_writable)
            elif store.exists() or store.is_symlink():
                store.unlink()
        except OSError:
            return None
        outcome = run_git(["init", "-q", "--bare", "--template=", str(store)], cwd)
        if outcome is None or outcome[0] != 0:
            return None
    fetched = run_git([git_dir, "-c", "transfer.fsckObjects=true", "fetch", "-q", "--depth", "1",
                       "--no-tags", "--no-recurse-submodules", "--", source, f"+{BRANCH_REF}:{BRANCH_REF}"],
                      cwd)
    if fetched is None or fetched[0] != 0:
        return None
    spec = f"{BRANCH_REF}:{BRANCH_FILE}"
    size = run_git([git_dir, "cat-file", "-s", spec], cwd)
    if size is None or size[0] != 0:
        return None
    try:
        length = int(size[1].decode("ascii", errors="replace").strip())
    except ValueError:
        return None
    if length > MAX_FILE_BYTES:
        raise ValueError(f"file is larger than 64 KiB ({length} bytes)")
    blob = run_git([git_dir, "cat-file", "blob", spec], cwd)
    if blob is None or blob[0] != 0:
        return None
    return blob[1]


def refresh(root: Path, ls_remote_fn: Optional[Callable[[str, list[str]], Optional[str]]] = None) -> RefreshResult:
    """The reader: look at the source's `advisories` branch and bring the cache up to date. Never raises.
    `advisory-check: off` does nothing at all (the cache stays as it is). A source that is a plain folder is
    read directly (`<folder>/advisories.json`); any other is asked with one ls-remote (`ls_remote_fn`, default
    ls_remote()), and only when the branch's commit differs from the recorded one is that branch fetched.
    A failed ls-remote changes nothing; an answer without the ref clears the cache (deleting the branch
    switches the feature off for everyone)."""
    try:
        return _refresh(root, ls_remote_fn)
    except Exception as exc:  # noqa: BLE001 -- the background worker must never fail the session
        return RefreshResult("error", exc.__class__.__name__)


def _refresh(root: Path, ls_remote_fn: Optional[Callable[[str, list[str]], Optional[str]]]) -> RefreshResult:
    if not enabled(root):
        return RefreshResult("disabled", "advisory-check is off")
    source = str(_lock_template(root).get("source") or "")
    if not source:
        return RefreshResult("no-source", "the lock records no template source")
    source = resolve_source(root, source)
    folder = Path(source)
    if _is_plain_folder(folder):
        path = folder / BRANCH_FILE
        if not path.is_file():
            return _clear(root)
        try:
            data = read_limited(path)
        except OSError as exc:
            _record(root, None, [], f"cannot read the file ({exc.__class__.__name__})", keep_ref=True)
            return RefreshResult("error", "cannot read the file")
        return _install(root, data, "file-" + hashlib.sha256(data).hexdigest()[:16])
    lister = ls_remote_fn or (lambda src, patterns: ls_remote(root, src, patterns))
    listing = lister(source, [BRANCH_REF])
    if listing is None:
        return RefreshResult("unreachable", "the source could not be asked")
    commit = ""
    for line in listing.splitlines():
        sha, _, name = line.partition("\t")
        if name.strip() == BRANCH_REF and _SHA_RE.fullmatch(sha.strip()):
            commit = sha.strip()
    if not commit:
        return _clear(root)
    state = _read_state(root)
    if state.get("ref_commit") == commit:
        _record(root, commit, [Rejection(item.get("id"), str(item.get("reason")))
                               for item in state.get("rejected", []) if isinstance(item, dict)],
                state.get("error") if isinstance(state.get("error"), str) else None)
        return RefreshResult("unchanged", "the branch has not moved")
    try:
        data = _fetch_branch(root, source)
    except ValueError as exc:
        try:
            cache_path(root).unlink(missing_ok=True)
        except OSError:
            pass
        _record(root, commit, [], str(exc))
        return RefreshResult("rejected", str(exc))
    if data is None:
        _record(root, None, [], "the branch could not be fetched", keep_ref=True)
        return RefreshResult("error", "the branch could not be fetched")
    return _install(root, data, commit)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def _cmd_check_file(path_text: str) -> int:
    result = validate_file(Path(path_text))
    if result.invalid:
        print(f"invalid file: {result.invalid}")
        return 1
    for advisory in result.advisories:
        print(f"accepted {advisory.id}: {advisory.severity}, affected {advisory.affected}")
    for rejection in result.rejected:
        print(f"rejected {rejection.id or 'file'}: {rejection.reason}")
    for note in result.notes:
        print(f"note {note}")
    print(f"{len(result.advisories)} accepted, {len(result.rejected)} rejected")
    return 1 if result.rejected else 0


def _cmd_status(root: Path) -> int:
    version = installed_version(root)
    template = _lock_template(root)
    state = _read_state(root)
    print(f"installed version: {version or 'unknown'}")
    print(f"lock commit: {str(template.get('commit') or '')[:12] or 'none'}")
    print(f"advisory-check: {'on' if enabled(root) else 'off'}")
    try:
        age = datetime.now() - datetime.fromtimestamp(cache_path(root).stat().st_mtime)
        print(f"cache: {int(age.total_seconds() // 3600)} h old")
    except OSError:
        print("cache: none")
    print(f"ref commit: {str(state.get('ref_commit') or 'none')[:12]}, checked {state.get('checked') or 'never'}"
          + (f", error: {state['error']}" if state.get("error") else ""))
    standings = evaluate(root)
    if not standings:
        print("no cached advisories")
    for item in standings:
        advisory = item.advisory
        fixed = f", fixed in {advisory.fixed_in}" if advisory.fixed_in else ""
        print(f"{advisory.id}  {advisory.severity:<8}  {item.state:<12}  affected {advisory.affected}{fixed}")
    for item in state.get("rejected", []):
        if isinstance(item, dict):
            print(f"rejected {item.get('id') or 'file'}: {item.get('reason')}")
    return 0


def _cmd_ack(root: Path, ids: list[str]) -> int:
    bad = [item for item in ids if _ID_RE.fullmatch(item.upper()) is None]
    if bad:
        print(f"advisory.py: not an advisory id: {', '.join(bad)} (an id looks like A1)", file=sys.stderr)
        return 2
    try:
        done, unknown = acknowledge(root, ids)
    except OSError as exc:
        print(f"advisory.py: {exc}", file=sys.stderr)
        return 1
    version = installed_version(root) or "unknown"
    for adv_id in done:
        print(f"{adv_id} acknowledged (template {version})")
    for adv_id in unknown:
        print(f"{adv_id}: no such advisory in the cache")
    if not done and not unknown:
        print("no active advisory")
    return 1 if unknown else 0


def _cmd_refresh(root: Path) -> int:
    result = refresh(root)
    print(f"refresh: {result.status}" + (f" ({result.detail})" if result.detail else ""))
    for rejection in result.rejected:
        print(f"rejected {rejection.id or 'file'}: {rejection.reason}")
    return 0 if result.status in ("updated", "unchanged", "cleared", "disabled") else 1


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Warnings from the template author for the installed template version (advisories). "
                    "Without an option: --status.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true",
                       help="show the installed version, the cache and each advisory as active, acked or "
                            "not affected (default)")
    group.add_argument("--ack", nargs="*", metavar="ID",
                       help="acknowledge the named advisories (no id: every active one); it then no longer shows "
                            "at session start, in the status line or on the board")
    group.add_argument("--check-file", metavar="PATH",
                       help="validate an advisories.json file: print the accepted ids and each rejection with its "
                            "reason, exit 1 if anything was rejected; works outside a project")
    group.add_argument("--refresh", action="store_true",
                       help="fetch the source's advisories branch now (5 s limit per git call) instead of "
                            "waiting for the daily background check; needs `advisory-check` on")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    if args.check_file is not None:
        return _cmd_check_file(args.check_file)
    try:
        root = actlib.repo_root()
    except RuntimeError:
        print("advisory.py: not inside a template-managed project (only --check-file works elsewhere)",
              file=sys.stderr)
        return 2
    if args.ack is not None:
        return _cmd_ack(root, args.ack)
    if args.refresh:
        return _cmd_refresh(root)
    return _cmd_status(root)


if __name__ == "__main__":
    sys.exit(main())
