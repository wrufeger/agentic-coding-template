#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check 1d — parallel workers never share write scope (R-cost-delegate, PreToolUse
#          Agent/Task of the orchestrator) plus the observer that frees a finished worker's entry.
#
# The orchestrator starts a worker with a `Write scope:` line (see checks/write_scope.py, which
# parses it and records one file per start under .act-local/worker-scopes/<tool_use_id>.json).
# Two workers running at the same time must not write into the same files, so a start whose scope
# overlaps the scope of a worker that is still running is refused (or only reported, mode warn).
#
# Rules: `Write scope: none` never overlaps anything (read-only). A start without the line counts
# as "everything" — it overlaps every scope except none. Two pattern lists overlap when one pair of
# patterns may match the same path. This is a cautious estimate, not a proof: exact paths are
# compared by matching, glob patterns by their fixed leading directory (the part before the first
# "*", "?" or "[") — one a path-prefix of the other counts as an overlap, a pattern that starts
# with a wildcard overlaps everything. Patterns are normalized by write_scope._parse_write_scope
# (a trailing "/" means "/**", absolute paths and `../sibling/...` resolve the same way).
#
# "Still running" = an entry exists, the observer has not removed it at SubagentStop, and it is
# younger than _OVERLAP_ENTRY_TTL. The harness reports a stop only with an agent_id; the entry is
# found through <session>/subagents/agent-<id>.meta.json ("toolUseId"), as write_scope does. The
# harness also fires SubagentStop for its own helper agents, which never had an entry — those are
# passed over silently (see checks/event_log.py). A worker that crashed without a stop leaves its
# entry until the TTL; the message says how to free it at once (delete the named file).
#
# This check records the start's own entry too (same file and content write_scope writes), so it
# works when `worker-write-scope` is off, and so a second start right behind the first already
# sees it. Two starts racing within the same instant can still both pass: each reads before the
# other has written.

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import actlib

from .common import _WORKER_TOOL_NAMES, _check_mode
from .shell_targets import _is_absolute_target
from .write_scope import (
    _matches_scope,
    _parse_write_scope,
    _read_json_object,
    _record_worker_scope,
    _split_glob_prefix,
    _worker_scope_file,
    _worker_scopes_dir,
)

__all__ = [
    "_OVERLAP_ENTRY_TTL", "_entry_time", "_patterns_overlap", "_scopes_overlap", "_remove_worker_scope",
    "check_worker_scope_overlap", "observe",
]

# Shorter than write_scope's 24 h: a crashed worker or a start refused by a later check leaves an
# entry that would otherwise lock its area for a day. Longer than a normal assignment.
_OVERLAP_ENTRY_TTL = timedelta(hours=3)
_FUTURE_SLACK = timedelta(minutes=5)  # a timestamp further ahead is invalid, not "running"


def _segments(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


def _is_path_prefix(shorter: str, longer: str) -> bool:
    a, b = _segments(shorter), _segments(longer)
    return len(a) <= len(b) and b[: len(a)] == a


def _patterns_overlap(first: str, second: str) -> bool:
    """True if two normalized Write scope patterns may match the same path (cautious)."""
    first_abs, second_abs = _is_absolute_target(first), _is_absolute_target(second)
    if first_abs != second_abs:
        return False  # project-relative vs. sibling-checkout (absolute) patterns never meet
    if os.name == "nt" or first_abs:
        first, second = first.casefold(), second.casefold()  # Windows paths ignore case
    first_prefix, first_glob = _split_glob_prefix(first)
    second_prefix, second_glob = _split_glob_prefix(second)
    if not first_glob and not second_glob:
        return first == second
    if not first_glob:
        return _matches_scope(first, [second])
    if not second_glob:
        return _matches_scope(second, [first])
    return _is_path_prefix(first_prefix, second_prefix) or _is_path_prefix(second_prefix, first_prefix)


def _describe(scope: dict) -> str:
    if scope.get("mode") == "unrestricted":
        return "everything (no `Write scope:` line)"
    return ", ".join(scope.get("patterns") or [])


def _scopes_overlap(new: dict, other: dict) -> Optional[tuple[str, str]]:
    """None if the two scopes cannot collide, else a pair of readable descriptions (new, other)."""
    new_mode, other_mode = new.get("mode"), other.get("mode")
    if new_mode not in ("patterns", "unrestricted") or other_mode not in ("patterns", "unrestricted"):
        return None  # none (read-only) and error (writes nothing) never overlap
    if new_mode == "unrestricted" or other_mode == "unrestricted":
        return _describe(new), _describe(other)
    for pattern in new.get("patterns") or []:
        for existing in other.get("patterns") or []:
            if isinstance(pattern, str) and isinstance(existing, str) and _patterns_overlap(pattern, existing):
                return pattern, existing
    return None


def _entry_time(entry: dict) -> Optional[datetime]:
    """The entry's timestamp as an aware datetime (a naive one is read as UTC), else None."""
    ts = entry.get("ts")
    try:
        when = datetime.fromisoformat(ts) if isinstance(ts, str) else None
        if when is not None and when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    return when


def _entry_is_running(entry: dict) -> bool:
    """Younger than the TTL and not more than 5 minutes in the future (then it is invalid)."""
    when = _entry_time(entry)
    if when is None:
        return False
    now = datetime.now(timezone.utc)
    try:
        return now - _OVERLAP_ENTRY_TTL <= when <= now + _FUTURE_SLACK
    except TypeError:
        return False


def check_worker_scope_overlap(payload: dict) -> int:
    """Check 1d: refuse an Agent/Task start whose write scope overlaps a running worker's
    (R-cost-delegate). Only the orchestrator's own calls are looked at. Parallel starts of one
    message really run at the same time, so the start first writes its own entry and only then
    reads the others; of two overlapping starts the one with the later (ts, tool_use_id) yields —
    it removes its own entry and is refused, the earlier one stays. Never both pass, never both
    refused."""
    config = actlib.read_config()
    mode = _check_mode(config, "worker-scope-overlap", default="block")
    if mode == "off":
        return 0
    if payload.get("agent_id") or payload.get("tool_name") not in _WORKER_TOOL_NAMES:
        return 0
    tool_input = payload.get("tool_input")
    tool_use_id = payload.get("tool_use_id")
    prompt = tool_input.get("prompt") if isinstance(tool_input, dict) else None
    if not isinstance(prompt, str) or not isinstance(tool_use_id, str) or not tool_use_id:
        return 0
    try:
        root = actlib.repo_root()
    except RuntimeError:
        return 0

    new = _parse_write_scope(prompt, root) or {"mode": "unrestricted"}
    _record_worker_scope(root, tool_use_id, new)  # claim first, then look at the others
    own_file = _worker_scope_file(root, tool_use_id)
    own_entry = _read_json_object(own_file) if own_file is not None else None
    own_when = _entry_time(own_entry) if own_entry else None
    own_key = (own_when or datetime.now(timezone.utc), tool_use_id)
    try:
        candidates = sorted(_worker_scopes_dir(root).glob("*.json"))
    except OSError:
        candidates = []
    for path in candidates:
        if path == own_file:
            continue
        entry = _read_json_object(path)
        if entry is None or not _entry_is_running(entry):
            continue
        other_when = _entry_time(entry)
        if other_when is None or (other_when, path.stem) > own_key:
            continue  # started after this one: that start yields, not this one
        clash = _scopes_overlap(new, entry)
        if clash is None:
            continue
        message = (
            f"[act] write scope overlaps a running worker's: {clash[0]} vs. {clash[1]} "
            f"(worker {path.stem}) — parallel workers need separate write scopes, otherwise start "
            "this one after the other has ended (R-cost-delegate): give each assignment its own line "
            "`Write scope: <glob>[, <glob> ...]`, e.g. `Write scope: src/api/**` (syntax: "
            ".act/rules/topics/checks.md). If that worker is gone "
            f"(crashed), delete .act-local/worker-scopes/{path.name} or wait {_OVERLAP_ENTRY_TTL}."
        )
        if mode == "warn":
            print(message)
            return 0
        _remove_worker_scope(root, tool_use_id)
        print(message, file=sys.stderr)
        return 2
    return 0


def _remove_worker_scope(root: Path, tool_use_id: str) -> None:
    path = _worker_scope_file(root, tool_use_id)
    if path is None:
        return
    for _attempt in range(20):
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.05)  # Windows: briefly held open by a concurrent reader; the TTL is the last resort


def observe(event: str, payload: dict) -> None:
    """SubagentStop: drop the finished worker's entry. PostToolUseFailure of an Agent/Task call:
    drop the entry of a start that failed. (Not PostToolUse: a background agent gets that right at
    its start.) Never raises; an agent without an entry (the harness's own helper agents) is
    passed over silently."""
    try:
        if event == "PostToolUseFailure":
            tool_use_id = payload.get("tool_use_id")
            if (
                payload.get("tool_name") in _WORKER_TOOL_NAMES
                and not payload.get("agent_id")
                and isinstance(tool_use_id, str)
                and tool_use_id
            ):
                _remove_worker_scope(actlib.repo_root(), tool_use_id)
            return
        if event != "SubagentStop":
            return
        agent_id = payload.get("agent_id")
        if not isinstance(agent_id, str) or not agent_id:
            return
        metas: list[Path] = []
        transcript = payload.get("transcript_path")
        if isinstance(transcript, str) and transcript:
            metas.append(Path(transcript).with_suffix("") / "subagents" / f"agent-{agent_id}.meta.json")
        agent_transcript = payload.get("agent_transcript_path")
        if isinstance(agent_transcript, str) and agent_transcript:
            metas.append(Path(agent_transcript).with_suffix(".meta.json"))
        root = actlib.repo_root()
        for meta_path in metas:
            meta = _read_json_object(meta_path)
            tool_use_id = meta.get("toolUseId") if meta else None
            if isinstance(tool_use_id, str) and tool_use_id:
                _remove_worker_scope(root, tool_use_id)
                return
    except Exception:  # noqa: BLE001 — an observer must never break the event
        return
