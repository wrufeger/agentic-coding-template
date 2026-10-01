#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Observer that keeps the board current after the working tree changed under it:
#          a merge, pull, rebase, branch switch ... brings tasks, inbox entries and journal files
#          other people wrote or finished, and the board view generated before that (docs/ai/
#          board.md, or .act-local/board-<branch>.md, chosen by the `board` key in
#          docs/ai/config.md) would otherwise show them stale until the next session start. The
#          versioned per-person board of `board: shared` is never written here -- only
#          act-commit's `board.py --shared` writes it. Registered in dispatch.py's _OBSERVERS as ("board_refresh", "observe").
#
# What triggers it: event "PostToolUse" (a call that ran and succeeded -- never PreToolUse, so a
#          call a check denies or that has not run yet never regenerates anything), tool Bash or
#          PowerShell, the orchestrator's own call (a worker's git access is read-only, see
#          R-role-worker), and a command containing `git <sub>` with <sub> in _REFRESH_SUBCOMMANDS:
#          merge, pull, rebase, switch, checkout, cherry-pick, reset, am, and `stash pop|apply`.
#          Found through checks/command_words.py's tokenizer (every simple command of the line,
#          wrappers and `env`/assignment prefixes stripped), never by a regex over the raw string;
#          git's own global options are skipped by checks/worker_git_write._parse_git_invocation,
#          so `git -C <dir> pull` is recognized and <dir> is the call's git target (see below).
#
# What it does: runs `python <project>/.act/scripts/board.py` in the project root, the same way
#          checks/session._refresh_board does at session start, with a timeout shorter than the
#          hook's own and all output captured. The project is only the hook's own: the root is
#          derived from this file's location, never from a path in the call. A git target (the
#          `-C` directory applied in order against the call's cwd, else the call's cwd: payload
#          "cwd", else CLAUDE_PROJECT_DIR, else the process cwd) that lies outside that project,
#          or inside a nested repository of its own, is skipped -- so a `git -C <fresh clone>
#          pull` never makes the hook run code from that directory. No docs/ai/config.md, no
#          .act/scripts/board.py, or `session-start-refresh: off|warn` in docs/ai/config.md §
#          Checks (same switch as the session-start refresh): nothing happens.
#
# Contract: never raises, never blocks, prints nothing -- any error (a broken board.py, a timeout,
#          an unreadable path) is swallowed. Cheap for every other call: one tokenizer pass over a
#          Bash/PowerShell command, and nothing at all for any other tool or event.
#
# Known limits: shares command_words.py's and worker_git_write.py's tokenizing limits (a `git`
#          inside `eval`, a dynamic `$VAR` directory ...); an unrecognized spelling means a stale
#          board until the next session start, never a wrong one. A `cd <dir> && git merge` in
#          another project is judged from the call's cwd, not from <dir>.

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import actlib

from .command_words import _git_invocations_with_prefix
from .common import _check_mode, _is_worker, _shell_command
from .worker_git_write import _parse_git_invocation, _resolve_dash_c_chain

__all__ = [
    "_REFRESH_SUBCOMMANDS", "_BOARD_TIMEOUT_SECONDS", "_command_changes_tree", "_find_project_root",
    "_own_project_root", "_targets_own_project", "_target_dirs", "observe",
]

_REFRESH_SUBCOMMANDS = frozenset({
    "merge", "pull", "rebase", "switch", "checkout", "cherry-pick", "reset", "am",
})
_STASH_REFRESH_ACTIONS = frozenset({"pop", "apply"})
_BOARD_TIMEOUT_SECONDS = 6  # below the PostToolUse hook timeout in .act/bridges/settings.hooks.json


def _command_changes_tree(command: str) -> "list[list[str]]":
    """The `-C` directory lists (one per matching `git` invocation, empty for none) of every git
    call in `command` that moves other people's work into the tree; [] when nothing matches."""
    found: "list[list[str]]" = []
    for _prefix, args in _git_invocations_with_prefix(command):
        subcommand, sub_args, dash_c_dirs, _override, _alias = _parse_git_invocation(args)
        if subcommand is None:
            continue
        if subcommand in _REFRESH_SUBCOMMANDS:
            found.append(dash_c_dirs)
        elif subcommand == "stash":
            action = next((arg for arg in sub_args if not arg.startswith("-")), None)
            if action in _STASH_REFRESH_ACTIONS:
                found.append(dash_c_dirs)
    return found


def _find_project_root(start: Path) -> Optional[Path]:
    """The nearest directory at or above `start` that holds docs/ai/config.md, else None."""
    try:
        current = start.resolve()
    except (OSError, ValueError):
        return None
    for candidate in (current, *current.parents):
        if (candidate / "docs" / "ai" / "config.md").is_file():
            return candidate
    return None


def _own_project_root() -> Optional[Path]:
    """The project this hook file belongs to (.act/hooks/checks/board_refresh.py -> three levels
    up), when it holds docs/ai/config.md; never derived from the call being observed."""
    try:
        root = Path(__file__).resolve().parents[3]
    except (OSError, IndexError):
        return None
    return root if (root / "docs" / "ai" / "config.md").is_file() else None


def _targets_own_project(target: Path, root: Path) -> bool:
    """True when `target` lies inside `root` with no repository of its own (a `.git` entry) in
    between -- the git call then acts on this project's repository."""
    try:
        current = target.resolve()
        current.relative_to(root)
    except (OSError, ValueError):
        return False
    for candidate in (current, *current.parents):
        if candidate == root:
            return True
        if (candidate / ".git").exists():
            return False
    return False


def _base_cwd(payload: dict) -> str:
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd:
        return cwd
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def _target_dirs(dash_c_lists: "list[list[str]]", base_cwd: str) -> "list[Path]":
    """The directories whose project needs a fresh board, without duplicates, in call order."""
    result: "list[Path]" = []
    for dash_c_dirs in dash_c_lists:
        target = _resolve_dash_c_chain(dash_c_dirs, base_cwd) if dash_c_dirs else Path(base_cwd)
        if target is not None and target not in result:
            result.append(target)
    return result


def observe(event: str, payload: dict) -> None:
    if event != "PostToolUse" or _is_worker(payload):
        return
    shell = _shell_command(payload)
    if shell is None:
        return
    _tool, command = shell
    dash_c_lists = _command_changes_tree(command)
    if not dash_c_lists:
        return
    root = _own_project_root()
    if root is None:
        return
    if _check_mode(actlib.read_config(root), "session-start-refresh", default="block") != "block":
        return
    board_script = root / ".act" / "scripts" / "board.py"
    if not board_script.is_file():
        return
    if not any(_targets_own_project(target, root)
               for target in _target_dirs(dash_c_lists, _base_cwd(payload))):
        return
    try:
        subprocess.run(
            [sys.executable, str(board_script)], cwd=str(root),
            timeout=_BOARD_TIMEOUT_SECONDS, capture_output=True,
        )
    except (OSError, subprocess.SubprocessError):
        pass  # a broken board refresh must never disturb the hook chain
