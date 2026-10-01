#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check — before Write/Edit/MultiEdit/NotebookEdit touches an existing file whose bytes
#          do not decode as UTF-8 (R-code-encoding: "Check a
#          file's encoding before editing it ... otherwise a UTF-8 write destroys the umlauts
#          of a Latin-1/Windows-1252 legacy file"). `block` (the default) stops the
#          *first* write per (session, file) once — exit 2, one line on stderr — and remembers
#          that file as noted, so the repeated write (the assistant trying again, now aware) goes
#          through unmodified (exit 0, no output). `warn` never stops the write; it only delivers
#          one note, via the PostToolUse channel (see below), once per (session, file). `off` does
#          neither. A missing/new file, or anything unreadable, is silently "nothing to say" here
#          in every mode — never a reason to deny.
#
# Delivery mechanism — this module used to emit PreToolUse JSON with permissionDecision: "allow"
# plus hookSpecificOutput.additionalContext, on the theory that additionalContext would reach the
# model on an "allow" decision. Checked again against the Claude Code hooks docs
# (code.claude.com/docs/en/hooks, 2026-09-23): PreToolUse's JSON output supports a *fixed* field
# set — permissionDecision, permissionDecisionReason, updatedInput, systemMessage,
# terminalSequence — and additionalContext is not one of them; it is documented as reaching the
# model only for PostToolUse, UserPromptSubmit and SessionStart. Worse, permissionDecision:
# "allow" *skips the person's own permission prompt* for the tool call — acceptable for a genuine
# deny/ask, not for what is meant to be a passive hint. Corrected design:
#   - `block`: the actual stop is the one channel PreToolUse *does* reliably deliver to the
#     assistant — exit 2 with the reason on stderr (the same convention every denying check in
#     this template already uses). It only fires once per (session, file); the second attempt is a
#     plain exit 0/no output allow, same as any other non-hit.
#   - `warn`: since a plain "[act] ..." stdout line on PreToolUse's exit-0 path is, per the same
#     docs, shown only to the person reading the transcript and never fed back to the model, this
#     check does not print anything from PreToolUse's `warn` branch at all. It only records, in
#     `.act-local/encoding-hints/pending/<tool_use_id>.json`, that a note is owed for THIS tool
#     call — the file may already have been rewritten as UTF-8 by the time PostToolUse fires, so
#     the detection itself only ever happens here, in PreToolUse, before the write.
#     `checks.dispatch`'s `_POST_TOOL_USE_NOTES` registry then calls `note_encoding_hint()` on the
#     matching PostToolUse event, which drains that queue and returns the note text as
#     `hookSpecificOutput.additionalContext` — the field actually documented to reach the model for
#     that event. See dispatch.py's own header for the registry.
#   - `off`: neither channel is touched.
#
# Two different keys, two different reasons (review, 2026-09-23):
#   - the PENDING queue is keyed by `tool_use_id`, not `session_id`: a worker and the main session
#     share the same `session_id` (only `agent_id` tells them apart, per live
#     probes), so a session-wide queue could hand one caller's note to a *different* caller's
#     PostToolUse event if two Write/Edit calls to non-UTF-8 files were in flight in the same
#     session at once. `tool_use_id` is unique per tool call and, per the harness, the SAME value
#     on a call's PreToolUse and its own PostToolUse — so `note_encoding_hint()` only ever drains
#     what THIS call's own PreToolUse queued.
#   - the DEDUP set (`_hints_file`, "have we already said something about this path") is keyed by
#     `session_id` **plus** `agent_id` (or the literal string "main" for the orchestrator's own
#     calls, which carry no `agent_id` at all) — because dedup is a per-*reader* concept: a worker
#     already told about a file should not silently suppress the orchestrator's own first note
#     about that same file (or a different worker's), even though they share one `session_id`.

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Optional

import actlib

from .common import (
    _TOOL_PATH_FIELDS,
    _check_mode,
    _load_pending_notes,
    _pop_pending_notes,
    _queue_pending_note,
)

__all__ = [
    "_READ_CHUNK_SIZE", "_HINTS_DIRNAME", "_SAFE_ID_RE", "_ENCODING_GUESSES",
    "_ENCODING_HINT_DENY", "_ENCODING_HINT_NOTE",
    "_hints_file", "_pending_file", "_load_noted_paths", "_note_path",
    "_load_pending_notes", "_queue_pending_note", "_pop_pending_notes",
    "_resolve_target", "_guess_encoding", "_looks_non_utf8", "_candidate_paths",
    "_reader_key", "check_encoding_hint", "note_encoding_hint",
]

_READ_CHUNK_SIZE = 64 * 1024
_HINTS_DIRNAME = "encoding-hints"
# A session_id/agent_id/tool_use_id becomes part of an entry's filename (see _hints_file,
# _pending_file); validated first, same reasoning as checks/write_scope.py's _SAFE_ID_RE for the
# same kind of harness-supplied id landing in a Path().
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Tried in order against the file's first chunk; the second always succeeds (Latin-1/ISO-8859-1
# maps every byte 0x00-0xFF to a character on its own), so this never returns without a guess.
_ENCODING_GUESSES = ("cp1252", "latin-1")

_ENCODING_HINT_DENY = (
    "[act] {path} is not UTF-8 (looks like {guess}) — writing may change its encoding; keep the "
    "encoding or convert in a separate commit, then repeat the write (R-code-encoding)"
)
_ENCODING_HINT_NOTE = (
    "[act] {path} was not UTF-8 before this write (looked like {guess}) — check that the change "
    "of encoding was intended, keep the original otherwise (R-code-encoding)"
)


def _reader_key(payload: dict) -> Optional[str]:
    """`<session_id>__<agent_id or "main">` — the dedup unit for _hints_file: a *reader*, not a
    session. A worker and the main session share one session_id (seen in live probes), so keying
    dedup by session_id alone would let a worker's note about a file silently suppress the
    orchestrator's own first note about that same file, or one worker's note suppress another's.
    None if session_id is missing/unsafe — dedup is then simply skipped (see check_encoding_hint),
    never a reason to act as if a file's encoding were already noted."""
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not _SAFE_ID_RE.match(session_id):
        return None
    agent_id = payload.get("agent_id")
    suffix = agent_id if isinstance(agent_id, str) and _SAFE_ID_RE.match(agent_id) else "main"
    return f"{session_id}__{suffix}"


def _hints_file(root: Path, reader_key: str) -> Optional[Path]:
    if not _SAFE_ID_RE.match(reader_key):
        return None
    return root / ".act-local" / _HINTS_DIRNAME / f"{reader_key}.json"


def _pending_file(root: Path, tool_use_id: str) -> Optional[Path]:
    """Queue of note texts `warn` mode owes THIS tool call, drained by note_encoding_hint() on the
    matching PostToolUse event — keyed by tool_use_id, not session_id (review, 2026-09-23): the
    harness stamps a call's PreToolUse and its own later PostToolUse with the same tool_use_id, so
    this queue can never hand one call's note to a different, concurrently-queued call's
    PostToolUse the way a session-wide queue could when two Write/Edit calls to non-UTF-8 files
    are in flight in the same session at once. A separate file from _hints_file's dedup set (that
    one is a set of paths already noted per reader, this one is the literal text still owed to one
    specific tool call)."""
    if not _SAFE_ID_RE.match(tool_use_id):
        return None
    return root / ".act-local" / _HINTS_DIRNAME / "pending" / f"{tool_use_id}.json"


def _load_noted_paths(path: Path) -> set:
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return set(data) if isinstance(data, list) else set()


def _note_path(path: Path, noted: set, target: str) -> None:
    """Best-effort bookkeeping: a failed write here only means the same note can repeat later in
    the session, never a reason to fail the tool call this check never blocks past its one-time
    stop in `block` mode."""
    noted.add(target)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sorted(noted), ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _resolve_target(raw: str, base_cwd: Optional[str]) -> Path:
    path = Path(raw)
    if not path.is_absolute() and base_cwd:
        path = Path(base_cwd) / raw
    return path


def _guess_encoding(chunk: bytes) -> str:
    """Best-effort label for the message: the first of _ENCODING_GUESSES that decodes the chunk
    without error. Latin-1 always succeeds, so this always returns something."""
    for name in _ENCODING_GUESSES:
        try:
            chunk.decode(name)
            return name
        except (LookupError, UnicodeDecodeError):
            continue
    return _ENCODING_GUESSES[-1]  # unreachable in practice (latin-1 never fails), kept defensive


def _looks_non_utf8(target: Path) -> Optional[str]:
    """The guessed 8-bit encoding name when the file exists and its first _READ_CHUNK_SIZE bytes
    do not decode as UTF-8; None when the file is missing, unreadable, or already UTF-8 — in each
    of those cases there is nothing to say, never grounds to fail closed (this check only ever
    notes or, in `block` mode, stops once — see the module header)."""
    try:
        if not target.is_file():
            return None
        with open(target, "rb") as handle:
            chunk = handle.read(_READ_CHUNK_SIZE)
    except OSError:
        return None
    try:
        chunk.decode("utf-8")
    except UnicodeDecodeError:
        return _guess_encoding(chunk)
    return None


def _candidate_paths(tool_name: str, tool_input: dict) -> list[str]:
    """The path(s) a Write/Edit/MultiEdit/NotebookEdit call would write to, reusing
    _TOOL_PATH_FIELDS the same way checks/write_guard.py does."""
    paths = []
    for field in _TOOL_PATH_FIELDS.get(tool_name, ()):
        value = tool_input.get(field)
        if isinstance(value, str) and value:
            paths.append(value)
    return paths


def check_encoding_hint(payload: dict) -> int:
    """PreToolUse: `block` stops the first write per (reader, file) to a non-UTF-8 existing file
    (exit 2), then stays quiet about that file for the rest of that reader's session. `warn` never
    stops the write; it queues one note, keyed by this call's own tool_use_id, for
    note_encoding_hint() (PostToolUse) to deliver. `off` does neither. See this module's header
    for the full rationale, including why the dedup key (reader) and the pending-queue key
    (tool_use_id) are deliberately different."""
    config = actlib.read_config()
    mode = _check_mode(config, "encoding-hint", default="block")
    if mode == "off":
        return 0

    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if tool_name not in _TOOL_PATH_FIELDS or not isinstance(tool_input, dict):
        return 0

    reader_key = _reader_key(payload)
    if reader_key is None:
        return 0  # cannot deduplicate per reader -- skip rather than act on every touch

    try:
        root = actlib.repo_root()
    except RuntimeError:
        return 0

    hints_path = _hints_file(root, reader_key)
    if hints_path is None:
        return 0
    noted = _load_noted_paths(hints_path)

    cwd_raw = payload.get("cwd")
    base_cwd = cwd_raw if isinstance(cwd_raw, str) and cwd_raw else None

    for raw in _candidate_paths(tool_name, tool_input):
        if raw in noted:
            continue
        guess = _looks_non_utf8(_resolve_target(raw, base_cwd))
        if guess is None:
            continue
        _note_path(hints_path, noted, raw)
        if mode == "warn":
            tool_use_id = payload.get("tool_use_id")
            if isinstance(tool_use_id, str) and tool_use_id:
                pending_path = _pending_file(root, tool_use_id)
                if pending_path is not None:
                    _queue_pending_note(pending_path, _ENCODING_HINT_NOTE.format(path=raw, guess=guess))
            return 0
        print(_ENCODING_HINT_DENY.format(path=raw, guess=guess), file=sys.stderr)
        return 2
    return 0


def note_encoding_hint(payload: dict) -> Optional[str]:
    """PostToolUse counterpart for `warn` mode: drains and returns whatever check_encoding_hint
    (this same tool call's PreToolUse, matched by tool_use_id — see this module's header) queued —
    None when there is nothing queued, including when the mode is `block`/`off` (neither ever
    queues) or changed since PreToolUse ran. Registered in dispatch.py's _POST_TOOL_USE_NOTES."""
    config = actlib.read_config()
    if _check_mode(config, "encoding-hint", default="block") != "warn":
        return None

    tool_use_id = payload.get("tool_use_id")
    if not isinstance(tool_use_id, str) or not tool_use_id:
        return None

    try:
        root = actlib.repo_root()
    except RuntimeError:
        return None

    pending_path = _pending_file(root, tool_use_id)
    if pending_path is None:
        return None
    notes = _pop_pending_notes(pending_path)
    if not notes:
        return None
    return "\n".join(notes)
