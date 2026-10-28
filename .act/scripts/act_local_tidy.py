#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Keeps `.act-local/` small. Throwaway material (probes, scratch projects, old backups,
#          leftovers of earlier versions) piles up there without limit; this module decides what
#          goes and removes it. Rules:
#            - `.act-local/tmp/`: every entry older than 7 days that belongs to no open task;
#            - `.act-local/backup/`: all but the newest 5 backups;
#            - every other entry directly under `.act-local/` that no template script creates
#              (KNOWN_ENTRIES below): same conditions as a `tmp/` entry. Known entries are never
#              removed by this rule.
#          "Age" is the newest mtime of anything inside an entry (links are not followed), so an
#          entry that is still written to stays. An entry "belongs to an open task" when its name
#          equals an open task id or starts with it followed by a non-digit (`<id>-x` belongs to the
#          task, `<id>0-x` does not; case-insensitive). `act-local-keep` in docs/ai/config.md § Checks
#          lists patterns (relative to `.act-local/`) that are never removed; `act-local-tidy`
#          there switches the check: `block` removes, `warn` only reports, `off` skips. Removal is
#          allowed only on a calendar day after the day a report-only result was shown to the human
#          (state key `reported`): until then a run only reports. If `.act-local` is itself a link
#          nothing is touched. A task without an `id:` line in its header (team mode before
#          `assign`) protects no folder.
#          The session start runs this once a day in a detached process (hooks/checks/session.py);
#          the CLI does the same by hand, and `--task` removes one task's folders after its commit.
# Usage:   python .act/scripts/act_local_tidy.py            (= --list: the plan, writes nothing)
#          python .act/scripts/act_local_tidy.py --apply    (remove per plan, as the config allows)
#          python .act/scripts/act_local_tidy.py --task <id>  (remove tmp/<id> and tmp/<id>-*, any age)
# Writes:  removes entries under .act-local/ only; state, result and lock files in .act-local/
#          (act-local-tidy.json, act-local-tidy-result.json, act-local-tidy.lock). Never touches
#          anything outside.
# Exit:    0 normally, 1 when an entry could not be removed, 2 on a usage error.

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import actlib  # noqa: E402

MAX_AGE_DAYS = 7
KEEP_BACKUPS = 5
STATE_NAME = "act-local-tidy.json"
RESULT_NAME = "act-local-tidy-result.json"
LOCK_NAME = "act-local-tidy.lock"
LOCK_STALE_SECONDS = 3600
LINK_NOTE = "skipped: .act-local is a link"

# Entries directly under .act-local/ that template scripts create (fnmatch, case-insensitive). Anything
# else there is "unknown". Where each one comes from:
KNOWN_ENTRIES: tuple[str, ...] = (
    "tmp",                      # this module: throwaway folders per task (handled by the tmp rule)
    "backup",                   # update.py: <YYYYmmdd-HHMMSS>/ copies of reset skill/role files (newest 5 kept)
    "notes",                    # rules: briefs and fetched notes (R-cost-delegate, R-safe-foreign-text)
    "state",                    # entries.py / board.py: working-state lines per task
    "adopt",                    # adopt*.py: state, tables, rescued and aborted copies
    "import", "export",         # import/export scripts
    "feedback",                 # feedback.py: state, outbox entries, sent protocol
    "learn",                    # act-teach skill: learning record per topic
    "usage",                    # hooks/checks/usage.py: event files
    "update-channel-hint",      # update.py: marker for the release-channel hint
    "*.template.md",            # init.py: rescue copies of root entry files (<stem>.template.md)
    "outside-allow",            # adopt scripts: marker read by the outside-root check
    "status-poll",              # hooks/checks/status_poll.py
    "worker-caps",              # hooks/checks/worker_cap.py
    "worker-scopes",            # hooks/checks/write_scope.py, worker_scope_overlap.py
    "danger-scan-hints",        # hooks/checks/danger_scan.py
    "encoding-hints",           # hooks/checks/encoding_hint.py
    "secret-scan-notes",        # hooks/checks/secret_scan.py
    "deps-scan-notes",          # hooks/checks/deps_scan.py
    "merge-heads",              # hooks/checks/deps_scan.py
    "security-scan-cache",      # security_scan.py
    "security-scan-lists",      # hooks/checks/deps_scan.py
    "security-scan-check.json", "security-scan-result.json",   # hooks/checks/session.py
    "update-check.json", "update-check-result.json",           # hooks/checks/session.py
    "advisories.git",           # advisory.py: bare repository the advisories branch is fetched into
    "advisories.json", "advisories-state.json",                # advisory.py: cache and check state
    "advisories-seen.json", "advisories-ack.json",             # advisory.py: todos/warnings shown, acknowledgements
    "update-tmp",               # update.py
    "template-dev",             # marker: this checkout builds the template (init.py refuses to convert it)
    "identity.json", "cache.json", "last-applied.json",        # actlib.py
    "tips.json", "usage.json", "context-hint.json",            # hooks/checks/tips.py, usage.py, context_hint.py
    "ideas-seen.json", "tier-proposals.json",                  # ideas.py, doctor.py
    "outside-root-note.json",   # hooks/checks/session.py
    "session-start.txt",        # hooks/checks/session.py: the whole session-start output
    "log-state.json", "log-state.lock", "entries.lock",        # log.py, entries.py
    "board-*.md", "inbox-*.md",  # board.py: generated views per branch / identity
    STATE_NAME, RESULT_NAME, LOCK_NAME,    # this module
)

_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_BACKUP_NAME_RE = re.compile(r"^(\d{8}-\d{6})(?:-(\d+))?$")
_TASK_ID_RE = re.compile(r"^[A-Za-z]+\d+[A-Za-z]?$")
_ID_LINE_RE = re.compile(r"^id:\s*(\S+)", re.IGNORECASE | re.MULTILINE)
_STATUS_LINE_RE = re.compile(r"^status:\s*(\S+)", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class TidyItem:
    path: Path      # absolute, inside .act-local/
    kind: str       # "tmp" | "backup" | "unknown"
    files: int
    size: int       # bytes
    newest: float   # newest mtime inside, epoch seconds


# ---------------------------------------------------------------------------
# Filesystem helpers (links are never followed)
# ---------------------------------------------------------------------------

def _fs(path: Path | str) -> str:
    """Path for filesystem calls; on Windows with the extended-length prefix so deep trees (node_modules)
    do not hit the 260-character limit."""
    text = os.path.abspath(str(path))
    if sys.platform == "win32" and not text.startswith("\\\\?\\"):
        text = "\\\\?\\UNC\\" + text[2:] if text.startswith("\\\\") else "\\\\?\\" + text
    return text


def _is_link_stat(st: os.stat_result) -> bool:
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)


def _scan(path: Path, stop_after: Optional[float] = None) -> tuple[int, int, float]:
    """(files, bytes, newest mtime) of `path`; a link counts as one file of size 0 and is not entered.
    With `stop_after` the walk ends as soon as something newer than it is found: the entry is kept then, so
    the counts (incomplete in that case) are not needed and `newest` alone is meaningful."""
    try:
        st = os.lstat(_fs(path))
    except OSError:
        return 0, 0, 0.0
    if _is_link_stat(st) or not stat.S_ISDIR(st.st_mode):
        return 1, (0 if _is_link_stat(st) else st.st_size), st.st_mtime
    files, size, newest = 0, 0, st.st_mtime
    if stop_after is not None and newest > stop_after:
        return files, size, newest
    stack = [_fs(path)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = list(it)
        except OSError:
            continue
        for entry in entries:
            try:
                est = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            newest = max(newest, est.st_mtime)
            if stop_after is not None and newest > stop_after:
                return files, size, newest
            if _is_link_stat(est):
                files += 1
            elif stat.S_ISDIR(est.st_mode):
                stack.append(entry.path)
            else:
                files += 1
                size += est.st_size
    return files, size, newest


def _clear_readonly(path: str) -> None:
    """Clears the read-only bit of a file or folder; never of a link (chmod would follow it to the target,
    possibly outside the project)."""
    try:
        if _is_link_stat(os.lstat(path)):
            return
        if os.chmod in os.supports_follow_symlinks:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD, follow_symlinks=False)
        else:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except PermissionError:
        _clear_readonly(path)
        os.unlink(path)
    except IsADirectoryError:
        os.rmdir(path)
    except OSError:
        # a directory link on Windows
        try:
            os.rmdir(path)
        except OSError:
            _clear_readonly(path)
            os.rmdir(path)


def _remove_tree(path: str) -> None:
    """Remove `path` (already an extended, absolute string). Links are removed as links."""
    st = os.lstat(path)
    if _is_link_stat(st) or not stat.S_ISDIR(st.st_mode):
        _unlink(path)
        return
    with os.scandir(path) as it:
        children = list(it)
    errors: list[str] = []
    for child in children:
        try:
            _remove_tree(child.path)
        except OSError as exc:
            errors.append(f"{child.name}: {exc.__class__.__name__}")
    if errors:
        raise OSError("; ".join(errors[:3]))
    try:
        os.rmdir(path)
    except PermissionError:
        _clear_readonly(path)
        os.rmdir(path)


def base_is_link(root: Path) -> bool:
    """True when `.act-local` itself is a link or junction: the tidy then does nothing, since every path
    below it would lead outside the project."""
    try:
        return _is_link_stat(os.lstat(_fs(root / ".act-local")))
    except OSError:
        return False


def _base_usable(root: Path) -> bool:
    """`.act-local` is a real directory (not a link)."""
    try:
        st = os.lstat(_fs(root / ".act-local"))
    except OSError:
        return False
    return stat.S_ISDIR(st.st_mode) and not _is_link_stat(st)


def _inside_tidy_dir(root: Path, path: Path) -> bool:
    """True when `path` is a direct or deeper child of .act-local/ (its parent resolved, the entry itself
    not: a link is judged by where it sits, never by where it points). False when `.act-local` itself is
    a link: it must resolve to where it sits."""
    plain = root.resolve() / ".act-local"
    try:
        base = (root / ".act-local").resolve()
        if base != plain:
            return False
        parent = path.parent.resolve()
    except OSError:
        return False
    if path.name in ("", ".", ".."):
        return False
    return parent == base or base in parent.parents


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

def _keep_patterns(config: dict[str, str]) -> list[str]:
    raw = config.get("act-local-keep", "").strip().strip("`").strip()
    if not raw or raw.lower() == "none":
        return []
    return [p.strip().strip("`").strip().replace("\\", "/").strip("/").lower() for p in raw.split(",") if p.strip()]


def _kept(rel: str, patterns: Iterable[str]) -> bool:
    """True when a pattern matches the entry's relative path or any parent of it (`tmp` keeps `tmp/x`), or
    names something below it (`mydata/important` keeps all of `mydata`: removing the entry would delete it)."""
    parts = rel.lower().split("/")
    prefixes = ["/".join(parts[:n]) for n in range(1, len(parts) + 1)]
    for pattern in patterns:
        if any(fnmatch.fnmatchcase(prefix, pattern) for prefix in prefixes):
            return True
        segments = pattern.split("/")
        if len(segments) > len(parts) and fnmatch.fnmatchcase(prefixes[-1], "/".join(segments[:len(parts)])):
            return True
    return False


def _is_known(name: str) -> bool:
    return any(fnmatch.fnmatchcase(name.lower(), pattern.lower()) for pattern in KNOWN_ENTRIES)


def open_task_ids(root: Path) -> list[str]:
    """Ids of the open tasks: task files under docs/ai/work/tasks/ whose header has an id and no
    `status: done`."""
    folder = root / "docs" / "ai" / "work" / "tasks"
    # Known limit: a task file without an `id:` header line (team mode before `assign`) protects nothing.
    ids: list[str] = []
    if not folder.is_dir():
        return ids
    for path in folder.glob("*.md"):
        if path.name.lower() == "readme.md":
            continue
        try:
            header = actlib.header_block(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        found = _ID_LINE_RE.search(header)
        status = _STATUS_LINE_RE.search(header)
        if found and not (status and status.group(1).lower() == "done"):
            ids.append(found.group(1).strip().lower())
    return ids


def _belongs_to_open_task(name: str, ids: Iterable[str]) -> bool:
    lowered = name.lower()
    for task_id in ids:
        if lowered == task_id:
            return True
        if lowered.startswith(task_id) and not lowered[len(task_id)].isdigit():
            return True
    return False


def _backup_key(name: str, mtime: float) -> tuple:
    match = _BACKUP_NAME_RE.match(name)
    if match:
        return (1, match.group(1), int(match.group(2) or 1), name)
    return (0, f"{mtime:020.3f}", 0, name)


def plan(root: Path, now: Optional[float] = None) -> list[TidyItem]:
    """What would be removed. Pure: reads the config and the task files, writes nothing."""
    import time
    now = time.time() if now is None else now
    base = root / ".act-local"
    if not _base_usable(root):
        return []
    config = actlib.read_config(root)
    patterns = _keep_patterns(config)
    ids = open_task_ids(root)
    limit = now - MAX_AGE_DAYS * 86400
    items: list[TidyItem] = []

    def old_enough(path: Path, rel: str, name: str) -> Optional[TidyItem]:
        if _kept(rel, patterns) or _belongs_to_open_task(name, ids):
            return None
        files, size, newest = _scan(path, limit)  # stops early on the first recent file: the entry stays
        if newest > limit:
            return None
        return TidyItem(path, "tmp" if rel.startswith("tmp/") else "unknown", files, size, newest)

    try:
        top = sorted(os.scandir(_fs(base)), key=lambda e: e.name)
    except OSError:
        return []
    for entry in top:
        name = entry.name
        path = base / name
        lowered = name.lower()
        if lowered == "tmp":
            try:
                st = os.lstat(_fs(path))
                if _is_link_stat(st) or not stat.S_ISDIR(st.st_mode):
                    continue
                children = sorted(os.scandir(_fs(path)), key=lambda e: e.name)
            except OSError:
                continue
            for child in children:
                item = old_enough(path / child.name, f"tmp/{child.name}", child.name)
                if item is not None:
                    items.append(item)
        elif lowered == "backup":
            try:
                st = os.lstat(_fs(path))
                if _is_link_stat(st) or not stat.S_ISDIR(st.st_mode):
                    continue
                children = [(c.name, c.stat(follow_symlinks=False).st_mtime) for c in os.scandir(_fs(path))]
            except OSError:
                continue
            children.sort(key=lambda c: _backup_key(c[0], c[1]), reverse=True)
            for child_name, _mtime in children[KEEP_BACKUPS:]:
                if _kept(f"backup/{child_name}", patterns):
                    continue
                files, size, newest = _scan(path / child_name)
                items.append(TidyItem(path / child_name, "backup", files, size, newest))
        elif not _is_known(name):
            item = old_enough(path, name, name)
            if item is not None:
                items.append(item)
    return items


# ---------------------------------------------------------------------------
# State, summary
# ---------------------------------------------------------------------------

def state_path(root: Path) -> Path:
    return root / ".act-local" / STATE_NAME


def result_path(root: Path) -> Path:
    return root / ".act-local" / RESULT_NAME


def read_state(root: Path) -> dict:
    try:
        data = json.loads(state_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_state(root: Path, **fields: str) -> None:
    if not _base_usable(root):
        return
    data = read_state(root)
    data.update(fields)
    try:
        state_path(root).parent.mkdir(parents=True, exist_ok=True)
        state_path(root).write_text(json.dumps(data) + "\n", encoding="utf-8")
    except OSError:
        pass


def _valid_date(value: object) -> Optional[date]:
    """The date in a state value, None for anything that is not an ISO date (treated as missing)."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def is_first_run(root: Path) -> bool:
    """True while no run has been recorded: the next run only reports."""
    return _valid_date(read_state(root).get("first_run")) is None


def removal_allowed(root: Path, today: date) -> bool:
    """Removal starts on a calendar day after the day a report-only result was shown (`reported`)."""
    reported = _valid_date(read_state(root).get("reported"))
    return reported is not None and reported < today


def record_reported(root: Path, today: Optional[date] = None) -> None:
    """A report-only result was shown to the human today: removal may start on a later day."""
    write_state(root, reported=(today or date.today()).isoformat())


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def _line(count: int, size: int, kinds: dict[str, int], names: list[str], verb: str, tail: str) -> str:
    split = ", ".join(f"{kind} {n}" for kind, n in sorted(kinds.items()))
    shown = ", ".join(names[:5]) + (f", +{count - 5} more" if count > 5 else "")
    return f"act-local-tidy: {verb} {count} entr{'y' if count == 1 else 'ies'} in .act-local/ ({_human_size(size)}; {split}): {shown}{tail}"


def _names(items: list[TidyItem]) -> list[str]:
    return [i.path.parent.name + "/" + i.path.name if i.kind != "unknown" else i.path.name for i in items]


def _kinds(items: list[TidyItem]) -> dict[str, int]:
    kinds: dict[str, int] = {}
    for item in items:
        kinds[item.kind] = kinds.get(item.kind, 0) + 1
    return kinds


_KEEP_HINT = " - keep an entry with `act-local-keep` in docs/ai/config.md"


def format_summary(items: list[TidyItem], first_run: bool) -> str:
    """One line for the human about what the plan would remove; "" when nothing."""
    if not items:
        return ""
    tail = (" - report only, nothing removed; removal starts on a later day, after this has been shown at a "
            "session start" if first_run else "") + _KEEP_HINT
    return _line(len(items), sum(i.size for i in items), _kinds(items), _names(items), "would remove", tail)


def format_result(data: dict, shown: Optional[date] = None) -> str:
    """The session-start line for a result file written by `run_daily`; "" when it holds nothing. `shown` is
    the day the line is shown (default today): a report-only line names the next day removal may start."""
    try:
        count = int(data.get("count", 0))
        failures = [str(f) for f in data.get("failures", [])]
        if not count and not failures:
            return ""
        parts = []
        if count:
            removed = data.get("mode") == "removed"
            first = ((shown or date.today()) + timedelta(days=1)).isoformat()
            tail = "" if removed else (
                f" - report only, nothing removed; removal starts on a later day, the first start on or after {first}"
                if data.get("pending_removal") else " - report only")
            parts.append(_line(count, int(data.get("bytes", 0)), dict(data.get("kinds", {})),
                               [str(n) for n in data.get("names", [])], "removed" if removed else "would remove",
                               tail + _KEEP_HINT))
        if failures:
            parts.append(f"act-local-tidy: could not remove {len(failures)}: {'; '.join(failures[:3])}")
        return " | ".join(parts)
    except (TypeError, ValueError, KeyError):
        return ""


# ---------------------------------------------------------------------------
# Removal
# ---------------------------------------------------------------------------

def _apply_items(root: Path, items: list[TidyItem]) -> tuple[list[TidyItem], int, list[str]]:
    removed: list[TidyItem] = []
    freed = 0
    failures: list[str] = []
    base = root / ".act-local"
    if base_is_link(root):
        return removed, freed, failures
    for item in items:
        label = item.path.relative_to(base).as_posix() if base in item.path.parents else str(item.path)
        if not _inside_tidy_dir(root, item.path):
            failures.append(f"{label}: outside .act-local, not touched")
            continue
        try:
            _remove_tree(_fs(item.path))
        except OSError as exc:
            failures.append(f"{label}: {exc}"[:200])
            continue
        removed.append(item)
        freed += item.size
    return removed, freed, failures


def apply(root: Path, items: list[TidyItem]) -> tuple[int, int, list[str]]:
    """Removes the items. Returns (removed count, bytes freed, failures as "<entry>: <reason>")."""
    removed, freed, failures = _apply_items(root, items)
    return len(removed), freed, failures


def remove_task(root: Path, task_id: str) -> list[Path]:
    """Removes .act-local/tmp/<id> and .act-local/tmp/<id>-*, any age; never the folders of a longer id
    (`<id>0-x`)."""
    if not _TASK_ID_RE.match(task_id.strip()):
        raise ValueError(f"not a task id: {task_id!r}")
    wanted = task_id.strip().lower()
    folder = root / ".act-local" / "tmp"
    removed: list[Path] = []
    if not _base_usable(root):
        return removed
    try:
        st = os.lstat(_fs(folder))
        if _is_link_stat(st) or not stat.S_ISDIR(st.st_mode):
            return removed
        children = sorted(os.scandir(_fs(folder)), key=lambda e: e.name)
    except OSError:
        return removed
    for child in children:
        lowered = child.name.lower()
        if lowered == wanted or lowered.startswith(wanted + "-"):
            target = folder / child.name
            if not _inside_tidy_dir(root, target):
                continue
            try:
                _remove_tree(_fs(target))
                removed.append(target)
            except OSError as exc:
                print(f"act-local-tidy: could not remove {target}: {exc}", file=sys.stderr)
    return removed


# ---------------------------------------------------------------------------
# The daily run (session start worker) and the shared decision
# ---------------------------------------------------------------------------

def tidy_mode(root: Path) -> str:
    value = actlib.read_config(root).get("act-local-tidy", "").strip().strip("`").lower()
    return value if value in ("block", "warn", "off") else "block"


def _lock_token(root: Path) -> str:
    try:
        return (root / ".act-local" / LOCK_NAME).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _take_lock(root: Path) -> str:
    """Exclusive lock file so two session starts at the same moment do not both run the worker. Returns the
    token written into the lock ("" = not taken). A lock older than LOCK_STALE_SECONDS is left over from a
    killed process: it is replaced atomically by one carrying our token, and we own it only if a re-read
    still shows that token."""
    import time
    import uuid
    token = f"{os.getpid()}-{uuid.uuid4().hex}"
    lock = _fs(root / ".act-local" / LOCK_NAME)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        pass
    except OSError:
        return ""
    else:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(token)
        return token
    tmp = f"{lock}.{token}"
    try:
        if time.time() - os.stat(lock).st_mtime < LOCK_STALE_SECONDS:
            return ""
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(token)
        os.replace(tmp, lock)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return ""
    return token if _lock_token(root) == token else ""


def _release_lock(root: Path, token: str) -> None:
    """Removes the lock only while it still carries our token (a run that outlived the stale limit must not
    delete the lock of the run that took over)."""
    if token and _lock_token(root) == token:
        try:
            os.unlink(_fs(root / ".act-local" / LOCK_NAME))
        except OSError:
            pass


def run_daily(root: Path, now: Optional[float] = None) -> dict:
    """One run as the session-start worker does it: at most once per calendar day, honouring the config
    value and the report-first rule (removal only on a day after a report-only result was shown). Writes
    the state file and, when there is anything to say, the result file the next session start reports.
    Returns the result (empty dict when skipped or nothing to do; {"skipped": ...} for a linked
    `.act-local`)."""
    import time
    now = time.time() if now is None else now
    today = datetime.fromtimestamp(now).date()
    mode = tidy_mode(root)
    if mode == "off":
        return {}
    if base_is_link(root):
        return {"skipped": LINK_NOTE}
    if not _base_usable(root):
        return {}
    token = _take_lock(root)
    if not token:
        return {}
    try:
        return _run_daily_locked(root, now, today, mode)
    finally:
        _release_lock(root, token)


def _run_daily_locked(root: Path, now: float, today: date, mode: str) -> dict:
    state = read_state(root)
    if state.get("last_run") == today.isoformat():
        return {}
    items = plan(root, now)
    allowed = mode == "block" and removal_allowed(root, today)
    result: dict = {}
    failures: list[str] = []
    if items:
        shown = items
        if allowed:
            done, freed, failures = _apply_items(root, items)
            shown = done
            result = {"mode": "removed", "count": len(done), "bytes": freed}
        elif _valid_date(state.get("reported")) == today:
            shown = []  # already reported today by the start that spawned this run: removal starts tomorrow
        else:
            result = {"mode": "would", "count": len(items), "bytes": sum(i.size for i in items),
                      "pending_removal": mode == "block"}
        if result:
            result.update({"kinds": _kinds(shown), "names": _names(shown)[:5], "failures": failures[:5],
                           "day": today.isoformat()})
    fields = {"last_run": today.isoformat()}
    if is_first_run(root):
        fields["first_run"] = today.isoformat()
    write_state(root, **fields)
    if result and (result["count"] or failures):
        try:
            result_path(root).write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")
        except OSError:
            pass
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_plan(items: list[TidyItem], root: Path) -> None:
    base = root / ".act-local"
    for item in items:
        print(f"{item.kind:8} {item.files:7} files {_human_size(item.size):>10}  "
              f"{item.path.relative_to(base).as_posix()}")
    print(f"total: {len(items)} entries, {sum(i.files for i in items)} files, {_human_size(sum(i.size for i in items))}")


def main(argv: Optional[list[str]] = None) -> int:
    # Entry names can carry non-ASCII; on Windows stdout/stderr otherwise use the console's legacy code page.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(
        description="Keep .act-local/ small: removes tmp/ entries older than 7 days that belong to no open task, "
                    "all but the newest 5 backups, and unknown old entries. Without an option the plan is listed "
                    "and nothing is written.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--list", action="store_true", help="list what would be removed (default); writes nothing")
    group.add_argument("--apply", action="store_true",
                       help="remove per the plan, honouring `act-local-tidy` (block|warn|off) in docs/ai/config.md "
                            "and the report-first rule (removal only on a calendar day after a report-only "
                            "result was shown; a hand run that only reports counts as shown)")
    group.add_argument("--task", metavar="ID",
                       help="remove .act-local/tmp/<ID> and .act-local/tmp/<ID>-* of any age (the act-commit step)")
    args = parser.parse_args(argv)
    try:
        root = actlib.repo_root()
    except RuntimeError as exc:
        print(f"act-local-tidy: {exc}", file=sys.stderr)
        return 2

    if base_is_link(root):
        print(f"act-local-tidy: {LINK_NOTE}")
        return 0

    if args.task is not None:
        try:
            removed = remove_task(root, args.task)
        except ValueError as exc:
            print(f"act-local-tidy: {exc}", file=sys.stderr)
            return 2
        for path in removed:
            print(f"act-local-tidy: removed {path.relative_to(root).as_posix()}")
        if not removed:
            print(f"act-local-tidy: nothing under .act-local/tmp/ for {args.task}")
        return 0

    items = plan(root)
    _print_plan(items, root)
    if not args.apply:
        return 0
    mode = tidy_mode(root)
    today = date.today()
    if mode == "off":
        print("act-local-tidy: `off` in docs/ai/config.md - nothing removed")
        return 0
    if mode == "warn" or not removal_allowed(root, today):
        reason = "`warn` in docs/ai/config.md" if mode == "warn" else "removal starts on a calendar day after this report"
        print(f"act-local-tidy: report only ({reason}) - nothing removed")
        if mode == "block" and items:
            fields = {"reported": today.isoformat()}
            if is_first_run(root):
                fields["first_run"] = today.isoformat()
            write_state(root, **fields)
        return 0
    count, freed, failures = apply(root, items)
    print(f"act-local-tidy: removed {count} of {len(items)} entries, {_human_size(freed)}")
    for failure in failures:
        print(f"act-local-tidy: could not remove {failure}", file=sys.stderr)
    write_state(root, last_run=today.isoformat())
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
