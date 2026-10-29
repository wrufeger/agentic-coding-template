#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Show, in a compact block, which project this session works in and its state: project name,
#          folder and host, the session name the project asks for, branch, last commit and number of
#          uncommitted changes, the installed template version with its update channel, the open
#          tasks and what waits for a human. Read-only and without network: it reads local files and
#          runs local git queries only, never a fetch or `ls-remote`. Meant for the phone as well as
#          the terminal, so the output is short.
#
# Usage:
#   python .act/scripts/info.py
#   python .act/scripts/info.py --limit 3     # list at most 3 tasks and 3 waiting entries
#
# Output format:
#   About 10-15 lines, English labels, one per line:
#     Project / Folder / Host / Session   - name from docs/ai/config.md, project root, hostname,
#                                           session title (or "auto" when the tool names it)
#     Branch / Last commit / Changes      - "no git repository" for a project without git
#     Template                            - installed version, commit and update channel
#     Tasks / Waiting                     - open tasks (id, title, status) and inbox questions and
#                                           todos for a human; "none" when nothing is open, a list
#                                           over --limit ends in "+n more"
#   The last line points to /act-version for the newest available version. Runs from any directory
#   inside the project; exit 0, exit 2 outside a project. Stdlib only.

from __future__ import annotations

import argparse
import os
import socket
import sys
from pathlib import Path
from typing import Optional

import actlib
import board
import update

DEFAULT_LIMIT = 5


def _more(items: list[str], limit: int) -> list[str]:
    """`items` cut to `limit`, with a trailing "+n more" when something was left out."""
    if len(items) <= limit:
        return items
    return items[:limit] + [f"+{len(items) - limit} more"]


def git_lines(root: Path) -> list[str]:
    """Branch, last commit and change count, or one line saying there is no git repository."""
    branch = board.get_branch(root)
    if branch is None:
        return ["Branch:   no git repository"]
    lines = [f"Branch:   {branch}"]
    commit = board.get_last_commit(root)
    lines.append(f"Commit:   {commit['hash']} {commit['subject']} ({commit['date']})" if commit
                 else "Commit:   none yet")
    # --no-optional-locks: a plain `git status` may refresh the index, and this script only reads
    status = board.run_git(["--no-optional-locks", "status", "--porcelain"], root)
    if status is not None:
        count = len([line for line in status.splitlines() if line.strip()])
        lines.append(f"Changes:  {count} uncommitted" if count else "Changes:  clean")
    return lines


def template_line(root: Path) -> str:
    """Installed version, commit and update channel, read from local files only. A lock or
    config the helpers cannot make sense of gives "unknown" here, not a failed block."""
    try:
        version, commit = update._installed_state(root)
        channel, _origin, problem = update._resolve_channel(root, None)
    except (AttributeError, KeyError, TypeError, ValueError, OSError) as error:
        return f"Template: unknown (lock or config unreadable: {type(error).__name__})"
    commit_text = commit[:7] if commit else "commit unknown"
    suffix = f" (config value unusable, using {channel})" if problem else ""
    return f"Template: {version or 'unknown'} ({commit_text}), channel {channel}{suffix}"


def task_lines(root: Path, limit: int) -> list[str]:
    """Open tasks as `id title [status]`, or a line saying there are none."""
    tasks = board.read_tasks(root) or []
    identity = actlib.read_identity()
    own = [t for t in tasks if board._is_own_task(t, identity.get("identity") if identity else None)]
    ordered = board._order_tasks(own)
    items = [f"{t['id'] + ' ' if t.get('id') else ''}{t['title']} [{t['status']}]" for t in ordered]
    if not items:
        return ["Tasks:    none open"]
    shown = _more(items, limit)
    return [f"Tasks:    {len(items)} open"] + [f"  - {text}" for text in shown]


def waiting_lines(root: Path, limit: int) -> list[str]:
    """Inbox questions and todos waiting for a human, as `id title`."""
    entries = board.read_inbox_entries(root) or []
    waiting, _assistant = board.split_entries(entries)
    waiting = [e for e in waiting if e["kind"] in ("question", "todo")]
    if not waiting:
        return ["Waiting:  nothing for a human"]
    items = [f"{e['label']} {e['title']}" for e in waiting]
    return [f"Waiting:  {len(items)} for a human"] + [f"  - {text}" for text in _more(items, limit)]


def build(root: Path, limit: int) -> list[str]:
    config = actlib.read_config(root)
    name = config.get("name", "").strip()
    if not name or (name.startswith("<") and name.endswith(">")):
        name = f"{root.name} (name not set)"
    title = actlib.session_title(config, root)
    lines = [
        f"Project:  {name}",
        f"Folder:   {root}",
        f"Host:     {socket.gethostname()}",
        f"Session:  {title if title is not None else 'auto (left to the tool)'}",
    ]
    lines += git_lines(root)
    lines.append(template_line(root))
    lines += task_lines(root, limit)
    lines += waiting_lines(root, limit)
    lines.append("Newest available version: /act-version")
    return lines


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(
        prog="info.py",
        description="Show which project this session works in and its state: name, folder, host, session "
                    "name, branch, last commit, uncommitted changes, installed template version and channel, "
                    "open tasks and what waits for a human. Read-only, no network.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, metavar="N",
                        help=f"list at most N tasks and N waiting entries, then '+n more' (default {DEFAULT_LIMIT})")
    args = parser.parse_args(argv)
    try:
        root = actlib.repo_root()
    except RuntimeError as error:
        print(f"info: {error}", file=sys.stderr)
        return 2
    os.chdir(root)  # the lock helpers resolve the project from the working directory
    try:
        lines = build(root, max(args.limit, 0))
    except (OSError, ValueError) as error:
        print(f"info: could not read the project state: {error}", file=sys.stderr)
        return 2
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
