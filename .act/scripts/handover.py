#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Answer "can this session be left now?" mechanically, read-only: uncommitted changes,
#          started tasks without a working-state line, inbox entries answered but not yet booked,
#          and the started tasks with their last state line (the input for the sentence the human
#          types into a new session). What no script can see - running workers, promises made
#          only in chat - is covered by the act-handover skill. Stdlib only.
#
# Usage:
#   python .act/scripts/handover.py
#   python .act/scripts/handover.py --json
#   python .act/scripts/handover.py --root <project>
#
# Output format:
#   One line per check, "<name>: ok" or "<name>: open: <detail>", then one line per started task
#   ("started T<n>: <title> - <last state line>"). Exit 0 when nothing is open, 1 otherwise.
#   With --json: {"ready": bool, "checks": {name: {"ok": bool, "detail": str, ...}},
#   "started": [{"id", "title", "state", "stamp", "wait", "text"}]}.
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

import actlib
import board

MAX_PATHS = 5
STATE_LINE_RE = re.compile(r"^State (\d{4}-\d{2}-\d{2} \d{2}:\d{2})( \(wait\))?: (.*)$")


def dirty_paths(root: Path) -> Optional[list[str]]:
    """Paths from `git status --porcelain`, or None if git cannot answer (not a repository)."""
    try:
        proc = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return [line[3:].strip() for line in proc.stdout.splitlines() if line.strip()]


def _read_header(path: Path) -> str:
    try:
        return actlib.header_block(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return ""


def started_tasks(root: Path) -> list[dict]:
    """Every task under docs/ai/work/tasks/ whose header carries `started:`, as
    {"id", "title", "state", "stamp", "wait", "text"}; state is the last working-state line or None."""
    tasks_dir = root / board.TASKS_DIR
    found: list[dict] = []
    if not tasks_dir.is_dir():
        return found
    for path in sorted(tasks_dir.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        header = _read_header(path)
        if not board.STARTED_RE.search(header):
            continue
        id_match = board.ID_RE.search(header)
        state = board._last_state_line(root, path.name)
        _stamp, waiting = board.parse_state_line(state)
        parsed = STATE_LINE_RE.match(state) if state else None
        found.append({
            "id": id_match.group(1) if id_match else path.stem,
            "title": board._first_heading(path) or path.stem,
            "state": state,
            "stamp": parsed.group(1) if parsed else None,
            "wait": waiting,
            "text": parsed.group(3) if parsed else state,
        })
    return found


def answered_inbox(root: Path) -> list[str]:
    """File names of inbox entries with `status: answered`."""
    inbox = root / actlib.INBOX_DIR
    names: list[str] = []
    if not inbox.is_dir():
        return names
    for path in sorted(inbox.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        match = board.STATUS_RE.search(_read_header(path))
        if match and match.group(1).lower() == "answered":
            names.append(path.name)
    return names


def collect(root: Path) -> dict:
    paths = dirty_paths(root)
    started = started_tasks(root)
    no_state = [task["id"] for task in started if not task["state"]]
    answered = answered_inbox(root)
    if paths is None:
        changes = {"ok": False, "detail": "git status not available", "count": 0, "paths": []}
    else:
        more = f" (+{len(paths) - MAX_PATHS} more)" if len(paths) > MAX_PATHS else ""
        changes = {"ok": not paths, "count": len(paths), "paths": paths[:MAX_PATHS],
                   "detail": f"{len(paths)} uncommitted: {', '.join(paths[:MAX_PATHS])}{more}" if paths else ""}
    checks = {
        "uncommitted": changes,
        "started-without-state": {"ok": not no_state, "ids": no_state, "detail": ", ".join(no_state)},
        "answered-inbox": {"ok": not answered, "files": answered, "detail": ", ".join(answered)},
    }
    return {"ready": all(check["ok"] for check in checks.values()), "checks": checks, "started": started}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check mechanically whether this session can be left (read-only).")
    parser.add_argument("--root", help="project root (default: found upward from the working directory)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()
    try:
        root = Path(args.root).resolve() if args.root else actlib.repo_root()
    except RuntimeError as error:
        print(f"handover: {error}", file=sys.stderr)
        return 2
    result = collect(root)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for name, check in result["checks"].items():
            print(f"{name}: ok" if check["ok"] else f"{name}: open: {check['detail']}")
        for task in result["started"]:
            mark = " (waiting)" if task["wait"] else ""
            print(f"started {task['id']}: {task['title']}{mark} - {task['state'] or 'no state recorded'}")
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
