#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check — repeated status queries on a running worker with no real work in between
# (R-cost-wait, PreToolUse, orchestrator only).
#
# R-cost-wait (.act/rules/orchestrator/30-cost.md) has the orchestrator start a worker and then
# either work on something independent or wait — not poll the worker's status on a hunch. This
# module is the mechanical backstop: it counts the orchestrator's own *consecutive* status-query
# tool calls (payload carries no agent_id — see checks.common._is_worker) and denies from the
# second one in a row. "Consecutive" is per-session (state keyed by session_id under
# .act-local/status-poll/) and resets the instant the orchestrator does anything else — including
# a genuinely different status-query tool right after another counts as staying "in a row"; only a
# *non*-poll tool call resets the streak, per the assignment's own wording ("any other tool use
# by the orchestrator resets the counter").
#
# Which tool names count as "a status query" — established against real evidence before writing
# any detection logic (per the assignment: "back this first with real tool names"), against
# the template maintainer's own Claude Code session transcripts,
# grepped for tool_use blocks' "name" field, 2026-09-23):
#
#   ReadNotifications   68 calls, every single one with input {} — a pure "anything waiting?"
#                       check with no side effect, exactly the "poll" shape this rule targets.
#   ListAgents          10 calls, likewise always {} — "who is running, since when".
#   SendMessage         25 calls, but every payload sampled carried a substantial, distinct
#                       "message" body to an *external* project's inbox (e.g. "approval: template
#                       update can proceed"), never a bare same-session status ping to a
#                       worker this session itself started. Deliberately left OUT of the poll set:
#                       the assignment names it as a candidate ("SendMessage to an agent with a
#                       question about status"), but nothing short of reading the message text can
#                       tell a status ping from real cross-agent communication, and the "message"
#                       field's *content* is exactly the kind of thing R-code-encoding-adjacent
#                       checks in this template avoid classifying on (heuristic text matching is
#                       what produced the false positives below) — conservative, per the
#                       assignment ("better too little than blocking real work").
#   TaskOutput          0 calls — never seen as an actual tool_use name anywhere in this session's
#                       full history (only as prose mentioning the name). Included in the poll set
#                       anyway, defensively: an unused name can never match a real tool_name, so
#                       listing it costs nothing against the (unconfirmed) chance a harness variant
#                       exposes it.
#   Bash/PowerShell     tried and rejected: a regex for "sleep|tail |cat .*\.output|Get-Content
#     "sleep/tail/cat"  .*-Wait" against this session's real Bash/PowerShell commands matched 283
#                       calls, every single one a false positive (ordinary greps whose search
#                       *text* happened to contain "cat "/"sleep", e.g. `grep -rn "Befund" ...`).
#                       No narrower shell-text heuristic was found that both catches a genuine
#                       poll-loop and stays clear of that noise, so shell commands are not treated
#                       as a status query at all here — same conservative call as SendMessage above.
#   Monitor             explicitly excluded, on purpose, the opposite way: the harness's own Bash
#                       tool description recommends Monitor as the *replacement* for a sleep-loop
#                       poll ("Use the Monitor tool to stream events ... instead"). Counting it as
#                       a poll would penalize exactly the behavior R-cost-wait wants; it counts as
#                       ordinary work here (falls through to the "not a poll" branch, resetting the
#                       streak) precisely by not being in _STATUS_POLL_TOOL_NAMES.
#
# State storage mirrors worker_cap.py's small conventions (imported from there rather than
# duplicated a third time): _atomic_write_json for the same temp-file+os.replace, write_scope's
# _SAFE_ID_RE to validate session_id as a filename, _read_json_object/_entry_is_fresh for the
# opportunistic 24h file-hygiene prune (_prune_stale_state — disk cleanup, not the streak logic
# itself). No locking here (unlike worker_cap's per-agent counter): the orchestrator is a single
# session issuing one tool call at a time, so its own state file never sees concurrent writers the
# way a worker's shared count file can.
#
# Follow-up (2026-09-27): check_status_poll used to bump the streak *before*
# deciding whether to deny, so the second-in-a-row poll that triggered the deny was itself counted
# into the streak it was denied over — mirrors the same fix in worker_cap.py's check_worker_cap,
# for the same reason: _bump_consecutive_polls now takes an optional `deny_threshold` and, in
# `block` mode, skips the write and reports the call as denied instead of bumping the streak;
# `warn` mode passes no threshold and keeps bumping on every poll exactly as before (it never
# denies here in the first place). See _bump_consecutive_polls' own docstring.
#
# Follow-up review (2026-09-23, BLOCK on the version before this comment): a streak used to
# survive indefinitely (only the 24h file-hygiene TTL ever cleared it), so a poll right after a
# fresh human turn — or one 20 minutes after the previous poll, with real work in between that
# this check simply never saw — could still count as "the second in a row". Two independent fixes:
# (1) _streak_still_active gives the streak itself a much shorter life, `_STREAK_TTL_SECONDS`
# (120s) — a previous "consecutive" value older than that is treated the same as none at all, so a
# poll long after the last one is "first" again purely by having gone stale, no other tool call
# required. (2) observe(event, payload), a new export, resets the streak to 0 outright on
# UserPromptSubmit — a fresh human turn is unambiguously "something else happened" even on two
# polls seconds apart. observe() only takes effect once the orchestrator adds
# `("status_poll", "observe")` to dispatch.py's `_OBSERVERS` tuple (outside this file's write
# scope — see dispatch.py's own docstring for the convention: observers are registered there, one
# line each, same as `("event_log", "observe")` / `("usage", "observe")` already are).

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
import sys

import actlib

from .common import _check_mode, _is_harness_message, _is_worker
from .worker_cap import _atomic_write_json
from .write_scope import _SAFE_ID_RE, _entry_is_fresh, _read_json_object

__all__ = [
    "_STATUS_POLL_DIRNAME", "_STATUS_POLL_TOOL_NAMES", "_STATUS_POLL_MESSAGE",
    "_STREAK_TTL_SECONDS", "_state_file", "_prune_stale_state", "_streak_still_active",
    "_bump_consecutive_polls", "check_status_poll", "observe",
]

_STATUS_POLL_DIRNAME = "status-poll"

# See this module's docstring for the evidence behind each entry (and each deliberate omission).
_STATUS_POLL_TOOL_NAMES = frozenset({"ReadNotifications", "ListAgents", "TaskOutput"})

_STATUS_POLL_MESSAGE = (
    "[act] a started worker reports on its own when done — do something else or wait "
    "(R-cost-wait)"
)

# How long a "consecutive" streak stays meaningful on its own, independent of the 24h file-hygiene
# TTL (_entry_is_fresh) — see this module's docstring, follow-up review point 7.
_STREAK_TTL_SECONDS = 120


def _state_file(root: Path, session_id: object) -> Optional[Path]:
    if not isinstance(session_id, str) or not _SAFE_ID_RE.match(session_id):
        return None
    return root / ".act-local" / _STATUS_POLL_DIRNAME / f"{session_id}.json"


def _prune_stale_state(dir_path: Path, skip: Path) -> None:
    """Same opportunistic 24h prune as worker_cap._prune_stale_entries, kept as its own tiny copy
    here rather than a third shared home for it — one session's own state file is the only thing
    ever written here, so there is nothing to race against."""
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


def _streak_still_active(entry: dict) -> bool:
    """True if `entry`'s "consecutive" count is still within _STREAK_TTL_SECONDS of now — a much
    shorter, streak-specific freshness window than _entry_is_fresh's 24h file-hygiene one (see this
    module's docstring, follow-up review point 7). A streak that has aged past this is treated the
    same as no previous streak at all, so the next poll is "first" again purely by elapsed time,
    with no other tool call required in between."""
    ts = entry.get("ts")
    try:
        when = datetime.fromisoformat(ts) if isinstance(ts, str) else None
    except ValueError:
        when = None
    return when is not None and when >= datetime.now(timezone.utc) - timedelta(seconds=_STREAK_TTL_SECONDS)


def _bump_consecutive_polls(
    root: Path, session_id: object, is_poll: bool, deny_threshold: Optional[int] = None,
) -> "tuple[Optional[int], bool]":
    """Update and return (this session's consecutive-status-query streak, denied): incremented
    when `is_poll` and the previous streak is still active (_streak_still_active), reset to 1 when
    `is_poll` but there was no usable previous streak, reset to 0 (and still written, so the
    file's timestamp stays fresh) when not `is_poll`. (None, False) only when session_id cannot be
    used as a filename at all — nothing to track, never blocks the call over it.

    `deny_threshold`: when given, `is_poll` is set, and incrementing would
    reach or exceed it, the *count* is left unchanged (previous_streak, True) is returned instead
    of the incremented value) — the poll check_status_poll is about to deny must never count
    towards its own streak (it never happened, from the streak's point of view); a later,
    genuinely new poll starts counting from the same streak value this denied one saw, not from
    one past it. The timestamp is still written on a deny (review finding): without
    that, a continuous poll loop would let the streak's `ts` go stale after 120s
    (_STREAK_TTL_SECONDS) purely because every poll past the first got denied before it could
    refresh it, so one poll would slip through as "first again" every 120s forever — writing
    `{"consecutive": previous, "ts": now}` on deny keeps the window anchored to the *last poll*,
    not the last *allowed* one, while still never bumping the count itself. `None` (the `warn`-mode
    caller's choice) means "always write, never deny here", the original behavior."""
    path = _state_file(root, session_id)
    if path is None:
        return None, False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None, False

    entry = _read_json_object(path)
    previous = entry.get("consecutive") if entry and _streak_still_active(entry) else None
    denied = False
    if is_poll:
        prospective = (previous + 1) if isinstance(previous, int) else 1
        if deny_threshold is not None and prospective >= deny_threshold:
            consecutive = previous if isinstance(previous, int) else 0
            denied = True
        else:
            consecutive = prospective
    else:
        consecutive = 0

    new_entry = {"consecutive": consecutive, "ts": datetime.now(timezone.utc).isoformat()}
    if _atomic_write_json(path, new_entry):
        _prune_stale_state(path.parent, skip=path)
    return consecutive, denied


def check_status_poll(payload: dict) -> int:
    """Deny the orchestrator's second consecutive status-query tool call in a row on a started
    worker (R-cost-wait). Never runs against a worker's own calls (see this module's docstring —
    the rule is about the orchestrator's behavior, not a worker's)."""
    config = actlib.read_config()
    mode = _check_mode(config, "status-poll", default="block")
    if mode == "off":
        return 0

    if _is_worker(payload):
        return 0

    tool_name = payload.get("tool_name")
    if not isinstance(tool_name, str):
        return 0

    try:
        root = actlib.repo_root()
    except RuntimeError:
        return 0

    is_poll = tool_name in _STATUS_POLL_TOOL_NAMES
    # `warn` mode never denies here, so it must never withhold the streak update either —
    # only `block` mode passes an actual threshold ("second in a row").
    threshold_for_call = 2 if mode != "warn" else None
    consecutive, denied = _bump_consecutive_polls(
        root, payload.get("session_id"), is_poll, deny_threshold=threshold_for_call,
    )
    if consecutive is None or not is_poll:
        return 0

    if denied:
        print(_STATUS_POLL_MESSAGE, file=sys.stderr)
        return 2
    if consecutive >= 2:  # warn mode only reaches here (block already denied above via `denied`)
        print(_STATUS_POLL_MESSAGE)
    return 0


def observe(event: str, payload: dict) -> None:
    """Reset this session's consecutive-status-query streak to 0 on UserPromptSubmit — a fresh
    human turn, unlike any tool call this check's own PreToolUse side ever sees. Registered as
    ("status_poll", "observe") in dispatch.py's _OBSERVERS tuple by the orchestrator (see this
    module's docstring); until that line is added, this function exists but is never called —
    harmless, since _STREAK_TTL_SECONDS still bounds a stale streak's life on its own. Observers
    never block (dispatch.py already swallows any exception here) and never raise past this
    function on their own account; every failure path below is a silent no-op for the same
    reason every other best-effort write in this module is.

    A harness-fed UserPromptSubmit (a worker's report, a task-finished notice — see
    checks.common._is_harness_message, seen in a live probe 2026-09-23) is deliberately
    NOT treated as "something else happened": it is not the orchestrator doing real work in
    between two polls, just the harness relaying a message the orchestrator did not ask
    for and may not even act on
    yet — resetting the streak on it would let a poll/poll/(worker message)/poll sequence dodge
    the second-in-a-row denial for free. Only a prompt the user actually typed resets it early;
    everything else still ages out via _STREAK_TTL_SECONDS on its own."""
    if event != "UserPromptSubmit" or _is_harness_message(payload.get("prompt")):
        return
    try:
        root = actlib.repo_root()
    except RuntimeError:
        return
    path = _state_file(root, payload.get("session_id"))
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    new_entry = {"consecutive": 0, "ts": datetime.now(timezone.utc).isoformat()}
    if _atomic_write_json(path, new_entry):
        _prune_stale_state(path.parent, skip=path)
