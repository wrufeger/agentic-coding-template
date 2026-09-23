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
import sys
from pathlib import Path

__all__ = [
    "_read_payload", "_check_mode", "_TOOL_PATH_FIELDS", "_WORKER_TOOL_NAMES",
    "_SHELL_TOOL_NAMES", "_shell_command", "_is_worker",
    "_load_pending_notes", "_queue_pending_note", "_pop_pending_notes",
]


def _read_payload() -> dict:
    """Read the hook's JSON payload from stdin. Returns {} for empty/malformed input — a
    payload we cannot parse is never grounds to crash, only to fall back to defaults."""
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _check_mode(config: dict[str, str], key: str, default: str) -> str:
    """Look up one row of the Checks table in docs/ai/config.md ("block" | "warn" | "off").
    Falls back to `default` for a missing key or an unrecognized value: default deny means
    an unrecognized value is treated the same as an absent row."""
    value = config.get(key, "").strip().lower()
    return value if value in ("block", "warn", "off") else default


# Which tool_input field holds the write target, per tool. Bash has no single target field —
# each check that needs a Bash command's write targets scans it itself via
# shell_targets._bash_write_targets. Shared by checks/write_guard.py and checks/write_scope.py.
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
# PowerShell next to Bash (seen live in T34); a check that inspects commands must look at both.
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
    worker's hook payloads and to none of the main session's (live probe T30)."""
    return bool(payload.get("agent_id"))


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

def _load_pending_notes(path: Path) -> list:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _queue_pending_note(path: Path, note: str) -> None:
    """Best-effort: a failed write here only means the matching note_<name>() finds nothing to
    drain later, never a reason to fail the (already allowed) tool call this queues a note for."""
    notes = _load_pending_notes(path)
    notes.append(note)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(notes, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _pop_pending_notes(path: Path) -> list:
    """Read and clear the queue in one go — each queued note is delivered exactly once."""
    notes = _load_pending_notes(path)
    if notes:
        try:
            path.write_text(json.dumps([], ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return notes
