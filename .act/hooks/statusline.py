#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Claude Code's `statusLine` command: a persistent one-line status shown under the
#          chat, so what is waiting for the human (open inbox entries) never scrolls out of view
#          the way a chat message does.
#          Reads the JSON Claude Code passes on stdin (see
#          https://code.claude.com/docs/en/statusline), uses only its "cwd"/"workspace" fields to
#          find the project, and prints exactly one line — the same "Waiting for you" count
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
#   "act · 3 waiting for you: Q103 Q104 Q105 · 5 tasks"      -- open inbox entries and open tasks
#   "act · 5 tasks"                                          -- nothing waiting, no list shown
#   "act"                                                    -- neither an inbox nor a tasks dir
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

MAX_LABELS = 5  # how many question/todo ids the line names before folding the rest into "+N"


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


def _waiting_summary(root: Path) -> tuple[int, list[str]]:
    """(total_count, labels) for every open inbox entry addressed to this identity or to "all" --
    the same two groups board.py's own "Waiting for you" list shows (board._group_by_recipient()),
    excluding entries addressed to someone else (board's separate "For others" count) since those
    are not, from this identity's own point of view, something to show as "waiting for you" here.
    `labels` is newest-first (board._sort_key()), the caller trims it to MAX_LABELS itself."""
    inbox_entries = board.read_inbox_entries(root)
    if inbox_entries is None:
        return 0, []
    open_entries = sorted((e for e in inbox_entries if e["status"] == "open"), key=board._sort_key)
    identity_data = actlib.read_identity()
    my_identity = identity_data.get("identity") if identity_data else None
    mine_open, all_open, _other_open = board._group_by_recipient(open_entries, my_identity)
    combined = mine_open + all_open
    return len(combined), [entry["label"] for entry in combined]


def _task_count(root: Path) -> Optional[int]:
    """Number of open tasks under docs/ai/work/tasks/, or None if that directory does not exist —
    same source and exclusion (README.md) as board.read_task_titles(), but every file counted
    instead of just the first TASKS_LIMIT."""
    tasks_dir = root / board.TASKS_DIR
    if not tasks_dir.is_dir():
        return None
    return sum(1 for p in tasks_dir.glob("*.md") if p.name.lower() != "readme.md")


def status_line(root: Path) -> str:
    """The one line this hook prints for a project at `root`."""
    waiting_count, labels = _waiting_summary(root)
    task_count = _task_count(root)

    segments = ["act"]
    if waiting_count:
        shown = labels[:MAX_LABELS]
        more = waiting_count - len(shown)
        suffix = f" +{more}" if more > 0 else ""
        segments.append(f"{waiting_count} waiting for you: {' '.join(shown)}{suffix}")
    if task_count is not None:
        segments.append(f"{task_count} tasks")
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
        line = status_line(root)
    except Exception:
        # Any failure (bad JSON, no project found, an unreadable file, ...) -> an empty line, never
        # an exception or a non-zero exit -- this hook must never surface as an error banner.
        line = ""
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
