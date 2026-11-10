#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check — a note, never a refusal, when the main session writes throwaway material to the wrong
#          place (R-work-throwaway, PreToolUse, main session only): a shell redirection or write target, or
#          the path of a Write/Edit/MultiEdit/NotebookEdit call, that lies in the system temp directory
#          (`/tmp`, `$TEMP`, `$TMP`, `$TMPDIR`, `%TEMP%`, `$env:TEMP`, the directory `tempfile.gettempdir()`
#          names) or is a file or folder directly under `.act-local/`. The note names the right folder:
#          `.act-local/tmp/<task-id>-<slug>/`, or `.act-local/tmp/<YYYYMMDD>-<slug>/` for work with no task.
#
# Switch `throwaway-place` in docs/ai/config.md § Checks: `warn` (the default, also for a missing row) notes,
# `off` says nothing; `block` counts as `warn` because the call is never refused. A worker's own call is
# not looked at: with a restricted `Write scope:`, `worker-write-scope` refuses it and names the way out. The targets are read with the
# scanners the worker write scope uses (worker_scope_overlap._main_write_paths: command_parse, shell_targets),
# nothing is parsed here. The note reaches the model as PostToolUse context (a PreToolUse line on stdout is
# only shown to the person), queued under `.act-local/throwaway-hints/<tool_use_id>.json`.
#
# Limits: a variable other than the temp variables above, a path built by a program (`mktemp`, `tempfile` in
# inline code) and a write a script file makes on its own are not seen.

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Optional

import actlib

from . import inline_code as _inline_code
from .common import (
    _SHELL_TOOL_NAMES, _TOOL_PATH_FIELDS, _check_mode, _is_worker, _note_only, _pop_pending_notes,
    _queue_pending_note,
)
from .shell_targets import _is_dynamic_target
from .worker_scope_overlap import _main_write_paths, _placed
from .write_scope import _SAFE_ID_RE, _TEMP_VARIABLE_RE, _names_throwaway_place

__all__ = [
    "_HINTS_DIRNAME", "_THROWAWAY_NOTE", "_hint_file", "_known_entry", "_misplaced",
    "check_throwaway_place", "note_throwaway_place",
]

_HINTS_DIRNAME = "throwaway-hints"
_LOCAL_PREFIX = ".act-local/"

_THROWAWAY_NOTE = (
    "[act] note: {where} {shown} — throwaway material belongs in `.act-local/tmp/<task-id>-<slug>/`, or in "
    "`.act-local/tmp/<YYYYMMDD>-<slug>/` for work with no task; `act-local-tidy` clears it after 7 days "
    "(R-work-throwaway). Not refused"
)


def _mode(config: dict) -> str:
    """`off` or `warn`: the call is never refused, so a `block` row counts as `warn`."""
    return "off" if _check_mode(config, "throwaway-place", default="warn") == "off" else "warn"


def _known_entry(name: str) -> bool:
    """A name the template itself creates directly under .act-local/ (act_local_tidy.KNOWN_ENTRIES)."""
    try:
        import act_local_tidy
    except ImportError:
        return False
    lowered = name.lower()
    return any(fnmatch.fnmatchcase(lowered, pattern.lower()) for pattern in act_local_tidy.KNOWN_ENTRIES)


def _misplaced(raw: str, base: Optional[str], literal: bool, root: Path) -> Optional[str]:
    """Where `raw` lies when it is the wrong place for throwaway material: "the system temp directory is not the
    place for" or "a file or folder directly under `.act-local/` is not the place for" (a first part below
    `.act-local/` the template does not create), else None."""
    text = str(raw)
    if _TEMP_VARIABLE_RE.match(text) or _names_throwaway_place(text, base, root, None, literal):
        return "the system temp directory is not the place for"
    placed = _placed(text, base, root, _is_dynamic_target(text) and not literal)
    if placed is not None and placed.startswith(_LOCAL_PREFIX):
        rest = placed[len(_LOCAL_PREFIX):].rstrip("/")
        if rest == _inline_code.WHOLE_FOLDER:
            return "deleting the folder"  # a recursive delete of `.act-local/` itself, not an entry below it
        if rest and not _known_entry(rest.split("/")[0]):
            return "a file or folder directly under `.act-local/` is not the place for"
    return None


def _hint_file(root: Path, tool_use_id: object) -> Optional[Path]:
    if not isinstance(tool_use_id, str) or not _SAFE_ID_RE.match(tool_use_id):
        return None
    path = root / ".act-local" / _HINTS_DIRNAME / f"{tool_use_id}.json"
    return path if actlib.local_write_ok(root, path) else None  # behind a link out of the project: no hint


def check_throwaway_place(payload: dict) -> int:
    """Notes the first misplaced target of this call (stdout, and queued for PostToolUse). Always 0."""
    tool_name = payload.get("tool_name")
    if _is_worker(payload) or not (tool_name in _TOOL_PATH_FIELDS or tool_name in _SHELL_TOOL_NAMES):
        return 0  # the tool is looked at before docs/ai/config.md is read
    if _mode(actlib.read_config()) == "off":
        return 0
    try:
        root = actlib.repo_root()
        targets, _inline = _main_write_paths(payload, root)
    except (RuntimeError, _inline_code.ReaderFailure):
        return 0
    for raw, base, literal in targets:
        where = _misplaced(raw, base, literal, root)
        if where is None:
            continue
        shown = str(raw).replace("\\", "/")
        if where == "deleting the folder":
            shown = _LOCAL_PREFIX
        shown = shown if len(shown) <= 80 else shown[:77] + "..."
        text = _THROWAWAY_NOTE.format(where=where, shown=shown)
        print(text)
        _note_only("throwaway-place")
        path = _hint_file(root, payload.get("tool_use_id"))
        if path is not None:
            _queue_pending_note(path, text, payload)
        return 0
    return 0


def note_throwaway_place(payload: dict) -> Optional[str]:
    """PostToolUse counterpart: the note queued for this very call (by tool_use_id), once; None when there is
    none. Registered in dispatch.py's _POST_TOOL_USE_NOTES."""
    if _is_worker(payload):
        return None
    try:
        path = _hint_file(actlib.repo_root(), payload.get("tool_use_id"))
    except RuntimeError:
        return None
    if path is None or not path.is_file():
        return None
    notes = [] if _mode(actlib.read_config()) == "off" else _pop_pending_notes(path, payload)
    try:
        path.unlink()
    except OSError:
        pass
    return "\n".join(notes) if notes else None
