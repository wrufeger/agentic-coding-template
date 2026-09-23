#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Local usage counter (T41) — how often each role starts, at which tier/model; how often
#          each skill, slash command, script and checklist is used; how a worker's outcome turned
#          out at acceptance time. Feeds two later mechanisms without any extra bookkeeping of
#          their own: the tips-that-fade-once-a-feature-is-used condition `unused:<key>` (T42,
#          docs/project/concepts/ai-dev-app/03-core-rules.md ~line 418, is_unused() below) and the
#          per-role/tier tier proposal in 13-model-tiers.md § 7 (roles.<name>.outcomes below, via
#          --outcome). Stdlib only. Never sent anywhere (docs/project/concepts/ai-dev-app/
#          13-model-tiers.md § 7: only the *pattern*, not this project's own numbers, ever goes
#          out — via the ordinary Feedback mechanism, not this script).
#
# Store: .act-local/usage.json (gitignored — decided: purely local, see the task order for T41).
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
# is_unused(root, key) — the `unused:<key>` tip condition (T42, not built here):
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
import os
import sys
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import Callable, Optional

import actlib

_CATEGORIES = ("roles", "skills", "commands", "scripts", "checklists", "checks")
_OUTCOME_VALUES = ("accepted", "reworked", "escalated")
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
    try:
        fd, tmp_name = tempfile.mkstemp(prefix="ev-", suffix=".tmp", dir=str(events_dir))
    except OSError:
        return
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        os.replace(tmp_name, str(Path(tmp_name).with_suffix(".json")))
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
    return store


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
        os.replace(tmp_name, path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass


def _bump(bucket: dict, field: str, name: str) -> None:
    sub = bucket.setdefault(field, {})
    sub[name] = sub.get(name, 0) + 1


def _fold_event(store: dict, event: dict) -> None:
    cat = event.get("cat")
    key = event.get("key")
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
    (T42). See this module's header for the bare-vs-prefixed key scheme."""
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
    return cmd_show(root)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
