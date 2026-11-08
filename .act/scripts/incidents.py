#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: The incident log. Hooks and scripts note what the human should see later but that no one
#          is told about at the moment it happens: a check in `warn` mode that fired, a check that
#          crashed or ran out of time, a worker outcome `escalated`, a refusal of the main session.
#          One line per event is appended to .act-local/incidents.jsonl (per machine, never
#          versioned); the next session start delivers the new ones as one inbox report
#          "Incident log <YYYY-MM-DD>" (kind: report, for: all) and says so in one line.
# Library: record(root, kind, source, message, role) -- append one event, never raises.
#          deliver(root) -- turn the events not delivered yet into the day's inbox report.
# Safety:  a line holds identifiers only (a check's module name, a tool name, a role/tier, the first
#          word of a command when it is a plain word) -- never a command, a path or a value that
#          could be a secret; message and source are cut and stripped of anything but plain text.
# Files:   .act-local/incidents.jsonl (events), .act-local/incidents.offset (bytes already
#          delivered). Delivered lines stay for KEEP_DAYS days, then the next delivery drops them.
# Limit:   an event appended in the instant a delivery rewrites the file (only when delivered lines
#          are older than KEEP_DAYS) may be lost; two session starts at the same instant may both
#          deliver the same events.

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import actlib

INCIDENTS_FILE = Path(".act-local") / "incidents.jsonl"
OFFSET_FILE = Path(".act-local") / "incidents.offset"
KEEP_DAYS = 30
_LOCK_WAIT = 1.0  # seconds to wait for entries.lock: SessionStart has a hard time limit
TITLE_PREFIX = "Incident log "
_WORD_RE = re.compile(r"\A[A-Za-z][A-Za-z0-9_.-]{0,30}\Z")  # a plain command word: no `=`, path or quote
_ROW_RE = re.compile(r"^\| (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| ([^|]*) \| ([^|]*) \| ([^|]*) \| ([^|]*) \|\s*$")


def command_word(command: object) -> str:
    """The first word of a command if it is a plain word (`git`, `python3`), else "?" -- an
    assignment such as `TOKEN=...` or a path is never kept."""
    words = command.split(None, 1) if isinstance(command, str) else []
    return words[0] if words and _WORD_RE.match(words[0]) else "?"


def _clean(text: object, limit: int) -> str:
    """One short line of plain text: whitespace folded, table and code marks removed, cut."""
    folded = " ".join(str(text).split())
    return re.sub(r"[|`\x00-\x1f]", "/", folded)[:limit]


def record(root: Path, kind: str, source: str, message: str = "", role: str = "") -> None:
    """Append one event. Never raises and writes nothing through a linked .act-local."""
    try:
        path = root / INCIDENTS_FILE
        if not actlib.local_write_ok(root, path.parent):
            return
        event = {"t": actlib.created_stamp(), "kind": _clean(kind, 20), "source": _clean(source, 40),
                 "role": _clean(role, 30), "msg": _clean(message, 100)}
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o666)
        try:
            os.write(fd, (json.dumps(event, ensure_ascii=True) + "\n").encode("ascii"))
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


def _row(event: dict) -> str:
    when = str(event["t"]).replace("T", " ")[:19]
    cells = [_clean(event.get(key, ""), 100) or "-" for key in ("kind", "source", "role", "msg")]
    return f"| {when} | " + " | ".join(cells) + " |"


def _body(rows: list[str], language: str) -> str:
    kinds: dict[str, int] = {}
    for row in rows:
        match = _ROW_RE.match(row)
        if match:
            kinds[match.group(2)] = kinds.get(match.group(2), 0) + 1
    counts = " · ".join(f"{kind} {number}" for kind, number in sorted(kinds.items(), key=lambda item: (-item[1], item[0])))
    heads = actlib.localized(language, "Time | Kind | Source | Role | Message", "Zeit | Art | Quelle | Rolle | Meldung")
    return (f"{actlib.localized(language, 'Counts', 'Anzahl')}: {counts} ({len(rows)})\n\n| {heads} |\n"
            "| :--- | :--- | :--- | :--- | :--- |\n" + "\n".join(rows) + "\n")


def _prune(root: Path, offset: int) -> int:
    """Drop delivered lines older than KEEP_DAYS; returns the offset after the cut."""
    path = root / INCIDENTS_FILE
    data = path.read_bytes()
    cutoff = (datetime.now() - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
    kept = b"".join(line for line in data[:offset].splitlines(True)
                    if (_new_events(line) or [{"t": ""}])[0]["t"] >= cutoff)
    if len(kept) == offset:
        return offset
    actlib.write_text_atomic(path, (kept + data[offset:]).decode("ascii", "replace"))
    return len(kept)


def deliver(root: Path) -> Optional[tuple[Path, int]]:
    """Put the events not delivered yet into the inbox report of today ("Incident log <date>"): an
    open one of the same day gets the rows appended (counts recomputed), else a new one is created
    the way `entries.py new report` does. Returns (entry, number of new events), or None when there
    was nothing to deliver or the inbox cannot be written. Marks the events delivered afterwards."""
    path = root / INCIDENTS_FILE
    if not path.is_file() or actlib.link_problem(root, path):
        return None
    data = path.read_bytes()
    offset = _read_offset(root)
    if offset > len(data):
        offset = 0  # the file was replaced by a shorter one
    end = data.rfind(b"\n") + 1  # a line still being written is left for the next time
    events = _new_events(data[offset:end]) if end > offset else []
    if not events:
        return None
    inbox = root / actlib.INBOX_DIR
    if actlib.link_problem(root, inbox):
        return None
    import entries  # deferred: entries imports actlib
    language = actlib.docs_language(root)
    day = datetime.now().strftime("%Y-%m-%d")
    title = f"{TITLE_PREFIX}{day}"
    new_rows = [_row(event) for event in events]
    target: Optional[Path] = None
    for candidate in sorted(inbox.glob(f"report-*-incident-log-{day}.md")) if inbox.is_dir() else []:
        try:
            text = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if re.search(r"^status:\s*open\b", text, re.MULTILINE) and not actlib.link_problem(root, candidate):
            target = candidate
    with entries._EntriesLock(root, _LOCK_WAIT) as lock:
        if not lock._held:
            return None  # the lock is busy: the events stay undelivered for the next start
        if target is None:
            # the lock is held here already; lock_timeout=0 keeps create_entry from waiting for itself
            entry = entries.create_entry(root, "report", title, body=_body(new_rows, language),
                                         slug=f"incident-log-{day}", lock_timeout=0.0)[0]
        else:
            text = target.read_text(encoding="utf-8")
            head = re.search(r"^# .*\n\n", text, re.MULTILINE)
            if head is None:
                return None
            old_rows = [line for line in text[head.end():].splitlines() if _ROW_RE.match(line)]
            actlib.write_text_atomic(target, text[:head.end()] + _body(old_rows + new_rows, language))
            entry = target
    try:
        actlib.write_text_atomic(root / OFFSET_FILE, str(_prune(root, end)))
    except OSError:
        actlib.write_text_atomic(root / OFFSET_FILE, str(end))
    return entry, len(events)
