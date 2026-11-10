#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check — refuses a Bash call that holds `cd` (or `pushd`) and a `git` command in the same chain
#          (`cd x && git status`, `cd x; git log`, `(cd x && git add .)`) and names `git -C <folder> ...`, in
#          a call of its own, as the way (PreToolUse, switch `cd-git`). Claude Code asks the human for
#          approval each time for `cd` together with `git` in one call, in auto mode too; `git -C` with the
#          folder written out does not. A `cd` into the folder the call runs in (the project root, `cd .`)
#          does not count. Applies to the main session and to workers.
#
# Switch `cd-git` in docs/ai/config.md § Checks: `block` (default), `warn` (names the way, lets the call
# pass), `off`. The check runs only when the `tools` row holds `claude-code`: it answers a prompt of that
# tool; for any other tool, or a project without the row, it does nothing.
#
# Reading: the dispatcher's shared parse (`Parse.stripped`: the argv of every simple command, nested
# subshells and `bash -c` text included). Bash only: the prompt is Claude Code's Bash permission check.
#
# Limits: a `cd` or a `git` made by a program (`python -c`, a script file) is not seen; a `cd` whose folder
# is a variable or a substitution counts as a `cd` elsewhere. Fails open: an exception lets the call pass.

from __future__ import annotations

import os
import re
import sys
from typing import Optional

import actlib

from .command_parse import parse_for
from .common import _check_mode, _shell_command

__all__ = ["check_cd_git"]

_CD_WORDS = ("cd", "pushd")
_MSYS_DRIVE_RE = re.compile(r"^/([A-Za-z])(/.*)?$")

_MESSAGE = (
    "[act] cd and git in one call: Claude Code asks the owner for approval each time for it (cd-git-compound), "
    "auto mode included. Run git in a call of its own with the folder written out: `git -C {folder} <command>`; "
    "a `cd` is not needed. Switch `cd-git` in docs/ai/config.md § Checks"
)


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path.replace("\\", "/")))


def _msys_to_drive(path: str) -> str:
    """`/d/dev/x` -> `d:/dev/x` on Windows (Git Bash paths); unchanged elsewhere."""
    match = _MSYS_DRIVE_RE.match(path)
    if sys.platform == "win32" and match:
        return f"{match.group(1)}:{match.group(2) or '/'}"
    return path


def _stays_here(target: str, cwd: str) -> bool:
    """True when `cd <target>` goes to the folder the call runs in: a literal path (no variable, no
    substitution, no `~`) that resolves to `cwd`."""
    if not target or any(char in target for char in "$`~*?"):
        return False
    text = _msys_to_drive(target)
    resolved = text if os.path.isabs(text) or re.match(r"^[A-Za-z]:", text) else os.path.join(cwd, text)
    return _norm(resolved) == _norm(cwd)


def _cd_target(words: list[str]) -> Optional[str]:
    """The folder a `cd`/`pushd` argv names ("" when it names none), None for a word list that is no cd."""
    if not words or words[0] not in _CD_WORDS:
        return None
    operands = [word for word in words[1:] if not word.startswith("-") or word == "-"]
    return operands[0] if operands else ""


def _is_git(words: list[str]) -> bool:
    return bool(words) and re.split(r"[\\/]", words[0])[-1].lower() in ("git", "git.exe")


def check_cd_git(payload: dict) -> int:
    """Refuse `cd`/`pushd` and `git` in one Bash call (exit 2, the reason on stderr); 0 otherwise."""
    try:
        shell = _shell_command(payload)
        if shell is None or shell[0] != "Bash":
            return 0
        command = shell[1]
        if ("cd" not in command and "pushd" not in command) or "git" not in command:
            return 0  # the cheap text test first: most calls end here without reading docs/ai/config.md
        config = actlib.read_config()
        mode = _check_mode(config, "cd-git", default="block")
        tools = [actlib.normalize_tool(tool) for tool in config.get("tools", "").split(",")]
        if mode == "off" or "claude-code" not in tools:
            return 0
        cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) and payload.get("cwd") else str(actlib.repo_root())
        word_lists = parse_for(payload, command).stripped()
        if not any(_is_git(words) for words in word_lists):
            return 0
        folder: Optional[str] = None
        for words in word_lists:
            target = _cd_target(words)
            if target is not None and not _stays_here(target, cwd):
                folder = target
                break
        if folder is None:
            return 0
    except Exception:  # noqa: BLE001 -- fail open: a check that cannot read the call lets it pass
        return 0
    shown = folder if folder and not any(char in folder for char in "$`~") else "<folder>"
    if " " in shown:
        shown = f'"{shown}"'
    message = _MESSAGE.format(folder=shown)
    if mode == "warn":
        print(message)
        return 0
    print(message, file=sys.stderr)
    return 2
