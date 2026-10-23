#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Local usage counter — how often each role starts, at which tier/model; how often
#          each skill, slash command, script and checklist is used; how a worker's outcome turned
#          out at acceptance time. Feeds two later mechanisms without any extra bookkeeping of
#          their own: the tips-that-fade-once-a-feature-is-used condition `unused:<key>`
#          (is_unused() below) and the
#          per-role/tier tier proposal (roles.<name>.outcomes below, via
#          --outcome). Stdlib only. Never sent anywhere (only the *pattern*, not this project's
#          own numbers, ever goes
#          out — via the ordinary Feedback mechanism, not this script).
#
# Store: .act-local/usage.json (gitignored — decided: purely local, see above).
#        Recording never touches that file directly, though — see "Concurrency" below and
#        .act/hooks/checks/usage.py's own header (the observer that calls record_event() for
#        every hook event). Both files' headers are meant to be read together; this one owns the
#        schema, the consolidation step and the CLI, checks/usage.py only turns hook events into
#        the tiny per-occurrence files this file folds in.
#
# Usage:
#   python .act/scripts/usage.py                          # same as --show
#   python .act/scripts/usage.py --show
#   python .act/scripts/usage.py --outcome <role> <tier> accepted|reworked|escalated
#   python .act/scripts/usage.py --unused <key>
#   python .act/scripts/usage.py --reset
#   python .act/scripts/usage.py --estimates              # measured effort per role/tier
#   python .act/scripts/usage.py --backfill [--transcripts-dir DIR]   # read existing transcripts once
#
# Measured runs (effort estimates): at each worker end the SubagentStop observer reads the
#   worker's own transcript (<session>/subagents/agent-<id>.jsonl, role from the neighbouring
#   agent-<id>.meta.json "agentType") and records duration, steps and tokens as a "run" event;
#   consolidation folds it into roles.<role>.runs.<tier>, a list of the newest 50 runs, each
#   {"id", "ended", "date", "minutes", "steps", "fresh", "cache", "output"}. "fresh" = input +
#   cache-creation + output tokens, "cache" = cache-read tokens, "minutes" = first to last record.
#   --estimates prints runs, median/p80 per role/tier; --backfill reads the project's transcripts
#   (~/.claude/projects/<project key>/*/subagents/, or $CLAUDE_CONFIG_DIR/projects/...) once -
#   a run already known by agent id is not counted twice. Only numbers are stored, no content;
#   they stay in .act-local/ and feedback.py does not send them.
#
# Output format:
#   --show:    one line per category with any entries ("Roles:", "Skills:", ...), one indented
#              line per key ("  builder: 4x, 2026-09-21..2026-09-23 tiers=standard:4
#              models=?:4"); "(no usage recorded yet)" if the store is empty. Exit 0 always.
#   --outcome: "usage: <role>/<tier> outcome recorded: <outcome>", exit 0; exit 2 with a message
#              on stderr for an unrecognized outcome word; exit 1 (rare) if the consolidate lock
#              could not be acquired in time — nothing was recorded, safe to just retry.
#   --unused:  "usage: <key> is unused|used"; exit 0 if never recorded (the tip may fire), exit 1
#              if it was (the tip stays quiet) — a shell-friendly inversion of the usual "0 means
#              found", picked to match the CLI contract this task's order specifies verbatim.
#   --reset:   "usage: reset (<n> file(s) removed)", exit 0.
#
# Schema of .act-local/usage.json:
#   {"version": 1,
#    "roles":      {"<role>": {"count": n, "first_used": "YYYY-MM-DD", "last_used": "...",
#                               "tiers": {"<tier-or-''>": n, ...}, "models": {"<model-or-''>": n},
#                               "outcomes": {"<tier-or-''>": {"accepted": n, "reworked": n,
#                                                              "escalated": n}}}},
#    "skills":     {"<skill>":     {"count": n, "first_used": ..., "last_used": ...}},
#    "commands":   {"<command>":   {"count": n, "first_used": ..., "last_used": ...}},
#    "scripts":    {"<script>":    {"count": n, "first_used": ..., "last_used": ...}},
#    "checklists": {"<checklist>": {"count": n, "first_used": ..., "last_used": ...}},
#    "checks":     {"<check>":     {"count": n, "first_used": ..., "last_used": ...,
#                                    "kinds": {"<kind>": n, ...}}}}
#   An empty string key ("" under "tiers"/"models") means "no Tier: line found in the prompt" /
#   "tool_input.model was absent" — kept distinct from an actual value, on purpose, so a tip or a
#   report can tell "workers of this role never carry a tier" from "they always run 'light'".
#
# is_unused(root, key) — the `unused:<key>` tip condition (not built here):
#   `key` is either bare ("reviewer", "act-a11y", "deps", "worker-cap") — matched against every
#   category, first hit in category order (roles, skills, commands, scripts, checklists, checks)
#   wins — or prefixed with one of those exact category names and a colon ("skills:act-a11y") to
#   pin it to one category, for the rare case where the same bare name is used in more than one
#   (e.g. a skill and a checklist sharing a name). Returns True ("unused", tip may fire) iff no
#   matching entry has count > 0 anywhere it was looked up. Consolidates first, so an occurrence
#   from the last few seconds — still only a pending event file — already counts.
#
# record(kind, key) — the one entry point a PreToolUse check (.act/hooks/checks/*.py) calls itself
#   to count a cap-hit or a denial, since the observer in checks/usage.py runs *before* the checks
#   (dispatch.py's fixed order) and so never sees them. One line for a check to add:
#       import usage; usage.record("denied", "worker-cap")
#   `kind` is the check's own short word for what happened ("cap_hit", "denied", ...), `key` its
#   name as it appears in docs/ai/config.md's Checks table. Folded into the "checks" category's
#   "kinds" sub-count (see schema above). Best-effort, like every write in this module: never
#   raises, so a bookkeeping failure can never put a check's own 0/2 PreToolUse contract at risk.
#
# Concurrency: recording (record_event()/record()) never opens usage.json — see .act/hooks/checks/
# usage.py's header for why (many dispatch.py processes can run at once; a shared JSON file
# updated read-modify-write per event would lose updates the same way checks/write_scope.py's own
# docstring documents, t26_race.py, 2026-09-23 review). Both instead call _write_event(), which
# gives each occurrence its own file under .act-local/usage/events/, named by tempfile.mkstemp and
# placed with os.replace (atomic on POSIX and Windows alike) — N parallel occurrences always
# produce N files, never a lost one, whatever order the processes finish in.
#
# Consolidation (folding those files into the single usage.json) is the one place that does
# read-modify-write on shared state, so it runs under a lock: .act-local/usage/consolidate.lock,
# taken with os.O_CREAT|os.O_EXCL (atomic create-if-absent on POSIX and Windows alike, same
# technique a PID-file lock uses) and released by unlinking it. Three independent callers can
# reach consolidation — the CLI (--show/--outcome/--unused), is_unused() and, since the 2026-09-23
# review (point 1: an unbounded events/ directory otherwise grows forever, point 5: cmd_outcome
# used to consolidate() and then _write_store() as two separate operations, so a second process's
# consolidate() could land its own write in between and be silently overwritten) — the observer's
# own SessionStart handler (checks/usage.py's observe(), consolidate_at_session_start() below).
# _acquire_lock() bounds how long a caller waits for the lock (lock_timeout) and treats a lock file
# older than 60s as abandoned by a crashed process (unlinks it and retries) — a lock is only ever
# held for the few milliseconds a fold-and-write takes, so anything older is orphaned, not merely
# slow. A caller that still cannot get the lock within its own timeout fails open: consolidate()
# returns the last-written store unchanged (never blocks, never guesses); the mutate-carrying path
# (consolidate_and_mutate(), used by --outcome) instead returns None, so cmd_outcome can tell "not
# recorded" from "recorded" rather than print success for a mutation that never happened.
# consolidate()'s own docstring names the one race the *locked* path still accepts (a crash
# between writing the consolidated file and deleting the folded event files re-folds — double-
# counts — those same files next time, rather than losing them) — acceptable for a nudge counter,
# not for anything billed on this number.

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional

import actlib

_CATEGORIES = ("roles", "skills", "commands", "scripts", "checklists", "checks")
_OUTCOME_VALUES = ("accepted", "reworked", "escalated")
_RUN_EVENT_CAT = "run"  # event-file category of one measured worker run (not a store category)
_RUNS_KEPT = 50  # newest measured runs kept per role and tier in usage.json
_MEASURED_ROLE_SKIP = ("fork",)  # not a role choice, see checks/usage.py
# like checks/usage.py, but also skips Markdown emphasis/backticks around the value (`Tier: `standard``)
_TIER_RE = re.compile(r"Tier:\s*[`*_]*([A-Za-z][A-Za-z0-9-]*)", re.IGNORECASE)
_LINE_STAMP_RE = re.compile(r'"timestamp"\s*:\s*"([^"]+)"')
_IDLE_GAP_MINUTES = 30.0  # a pause between two records longer than this is idle time, not work
_AGENT_FILE_RE = re.compile(r"\Aagent-([A-Za-z0-9_-]+)\.meta\.json\Z")
_LOCK_STALE_AFTER = 60.0  # seconds — a lock file older than this is treated as an orphan, not slow
_SESSION_START_BUDGET = 1.0  # seconds, wall clock incl. lock wait — SessionStart must stay fast


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _usage_dir(root: Path) -> Path:
    return root / ".act-local" / "usage"


def _events_dir(root: Path) -> Path:
    return _usage_dir(root) / "events"


def _store_path(root: Path) -> Path:
    return root / ".act-local" / "usage.json"


def _empty_store() -> dict:
    return {"version": 1, **{cat: {} for cat in _CATEGORIES}}


def _lock_path(root: Path) -> Path:
    return _usage_dir(root) / "consolidate.lock"


# ---------------------------------------------------------------------------
# Recording — one file per occurrence, see this module's "Concurrency" section above
# ---------------------------------------------------------------------------

def _write_event(root: Path, category: str, key: str, **fields: str) -> None:
    if category not in _CATEGORIES or not key:
        return
    events_dir = _events_dir(root)
    try:
        events_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    entry: dict = {"cat": category, "key": key, "date": date.today().isoformat()}
    entry.update({name: value for name, value in fields.items() if value})
    _write_entry(events_dir, entry)


def _write_entry(events_dir: Path, entry: dict) -> None:
    try:
        fd, tmp_name = tempfile.mkstemp(prefix="ev-", suffix=".tmp", dir=str(events_dir))
    except OSError:
        return
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        actlib.replace_file(tmp_name, str(Path(tmp_name).with_suffix(".json")))
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass


def record_event(root: Path, category: str, key: str, **fields: str) -> None:
    """Record one occurrence in `category` ("roles", "skills", "commands", "scripts",
    "checklists") — called by .act/hooks/checks/usage.py's observe(). `fields` are folded in by
    _fold_event() (e.g. tier=/model= for "roles"). See this module's header for the write itself
    and why it never touches usage.json directly."""
    _write_event(root, category, key, **fields)


def record(kind: str, key: str) -> None:
    """Public API for a PreToolUse check to count one of its own cap-hits or denials — see this
    module's header for the one line a check needs. Best-effort: never raises."""
    try:
        root = actlib.repo_root()
    except RuntimeError:
        return
    _write_event(root, "checks", key, kind=kind)


# ---------------------------------------------------------------------------
# Measuring one worker run from its transcript
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RunMeasure:
    """One finished worker run: who it was and what it cost. `fresh` = input + cache-creation +
    output tokens, `cache` = cache-read tokens, `minutes` = first to last transcript record."""
    agent_id: str
    role: str
    tier: str
    ended: str
    minutes: float
    steps: int
    fresh: int
    cache: int
    output: int

    def record(self) -> dict:
        """The part kept in usage.json (role and tier are the keys it is filed under)."""
        data = asdict(self)
        del data["role"], data["tier"], data["agent_id"]
        data["id"] = self.agent_id
        data["date"] = self.ended[:10]
        return data


def _parse_timestamp(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _record_text(line: str) -> str:
    """message.content of one transcript line as text ("" when unreadable)."""
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        return ""
    message = entry.get("message") if isinstance(entry, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(block.get("text", "") for block in content
                         if isinstance(block, dict) and isinstance(block.get("text"), str))
    return ""


def _active_minutes(stamps: list[datetime], wall_minutes: float) -> float:
    """Working time of a run: the sum of the gaps between consecutive records that are at most
    _IDLE_GAP_MINUTES long. A worker that ended and was continued with a message hours later would
    otherwise carry the whole pause in its minutes. Fewer than two readable stamps: the wall-clock
    minutes stand. May raise TypeError when naive and aware stamps are mixed."""
    if len(stamps) < 2:
        return wall_minutes
    total = 0.0
    for before, after in zip(stamps, stamps[1:]):
        gap = (after - before).total_seconds() / 60
        if 0 <= gap <= _IDLE_GAP_MINUTES:
            total += gap
    return min(total, wall_minutes)


def measure_transcript(path: Path, agent_id: str, role: str) -> Optional[RunMeasure]:
    """Read one worker transcript line by line and return what the run cost, or None when the
    file is missing, unreadable or holds no usable record (never raises). Tokens are summed per
    distinct message id (a streamed message repeats its record; the last one counts)."""
    first_line = ""
    last_line = ""
    last_usage_ts: Optional[datetime] = None
    stamps: list[datetime] = []
    messages: dict[str, tuple[int, int, int]] = {}
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.strip():
                    continue
                if not first_line:
                    first_line = line
                last_line = line
                stamp_match = _LINE_STAMP_RE.search(line)
                line_stamp = _parse_timestamp(stamp_match.group(1)) if stamp_match else None
                if line_stamp is not None:
                    stamps.append(line_stamp)
                if '"usage"' not in line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                message = entry.get("message") if isinstance(entry, dict) else None
                if not isinstance(message, dict) or entry.get("type") != "assistant":
                    continue
                usage = message.get("usage")
                message_id = message.get("id")
                if not isinstance(usage, dict) or not isinstance(message_id, str):
                    continue
                parts = [usage.get(name) for name in (
                    "input_tokens", "cache_creation_input_tokens", "output_tokens",
                    "cache_read_input_tokens")]
                numbers = [value if isinstance(value, int) else 0 for value in parts]
                messages[message_id] = (numbers[0] + numbers[1] + numbers[2], numbers[3], numbers[2])
                stamp = _parse_timestamp(entry.get("timestamp"))
                if stamp is not None:
                    last_usage_ts = stamp
    except (OSError, ValueError):
        return None
    if not messages or not first_line:
        return None
    try:
        first_entry = json.loads(first_line)
        last_entry = json.loads(last_line)
    except json.JSONDecodeError:
        return None
    first_ts = _parse_timestamp(first_entry.get("timestamp") if isinstance(first_entry, dict) else None)
    last_ts = _parse_timestamp(last_entry.get("timestamp") if isinstance(last_entry, dict) else None)
    last_ts = max((s for s in (last_ts, last_usage_ts) if s is not None), default=None)
    if first_ts is None or last_ts is None:
        return None
    tier_match = _TIER_RE.search(_record_text(first_line))
    try:
        minutes = max(0.0, (last_ts - first_ts).total_seconds() / 60)
        minutes = _active_minutes(stamps, minutes)
    except TypeError:  # one naive and one aware timestamp
        return None
    return RunMeasure(
        agent_id=agent_id, role=role, tier=tier_match.group(1).lower() if tier_match else "",
        ended=last_ts.isoformat(), minutes=round(minutes, 2), steps=len(messages),
        fresh=sum(m[0] for m in messages.values()), cache=sum(m[1] for m in messages.values()),
        output=sum(m[2] for m in messages.values()))


def _meta_role(meta_path: Path) -> str:
    """agentType from agent-<id>.meta.json; "" for a missing/unreadable file, a helper agent
    without agentType, a fork, or a run the meta file marks unfinished."""
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(meta, dict) or meta.get("finished") is False:
        return ""
    role = meta.get("agentType")
    return role if isinstance(role, str) and role not in _MEASURED_ROLE_SKIP else ""


def measure_agent(agent_transcript: Path, agent_id: str, fallback_role: str = "") -> Optional[RunMeasure]:
    """Measure the worker whose transcript is `agent_transcript`; its role comes from the
    neighbouring meta.json, else `fallback_role` (the hook payload's agent_type). No role (a
    helper agent of the harness) or no usable transcript: None."""
    meta_path = agent_transcript.with_name(f"agent-{agent_id}.meta.json")
    if meta_path.is_file():
        role = _meta_role(meta_path)
    else:
        role = fallback_role if fallback_role not in _MEASURED_ROLE_SKIP else ""
    if not role:
        return None
    return measure_transcript(agent_transcript, agent_id, role)


def record_run(root: Path, run: RunMeasure) -> None:
    """Write one measured run as an event file (folded into usage.json by consolidation). Best
    effort, never raises - same contract as the other recorders."""
    if not run.role:
        return
    events_dir = _events_dir(root)
    try:
        events_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    _write_entry(events_dir, {"cat": _RUN_EVENT_CAT, "key": run.role, "tier": run.tier,
                              "date": date.today().isoformat(), "run": run.record()})


# ---------------------------------------------------------------------------
# Store I/O and consolidation
# ---------------------------------------------------------------------------

def _read_store(root: Path) -> dict:
    path = _store_path(root)
    store = _empty_store()
    if not path.is_file():
        return store
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return store
    if isinstance(data, dict):
        for cat in _CATEGORIES:
            value = data.get(cat)
            if isinstance(value, dict):
                store[cat] = value
    _sanitize_store(store, path)
    return store


# Fields of a store entry that hold a mapping, and the type their values must have.
_ENTRY_MAPS = {"tiers": int, "models": int, "kinds": int, "runs": list, "outcomes": dict}


def _sanitize_store(store: dict, path: Path) -> None:
    """Drop what has the wrong type in a hand-edited or damaged usage.json - an entry that is not
    an object, a `count` that is not a number, a `tiers`/`models`/`kinds`/`runs`/`outcomes` field of
    the wrong shape - with one note per read on stderr naming the place, so folding events and
    every read path work on a clean store instead of ending in a traceback. The file itself is
    rewritten by the next consolidation."""
    problems: list[str] = []
    for cat in _CATEGORIES:
        entries = store[cat]
        for name in list(entries):
            entry = entries[name]
            if not isinstance(entry, dict):
                problems.append(f"{cat}.{name} is {type(entry).__name__}, not an object")
                del entries[name]
                continue
            count = entry.get("count", 0)
            if isinstance(count, bool) or not isinstance(count, int):
                problems.append(f"{cat}.{name}.count is {count!r}, not a number")
                entry["count"] = 0
            for field, inner in _ENTRY_MAPS.items():
                if field not in entry:
                    continue
                value = entry[field]
                if not isinstance(value, dict):
                    problems.append(f"{cat}.{name}.{field} is {type(value).__name__}, not an object")
                    del entry[field]
                    continue
                for key in list(value):
                    if not isinstance(value[key], inner):
                        problems.append(f"{cat}.{name}.{field}.{key or '?'} is "
                                        f"{type(value[key]).__name__}, not {inner.__name__}")
                        del value[key]
                if field == "outcomes":
                    # Each tier maps outcome names to counts; a count of another type would end
                    # in a TypeError when the next outcome is added or a proposal is computed.
                    for tier_key, counts in value.items():
                        for kind in list(counts):
                            number = counts[kind]
                            if isinstance(number, bool) or not isinstance(number, int):
                                problems.append(f"{cat}.{name}.{field}.{tier_key or '?'}.{kind} is "
                                                f"{number!r}, not a number")
                                del counts[kind]
    for problem in problems:
        print(f"usage: ignoring {problem} in {path}", file=sys.stderr)


def _write_store(root: Path, store: dict) -> None:
    path = _store_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".usage-", suffix=".tmp", dir=str(path.parent))
    except OSError:
        return
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(store, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        actlib.replace_file(tmp_name, path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass


def _bump(bucket: dict, field: str, name: str) -> None:
    sub = bucket.setdefault(field, {})
    sub[name] = sub.get(name, 0) + 1


def _clean_run(record: object) -> Optional[dict]:
    """A run record with checked field types, or None when it is malformed."""
    if not isinstance(record, dict):
        return None
    agent_id, ended = record.get("id"), record.get("ended")
    if not isinstance(agent_id, str) or not agent_id or not isinstance(ended, str) or not ended:
        return None
    numbers = {}
    for name in ("minutes", "steps", "fresh", "cache", "output"):
        value = record.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        numbers[name] = value
    return {"id": agent_id, "ended": ended, "date": ended[:10], **numbers}


def _add_run(store: dict, role: str, tier: str, record: object) -> str:
    """File one run under roles.<role>.runs.<tier>: "added", "updated" (same agent id, later end:
    a run measured while still going is replaced by the finished one) or "known" (same id, nothing
    newer, or a malformed record). Keeps the newest _RUNS_KEPT by end time, so a run that already
    rolled out of the window stays out when it is read again."""
    run = _clean_run(record)
    if run is None:
        return "known"
    bucket = store["roles"].setdefault(role, {"count": 0})
    runs = bucket.setdefault("runs", {}).setdefault(tier or "", [])
    status = "added"
    for index, old in enumerate(runs):
        if isinstance(old, dict) and old.get("id") == run["id"]:
            if str(old.get("ended", "")) >= run["ended"]:
                return "known"
            runs[index] = run
            status = "updated"
            break
    else:
        runs.append(run)
    runs.sort(key=lambda item: str(item.get("ended", "")) if isinstance(item, dict) else "")
    del runs[:-_RUNS_KEPT]
    return status if run in runs else "known"


def _fold_event(store: dict, event: dict) -> None:
    cat = event.get("cat")
    key = event.get("key")
    if cat == _RUN_EVENT_CAT:
        if isinstance(key, str) and key:
            tier = event.get("tier")
            _add_run(store, key, tier if isinstance(tier, str) else "", event.get("run"))
        return
    if cat not in _CATEGORIES or not isinstance(key, str) or not key:
        return
    bucket = store[cat].setdefault(key, {"count": 0})
    bucket["count"] = bucket.get("count", 0) + 1
    day = event.get("date")
    if isinstance(day, str) and day:
        if not bucket.get("first_used") or day < bucket["first_used"]:
            bucket["first_used"] = day
        if not bucket.get("last_used") or day > bucket["last_used"]:
            bucket["last_used"] = day
    if cat == "roles":
        _bump(bucket, "tiers", event.get("tier") or "")
        _bump(bucket, "models", event.get("model") or "")
    elif cat == "checks":
        kind = event.get("kind")
        if isinstance(kind, str) and kind:
            _bump(bucket, "kinds", kind)


def _acquire_lock(root: Path, timeout: float) -> Optional[Path]:
    """Take .act-local/usage/consolidate.lock via O_CREAT|O_EXCL (fails if it already exists —
    atomic on POSIX and Windows alike), retrying until `timeout` seconds have passed. A lock file
    older than _LOCK_STALE_AFTER is assumed orphaned (its owner crashed or was killed before
    releasing it) and is removed on sight, without counting against `timeout`. Returns the lock
    path on success, None if it could not be acquired in time — the caller decides what "could not
    lock" means for it (see this module's header)."""
    path = _lock_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    deadline = time.monotonic() + max(timeout, 0.0)
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return path
        except FileExistsError:
            try:
                if time.time() - path.stat().st_mtime > _LOCK_STALE_AFTER:
                    path.unlink()
                    continue  # retry at once, an orphan does not cost the caller any wait time
            except OSError:
                pass
        except OSError:
            return None
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.02)


def _release_lock(lock: Optional[Path]) -> None:
    if lock is None:
        return
    try:
        lock.unlink()
    except OSError:
        pass


def _fold_events_locked(root: Path, deadline: Optional[float] = None,
                         mutate: Optional[Callable[[dict], None]] = None) -> dict:
    """Must only be called while holding the consolidate lock. Folds pending event files into the
    store, applies `mutate(store)` if given, writes once if anything changed, then deletes exactly
    the event files it folded. `deadline` (a time.monotonic() cutoff) bounds how many files get
    folded in one call — files past the deadline are left untouched for the next consolidation
    (used by consolidate_at_session_start() to keep a SessionStart hook fast even with a large
    backlog); `mutate` is always applied regardless of the deadline, so --outcome never gets
    silently skipped by it."""
    store = _read_store(root)
    events_dir = _events_dir(root)
    paths = sorted(events_dir.glob("*.json"))
    folded = []
    for path in paths:
        if deadline is not None and time.monotonic() >= deadline:
            break
        try:
            event = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            folded.append(path)  # unreadable — folded in as "nothing", still removed
            continue
        if isinstance(event, dict):
            _fold_event(store, event)
        folded.append(path)
    changed = bool(folded)
    if mutate is not None:
        mutate(store)
        changed = True
    if changed:
        _write_store(root, store)
    for path in folded:
        try:
            path.unlink()
        except OSError:
            pass
    return store


def consolidate(root: Path, *, lock_timeout: float = 5.0,
                 deadline: Optional[float] = None) -> dict:
    """Fold every pending event file under .act-local/usage/events/ into .act-local/usage.json and
    return the resulting store. Called first by every read path below (--show, is_unused()) and by
    consolidate_at_session_start(), so each sees the latest state it can afford to wait for. Fails
    open on lock contention: if the lock is not free within `lock_timeout`, returns the store as it
    was last written, without folding or blocking further — see this module's header
    ("Concurrency") for why a plain read is an acceptable fallback here, and consolidate_and_mutate
    for the path that is not allowed to fail silently."""
    lock = _acquire_lock(root, lock_timeout)
    if lock is None:
        return _read_store(root)
    try:
        return _fold_events_locked(root, deadline=deadline)
    finally:
        _release_lock(lock)


def consolidate_and_mutate(root: Path, mutate: Callable[[dict], None], *,
                            lock_timeout: float = 5.0) -> Optional[dict]:
    """Fold pending events AND apply `mutate(store)` in the same locked critical section, so a
    concurrent consolidate can never land its own write between the fold and the mutation (review
    point 5: cmd_outcome used to call consolidate() and then _write_store() as two separate,
    unlocked steps). Returns None if the lock could not be acquired within `lock_timeout` — the
    caller must treat that as "not recorded" (see cmd_outcome), never as silent success."""
    lock = _acquire_lock(root, lock_timeout)
    if lock is None:
        return None
    try:
        return _fold_events_locked(root, mutate=mutate)
    finally:
        _release_lock(lock)


def consolidate_at_session_start(root: Path) -> dict:
    """Opportunistic consolidation trigger for SessionStart (checks/usage.py's observe(), review
    point 1: .act-local/usage/events/ otherwise only ever grows). Bounded by
    _SESSION_START_BUDGET seconds of wall clock, lock wait included — a large backlog is folded a
    chunk at a time across several session starts rather than in one slow call. Never raises: a
    SessionStart hook must never fail the session over a bookkeeping mechanism, the same contract
    dispatch.py's own header states for refresh_session()."""
    try:
        deadline = time.monotonic() + _SESSION_START_BUDGET
        return consolidate(root, lock_timeout=_SESSION_START_BUDGET, deadline=deadline)
    except Exception:  # noqa: BLE001 — never break the session over usage bookkeeping
        return _empty_store()


def is_unused(root: Path, key: str) -> bool:
    """True iff `key` was never recorded with a count > 0 — the `unused:<key>` tip condition
    See this module's header for the bare-vs-prefixed key scheme."""
    store = consolidate(root)
    prefix, sep, rest = key.partition(":")
    if sep and prefix in _CATEGORIES:
        entry = store.get(prefix, {}).get(rest)
        return not (isinstance(entry, dict) and entry.get("count", 0) > 0)
    for cat in _CATEGORIES:
        entry = store.get(cat, {}).get(key)
        if isinstance(entry, dict) and entry.get("count", 0) > 0:
            return False
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_LABELS = {
    "roles": "Roles", "skills": "Skills", "commands": "Commands",
    "scripts": "Scripts", "checklists": "Checklists", "checks": "Checks",
}


def _format_entry(cat: str, name: str, entry: dict) -> str:
    count = entry.get("count", 0)
    if cat == "roles" and not count and entry.get("runs"):
        measured = sum(len(runs) for runs in entry["runs"].values() if isinstance(runs, list))
        return f"  {name}: no start counted, {measured} measured run(s)"
    span = ""
    first = entry.get("first_used")
    if first:
        span = f", {first}..{entry.get('last_used', first)}"
    detail = ""
    if cat == "roles":
        tiers = entry.get("tiers") or {}
        models = entry.get("models") or {}
        if tiers:
            detail += " tiers=" + ",".join(f"{k or '?'}:{v}" for k, v in sorted(tiers.items()))
        if models:
            detail += " models=" + ",".join(f"{k or '?'}:{v}" for k, v in sorted(models.items()))
        outcomes = entry.get("outcomes") or {}
        for tier, counts in sorted(outcomes.items()):
            parts = ",".join(f"{k}={v}" for k, v in sorted(counts.items()))
            detail += f" outcomes[{tier or '?'}]={parts}"
    elif cat == "checks":
        kinds = entry.get("kinds") or {}
        if kinds:
            detail += " " + ",".join(f"{k}:{v}" for k, v in sorted(kinds.items()))
    return f"  {name}: {count}x{span}{detail}"


def cmd_show(root: Path) -> int:
    store = consolidate(root)
    lines: list[str] = []
    for cat in _CATEGORIES:
        entries = store.get(cat) or {}
        if not entries:
            continue
        lines.append(f"{_LABELS[cat]}:")
        for name in sorted(entries):
            lines.append(_format_entry(cat, name, entries[name]))
    print("\n".join(lines) if lines else "(no usage recorded yet)")
    return 0


def cmd_outcome(root: Path, role: str, tier: str, outcome: str) -> int:
    if outcome not in _OUTCOME_VALUES:
        print(f"usage: outcome must be one of {', '.join(_OUTCOME_VALUES)}", file=sys.stderr)
        return 2

    def _mutate(store: dict) -> None:
        bucket = store["roles"].setdefault(role, {"count": 0})
        counts = bucket.setdefault("outcomes", {}).setdefault(tier or "", {})
        counts[outcome] = counts.get(outcome, 0) + 1

    store = consolidate_and_mutate(root, _mutate)
    if store is None:
        print("usage: could not acquire the consolidation lock in time — try again",
              file=sys.stderr)
        return 1
    print(f"usage: {role}/{tier or '(no tier)'} outcome recorded: {outcome}")
    return 0


def cmd_unused(root: Path, key: str) -> int:
    unused = is_unused(root, key)
    print(f"usage: {key} is {'unused' if unused else 'used'}")
    return 0 if unused else 1


def cmd_reset(root: Path) -> int:
    removed = 0
    store_path = _store_path(root)
    if store_path.is_file():
        try:
            store_path.unlink()
            removed += 1
        except OSError:
            pass
    events_dir = _events_dir(root)
    if events_dir.is_dir():
        for path in events_dir.glob("*.json"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        try:
            events_dir.rmdir()
        except OSError:
            pass
    lock_path = _lock_path(root)
    if lock_path.is_file():
        try:
            lock_path.unlink()
            removed += 1
        except OSError:
            pass
    try:
        _usage_dir(root).rmdir()
    except OSError:
        pass
    print(f"usage: reset ({removed} file(s) removed)")
    return 0


def _percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile over the sorted values (`fraction` 0..1); 0 for no values."""
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))]


def _fmt_tkn(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1000:
        return f"{value / 1000:.0f}k"
    return f"{value:.0f}"


def _median_p80(runs: list[dict], field: str, fmt: Callable[[float], str]) -> str:
    values = [float(run[field]) for run in runs]
    return f"{fmt(statistics.median(values))}/{fmt(_percentile(values, 0.8))}"


def cmd_estimates(root: Path) -> int:
    store = consolidate(root)
    rows: list[tuple[str, ...]] = []
    for role in sorted(store.get("roles") or {}):
        entry = store["roles"][role]
        by_tier = entry.get("runs") if isinstance(entry, dict) else None
        for tier, runs in sorted((by_tier or {}).items()):
            runs = [run for run in runs if _clean_run(run) is not None]
            if not runs:
                continue
            rows.append((
                f"{role}/{tier or '?'}", str(len(runs)),
                _median_p80(runs, "minutes", lambda v: f"{v:.1f}"),
                _median_p80(runs, "steps", lambda v: f"{v:.0f}"),
                _median_p80(runs, "fresh", _fmt_tkn), _median_p80(runs, "cache", _fmt_tkn),
                max(str(run["date"]) for run in runs)))
    if not rows:
        print("(no measured runs yet - they are recorded when a worker ends; "
              "usage.py --backfill reads the existing transcripts)")
        return 0
    header = ("role/tier", "runs", "min med/p80", "steps med/p80", "tkn fresh med/p80",
              "tkn cache med/p80", "last measured")
    table = [header, *rows]
    widths = [max(len(row[i]) for row in table) for i in range(len(header))]
    for row in table:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    print("fresh = input + cache-creation + output tokens, cache = cache-read tokens; "
          f"newest {_RUNS_KEPT} runs per role/tier")
    return 0


def transcripts_dir_for(root: Path) -> Optional[Path]:
    """Where Claude Code keeps this project's transcripts: <config dir>/projects/<key>, the key
    being the project path with every character outside A-Z a-z 0-9 turned into "-". The config
    dir is $CLAUDE_CONFIG_DIR, else ~/.claude. None if there is no such folder."""
    config = os.environ.get("CLAUDE_CONFIG_DIR")
    projects = (Path(config) if config else Path.home() / ".claude") / "projects"
    key = re.sub(r"[^A-Za-z0-9]", "-", str(root))
    direct = projects / key
    if direct.is_dir():
        return direct
    try:  # Windows drive letters differ in case between tools
        for child in projects.iterdir():
            if child.name.lower() == key.lower() and child.is_dir():
                return child
    except OSError:
        pass
    return None


def cmd_backfill(root: Path, transcripts_dir: Optional[Path] = None) -> int:
    source = transcripts_dir or transcripts_dir_for(root)
    if source is None or not source.is_dir():
        print(f"usage: backfill: no transcript folder found for {root} "
              f"(looked for {transcripts_dir or 'the Claude Code project folder'})", file=sys.stderr)
        return 1
    measured: list[RunMeasure] = []
    seen = skipped = 0
    for meta_path in sorted(source.glob("*/subagents/agent-*.meta.json")):
        match = _AGENT_FILE_RE.match(meta_path.name)
        if not match:
            continue
        seen += 1
        role = _meta_role(meta_path)
        run = measure_transcript(meta_path.with_name(f"agent-{match.group(1)}.jsonl"),
                                 match.group(1), role) if role else None
        if run is None:
            skipped += 1
        else:
            measured.append(run)
    counts = {"added": 0, "updated": 0, "known": 0}

    def _mutate(store: dict) -> None:
        for run in measured:
            counts[_add_run(store, run.role, run.tier, run.record())] += 1

    if consolidate_and_mutate(root, _mutate) is None:
        print("usage: could not acquire the consolidation lock in time - try again", file=sys.stderr)
        return 1
    print(f"usage: backfill: {seen} worker transcript(s) found, {counts['added']} run(s) added, "
          f"{counts['updated']} updated, {counts['known']} already known or beyond the newest "
          f"{_RUNS_KEPT} per role/tier, "
          f"{skipped} skipped (no role, not finished or unreadable)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="usage.py",
        description="Local usage counter: worker starts by role/tier/model, "
                     "skill/command/script/checklist calls, worker outcomes.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--show", action="store_true", help="readable overview (default)")
    group.add_argument("--outcome", nargs=3, metavar=("ROLE", "TIER", "OUTCOME"),
                        help="record accepted|reworked|escalated for one role/tier")
    group.add_argument("--unused", metavar="KEY",
                        help="exit 0 if KEY was never recorded, 1 if it was (see is_unused())")
    group.add_argument("--reset", action="store_true", help="delete every recorded count")
    group.add_argument("--estimates", action="store_true",
                       help="measured runs per role/tier: median and 80th percentile of minutes "
                            "and tokens (fresh/cache), run count, last measurement")
    group.add_argument("--backfill", action="store_true",
                       help="read this project's existing worker transcripts once "
                            "(a second run adds nothing twice)")
    parser.add_argument("--transcripts-dir", metavar="DIR",
                        help="with --backfill: the transcript folder to read instead of "
                             "Claude Code's folder for this project")
    return parser


def main(argv: list[str]) -> int:
    # UTF-8 on stdout/stderr: same fix as .act/hooks/dispatch.py and .act/scripts/entries.py —
    # Windows otherwise picks the console's legacy code page, which mangles "·"/"…" in --show.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    args = build_parser().parse_args(argv)
    root = actlib.repo_root()

    if args.outcome:
        return cmd_outcome(root, *args.outcome)
    if args.unused is not None:
        return cmd_unused(root, args.unused)
    if args.reset:
        return cmd_reset(root)
    if args.estimates:
        return cmd_estimates(root)
    if args.backfill:
        return cmd_backfill(root, Path(args.transcripts_dir) if args.transcripts_dir else None)
    return cmd_show(root)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
