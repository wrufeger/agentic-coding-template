#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Claude Code's `statusLine` command: a persistent one-line status shown under the
#          chat, so what is waiting for the human (open inbox entries) never scrolls out of view
#          the way a chat message does.
#          Reads the JSON Claude Code passes on stdin (see
#          https://code.claude.com/docs/en/statusline), uses its "cwd"/"workspace" fields to
#          find the project and its "context_window" (else "transcript_path") for the context size
#          (context_size.py), and prints exactly one line — the same "Waiting for you" count
#          board.py's board already computes, reused via import (board.py is another worker's file
#          in this task's write scope, so it is only ever imported here, never edited or
#          reimplemented, R-role-worker).
#
# Usage: not run directly by a person — invoked by Claude Code itself, once per assistant message,
#        per the "statusLine" command bridge in .act/bridges/settings.hooks.json
#        (actlib.status_line_command()). Can be run by hand for a quick check:
#          echo '{"cwd": "."}' | python .act/hooks/statusline.py
#
# Output format: exactly one line on stdout, e.g.
#   "act · Q103 Q104 Q105 · tasks: 1 run, 2 wait, 4 new"     -- open inbox entries and open tasks
#   "act · Q105, U4 U3, 2 reports · tasks: 2 new"            -- ids by name (questions, then todos),
#                                                              entries without an id as a count per kind
#   "act · tasks: 5 new"                                     -- nothing waiting, no list shown
#   "act"                                                    -- nothing waiting and no open task
#   "act · tasks: 1 run · ctx 127k"                          -- context size last, when Claude Code
#                                                              passes it (or the transcript has it)
# Never writes to stderr, never a non-zero exit: any failure (malformed stdin JSON, no project
# found from cwd, an unreadable inbox/tasks directory, ...) prints an empty line and exits 0 — a
# broken status line must never show an error banner in Claude Code, per Claude Code's own
# statusLine contract, and this hook is deliberately never allowed to block anything (unlike
# PreToolUse's write_guard/write_scope/nesting_guard, it has no blocking channel to begin with).
#
# Performance: no git call, no subprocess — only local file reads under docs/ai/, capped by the
# same OPEN_LIMIT-sized data board.py already reads, well under the < 200 ms budget this hook has
# to meet since it runs after every assistant message.

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
try:
    # A broken or missing actlib.py/board.py (a half-updated .act/, an unreadable file) must not
    # crash at import time -- that would exit nonzero before main()'s own try/except ever runs,
    # showing an error banner in Claude Code (see the module docstring's "never a non-zero exit").
    # A name left None here still fails inside main()'s try, caught the same way as any other
    # runtime error, ending in the same empty-line, exit-0 fallback.
    import actlib  # noqa: E402 (sys.path setup above must run first)
    import board  # noqa: E402 -- read-only reuse of board.py's own inbox counting, never edited here
except Exception:
    actlib = None  # type: ignore[assignment]
    board = None  # type: ignore[assignment]
try:
    # Separate from the imports above: without it the line still shows the inbox and the tasks.
    import context_size  # noqa: E402
except Exception:
    context_size = None  # type: ignore[assignment]

MAX_LABELS = 5  # how many ids the line names in all before folding the rest into "+N"
# Entries with an id (a question, a todo) are named, in this order of kinds.
ID_ORDER = ("question", "todo")
# Entries without an id (a report, a note, a todo not numbered yet) are counted per kind instead of
# named one by one -- "todo todo todo todo" says less than "4 todos". Kinds in this order, anything
# else last.
KIND_ORDER = ("todo", "report", "note")


def _cwd_from_stdin_json(data: dict) -> Optional[str]:
    """The directory to resolve the project from, per Claude Code's statusLine payload
    (https://code.claude.com/docs/en/statusline): "cwd" first, else "workspace" -- either
    "current_dir" or "project_dir" inside it, whichever is present. Every other field in `data`
    (model, transcript_path, output_style, ...) is deliberately ignored -- this hook only ever
    needs to find the project root."""
    cwd = data.get("cwd")
    if isinstance(cwd, str) and cwd.strip():
        return cwd
    workspace = data.get("workspace")
    if isinstance(workspace, dict):
        for key in ("current_dir", "project_dir"):
            value = workspace.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return None


def _waiting_summary(root: Path) -> tuple[int, list[dict]]:
    """(total_count, entries) for every open inbox entry addressed to this identity or to "all" --
    the same two groups board.py's own "Waiting for you" list shows (board._group_by_recipient()),
    excluding entries addressed to someone else (board's separate "For others" count) since those
    are not, from this identity's own point of view, something to show as "waiting for you" here.
    `entries` is newest-first (board._sort_key()); _waiting_text() turns it into the line's text."""
    inbox_entries = board.read_inbox_entries(root)
    if inbox_entries is None:
        return 0, []
    open_entries = sorted((e for e in inbox_entries if e["status"] == "open"), key=board._sort_key)
    identity_data = actlib.read_identity(root)
    my_identity = identity_data.get("identity") if identity_data else None
    mine_open, all_open, _other_open = board._group_by_recipient(open_entries, my_identity)
    combined = mine_open + all_open
    return len(combined), combined


def _waiting_text(entries: list[dict]) -> str:
    """"Q105 Q104, U4 U3 +2, 4 todos, 1 report": every entry with an id by name — questions first,
    then todos, then any other kind that carries one, each group newest first, at most MAX_LABELS
    ids in all (the rest as one "+N" after the last group) — then the entries without an id (a
    report, a note, a todo not numbered yet in team mode) as a count per kind, in KIND_ORDER."""
    named: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    for entry in entries:
        if entry["label"] != entry["kind"]:  # the board's label is the id whenever there is one
            named.setdefault(entry["kind"], []).append(entry["label"])
        else:
            counts[entry["kind"]] = counts.get(entry["kind"], 0) + 1
    order = [kind for kind in ID_ORDER if kind in named] + sorted(kind for kind in named if kind not in ID_ORDER)
    budget = MAX_LABELS
    groups: list[str] = []
    for kind in order:
        shown = named[kind][:budget]
        budget -= len(shown)
        if shown:
            groups.append(" ".join(shown))
    more = sum(len(labels) for labels in named.values()) - (MAX_LABELS - budget)
    if more > 0 and groups:
        groups[-1] += f" +{more}"
    parts = list(groups)
    count_order = list(KIND_ORDER) + sorted(kind for kind in counts if kind not in KIND_ORDER)
    for kind in count_order:
        if counts.get(kind):
            parts.append(f"{counts[kind]} {kind}{'' if counts[kind] == 1 else 's'}")
    return ", ".join(parts)


def _task_counts(root: Path) -> Optional[tuple[int, int, int]]:
    """(running, waiting, new) open tasks under docs/ai/work/tasks/ — or None if that directory
    does not exist. The classification is board.classify_task()'s: new without a `started:`
    header, otherwise waiting or running. Same source as board.read_tasks(), every file counted
    instead of just the first TASKS_LIMIT."""
    tasks = board.read_tasks(root)
    if tasks is None:
        return None
    counts = {"run": 0, "wait": 0, "new": 0}
    for task in tasks:
        counts[task["status"]] += 1
    return counts["run"], counts["wait"], counts["new"]


def _tasks_text(running: int, waiting: int, new: int) -> str:
    """"tasks: 1 run, 1 wait, 2 new" — a count of 0 is left out."""
    parts = [f"{count} {word}" for count, word in ((running, "run"), (waiting, "wait"), (new, "new")) if count]
    return "tasks: " + ", ".join(parts)


def _context_text(data: Optional[dict]) -> Optional[str]:
    """"ctx 127k" -- the session's context size from the stdin JSON (or its transcript), else None."""
    if not data or context_size is None:
        return None
    try:
        return context_size.status_segment(data)
    except Exception:
        return None


def status_line(root: Path, data: Optional[dict] = None) -> str:
    """The one line this hook prints for a project at `root`; `data` is the stdin JSON."""
    waiting_count, entries = _waiting_summary(root)
    task_counts = _task_counts(root)

    segments = ["act"]
    if waiting_count:
        # No total in front: the ids and per-kind counts already say how much is waiting.
        segments.append(_waiting_text(entries))
    if task_counts is not None and sum(task_counts):
        segments.append(_tasks_text(*task_counts))
    context = _context_text(data)
    if context:
        segments.append(context)
    return " · ".join(segments)


def main() -> int:
    # The line carries a middle dot (·); Windows' stdout otherwise defaults to the console's
    # legacy code page instead of UTF-8, which would corrupt it (same fix as board.py's main()).
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        if not isinstance(data, dict):
            data = {}
        cwd = _cwd_from_stdin_json(data) or "."
        root = actlib.repo_root(Path(cwd))
        line = status_line(root, data)
    except Exception:
        # Any failure (bad JSON, no project found, an unreadable file, ...) -> an empty line, never
        # an exception or a non-zero exit -- this hook must never surface as an error banner.
        line = ""
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
