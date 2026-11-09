#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: The incident log. Hooks and scripts note what went wrong without stopping anyone and that the
#          human should see later: a protected file a worker changed that `protected-watch` put back
#          (`restored`) or could not put back (`restore-failed`), a check that crashed or ran out of time
#          (`check-error`, `check-slow`), a `warn` hit where the call went through and wrote, deleted or
#          read a secret file (`warn`), a worker outcome `escalated`, a refusal that made the session or a
#          worker switch model (`model-switch`). Not in it: a refusal (the caller sees it at once; it is
#          only counted, see usage.py), a read-only hint, a hint to the main session.
#          One line per event is appended to .act-local/incidents.jsonl (per machine, never
#          versioned); the next session start delivers the new ones as one inbox report
#          "Incident log <YYYY-MM-DD>" (kind: report, for: all) and says so in one line. Equal events
#          (same kind, source, role and message) are one row with a count.
# Library: record(root, kind, source, message, role) -- append one event, never raises.
#          deliver(root) -- turn the events not delivered yet into the day's inbox report.
#          pending(root) -- how many events wait for delivery (reads only).
# Switch:  ACT_INCIDENT_LOG=off in the environment: both write and deliver nothing for that run
#          (a test suite that drives the hooks keeps the project's own log clean); is_off() tells.
# Safety:  a line holds identifiers only (a check's module name, a tool name, a role/tier, a reason and a
#          masked target class, the first word of a command when it is a plain word, else a class such as
#          `(path)`) -- never a command, a path or a value that could be a secret; message and source are
#          cut and stripped of anything but plain text.
# Files:   .act-local/incidents.jsonl (events), .act-local/incidents.offset (bytes already
#          delivered), .act-local/incidents.lock (held for the instant of one append: on Windows an
#          append is not atomic, two at once could mix a line). Delivered lines stay for KEEP_DAYS days,
#          then the next delivery drops them.
# Limit:   an event appended while a delivery rewrites the file (only when delivered lines are older than
#          KEEP_DAYS) waits for the append lock; it is lost only when that wait runs out; two session starts at the same instant may both
#          deliver the same events; when the offset cannot be written after a delivery, the same events
#          come again with the next one. An append lock that does not come free within half a second is
#          ignored.

from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import actlib

INCIDENTS_FILE = Path(".act-local") / "incidents.jsonl"
OFFSET_FILE = Path(".act-local") / "incidents.offset"
APPEND_LOCK = Path(".act-local") / "incidents.lock"
KEEP_DAYS = 30
OFF_ENV = "ACT_INCIDENT_LOG"  # "off" turns the log off for one run
_LOCK_WAIT = 1.0  # seconds to wait for entries.lock: SessionStart has a hard time limit
_APPEND_WAIT = 0.5  # seconds to wait for the append lock before appending without it
_APPEND_STALE = 5.0  # a lock older than this belongs to a process that died
TITLE_PREFIX = "Incident log "
_WORD_RE = re.compile(r"\A[A-Za-z][A-Za-z0-9_.-]{0,30}\Z")  # a plain command word: no `=`, path or quote
_ASSIGN_RE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*\+?=")
_DRIVE_RE = re.compile(r"\A[A-Za-z]:[\\/]")
_ROW_RE = re.compile(r"^\| (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| ([^|]*) \| ([^|]*) \| ([^|]*) \| ([^|]*) \|(?: (\d+) \|)?\s*$")
_GENERATED_RE = re.compile(r"^(?:Counts|Anzahl): |^\| (?:Time|Zeit) \| |^\| :---")  # the lines of a report this module wrote


def command_word(command: object) -> str:
    """The first word of a command if it is a plain word (`git`, `python3`), else a class in
    parentheses that says why there is none: `(assign)` for `NAME=value`, `(path)`, `(quoted)`,
    `(subshell)`, `(none)` for no text at all, `(other)`. An assignment's value, a path or a quoted
    text is never kept."""
    words = command.split(None, 1) if isinstance(command, str) else []
    if not words:
        return "(none)"
    word = words[0]
    if _WORD_RE.match(word):
        return word
    if _ASSIGN_RE.match(word):
        return "(assign)"
    if word[0] in "\"'":
        return "(quoted)"
    if word[0] in "$(`{":
        return "(subshell)"
    if word[0] in "/.~\\" or _DRIVE_RE.match(word):
        return "(path)"
    return "(other)"


def _clean(text: object, limit: int) -> str:
    """One short line of plain text: whitespace folded, table and code marks removed, cut."""
    folded = " ".join(str(text).split())
    return re.sub(r"[|`\x00-\x1f]", "/", folded)[:limit]


def _off() -> bool:
    """True when ACT_INCIDENT_LOG=off is set for this run."""
    return os.environ.get(OFF_ENV, "").strip().lower() == "off"


def is_off() -> bool:
    """The same, for the other places that write bookkeeping this switch keeps clean (usage.py's refusal counter)."""
    return _off()


class _AppendLock:
    """A lock held for the instant of one append (an exclusively created file). Best effort: a lock that does
    not come free within _APPEND_WAIT is ignored, a stale one is removed -- an event is never dropped for it.
    The file holds its owner's token and only the owner removes it; a stale one is renamed away first, so only one
    waiter takes it, and put back when what was taken is fresh (the same as the note lock in checks/common.py;
    that one cannot be imported here)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.held = False
        self.token = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"

    def _break_stale(self) -> bool:
        """True once the stale lock was renamed away (the caller tries to take the lock again at once); False
        when it could not be, so that the caller's wait runs out as usual."""
        claim = self.path.with_name(f"{self.path.name}.{uuid.uuid4().hex[:8]}.stale")
        try:
            os.rename(self.path, claim)
        except OSError:
            return False
        try:
            if time.time() - claim.stat().st_mtime <= _APPEND_STALE:
                os.link(claim, self.path)  # fails when a new lock was made meanwhile: that one stays
        except OSError:
            pass
        try:
            claim.unlink()
        except OSError:
            pass
        return True

    def __enter__(self) -> "_AppendLock":
        deadline = time.monotonic() + _APPEND_WAIT
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                self.held = True
                try:
                    os.write(fd, self.token.encode("ascii"))
                finally:
                    os.close(fd)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > _APPEND_STALE and self._break_stale():
                        continue
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    return self
                time.sleep(0.005)
            except OSError:
                return self

    def __exit__(self, *_exc: object) -> None:
        if self.held:
            try:
                if self.path.read_text(encoding="ascii", errors="replace") == self.token:
                    self.path.unlink()
            except OSError:
                pass


def record(root: Path, kind: str, source: str, message: str = "", role: str = "") -> None:
    """Append one event. Never raises and writes nothing through a linked .act-local or with
    ACT_INCIDENT_LOG=off."""
    try:
        if _off():
            return
        path = root / INCIDENTS_FILE
        if not actlib.local_write_ok(root, path.parent):
            return
        event = {"t": actlib.created_stamp(), "kind": _clean(kind, 20), "source": _clean(source, 40),
                 "role": _clean(role, 30), "msg": _clean(message, 100)}
        path.parent.mkdir(parents=True, exist_ok=True)
        line = (json.dumps(event, ensure_ascii=True) + "\n").encode("ascii")
        with _AppendLock(root / APPEND_LOCK):
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o666)
            try:
                os.write(fd, line)
            finally:
                os.close(fd)
    except Exception:  # noqa: BLE001 -- a log that cannot be written must never break a hook or script
        pass


def _read_offset(root: Path) -> int:
    try:
        return max(0, int((root / OFFSET_FILE).read_text(encoding="ascii").strip()))
    except (OSError, ValueError):
        return 0


def _new_events(data: bytes) -> list[dict]:
    events: list[dict] = []
    for line in data.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and isinstance(event.get("t"), str) and isinstance(event.get("kind"), str):
            events.append(event)
    return events


def _undelivered(root: Path) -> tuple[bytes, int, int, list[dict]]:
    """(file content, offset, end, events) -- `end` is the end of the last complete line: a line still being
    written is left for the next time."""
    data = (root / INCIDENTS_FILE).read_bytes()
    offset = _read_offset(root)
    if offset > len(data):
        offset = 0  # the file was replaced by a shorter one
    end = data.rfind(b"\n") + 1
    return data, offset, end, (_new_events(data[offset:end]) if end > offset else [])


def pending(root: Path) -> int:
    """How many events wait for delivery. Reads only; 0 on any trouble or with ACT_INCIDENT_LOG=off."""
    try:
        path = root / INCIDENTS_FILE
        if _off() or not path.is_file() or actlib.link_problem(root, path):
            return 0
        return len(_undelivered(root)[3])
    except Exception:  # noqa: BLE001 -- informational only
        return 0


def _event_row(event: dict) -> list:
    when = str(event["t"]).replace("T", " ")[:19]
    return [when, *[_clean(event.get(key, ""), 100) or "-" for key in ("kind", "source", "role", "msg")], 1]


def _merge(rows: list[list]) -> list[list]:
    """Rows with the same kind, source, role and message become one: the latest time, the counts added."""
    merged: dict[tuple, list] = {}
    for row in rows:
        key = tuple(row[1:5])
        if key in merged:
            merged[key][0] = max(merged[key][0], row[0])
            merged[key][5] += row[5]
        else:
            merged[key] = list(row)
    return list(merged.values())


def _body(rows: list[list], language: str, extra: str = "") -> str:
    kinds: dict[str, int] = {}
    for row in rows:
        kinds[row[1]] = kinds.get(row[1], 0) + row[5]
    counts = " · ".join(f"{kind} {number}" for kind, number in sorted(kinds.items(), key=lambda item: (-item[1], item[0])))
    heads = actlib.localized(language, "Time | Kind | Source | Role | Message | Count", "Zeit | Art | Quelle | Rolle | Meldung | Anzahl")
    lines = [f"| {row[0]} | " + " | ".join(row[1:5]) + f" | {row[5]} |" for row in rows]
    text = (f"{actlib.localized(language, 'Counts', 'Anzahl')}: {counts} ({sum(kinds.values())})\n\n| {heads} |\n"
            "| :--- | :--- | :--- | :--- | :--- | ---: |\n" + "\n".join(lines) + "\n")
    return text + (f"\n{extra}\n" if extra else "")


def _split_report(body: str) -> tuple[list[list], str]:
    """(rows, other text) of an open report's body: the table rows this module wrote (a row without a count
    cell, from an older version, counts once) and everything else except the lines it generates -- what a
    person wrote into the report stays."""
    rows: list[list] = []
    other: list[str] = []
    for line in body.splitlines():
        match = _ROW_RE.match(line)
        if match:
            rows.append([*match.group(1, 2, 3, 4, 5), int(match.group(6) or 1)])
        elif not _GENERATED_RE.match(line):
            other.append(line)
    return rows, "\n".join(other).strip("\n")


def _prune_plan(root: Path, end: int) -> tuple[Optional[bytes], int]:
    """(new file content, offset after the cut) when delivered lines older than KEEP_DAYS are to go, else
    (None, end). Nothing is written here."""
    data = (root / INCIDENTS_FILE).read_bytes()
    cutoff = (datetime.now() - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
    kept = b"".join(line for line in data[:end].splitlines(True)
                    if (_new_events(line) or [{"t": ""}])[0]["t"] >= cutoff)
    if len(kept) == end:
        return None, end
    return kept + data[end:], len(kept)


def _open_report_text(root: Path, candidate: Path) -> Optional[str]:
    """The text of `candidate` (CRLF folded) when it is an open report that may be written, else None. Read as
    bytes: a report saved with CRLF line endings (an editor on Windows) is still recognised."""
    try:
        text = candidate.read_bytes().decode("utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeDecodeError):
        return None
    if re.search(r"^status:\s*open\b", text, re.MULTILINE) and not actlib.link_problem(root, candidate):
        return text
    return None


def deliver(root: Path) -> Optional[tuple[Path, int]]:
    """Put the events not delivered yet into the inbox report of today ("Incident log <date>"): an
    open one of the same day gets the rows merged in (equal rows counted together, counts recomputed,
    text a person added kept), else a new one is created the way `entries.py new report` does. Returns
    (entry, number of new events), or None when there was nothing to deliver, the inbox cannot be
    written or ACT_INCIDENT_LOG=off. Marks the events delivered afterwards: the new offset is written
    first, then the delivered lines older than KEEP_DAYS are cut (a failure there changes nothing that
    was delivered)."""
    path = root / INCIDENTS_FILE
    if _off() or not path.is_file() or actlib.link_problem(root, path):
        return None
    _data, _offset, end, events = _undelivered(root)
    if not events:
        return None
    inbox = root / actlib.INBOX_DIR
    if actlib.link_problem(root, inbox):
        return None
    import entries  # deferred: entries imports actlib
    language = actlib.docs_language(root)
    day = datetime.now().strftime("%Y-%m-%d")
    title = f"{TITLE_PREFIX}{day}"
    new_rows = [_event_row(event) for event in events]
    candidates = sorted(inbox.glob(f"report-*-incident-log-{day}.md")) if inbox.is_dir() else []
    with entries._EntriesLock(root, _LOCK_WAIT) as lock:
        if not lock._held:
            return None  # the lock is busy: the events stay undelivered for the next start
        # read under the lock, so that what a person saved while this waited is kept
        target: Optional[Path] = None
        text = ""
        for candidate in candidates:
            found = _open_report_text(root, candidate)
            if found is not None:
                target, text = candidate, found
        if target is None:
            # the lock is held here already; lock_timeout=0 keeps create_entry from waiting for itself
            entry = entries.create_entry(root, "report", title, body=_body(_merge(new_rows), language),
                                         slug=f"incident-log-{day}", lock_timeout=0.0)[0]
        else:
            head = re.search(r"^# .*\n\n", text, re.MULTILINE)
            if head is None:
                return None
            old_rows, extra = _split_report(text[head.end():])
            actlib.write_text_atomic(target, text[:head.end()] + _body(_merge(old_rows + new_rows), language, extra))
            entry = target
    with _AppendLock(root / APPEND_LOCK):  # no append lands between reading the file and rewriting it
        try:
            data, new_end = _prune_plan(root, end)
        except OSError:
            data, new_end = None, end
        try:
            actlib.write_text_atomic(root / OFFSET_FILE, str(new_end))
        except OSError:
            return entry, len(events)  # the offset stays: these events come again with the next delivery
        if data is not None:
            try:
                actlib.write_text_atomic(path, data.decode("ascii", "replace"))
            except OSError:
                try:
                    actlib.write_text_atomic(root / OFFSET_FILE, str(end))  # the file was not cut: the old offset fits it
                except OSError:
                    pass
    return entry, len(events)
