#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check 1c — per-worker write scope (R-cost-delegate, PreToolUse).
#
# R-cost-delegate (.act/rules/orchestrator/30-cost.md) has the orchestrator name a `Write scope:`
# line in every assignment — one or more comma-separated glob patterns (project-root-relative,
# "/" as the separator; a bullet prefix and backticks around a pattern are both tolerated, see
# _parse_write_scope), or the literal `none` for a read-only assignment. Missing the line at all
# means "unrestricted" (no scope beyond the template's own .act/ write-guard, check 1) — a
# project that never writes the line never sees this check do anything beyond bookkeeping.
#
# Binding a worker's tool call back to the scope its assignment named runs through the harness's
# own bookkeeping (2026-09-23 live-probe, see the comment above _WORKER_TOOL_NAMES in
# checks/nesting_guard.py for the file): the orchestrator's PreToolUse for "Agent"/"Task" carries
# "tool_use_id" and "tool_input.prompt"; the harness then writes <transcript_path-without-
# ".jsonl">/subagents/agent-<agent_id>.meta.json for that spawned worker, whose "toolUseId" field
# is exactly that same tool_use_id, and agent-<agent_id>.jsonl, whose first line is the worker's
# own initial user message (message.content == the assignment prompt verbatim). So: record the
# scope parsed from the assignment prompt, in its own file keyed by tool_use_id (see
# _worker_scope_file — one file per id, not a shared JSON document, so N parallel Agent/Task
# starts never race each other into a lost update), when the orchestrator starts a worker; look
# it up again, keyed by agent_id -> meta.json -> toolUseId, when that worker later tries to write
# something. A second path (reading the assignment prompt straight out of the worker's own first
# transcript line) covers a missing/unreadable meta.json. If neither works, the binding is
# unresolved for *this* call — see _resolve_worker_scope and check_worker_write_scope's docstring
# for what happens then (it is fail-closed only when scoping is demonstrably in use nearby, not
# unconditionally).

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import actlib

from .common import _TOOL_PATH_FIELDS, _WORKER_TOOL_NAMES, _check_mode
from .powershell_targets import _powershell_write_targets, _ps_raw_redirect_targets
from .shell_targets import (
    _GIT_WRITES_WORKER_SCOPE,
    _bash_write_targets,
    _is_absolute_target,
    _is_dynamic_target,
    _to_native_path,
)

__all__ = [
    "_WORKER_SCOPES_DIRNAME", "_SCOPE_ENTRY_TTL", "_SAFE_ID_RE", "_SCOPE_LINE_RE",
    "_strip_backticks", "_split_glob_prefix", "_root_relative_pattern", "_external_directories",
    "_external_pattern", "_scope_pattern", "_parse_write_scope", "_worker_scopes_dir",
    "_worker_scope_file", "_read_json_object", "_entry_is_fresh", "_prune_worker_scope_files",
    "_record_worker_scope", "_read_worker_scope_entry", "_recent_restricted_scope_registered",
    "_scope_via_meta", "_scope_via_transcript", "_resolve_worker_scope",
    "_normalize_candidate_path", "_within_scratchpad", "_matches_scope", "_write_scope_message",
    "check_worker_write_scope",
]

_WORKER_SCOPES_DIRNAME = "worker-scopes"
_SCOPE_ENTRY_TTL = timedelta(hours=24)

# A tool_use_id becomes an entry's filename (see _worker_scope_file), so it is validated first —
# the harness's own ids look like "toolu_01Ab...", but nothing here may assume that without
# checking, since the string ultimately lands in a Path().
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# "Write scope: <patterns>" — one line, read top to bottom (first match wins, same as a human
# skimming the assignment). An optional leading "- "/"* " bullet is tolerated (assignments are
# often written as a bulleted list), and so is Markdown bold around the key (`**Write scope:**`,
# `**Write scope**:`, also with `__`). "none" (case-insensitive) means read-only; anything else is a
# comma-separated pattern list, each pattern optionally wrapped in backticks (`` `src/**` ``) and/or
# ending in "/" (read as "/**", i.e. a bare directory name means "everything under it"). A prompt
# with no such line at all is "unrestricted", which is deliberately a different value than an
# (impossible) empty pattern list — see _parse_write_scope.
_SCOPE_LINE_RE = re.compile(
    r"^[ \t]*(?:[-*]\s+)?(?:\*\*|__)?Write scope(?:\*\*|__)?:(?:\*\*|__)?\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _strip_backticks(text: str) -> str:
    if len(text) >= 2 and text[0] == "`" and text[-1] == "`":
        return text[1:-1].strip()
    return text


_GLOB_CHARS = frozenset("*?[")


def _split_glob_prefix(native_pattern: str) -> tuple[str, str]:
    """(literal prefix, glob remainder without a leading "/") split at the last "/" before the
    first "*", "?" or "[" in `native_pattern` — the prefix itself holds no glob character, so it is
    safe to pass to Path.resolve() (B127: on Python 3.9/Windows, Path("D:/…/src/**").resolve() can
    raise OSError — WinError 123, "The filename, directory name, or volume label syntax is
    incorrect" — for the glob part alone, which the caller then mistook for "outside the project
    root" and refused every write). No glob character at all: the whole pattern is the prefix,
    remainder "". A glob character in the first path segment (no "/" before it): prefix "",
    remainder the whole pattern unchanged — resolving is not attempted there either."""
    idx = next((i for i, ch in enumerate(native_pattern) if ch in _GLOB_CHARS), None)
    if idx is None:
        return native_pattern, ""
    cut = native_pattern.rfind("/", 0, idx)
    if cut == -1:
        return "", native_pattern
    return native_pattern[:cut], native_pattern[cut + 1:]


def _root_relative_pattern(pattern: str, root: Path) -> tuple[Optional[str], Optional[str]]:
    """A single `Write scope:` pattern (already "/"-normalized, no trailing "/"), turned
    project-root-relative if it is written as an absolute path (Windows drive letter, POSIX, or a
    Git-Bash `/d/...` form via _to_native_path): drive letter/case and "\\" vs "/" are normalized
    the same way _normalize_candidate_path does it for a write target, since that is what a
    pattern is ultimately matched against (_matches_scope always compares against a root-relative
    path — B127). A pattern left as-is (already relative) comes back unchanged, (pattern, None).
    An absolute pattern that resolves inside `root` comes back as (root-relative, None). One that
    does not — genuinely outside the project — comes back as (None, message), the message naming
    the pattern and stating that patterns are root-relative. Only the glob-free part of the
    pattern is ever given to Path.resolve() (see _split_glob_prefix, B127) — a pattern with no
    glob-free prefix at all (a glob character in its very first segment) is passed through
    unresolved, since there is nothing safe left to resolve."""
    if not _is_absolute_target(pattern):
        return pattern, None
    native = _to_native_path(pattern)
    prefix, remainder = _split_glob_prefix(native)
    if not prefix:
        return pattern, None
    try:
        rel = Path(prefix).resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        message = (
            f"[act] write scope pattern is outside the project root: {pattern} "
            "(a Write scope pattern is always project-root-relative, R-cost-delegate)"
        )
        return None, message
    rel_str = rel.as_posix()
    if not remainder:
        return rel_str, None
    return (remainder if rel_str == "." else f"{rel_str}/{remainder}"), None


def _external_directories(root: Path) -> list[Path]:
    """Every directory named in `permissions.additionalDirectories`, read from `.claude/
    settings.json` and `.claude/settings.local.json` under `root` (both, local's own entries added
    to the project's — the same two files Claude Code itself reads its own additionalDirectories
    from), each resolved to an absolute path — a relative entry (the usual case: `../sibling`) the
    same way Claude Code reads it itself, relative to the project root (B138). Best-effort: a
    missing, unreadable or malformed settings file simply contributes nothing; this is read fresh
    on every call rather than cached, matching how little else in this module caches project state."""
    directories: list[Path] = []
    for name in ("settings.json", "settings.local.json"):
        data = _read_json_object(root / ".claude" / name)
        if data is None:
            continue
        permissions = data.get("permissions")
        entries = permissions.get("additionalDirectories") if isinstance(permissions, dict) else None
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, str) or not entry:
                continue
            native = _to_native_path(entry.replace("\\", "/"))
            try:
                candidate = Path(native)
                resolved = candidate.resolve() if candidate.is_absolute() else (root / native).resolve()
            except OSError:
                continue
            directories.append(resolved)
    return directories


def _external_pattern(native_pattern: str, root: Path) -> Optional[str]:
    """A `Write scope:` pattern's resolved absolute-POSIX form (glob remainder kept, see
    _split_glob_prefix) if its glob-free prefix resolves inside one of `root`'s own
    `permissions.additionalDirectories` (B138) — a worker's assignment can then name a path in a
    sibling checkout, e.g. `../template-next/.act/**` (written relative to the project root, same
    as any other Write scope pattern) or the equivalent absolute path. None if it resolves inside
    none of them — deliberately not an error on its own; the caller still has its own out-of-root
    message to fall back to. `native_pattern` is resolved from `root` when it is not already
    absolute, same as a Write scope pattern always is."""
    prefix, remainder = _split_glob_prefix(native_pattern)
    if not prefix:
        return None
    try:
        prefix_path = Path(prefix)
        resolved_prefix = prefix_path.resolve() if prefix_path.is_absolute() else (root / prefix).resolve()
    except OSError:
        return None
    for directory in _external_directories(root):
        try:
            resolved_prefix.relative_to(directory)
        except ValueError:
            continue
        rel_str = str(resolved_prefix).replace("\\", "/")
        return rel_str if not remainder else f"{rel_str}/{remainder}"
    return None


def _scope_pattern(pattern: str, root: Path) -> tuple[Optional[str], Optional[str]]:
    """One `Write scope:` pattern (already "/"-normalized, no trailing slash), turned into the form
    _matches_scope compares a write target against: project-root-relative for the ordinary case, or
    — since B138 — the pattern's own resolved absolute-POSIX form when it names a directory listed
    in `root`'s `permissions.additionalDirectories` instead (a worker's assignment reaching into a
    sibling checkout pulled in that way). Tried in order: _root_relative_pattern for an absolute
    pattern (unchanged, B127); left unchanged, without touching the filesystem, for a relative
    pattern that plainly stays inside the project root (the overwhelmingly common case — anything
    not starting with ".."); _external_pattern for an absolute pattern _root_relative_pattern
    refused, or a relative one starting with ".."; an out-of-root error otherwise, naming both ways
    a pattern is accepted (project-root-relative, or under additionalDirectories)."""
    if _is_absolute_target(pattern):
        rel, error = _root_relative_pattern(pattern, root)
        if not error:
            return rel, None
        external = _external_pattern(_to_native_path(pattern), root)
        if external is not None:
            return external, None
    elif not pattern.startswith("..") or (len(pattern) > 2 and pattern[2] not in "/\\"):
        return pattern, None  # relative, stays inside the project root -- unchanged, as always
    else:
        external = _external_pattern(pattern, root)
        if external is not None:
            return external, None
    message = (
        f"[act] write scope pattern is outside the project root: {pattern} "
        "(a Write scope pattern is project-root-relative, or leads into a directory listed in "
        "permissions.additionalDirectories, R-cost-delegate)"
    )
    return None, message


def _parse_write_scope(prompt: str, root: Optional[Path] = None) -> Optional[dict]:
    """Parse the first `Write scope: ...` line out of an assignment prompt (see _SCOPE_LINE_RE for
    the accepted line shapes: an optional bullet, patterns optionally backtick-wrapped and/or
    ending in "/"). Returns None if no such line is present at all ("unrestricted" — deliberately
    distinct from a scope that names zero patterns, which cannot happen: an empty pattern list
    falls back to None too). Otherwise {"mode": "none"}, {"mode": "patterns", "patterns": [...]},
    or — when `root` is given and a pattern is an absolute path outside it (B127) —
    {"mode": "error", "message": <str>}, one message for the first such pattern found; that mode is
    only ever surfaced by the caller at the point of an actual write attempt, not at worker start
    (see check_worker_write_scope), since a bad scope is otherwise only recorded, never enforced,
    when nothing is ever written under it. Without `root` (a caller that has none reachable), an
    absolute pattern is passed through unchanged, same as before B127."""
    match = _SCOPE_LINE_RE.search(prompt)
    if not match:
        return None
    raw = match.group(1).strip()
    parts = [_strip_backticks(p.strip()) for p in raw.split(",")]
    parts = [p for p in parts if p]
    if not parts:
        return None
    if len(parts) == 1 and parts[0].lower() == "none":
        return {"mode": "none"}
    patterns = []
    for part in parts:
        pattern = part.replace("\\", "/")
        trailing_slash = pattern.endswith("/")
        if trailing_slash:
            pattern = pattern[:-1]
        if root is not None:
            pattern, error = _scope_pattern(pattern, root)
            if error:
                return {"mode": "error", "message": error}
        if trailing_slash:
            pattern += "/**"
        patterns.append(pattern)
    return {"mode": "patterns", "patterns": patterns}


def _worker_scopes_dir(root: Path) -> Path:
    return root / ".act-local" / _WORKER_SCOPES_DIRNAME


def _worker_scope_file(root: Path, tool_use_id: str) -> Optional[Path]:
    """Path for one worker's recorded scope — one file per tool_use_id, so N parallel Agent/Task
    starts each own their own file and never race each other into a lost update the way a single
    shared JSON file did under concurrent read-modify-write (2026-09-23 review, t26_race.py: 8
    parallel starts lost 6 of 8 entries against the old single-file scheme). None if `tool_use_id`
    is not a safe filename (see _SAFE_ID_RE) — such an id is simply never recorded, not written
    somewhere unsafe."""
    if not isinstance(tool_use_id, str) or not _SAFE_ID_RE.match(tool_use_id):
        return None
    return _worker_scopes_dir(root) / f"{tool_use_id}.json"


def _read_json_object(path: Path) -> Optional[dict]:
    """Local, minimal twin of actlib._read_json — kept in this module rather than imported since
    that helper is private to actlib.py. Same contract: None for missing/unreadable/non-object."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _entry_is_fresh(entry: dict) -> bool:
    ts = entry.get("ts")
    try:
        when = datetime.fromisoformat(ts) if isinstance(ts, str) else None
    except ValueError:
        when = None
    return when is not None and when >= datetime.now(timezone.utc) - _SCOPE_ENTRY_TTL


def _prune_worker_scope_files(dir_path: Path, skip: Path) -> None:
    """Delete every scope file older than _SCOPE_ENTRY_TTL, or unreadable/malformed — run
    opportunistically on each write rather than on a schedule, so no separate cleanup process is
    needed. `skip` is the file just written in this same call, left alone unconditionally (it
    cannot be stale — it was just stamped with the current time)."""
    try:
        candidates = list(dir_path.glob("*.json"))
    except OSError:
        return
    for path in candidates:
        if path == skip:
            continue
        entry = _read_json_object(path)
        if entry is None or not _entry_is_fresh(entry):
            try:
                path.unlink()
            except OSError:
                pass


def _record_worker_scope(root: Path, tool_use_id: str, scope: dict) -> None:
    """Record one Agent/Task start's write scope in its own file (see _worker_scope_file), so a
    worker's later call can look it up via its meta.json's "toolUseId" (_scope_via_meta). Always
    called — even for "unrestricted" — so _recent_restricted_scope_registered can tell "a start was
    registered here and named no restriction" from "nothing has run against this check yet" (see
    that function and check_worker_write_scope's fail-closed fallback). Best-effort: a failed write
    here only weakens that fallback, it never blocks the orchestrator's own call.

    Written via a temp file plus os.replace in the same directory, so a concurrent reader never
    observes a partially written file — os.replace is an atomic rename on both POSIX and Windows."""
    path = _worker_scope_file(root, tool_use_id)
    if path is None:
        return  # unsafe id -- never recorded, not an error
    entry = dict(scope)
    entry["ts"] = datetime.now(timezone.utc).isoformat()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # suffix ".tmp", not ".json": _prune_worker_scope_files globs "*.json", and a temp file
        # that matched that pattern was briefly visible (between creation and the os.replace
        # below) to a *concurrent* writer's own prune pass — which could delete it before this
        # replace runs, dropping this write silently (2026-09-23 review, t26_race.py: 8 parallel
        # starts sometimes wrote as few as 4 of 8 files under the old ".json"-suffixed temp name).
        fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", suffix=".tmp", dir=str(path.parent))
    except OSError:
        return
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp_name, path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        return
    _prune_worker_scope_files(path.parent, skip=path)


def _read_worker_scope_entry(root: Path, tool_use_id: str) -> Optional[dict]:
    """The scope recorded for one tool_use_id, or None if it was never recorded, is unreadable, or
    has aged past _SCOPE_ENTRY_TTL."""
    path = _worker_scope_file(root, tool_use_id)
    if path is None:
        return None
    entry = _read_json_object(path)
    if entry is None or not _entry_is_fresh(entry):
        return None
    return entry


def _recent_restricted_scope_registered(root: Path) -> bool:
    """True if any worker-scopes file, within _SCOPE_ENTRY_TTL, holds an entry whose mode is "none"
    or "patterns" (i.e. an assignment actually named a restriction) — as opposed to only
    "unrestricted" entries or none at all. Used by check_worker_write_scope's fail-closed fallback:
    a binding failure is only treated as suspicious when scoping is demonstrably in active use
    nearby.

    A damaged file (unreadable, not JSON, no usable "mode") does not count as "restricted" — so if
    such files are all there is, an unbound worker is allowed. Deliberate: a broken bookkeeping file
    must not lock every worker out; it is pruned on the orchestrator's next Agent/Task start
    (_prune_worker_scope_files), and a bound worker is unaffected either way."""
    try:
        candidates = list(_worker_scopes_dir(root).glob("*.json"))
    except OSError:
        return False
    for path in candidates:
        entry = _read_json_object(path)
        if entry is None or entry.get("mode") not in ("none", "patterns"):
            continue
        if _entry_is_fresh(entry):
            return True
    return False


def _scope_via_meta(root: Path, transcript_path: object, agent_id: str) -> Optional[dict]:
    """Look up the scope recorded for this worker via <session>/subagents/agent-<id>.meta.json's
    "toolUseId" (see this module's docstring). None if the meta.json is missing/unreadable, has
    no usable "toolUseId", or nothing was ever recorded under that id."""
    if not isinstance(transcript_path, str) or not transcript_path:
        return None
    meta_path = Path(transcript_path).with_suffix("") / "subagents" / f"agent-{agent_id}.meta.json"
    meta = _read_json_object(meta_path)
    if not meta:
        return None
    tool_use_id = meta.get("toolUseId")
    if not isinstance(tool_use_id, str) or not tool_use_id:
        return None
    return _read_worker_scope_entry(root, tool_use_id)


def _scope_via_transcript(transcript_path: object, agent_id: str, root: Path) -> Optional[dict]:
    """Fallback for _scope_via_meta: read the assignment prompt straight out of the worker's own
    first transcript line (<session>/subagents/agent-<id>.jsonl, message.content of the first
    record) and parse a `Write scope:` line out of it directly — no tool_use_id round-trip needed.
    None if the file is missing/unreadable or its first line has no usable message content."""
    if not isinstance(transcript_path, str) or not transcript_path:
        return None
    agent_transcript = Path(transcript_path).with_suffix("") / "subagents" / f"agent-{agent_id}.jsonl"
    if not agent_transcript.is_file():
        return None
    try:
        with open(agent_transcript, "r", encoding="utf-8") as handle:
            first_line = handle.readline()
    except OSError:
        return None
    try:
        record = json.loads(first_line)
    except json.JSONDecodeError:
        return None
    message = record.get("message") if isinstance(record, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        return None
    return _parse_write_scope(content, root) or {"mode": "unrestricted"}


def _resolve_worker_scope(root: Path, payload: dict) -> Optional[dict]:
    """Bind this PreToolUse call's agent_id to the scope its assignment named: meta.json first,
    the worker's own transcript as fallback (see this module's docstring). None if neither
    resolves — a genuinely unbound call, handled by the fail-closed fallback in the caller."""
    agent_id = payload.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id:
        return None
    transcript_path = payload.get("transcript_path")
    try:
        entry = _scope_via_meta(root, transcript_path, agent_id)
    except Exception:
        entry = None
    if entry is not None:
        return entry
    try:
        entry = _scope_via_transcript(transcript_path, agent_id, root)
    except Exception:
        entry = None
    return entry


def _normalize_candidate_path(raw: str, root: Path, base: str) -> Optional[str]:
    """Turn a write-target path (absolute Windows, forward-slash, or Git-Bash `/d/...` form, or
    one already relative — resolved against `base`, not always `root`: a Bash target is relative to
    the tool call's own `cwd`, tracked forward through any `cd` the command made, see
    shell_targets._bash_write_targets) into the form _matches_scope compares against: project-root-
    relative POSIX when it resolves under `root`, same as always; its own resolved absolute-POSIX
    form otherwise (B138) — still out of scope by definition (shell_targets' module docstring step
    4) unless the scope's own patterns include a matching absolute-POSIX one, which only happens for
    a pattern resolved under `permissions.additionalDirectories` (_external_pattern); every other
    out-of-root target still matches nothing there either. None only if the path cannot be resolved
    to an absolute path at all. The worker's own scratchpad is exempted separately by the caller,
    before this is ever called."""
    if not raw:
        return None
    candidate = _to_native_path(raw)
    try:
        path = Path(candidate)
        if not path.is_absolute():
            path = Path(_to_native_path(base)) / candidate
        resolved = path.resolve()
    except (OSError, ValueError):
        return None
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(resolved).replace("\\", "/")


def _within_scratchpad(raw: str, scratchpad_dir: str) -> bool:
    """True if `raw` resolves under the worker's own scratchpad_dir (from the hook payload) —
    exempt from write-scope enforcement per shell_targets' module docstring step 4 (a worker's temp
    files are never "the project" in the sense a Write scope line means)."""
    try:
        target = Path(_to_native_path(raw))
        if not target.is_absolute():
            return False
        target = target.resolve()
        target.relative_to(Path(scratchpad_dir).resolve())
        return True
    except (OSError, ValueError):
        return False


def _matches_scope(rel_posix: str, patterns: list[str]) -> bool:
    """True if `rel_posix` matches one of `patterns` — but an absolute target (one
    _normalize_candidate_path could not resolve under the project root, B138) is only ever compared
    against a pattern that is itself absolute, i.e. one _external_pattern already resolved under
    `permissions.additionalDirectories`. Without this split, `fnmatch` cannot tell "*.py" (an
    ordinary, project-root-relative pattern) from a path with slashes in it — `*` matches "/" too —
    so an absolute target the caller never meant to allow (`D:/dev/rufeger/elsewhere/evil.py`, a
    sibling checkout never listed in additionalDirectories) matched a plain `*.py`/`*.md` scope
    outright (T76 review, 2026-09-25). A relative target is likewise only compared against relative
    patterns, for the same reason in the other direction."""
    is_absolute_target = _is_absolute_target(rel_posix)
    return any(
        _is_absolute_target(pattern) == is_absolute_target and fnmatch.fnmatch(rel_posix, pattern)
        for pattern in patterns
    )


def _write_scope_message(target: str, scope: dict) -> str:
    if scope.get("mode") == "none":
        allowed = "none (read-only assignment)"
    else:
        allowed = ", ".join(scope.get("patterns") or []) or "none"
    return (
        f"[act] outside this assignment's write scope: {target} (allowed: {allowed}; "
        "Write scope patterns are project-root-relative)"
    )


def check_worker_write_scope(payload: dict) -> int:
    """Check 1c: a worker may only write where its assignment's `Write scope:` line allows
    (R-cost-delegate). See this module's docstring for the binding mechanism. Unlike check 1
    (the template write-guard), this one is *not* unconditionally fail-closed: when a call's
    agent_id cannot be bound to a recorded scope at all, it is denied only if a restricted scope
    was demonstrably registered recently (_recent_restricted_scope_registered) — i.e. only when
    scoping is in active use nearby. With no restricted scope registered anywhere recently (the
    common case for a project that never writes a `Write scope:` line), an unresolved binding is
    allowed, same as an explicit "unrestricted" scope would be."""
    config = actlib.read_config()
    mode = _check_mode(config, "worker-write-scope", default="block")
    if mode == "off":
        return 0

    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
        return 0

    try:
        root = actlib.repo_root()
    except RuntimeError:
        return 0  # not inside a template-managed project — nothing to enforce against

    if not payload.get("agent_id"):
        # The orchestrator's own call: never write-scope-restricted itself (check 1 already
        # guards .act/). If this is an Agent/Task start, record the scope it names for the
        # worker it is about to spawn.
        if tool_name in _WORKER_TOOL_NAMES:
            tool_use_id = payload.get("tool_use_id")
            prompt = tool_input.get("prompt")
            if isinstance(tool_use_id, str) and tool_use_id and isinstance(prompt, str):
                scope = _parse_write_scope(prompt, root) or {"mode": "unrestricted"}
                _record_worker_scope(root, tool_use_id, scope)
        return 0

    write_targets: list[tuple[str, Optional[str]]] = []
    if tool_name in _TOOL_PATH_FIELDS:
        for field in _TOOL_PATH_FIELDS[tool_name]:
            value = tool_input.get(field)
            if isinstance(value, str) and value:
                write_targets.append((value, str(root)))
    elif tool_name == "Bash":
        command = tool_input.get("command")
        if isinstance(command, str):
            cwd_raw = payload.get("cwd")
            base_cwd = cwd_raw if isinstance(cwd_raw, str) and cwd_raw else str(root)
            write_targets = _bash_write_targets(command, base_cwd, _GIT_WRITES_WORKER_SCOPE)
    elif tool_name == "PowerShell":
        command = tool_input.get("command")
        if isinstance(command, str):
            cwd_raw = payload.get("cwd")
            base_cwd = cwd_raw if isinstance(cwd_raw, str) and cwd_raw else str(root)
            ps_targets = _powershell_write_targets(command, base_cwd, _GIT_WRITES_WORKER_SCOPE)
            if ps_targets is None:
                ps_targets = _ps_raw_redirect_targets(command)
            # powershell_targets already resolves what it can to an absolute path itself (a
            # PowerShell script has exactly one current directory at any point, unlike Bash's
            # possibly-several); pairing every target with base=None below still resolves
            # correctly in the loop further down — an absolute target ignores `base` entirely
            # (_normalize_candidate_path), and a non-absolute one (unresolved/dynamic) falls into
            # the same "base is None and not absolute -> offending" branch a Bash target with an
            # unknown base would.
            write_targets = [(target, None) for target in ps_targets]
    if not write_targets:
        return 0  # not a tool/shape this check understands as a write

    scope = _resolve_worker_scope(root, payload)
    if scope is None:
        if not _recent_restricted_scope_registered(root):
            return 0  # scoping is not demonstrably in use nearby — nothing to fail closed against
        message = (
            "[act] could not bind this worker to its assignment's write scope, and a restricted "
            "scope was registered recently — denying as a precaution (R-cost-delegate)"
        )
        if mode == "warn":
            print(message)
            return 0
        print(message, file=sys.stderr)
        return 2

    if scope.get("mode") == "unrestricted":
        return 0

    if scope.get("mode") == "error":
        # An absolute pattern outside the project root (B127) — refused here, at the first write
        # attempt, rather than at worker start (_record_worker_scope only records the bad scope,
        # see _parse_write_scope's docstring): a scope nothing is ever written under would
        # otherwise never surface the problem.
        message = scope.get("message") or "[act] invalid write scope"
        if mode == "warn":
            print(message)
            return 0
        print(message, file=sys.stderr)
        return 2

    scratchpad_dir = payload.get("scratchpad_dir")
    for raw_target, base in write_targets:
        dynamic = _is_dynamic_target(raw_target)
        if (
            not dynamic
            and isinstance(scratchpad_dir, str)
            and scratchpad_dir
            and _within_scratchpad(raw_target, scratchpad_dir)
        ):
            continue
        if scope.get("mode") == "none":
            offending = raw_target
        elif dynamic or (base is None and not _is_absolute_target(raw_target)):
            # The shell still expands this target ($VAR, $(...), ~, {a,b}), or it is relative and
            # the directory it resolves against is unknown (pushd, a subshell `cd`, `cd $X`, ...,
            # see shell_targets._scan_tokens) — deny rather than check it against a guessed path.
            offending = raw_target
        else:
            rel = _normalize_candidate_path(raw_target, root, base if base is not None else str(root))
            if rel is not None and _matches_scope(rel, scope.get("patterns") or []):
                continue
            offending = raw_target
        message = _write_scope_message(offending, scope)
        if mode == "warn":
            print(message)
            return 0
        print(message, file=sys.stderr)
        return 2
    return 0
