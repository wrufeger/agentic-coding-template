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
# patterns may match the same path. An exact path is compared with the other pattern by matching it
# (write_scope._matches_scope). Two glob patterns are compared as the matching reads them — `*` any run
# of characters, `/` included, `?` any one character, every other character (a `[` too) itself — and
# overlap when one string can match both: `src/lib/alpha/**` and `src/lib/beta*` do not (the literal
# `alpha` and `beta` part them), `src/lib/**` and `src/lib/beta*` do, and so do a pattern that starts
# with a wildcard and any other that it can reach (`*.md` and `docs/**`). `dir/**` also counts as the
# directory `dir`, which a worker with that scope may create. Patterns longer than _TABLE_LIMIT
# (as a product of their lengths) count as overlapping. Patterns are normalized by
# write_scope._parse_write_scope (a trailing "/" means "/**", absolute paths and `../sibling/...`
# resolve the same way).
#
# "Still running" = an entry exists, the observer has not marked it ended, and it is younger than
# _OVERLAP_ENTRY_TTL. The harness reports a stop only with an agent_id; the entry is found through
# <session>/subagents/agent-<id>.meta.json ("toolUseId"), as write_scope does. The harness also fires
# SubagentStop for its own helper agents, which never had an entry — those are passed over silently (see
# checks/event_log.py). Three events reach observe():
#   - SubagentStop, and PostToolUse of the orchestrator's TaskStop (its tool_input.task_id is the agent id;
#     a worker stopped that way is not seen ending through SubagentStop): the entry is marked ended, not
#     deleted. The worker no longer counts as running.
#   - SubagentStart: a worker the orchestrator continues with a message (SendMessage) starts again under
#     the same agent id, and no new Agent/Task call records anything. If its entry is marked ended, the mark
#     is cleared and the entry's time renewed: the worker runs again. write_scope finds its scope either
#     way (an ended entry still binds a call of that agent id to its scope).
# Why marked, not deleted: a deleted entry is gone for the resume, and the restricted scopes of workers
# started in the meantime then make write_scope's fail-closed fallback refuse the resumed worker's own writes.
# A worker that crashed without a stop leaves its entry until the TTL; the message names the way to free it
# at once (stop it with TaskStop).
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
    _SAFE_ID_RE,
    _entry_has_ended,
    _matches_scope,
    _parse_write_scope,
    _read_json_object,
    _record_worker_scope,
    _split_glob_prefix,
    _store_worker_scope_entry,
    _worker_scope_file,
    _worker_scopes_dir,
)

__all__ = [
    "_OVERLAP_ENTRY_TTL", "_entry_time", "_patterns_overlap", "_scopes_overlap", "_remove_worker_scope",
    "_mark_worker_scope", "check_worker_scope_overlap", "observe",
]

# Shorter than write_scope's 24 h: a crashed worker or a start refused by a later check leaves an
# entry that would otherwise lock its area for a day. Longer than a normal assignment.
_OVERLAP_ENTRY_TTL = timedelta(hours=3)
_FUTURE_SLACK = timedelta(minutes=5)  # a timestamp further ahead is invalid, not "running"
_TABLE_LIMIT = 250_000  # pattern length product up to which two globs are compared exactly


def _glob_forms(pattern: str) -> list[str]:
    """What a pattern matches as write_scope._matches_scope reads it: the pattern itself and, for
    `dir/**`, the directory `dir` as well (a worker with that scope may create it)."""
    root = pattern[:-3] if pattern.endswith("/**") and len(pattern) > 3 else None
    if root is not None and not any(char in root for char in "*?"):
        return [pattern, root]
    return [pattern]


def _globs_intersect(first: str, second: str) -> bool:
    """True if some path matches both patterns, read the way write_scope._matches_scope matches
    (fnmatch): `*` is any run of characters, `/` included, `?` is any one character, everything else —
    `[` too — stands for itself. Two such patterns are compared character by character, so a literal
    part that cannot match (`t194-*` against `t195-*`) keeps them apart wherever the glob sits. Patterns
    too long to tabulate count as meeting (the cautious answer)."""
    rows, cols = len(first), len(second)
    if rows * cols > _TABLE_LIMIT:
        return True
    # meet[i][j]: the tails first[i:] and second[j:] have a common match. A `*` matches nothing or
    # eats one character of the other pattern's tail (a `*` of its own included, which is the same as
    # skipping it); any other pair of characters must agree, `?` agreeing with every one.
    meet = [[False] * (cols + 1) for _ in range(rows + 1)]
    for i in range(rows, -1, -1):
        for j in range(cols, -1, -1):
            if i == rows and j == cols:
                meet[i][j] = True
            elif i < rows and first[i] == "*":
                meet[i][j] = meet[i + 1][j] or (j < cols and meet[i][j + 1])
            elif j < cols and second[j] == "*":
                meet[i][j] = meet[i][j + 1] or (i < rows and meet[i + 1][j])
            elif i < rows and j < cols:
                meet[i][j] = (first[i] == "?" or second[j] == "?" or first[i] == second[j]) and meet[i + 1][j + 1]
    return meet[0][0]


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
    return any(
        _globs_intersect(one, other)
        for one in _glob_forms(first)
        for other in _glob_forms(second)
    )


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
    """Not marked ended, younger than the TTL and not more than 5 minutes in the future (then it is
    invalid)."""
    if _entry_has_ended(entry):
        return False
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
            f"(worker {path.stem}) — parallel workers need separate write scopes (R-cost-delegate): give "
            "each assignment its own line `Write scope: <glob>[, <glob> ...]`, e.g. `Write scope: "
            "src/api/**` (syntax: .act/rules/topics/checks.md); or merge both tasks into one assignment "
            "with one write scope; or start this one after the other has ended. If that worker is no longer "
            "wanted, stop it with TaskStop: that frees its scope at once. A worker that crashed without any "
            f"stop frees it after {_OVERLAP_ENTRY_TTL}."
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


def _mark_worker_scope(root: Path, tool_use_id: str, ended: bool) -> None:
    """Mark the entry of one Agent/Task start as ended (the worker stopped), or clear that mark and renew
    the entry's time (the worker runs again). Nothing else of the entry changes; an entry that is missing,
    unreadable or already in that state is left alone, and none is created."""
    path = _worker_scope_file(root, tool_use_id)
    entry = _read_json_object(path) if path is not None else None
    if path is None or entry is None or _entry_has_ended(entry) == ended:
        return
    now = datetime.now(timezone.utc).isoformat()
    if ended:
        entry["ended"] = now
    else:
        entry.pop("ended", None)
        entry["ts"] = now
    _store_worker_scope_entry(path, entry)


def _mark_agent_scope(payload: dict, agent_id: object, ended: bool) -> None:
    """Find the entry of the worker `agent_id` through its meta.json ("toolUseId") in the session's
    subagents folder (payload transcript_path) or next to the worker's own transcript
    (agent_transcript_path) and mark it (_mark_worker_scope). An id that is not a safe filename, a meta.json
    that is missing or has no toolUseId: nothing happens."""
    if not isinstance(agent_id, str) or not _SAFE_ID_RE.match(agent_id):
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
            _mark_worker_scope(root, tool_use_id, ended)
            return


def observe(event: str, payload: dict) -> None:
    """SubagentStop and the orchestrator's TaskStop (PostToolUse): mark the stopped worker's entry ended.
    SubagentStart: clear that mark when a stopped worker is continued. PostToolUseFailure of an Agent/Task
    call: drop the entry of a start that failed. (Not PostToolUse of Agent/Task: a background agent gets
    that right at its start.) Never raises; an agent without an entry (the harness's own helper agents) is
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
        if event == "PostToolUse":
            if payload.get("tool_name") == "TaskStop" and not payload.get("agent_id"):
                tool_input = payload.get("tool_input")
                _mark_agent_scope(payload, tool_input.get("task_id") if isinstance(tool_input, dict) else None, True)
            return
        if event in ("SubagentStop", "SubagentStart"):
            _mark_agent_scope(payload, payload.get("agent_id"), event == "SubagentStop")
    except Exception:  # noqa: BLE001 — an observer must never break the event
        return
