#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check — a worker's tool calls beyond its assignment's cap (R-cost-delegate, PreToolUse).
#
# R-cost-delegate (.act/rules/orchestrator/30-cost.md) has the orchestrator name a `Cap: <n>` line
# in every assignment, mechanically checked the same way `Write scope:` is (checks/write_scope.py)
# — this module is that check. Without a `Cap:` line, the cap falls back to the default for the
# tier named in a `Tier: <tier>` line (`light` 10, `standard` 40, `elevated` 60, `high`/`expert`
# 80); with neither line, `standard` (40). See _parse_cap_and_tier.
#
# Binding a worker's tool call back to the cap its assignment named reuses the same mechanism as
# write_scope.py (see that module's docstring for the full rationale: meta.json's "toolUseId"
# first, the worker's own first transcript line as a fallback), but *not* write_scope's own
# functions — those parse and store its "scope" shape (mode/patterns), not a bare cap number, and
# this module must not edit write_scope.py (another builder's file) to add a generic variant. What
# *is* reused directly from write_scope.py (imported, not copied) is its lower-level, already-
# generic plumbing: `_read_json_object` (meta.json/state-file parsing), `_entry_is_fresh` (the
# same 24h freshness window `_SCOPE_ENTRY_TTL` already uses, reused here rather than redefining a
# second TTL constant), and `_SAFE_ID_RE` (the same "is this string a safe filename" check). The
# path-construction lines themselves (`<transcript>/subagents/agent-<id>.meta.json` /
# `.jsonl`) are the one piece genuinely duplicated from write_scope.py's _scope_via_meta /
# _scope_via_transcript — about ten lines of straightforward, unlikely-to-drift path arithmetic,
# not the check logic itself. See _meta_tool_use_id / _transcript_first_prompt.
#
# Storage lives in its own directory, `.act-local/worker-caps/` (not write_scope's
# `worker-scopes/`, per this check's own assignment): one file per Agent/Task start, keyed by
# `tool_use_id` (the cap that assignment names — _record_worker_cap/_resolve_worker_cap), and one
# file per running worker, keyed by `agent_id` (that worker's running tool-call count —
# _register_worker_call). Both kinds of file share the directory and the "*.json" prune glob
# (_prune_stale_entries), same as write_scope's single worker-scopes/ directory holds only one
# kind — nothing here assumes the two kinds cannot coexist since their filenames never collide
# (a raw tool_use_id vs. "count-" + agent_id).
#
# Two agent_ids never share a count file, so two parallel workers count separately by
# construction. A single agent_id's count file CAN see genuinely concurrent writers in a way
# write_scope's worker-scopes files do not (that module records/reads once per call; this one
# read-modifies-writes on every single worker tool call) — so, unlike write_scope's plain
# temp-file+os.replace, incrementing here is wrapped in a directory-based mutex (_locked): a
# same-named ".lock" directory, created via Path.mkdir(exist_ok=False), which is atomic on both
# POSIX and Windows and needs no third-party dependency. A lock that cannot be acquired within
# `_LOCK_TIMEOUT` is *not* treated as a permanent block on the worker's own tool call (fail open,
# same philosophy as every check here but write_guard) — the increment proceeds unlocked, meaning
# the cap arithmetic degrades to best-effort under that specific failure mode instead of ever
# stalling a worker over our own bookkeeping.
#
# Non-blocking hints (delivered at most once each per worker, see the config table's "a note at
# the cap"): researched against the Claude Code hook docs (code.claude.com/docs/en/hooks, fetched
# 2026-09-23) before writing this. Its `hookSpecificOutput.additionalContext` field is honored
# only for PostToolUse, UserPromptSubmit and SessionStart — explicitly *not* for PreToolUse (the
# docs list a fixed field set for PreToolUse: permissionDecision, permissionDecisionReason,
# updatedInput, systemMessage, terminalSequence; permissionDecision "allow" ignores
# permissionDecisionReason and additionalContext both). More generally: a PreToolUse hook's
# *plain-text* stdout on exit 0 goes to the debug log only and is never added to Claude's context —
# this template's own PreToolUse `warn`-mode notes (write_guard, nesting_guard, write_scope) share
# that same known limitation. The only channel confirmed to reach Claude for PreToolUse is exit 2 +
# stderr (deny) — still used here, unchanged, for the 1.5x-the-cap denial in `block` mode.
#
# For the two non-blocking hints ("cap reached" and, in `warn` mode, "cap exceeded"), this module
# now (after T35 wired PostToolUse into dispatch.py) exports note_worker_cap(payload), registered
# in dispatch.py's _POST_TOOL_USE_NOTES and delivered via that event's own
# hookSpecificOutput.additionalContext — the field actually documented to reach the model. Division
# of labor: check_worker_cap (PreToolUse) is the only place that increments the running counter
# (_register_worker_call) and the only place that denies; it never prints a hint any more.
# note_worker_cap (PostToolUse) only *reads* the count check_worker_cap already wrote for this same
# tool call — it never increments a second time — and decides whether either hint is due, each
# delivered at most once per worker (`hinted_cap` / `hinted_exceeded` flags in the same count
# file). The "cap exceeded" hint only matters in `warn` mode: in `block` mode, a call at or past
# 1.5x the cap is denied by check_worker_cap before it ever runs, so PostToolUse never fires for it.
#
# Follow-up review (2026-09-23, BLOCK on the version before this comment): `_CAP_LINE_RE` /
# `_TIER_LINE_RE` used to require `Cap:`/`Tier:` at the start of a line, missing the shape real
# assignment headers actually use ("Tier: standard · Schätzung: ... · Cap: 95." — Tier at the
# start, Cap only after a "·"); `_KEY_BOUNDARY` now also matches right after "·", "|", ";" or ","
# anywhere in the line (see the comment above it for why a quoted "> Cap: 999" line still doesn't
# match either way). Also: `_locked`'s wait loop and `_prune_stale_entries` both now clear a lock
# directory older than `_LOCK_STALE_SECONDS` (`_clear_if_orphaned`) — previously an orphaned lock
# (holder crashed between mkdir and rmdir) cost every later caller the full `_LOCK_TIMEOUT` wait,
# forever, since nothing ever removed it.

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from re import IGNORECASE, MULTILINE, compile as re_compile
from typing import Optional

import actlib

from .common import _WORKER_TOOL_NAMES, _check_mode, _is_worker
from .write_scope import _SAFE_ID_RE, _entry_is_fresh, _read_json_object

__all__ = [
    "_WORKER_CAPS_DIRNAME", "_TIER_DEFAULT_CAPS", "_DEFAULT_TIER", "_DEFAULT_CAP",
    "_KEY_BOUNDARY", "_CAP_LINE_RE", "_TIER_LINE_RE", "_LOCK_TIMEOUT", "_LOCK_POLL",
    "_LOCK_STALE_SECONDS", "_parse_cap_and_tier", "_worker_caps_dir", "_cap_assignment_file",
    "_count_file", "_atomic_write_json", "_prune_stale_entries", "_record_worker_cap",
    "_read_cap_assignment_entry", "_meta_tool_use_id", "_transcript_first_prompt",
    "_resolve_worker_cap", "_clear_if_orphaned", "_locked", "_register_worker_call",
    "check_worker_cap", "note_worker_cap",
]

_WORKER_CAPS_DIRNAME = "worker-caps"

# Defaults per tier (R-cost-delegate); "expert" shares "high"'s default — both are one reasoning
# step further on top of an existing tier, not a scope difference on their own.
_TIER_DEFAULT_CAPS = {
    "light": 10,
    "standard": 40,
    "elevated": 60,
    "high": 80,
    "expert": 80,
}
_DEFAULT_TIER = "standard"
_DEFAULT_CAP = _TIER_DEFAULT_CAPS[_DEFAULT_TIER]

# "Cap: <n>" / "Tier: <name>" — recognized two ways (real assignments use both): at the start of
# its own line (optional "- "/"* " bullet, optional Markdown bold **/__ around the key — same
# shapes as write_scope's _SCOPE_LINE_RE), or right after one of "·", "|", ";", "," anywhere in a
# line (real assignment header shape: "Tier: standard · Schätzung: ... · Cap: 95."). A quoted line
# ("> Cap: 999") is not "start of line" (the literal "> " sits between ^ and the key) and has no
# ·/|/;/, directly before "Cap" either, so it stays ignored either way. The value only needs to
# start with what we look for (digits for Cap, a word for Tier) — trailing text on the same line
# ("Cap: 95 tool calls", "Tier: standard-high") is tolerated and ignored past that point; a
# trailing "." after the number (as in "Cap: 95.") is simply not part of \d+ and left alone.
_KEY_BOUNDARY = r"(?:^[ \t]*(?:[-*]\s+)?|(?<=[·|;,])\s*)"
_CAP_LINE_RE = re_compile(
    _KEY_BOUNDARY + r"(?:\*\*|__)?Cap(?:\*\*|__)?:(?:\*\*|__)?\s*(\d+)",
    IGNORECASE | MULTILINE,
)
_TIER_LINE_RE = re_compile(
    _KEY_BOUNDARY + r"(?:\*\*|__)?Tier(?:\*\*|__)?:(?:\*\*|__)?\s*([A-Za-z][A-Za-z-]*)",
    IGNORECASE | MULTILINE,
)

# How long to wait for another process's lock on the same count file before giving up and
# incrementing unlocked (see this module's docstring) — generous relative to a single JSON
# read+write, stingy relative to a tool call's own timeout budget.
_LOCK_TIMEOUT = 5.0
_LOCK_POLL = 0.02

# A lock directory older than this is treated as orphaned (its holder crashed or was killed
# between mkdir and the matching rmdir) rather than genuinely contended — see _clear_if_orphaned
# and _locked. Deliberately well above _LOCK_TIMEOUT: a lock still within one caller's own wait
# window is still plausibly live; only one that has outlived several callers' worth of waiting is
# assumed abandoned. Without this, an orphaned lock would cost *every* later call the full
# _LOCK_TIMEOUT, forever (2026-09-23 review finding).
_LOCK_STALE_SECONDS = 10.0


def _parse_cap_and_tier(prompt: str) -> int:
    """The tool-call cap for one assignment prompt: an explicit `Cap: <n>` line wins outright;
    otherwise the default for the tier a `Tier: <tier>` line names (a "-high"/... suffix on the
    tier word, e.g. "standard-high", is stripped before the lookup — it selects a reasoning
    variant of the role, not a different cap); with neither line, or an unrecognized tier word,
    the standard default."""
    cap_match = _CAP_LINE_RE.search(prompt)
    if cap_match:
        try:
            value = int(cap_match.group(1))
        except ValueError:
            value = None
        if value is not None and value > 0:
            return value
    tier_match = _TIER_LINE_RE.search(prompt)
    tier_word = tier_match.group(1).strip().lower() if tier_match else ""
    tier_base = tier_word.split("-", 1)[0]
    return _TIER_DEFAULT_CAPS.get(tier_base, _DEFAULT_CAP)


def _worker_caps_dir(root: Path) -> Path:
    return root / ".act-local" / _WORKER_CAPS_DIRNAME


def _cap_assignment_file(root: Path, tool_use_id: str) -> Optional[Path]:
    """One file per Agent/Task start, keyed by tool_use_id — same one-file-per-id reasoning as
    write_scope._worker_scope_file (N parallel starts never race each other's file)."""
    if not isinstance(tool_use_id, str) or not _SAFE_ID_RE.match(tool_use_id):
        return None
    return _worker_caps_dir(root) / f"{tool_use_id}.json"


def _count_file(root: Path, agent_id: str) -> Optional[Path]:
    """One running counter per worker, keyed by agent_id. The "count-" prefix keeps this
    filename shape disjoint from _cap_assignment_file's bare tool_use_id one, so both kinds of
    entry share _worker_caps_dir()/_prune_stale_entries() without ever colliding."""
    if not isinstance(agent_id, str) or not _SAFE_ID_RE.match(agent_id):
        return None
    return _worker_caps_dir(root) / f"count-{agent_id}.json"


def _atomic_write_json(path: Path, data: dict) -> bool:
    """Write `data` as JSON via temp file + os.replace (atomic on POSIX and Windows alike). The
    temp file's suffix is ".tmp", not ".json" — write_scope._record_worker_scope's own comment
    explains why: a ".json"-suffixed temp file is briefly visible to a *concurrent* writer's own
    _prune_stale_entries glob (before this replace lands), which could delete it out from under
    us (2026-09-23 review, referenced there as t26_race.py). Best-effort: a failed write here
    only weakens the cap/count bookkeeping, never raises into the caller."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", suffix=".tmp", dir=str(path.parent))
    except OSError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp_name, path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        return False
    return True


def _prune_stale_entries(dir_path: Path, skip: Path) -> None:
    """Delete every worker-caps file (either kind) older than write_scope's 24h freshness window
    (_entry_is_fresh, reused rather than redefined), or unreadable/malformed — run opportunistically
    on each write, mirroring write_scope._prune_worker_scope_files. `skip` is the file just written
    in this same call. Also clears any orphaned "*.lock" directory left behind under the same dir
    (see _clear_if_orphaned) — a second, independent chance to clean one up beyond the self-healing
    already built into _locked's own wait loop, e.g. for a lock whose holder crashed with nobody
    left to ever retry acquiring it."""
    try:
        candidates = list(dir_path.glob("*.json"))
    except OSError:
        candidates = []
    for path in candidates:
        if path == skip:
            continue
        entry = _read_json_object(path)
        if entry is None or not _entry_is_fresh(entry):
            try:
                path.unlink()
            except OSError:
                pass
    try:
        lock_candidates = list(dir_path.glob("*.lock"))
    except OSError:
        lock_candidates = []
    for lock_dir in lock_candidates:
        _clear_if_orphaned(lock_dir, _LOCK_STALE_SECONDS)


def _record_worker_cap(root: Path, tool_use_id: str, cap: int) -> None:
    """Record one Agent/Task start's cap in its own file (_cap_assignment_file), so the worker it
    spawns can look it up later via _resolve_worker_cap. Always called, even when the assignment
    named no explicit `Cap:` (the resolved tier default is recorded either way) — mirrors
    write_scope._record_worker_scope always recording, including "unrestricted"."""
    path = _cap_assignment_file(root, tool_use_id)
    if path is None:
        return  # unsafe id -- never recorded, not an error
    entry = {"cap": cap, "ts": datetime.now(timezone.utc).isoformat()}
    if _atomic_write_json(path, entry):
        _prune_stale_entries(path.parent, skip=path)


def _read_cap_assignment_entry(root: Path, tool_use_id: str) -> Optional[int]:
    path = _cap_assignment_file(root, tool_use_id)
    if path is None:
        return None
    entry = _read_json_object(path)
    if entry is None or not _entry_is_fresh(entry):
        return None
    cap = entry.get("cap")
    return cap if isinstance(cap, int) and cap > 0 else None


def _meta_tool_use_id(transcript_path: object, agent_id: str) -> Optional[str]:
    """This worker's tool_use_id, via <session>/subagents/agent-<id>.meta.json's "toolUseId" —
    same file write_scope._scope_via_meta reads, read again here independently (see this module's
    docstring on why: write_scope's own reader returns its scope shape, not a bare id, and it is
    not this module's to edit)."""
    if not isinstance(transcript_path, str) or not transcript_path:
        return None
    meta_path = Path(transcript_path).with_suffix("") / "subagents" / f"agent-{agent_id}.meta.json"
    meta = _read_json_object(meta_path)
    if not meta:
        return None
    tool_use_id = meta.get("toolUseId")
    return tool_use_id if isinstance(tool_use_id, str) and tool_use_id else None


def _transcript_first_prompt(transcript_path: object, agent_id: str) -> Optional[str]:
    """Fallback for _meta_tool_use_id: the assignment prompt straight out of the worker's own
    first transcript line (<session>/subagents/agent-<id>.jsonl), the same file
    write_scope._scope_via_transcript reads for the same reason."""
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
    return content if isinstance(content, str) else None


def _resolve_worker_cap(root: Path, payload: dict) -> int:
    """The cap that applies to this worker's tool call: the cap recorded for its Agent/Task start
    (via meta.json's toolUseId), else a fresh parse of its own first transcript line, else the
    standard default when neither binds ("Worker nicht bindbar -> Stufen-Vorgabe standard")."""
    agent_id = payload.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id:
        return _DEFAULT_CAP
    transcript_path = payload.get("transcript_path")

    try:
        tool_use_id = _meta_tool_use_id(transcript_path, agent_id)
    except Exception:  # noqa: BLE001 — a resolution failure falls back, never raises
        tool_use_id = None
    if tool_use_id:
        cap = _read_cap_assignment_entry(root, tool_use_id)
        if cap is not None:
            return cap

    try:
        prompt = _transcript_first_prompt(transcript_path, agent_id)
    except Exception:  # noqa: BLE001
        prompt = None
    if isinstance(prompt, str) and prompt:
        return _parse_cap_and_tier(prompt)

    return _DEFAULT_CAP


def _clear_if_orphaned(lock_dir: Path, stale_after: float) -> bool:
    """Remove `lock_dir` if it looks abandoned (older than `stale_after` seconds, via its own
    mtime — mkdir sets it, and nothing else ever touches an empty lock directory again). Without
    this, a lock whose holder died between mkdir and the matching rmdir would cost every later
    caller the full _LOCK_TIMEOUT wait, forever, rather than just until it ages past
    `stale_after` (2026-09-23 review finding). Best-effort: any OSError — the holder is still
    genuinely alive and removes it itself moments later, a permissions hiccup, a raced double
    removal — is swallowed, not raised; worst case this call falls through to the normal
    wait/give-up path in _locked, or is simply skipped in _prune_stale_entries's pass. Returns
    True only if it actually removed something."""
    try:
        age = time.time() - lock_dir.stat().st_mtime
    except OSError:
        return False
    if age <= stale_after:
        return False
    try:
        lock_dir.rmdir()
    except OSError:
        return False
    return True


@contextmanager
def _locked(count_path: Path, timeout: float = _LOCK_TIMEOUT, poll: float = _LOCK_POLL):
    """Directory-based mutex for one count file: `<count_path>.lock` created via
    Path.mkdir(exist_ok=False), atomic exclusive creation on both POSIX and Windows, no
    third-party dependency. Yields True once acquired; yields False (proceeds unlocked, best
    effort) if `timeout` is exceeded — a worker's tool call must never stall over our own
    bookkeeping (see this module's docstring). While waiting, a lock directory that has aged past
    _LOCK_STALE_SECONDS is treated as orphaned and cleared immediately (_clear_if_orphaned) rather
    than left for the caller to wait out — retried right away, no extra sleep, since clearing it
    means the next mkdir can very likely succeed at once."""
    lock_dir = count_path.parent / f"{count_path.name}.lock"
    deadline = time.monotonic() + timeout
    acquired = False
    while True:
        try:
            lock_dir.mkdir(parents=True, exist_ok=False)
            acquired = True
            break
        except FileExistsError:
            if _clear_if_orphaned(lock_dir, _LOCK_STALE_SECONDS):
                continue  # just cleared it -- retry mkdir immediately
            if time.monotonic() >= deadline:
                break
            time.sleep(poll)
        except OSError:
            break  # cannot even attempt the lock (e.g. unwritable dir) — proceed unlocked
    try:
        yield acquired
    finally:
        if acquired:
            try:
                lock_dir.rmdir()
            except OSError:
                pass


def _register_worker_call(root: Path, agent_id: str) -> Optional[int]:
    """Atomically increment this worker's running tool-call counter, returning the new count
    (None when agent_id is not a safe filename — never counted, not an error, mirrors
    write_scope's same convention for an unsafe id). Counting only ever happens here, in
    check_worker_cap (PreToolUse); note_worker_cap (PostToolUse) only reads what this wrote for
    the same tool call, never increments a second time. Other fields already in the entry
    (`hinted_cap`, `hinted_exceeded` — see note_worker_cap) are carried over unchanged, not
    overwritten by this increment."""
    path = _count_file(root, agent_id)
    if path is None:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    with _locked(path):
        entry = _read_json_object(path) or {}
        previous = entry.get("count")
        count = (previous + 1) if isinstance(previous, int) else 1
        new_entry = dict(entry)
        new_entry["count"] = count
        new_entry["ts"] = datetime.now(timezone.utc).isoformat()
        if _atomic_write_json(path, new_entry):
            _prune_stale_entries(path.parent, skip=path)
    return count


def check_worker_cap(payload: dict) -> int:
    """A worker's tool calls beyond its assignment's cap (R-cost-delegate). Orchestrator side:
    records the cap an Agent/Task start names, never denies. Worker side: counts every tool call
    but SubagentHandback (never counted, never denied — a worker must always be able to hand back
    its result), denies from 1.5x the cap onward in `block` mode (`warn` counts but never denies).
    Never prints a hint itself any more — see note_worker_cap (PostToolUse) and this module's
    header for why, and for the lock design."""
    config = actlib.read_config()
    mode = _check_mode(config, "worker-cap", default="block")
    if mode == "off":
        return 0

    tool_name = payload.get("tool_name")
    if tool_name == "SubagentHandback":
        return 0

    if not _is_worker(payload):
        tool_input = payload.get("tool_input")
        if tool_name in _WORKER_TOOL_NAMES and isinstance(tool_input, dict):
            tool_use_id = payload.get("tool_use_id")
            prompt = tool_input.get("prompt")
            if isinstance(tool_use_id, str) and tool_use_id and isinstance(prompt, str):
                try:
                    root = actlib.repo_root()
                except RuntimeError:
                    return 0
                _record_worker_cap(root, tool_use_id, _parse_cap_and_tier(prompt))
        return 0

    try:
        root = actlib.repo_root()
    except RuntimeError:
        return 0

    agent_id = payload.get("agent_id")
    cap = _resolve_worker_cap(root, payload)
    count = _register_worker_call(root, agent_id)
    if count is None:
        return 0  # agent_id not a safe filename -- nothing to enforce against

    deny_threshold = (cap * 3 + 1) // 2  # ceil(1.5 * cap)
    if count >= deny_threshold and mode != "warn":
        print(
            f"[act] cap of {cap} tool calls exceeded ({count} so far) — "
            "deliver your state via your final report",
            file=sys.stderr,
        )
        return 2

    return 0


def note_worker_cap(payload: dict) -> Optional[str]:
    """PostToolUse counterpart for check_worker_cap's two non-blocking hints (see this module's
    header). Never re-increments the counter — only reads the count check_worker_cap already wrote
    for this same tool call. Delivers, each at most once per worker (`hinted_cap` /
    `hinted_exceeded` flags stored in the same count file):
      - "cap reached" once the count reaches the cap, in either mode;
      - "cap exceeded" once the count reaches 1.5x the cap, `warn` mode only — in `block` mode a
        call past that point is denied by check_worker_cap before it runs, so PostToolUse never
        sees it. Registered in dispatch.py's _POST_TOOL_USE_NOTES."""
    config = actlib.read_config()
    mode = _check_mode(config, "worker-cap", default="block")
    if mode == "off":
        return None
    if not _is_worker(payload):
        return None
    if payload.get("tool_name") == "SubagentHandback":
        return None

    try:
        root = actlib.repo_root()
    except RuntimeError:
        return None

    agent_id = payload.get("agent_id")
    path = _count_file(root, agent_id)
    if path is None:
        return None

    cap = _resolve_worker_cap(root, payload)
    deny_threshold = (cap * 3 + 1) // 2  # ceil(1.5 * cap), same formula as check_worker_cap

    with _locked(path):
        entry = _read_json_object(path)
        if entry is None:
            return None
        count = entry.get("count")
        if not isinstance(count, int):
            return None

        if mode == "warn" and count >= deny_threshold and not entry.get("hinted_exceeded"):
            entry["hinted_exceeded"] = True
            entry["hinted_cap"] = True
            message = (
                f"[act] cap of {cap} tool calls exceeded ({count} so far) — "
                "deliver your state via your final report"
            )
        elif count >= cap and not entry.get("hinted_cap"):
            entry["hinted_cap"] = True
            message = f"[act] cap reached — deliver your current state now ({count}/{cap})"
        else:
            return None

        _atomic_write_json(path, entry)
    return message
