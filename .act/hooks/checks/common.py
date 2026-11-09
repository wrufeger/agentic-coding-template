#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Helpers shared by more than one check module under .act/hooks/checks/ — reading the
#          hook's JSON payload, resolving a check's on/off/warn mode from docs/ai/config.md, and
#          the two small lookup tables (which tool_input field holds a write target, which tool
#          names start a worker) more than one check needs. Anything used by exactly one check
#          stays in that check's own module instead of here.

from __future__ import annotations

import json
import os
import random
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Callable

__all__ = [
    "_read_payload", "_check_mode", "_TOOL_PATH_FIELDS", "_WORKER_TOOL_NAMES",
    "_SHELL_TOOL_NAMES", "_shell_command", "_is_worker",
    "_HARNESS_MESSAGE_PREFIXES", "_is_harness_message",
    "_load_pending_notes", "_queue_pending_note", "_pop_pending_notes",
    "MAX_NESTING", "_unplaced_target", "_is_unplaced_target", "_unplaced_reason",
]


# How many levels of command text inside command text (`sh -c`, `eval`, `$(...)`, a program's command line,
# PowerShell's `-Command`) any check follows. The one search depth of the write, delete and secret checks: text
# nested deeper is unknown to them, and what a check cannot read it refuses (an unplaced target, below).
MAX_NESTING = 4

# The target that stands for a write the scan could not place or read to the end (deeper than MAX_NESTING, past
# a work budget, code whose path the text does not show). It is no path: every check that reads write targets
# refuses a command that holds one, and none resolves it against the directory the command started in.
_UNPLACED_PREFIX = "<unplaced write: "


def _unplaced_target(reason: str) -> str:
    """The target no check may place, carrying the reason (_UNPLACED_PREFIX)."""
    return f"{_UNPLACED_PREFIX}{reason}>"


def _is_unplaced_target(target: object) -> bool:
    """True for a target of _unplaced_target."""
    return isinstance(target, str) and target.startswith(_UNPLACED_PREFIX) and target.endswith(">")


def _unplaced_reason(target: str) -> str:
    """The reason an _unplaced_target carries, for the message of the check that refuses it."""
    return target[len(_UNPLACED_PREFIX):-1] if _is_unplaced_target(target) else target


def _read_payload() -> dict:
    """Read the hook's JSON payload from stdin. Returns {} for empty/malformed input — a
    payload we cannot parse is never grounds to crash, only to fall back to defaults.

    Reads raw bytes and decodes as UTF-8 explicitly, mirroring dispatch.py's own early
    PostToolUse read — sys.stdin.read() alone picks the console's legacy code page on Windows
    (e.g. cp1252), which silently mangles non-ASCII bytes in the payload before json.loads ever
    sees them (seen in a live probe, 2026-09-23: a prompt's "wörtlich" arrived as "wÃ¶rtlich" in
    ai.log, and a project path with an umlaut made the .act/ write-guard compare against the
    wrong path). errors="replace" keeps a genuinely undecodable byte from crashing the hook."""
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    except (OSError, ValueError, AttributeError):
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


MODES_SEEN: dict[str, str] = {}


def _check_mode(config: dict[str, str], key: str, default: str) -> str:
    """Look up one row of the Checks table in docs/ai/config.md ("block" | "warn" | "off").
    Falls back to `default` for a missing key or an unrecognized value: default deny means
    an unrecognized value is treated the same as an absent row."""
    value = config.get(key, "").strip().lower()
    mode = value if value in ("block", "warn", "off") else default
    MODES_SEEN[key] = mode  # dispatch.py reads which row a check consulted, to tell a `warn` hit from a plain note
    return mode


# What a check in `warn` mode tells the dispatcher about a hit that let the call through, for the incident log:
# row -> {"reason": class word, "target": masked target class, "acts": True when the call wrote, deleted or read a
# secret file}. A check that knows more than "it printed a warning" (the environment override of a row, a read
# against a write, a note that is queued instead of printed) sets it; for any other warning the dispatcher falls
# back on the printed text. Identifiers only: never a path, a command or a value.
HITS: dict[str, dict] = {}


def _note_hit(row: str, reason: str, target: str = "-", acts: bool = True) -> None:
    HITS[row] = {"reason": reason, "target": target, "acts": acts}


def _note_only(row: str) -> None:
    """The row printed a plain note that is no `warn` hit (an informational line of a check whose row says `warn`)."""
    MODES_SEEN[row] = "note"


def _target_class(path: object, root: object = None) -> str:
    """A masked class of a path for the incident log: `project`, `home`, `relative` or `other`, and the number of its
    names, counted below the project or home folder (`home/d3`). Never a name, so no personal data ends up in a log line."""
    try:
        text = str(path).replace("\\", "/").strip()
        if not text:
            return "-"
        lowered = text.lower()
        kind = "other"
        for name, base in (("project", root), ("home", os.path.expanduser("~"))):
            if base:
                prefix = str(base).replace("\\", "/").rstrip("/").lower()
                if prefix and (lowered == prefix or lowered.startswith(prefix + "/")):
                    kind = name
                    text = text[len(prefix):]  # the depth counts below the project or home folder
                    break
        else:
            if not (text.startswith(("/", "~")) or re.match(r"[A-Za-z]:", text)):
                kind = "relative"
        depth = len([part for part in text.split("/") if part and part != "." and not re.fullmatch(r"[A-Za-z]:", part)])
        return f"{kind}/d{depth}"
    except Exception:  # noqa: BLE001 -- a class that cannot be told is no reason to break a check
        return "-"


# Which tool_input field holds the write target, per tool. Bash has no single target field —
# each check that needs a Bash command's write targets reads them through the dispatcher's shared
# parse (`Parse.bash_write_targets`). Shared by checks/write_guard.py and checks/write_scope.py.
_TOOL_PATH_FIELDS = {
    "Write": ("file_path",),
    "Edit": ("file_path",),
    "MultiEdit": ("file_path",),
    "NotebookEdit": ("notebook_path", "file_path"),
}

# The two tool names that start a sub-agent. Shared by checks/nesting_guard.py (denies a
# sub-agent calling either) and checks/write_scope.py (records/reads the write scope an
# Agent/Task start names for the worker it is about to spawn).
_WORKER_TOOL_NAMES = {"Agent", "Task"}

# Tools that run a shell command line in tool_input.command. Claude Code on Windows offers
# PowerShell next to Bash (seen in a live probe); a check that inspects commands must look at both.
_SHELL_TOOL_NAMES = {"Bash", "PowerShell"}


def _shell_command(payload: dict) -> "tuple[str, str] | None":
    """(tool_name, command) for a Bash/PowerShell call, else None."""
    tool_name = payload.get("tool_name")
    if tool_name not in _SHELL_TOOL_NAMES:
        return None
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command.strip():
        return None
    return tool_name, command


def _is_worker(payload: dict) -> bool:
    """True when the call comes from a sub-agent: the harness adds agent_id (and agent_type) to a
    worker's hook payloads and to none of the main session's (seen in a live probe)."""
    return bool(payload.get("agent_id"))


# UserPromptSubmit fires the same way for text the user actually typed and for several things the
# harness itself feeds into the conversation — a worker's SubagentHandback relayed to its caller
# ("<agent-message from=\"...\">...</agent-message>"), a finished-task notice
# ("<task-notification>...</task-notification>"), a message from another session, or a system
# reminder block — confirmed against real payloads from a live probe (2026-09-23,
# its captured payloads.jsonl): both agent-message and
# task-notification observed verbatim, opening the prompt right after leading whitespace, no other
# text before the tag. Neither is something a user "typed" (usage counting, the [user][prompt] log
# line, and a reminder/tip nudge all assume that), so every consumer of payload.prompt on
# UserPromptSubmit checks this first. cross-session-message and system-reminder share the same
# wrapper shape by the harness's own naming convention but were not present in the captured
# session; included defensively, at no cost to the confirmed two.
_HARNESS_MESSAGE_PREFIXES = (
    "<agent-message", "<task-notification", "<cross-session-message", "<system-reminder",
)


def _is_harness_message(prompt: object) -> bool:
    """True when `prompt` (UserPromptSubmit's payload["prompt"]) is harness-fed rather than typed
    by the user — see the prefixes above. A non-string prompt (missing/malformed payload) is never
    a harness message either, just not a match."""
    return isinstance(prompt, str) and prompt.lstrip().startswith(_HARNESS_MESSAGE_PREFIXES)


# --- PostToolUse note queues -------------------------------------------------------------------
# Generic, path-parameterized read/write for a small JSON list of note texts still owed to a
# PostToolUse call — a PreToolUse check queues one or more with _queue_pending_note(path, text),
# the matching note_<name>() drains them all in one go with _pop_pending_notes(path). Moved here
# (2026-09-23, review) from checks/encoding_hint.py, which originated them: checks/secret_scan.py
# also queues/drains through these two, and encoding_hint.py's own key scheme for `path` (which
# id becomes the filename) changed independently of secret_scan.py's — keeping the read/write
# mechanics here, agnostic to what `path` means to any one caller, is what lets both keep using
# them unmodified. encoding_hint.py re-exports both names for backward compatibility (anything
# that did `from .encoding_hint import _pop_pending_notes, _queue_pending_note` keeps working).

def _read_pending_notes(path: Path) -> "list | None":
    """The stored list, [] for a missing or corrupt file, None when the file exists but could not be read
    (on Windows it is briefly unreadable while another hook moves a new version over it, and under load
    that can outlast a few retries) - a caller that is about to write must not mistake that for empty."""
    if not path.is_file():
        return []
    for _attempt in range(25):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except PermissionError:
            time.sleep(0.02)
            continue
        except (OSError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []
    return None


def _load_pending_notes(path: Path) -> list:
    notes = _read_pending_notes(path)
    return [] if notes is None else notes


# Two PostToolUse hooks of one session can queue a note at the same moment. The queue file is
# therefore changed only under a short lock (an exclusively created `<name>.lock` next to it) and
# always written whole to a temp file in the same folder, then moved over the target with
# os.replace, so a reader never sees a half-written list. The lock never blocks or fails a hook:
# a lock that does not free up within the timeout is given up on and the change is made anyway
# (still atomically; at worst a concurrent note is lost, as before), and a lock file older than
# the stale limit belongs to a hook that died and is removed.
_LOCK_TIMEOUT_SECONDS = 3.0
_LOCK_STALE_SECONDS = 10.0
_LOCK_POLL_SECONDS = (0.001, 0.01)  # random pause between two tries, so no waiter starves


def _acquire_note_lock(lock_path: Path) -> bool:
    """Create `lock_path` exclusively. True when this call holds the lock; False after the
    timeout or when the folder cannot be written (the caller then goes on without a lock)."""
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    denied_since: "float | None" = None  # start of the current streak of PermissionErrors
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except PermissionError:
            # on Windows a lock file that is just being deleted refuses a new one for a moment; a folder that
            # really refuses writing is given up on after a short while
            now = time.monotonic()
            if denied_since is None:
                denied_since = now
            if now >= min(deadline, denied_since + 0.5):
                return False
            time.sleep(random.uniform(*_LOCK_POLL_SECONDS))
            continue
        except FileExistsError:
            denied_since = None  # an ordinary wait for the holder, not a refused folder
            try:
                age = time.time() - lock_path.stat().st_mtime
            except OSError:
                age = 0.0  # released between the two calls (or unreadable): look again below
            if age > _LOCK_STALE_SECONDS:
                try:
                    # look once more right before removing: another waiter may have replaced it already
                    if time.time() - lock_path.stat().st_mtime > _LOCK_STALE_SECONDS:
                        lock_path.unlink()
                except OSError:
                    pass
            if time.monotonic() >= deadline:
                return False
            time.sleep(random.uniform(*_LOCK_POLL_SECONDS))
            continue
        except OSError:
            return False
        try:
            os.write(fd, str(os.getpid()).encode("ascii"))
        except OSError:
            pass
        finally:
            os.close(fd)
        return True


def _write_notes_atomic(path: Path, notes: list) -> None:
    """Write the list to a uniquely named temp file next to `path`, then os.replace it over
    `path`. Raises OSError when that fails; the temp file is removed then."""
    data = json.dumps(notes, ensure_ascii=False).encode("utf-8")
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with open(tmp, "xb") as handle:
            handle.write(data)
        # On Windows a reader that has the target open makes replace fail for a moment: retry for a while.
        for attempt in range(40):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 39:
                    raise
                time.sleep(random.uniform(0.002, 0.015))
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _change_notes(path: Path, change: "Callable[[list], list | None]") -> list:
    """Under the lock: load the list, let `change` return the list to store (None: store
    nothing), write it atomically. Returns the list as it was loaded. Best-effort: no failure
    here ever reaches the hook."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    lock_path = path.with_name(f"{path.name}.lock")
    locked = _acquire_note_lock(lock_path)
    try:
        read = _read_pending_notes(path)
        if read is None:  # unreadable right now: writing would replace the stored notes by a guess
            return []
        loaded = read
        stored = change(list(loaded))
        if stored is not None:
            try:
                _write_notes_atomic(path, stored)
            except OSError:
                try:  # the file stayed busy: the plain write is better than losing the note
                    path.write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")
                except OSError:
                    pass
        return loaded
    finally:
        if locked:
            try:
                lock_path.unlink()
            except OSError:
                pass


def _queue_pending_note(path: Path, note: str) -> None:
    """Best-effort: a failed write here only means the matching note_<name>() finds nothing to
    drain later, never a reason to fail the (already allowed) tool call this queues a note for."""
    _change_notes(path, lambda notes: [*notes, note])


def _pop_pending_notes(path: Path) -> list:
    """Read and clear the queue in one go — each queued note is delivered exactly once."""
    if not path.is_file():
        return []
    return _change_notes(path, lambda notes: [] if notes else None)
