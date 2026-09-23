#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check — a recursive delete run from the shell (PreToolUse, R-safe-no-shell-delete).
#          AGENTS.md § Umgang mit Sicherheits-/Safeguard-Warnungen: "Kein `rm -rf` aus der Shell
#          ... Aufräumen mit den Mitteln der Sprache (`shutil.rmtree` in Python) oder gezielt Datei
#          für Datei." For **everyone**, orchestrator included — a shell-level recursive delete is
#          the risk this check exists for regardless of who runs it. `python -c
#          "shutil.rmtree(...)"` is deliberately never matched: it is the recommended way and is
#          invisible to a shell-command scan by construction (the delete happens inside the
#          interpreter, not as a shell command word this check inspects).
#
#          Recognized as a single command: Bash `rm -r`/`-R`/`--recursive` (including a combined
#          cluster like `-rf`/`-fr`); the Windows cmd-style `rmdir /s`/`rd /s`/`del /s`/`erase /s`
#          (case-insensitive, any `/q` alongside does not matter); PowerShell `Remove-Item
#          -Recurse` and its aliases `rm`/`ri`/`del`/`rd`/`rmdir`/`erase` with `-Recurse` or an
#          unambiguous prefix of it (`-r`, `-rec`, ... — PowerShell's own parameter-name prefix
#          matching, not attempted for a flag glued to a value); `find ... -exec ... -delete`.
#          Recognized as a *pair*: a pipeline shaped like `Get-ChildItem ... -Recurse | <delete
#          command>` (also via its aliases `gci`/`dir`/`ls`) — neither half looks recursive on its
#          own (a plain `Remove-Item` without `-Recurse` only removes what the pipe hands it, but
#          the pipe itself hands it an entire recursive listing), so this is checked as an
#          adjacency, not a per-command flag (see _is_recursive_listing/_is_delete_sink and the
#          pairwise scan in check_recursive_delete). A plain `rmdir`/`rd`/`del`/`erase` with no
#          recursion marker (removes only an already-empty directory / one named file) is not
#          flagged.
#
#          Command decomposition (finding every simple command despite quoting, heredocs, `bash
#          -c`/`pwsh -c`/`cmd /c`/`eval`/`$(...)`/backticks/`find -exec`/`xargs`) is
#          checks/command_words.py's job, shared with checks/worker_git_write.py and
#          checks/commit_pathspec.py — see that module's own header for why the first version of
#          this stage's segmenting (a bare operator-character regex split) was wrong and got
#          replaced (review, 2026-09-23); this check is also the one that needs
#          _command_word_lists' separator information directly, for the pipeline pattern above.
#
# Known limits:
#   - `-r`/`-rec`/... as a PowerShell `-Recurse` abbreviation is matched only when it stands as
#     its own token (an unquoted, space-separated argument); `-Recurse:$true` or a value glued
#     directly onto the flag is not specifically parsed (would still match as a "recurse"-prefix
#     token as long as the glued remainder does not turn it into something that no longer starts
#     with a `-recurse` prefix, e.g. `-Recurse:$true` still matches; `-RecurseFoo` would not,
#     since "recurse" is not a prefix of "recursefoo" the other way around — the match direction
#     is deliberately "does 'recurse' start with this flag's own letters", not the reverse).
#   - the pipeline pattern only looks at the ONE command immediately before a `|` — a longer chain
#     (`Get-ChildItem ... -Recurse | Where-Object {...} | Remove-Item`) is not connected across the
#     filter stage; accepted as a known gap rather than modeling arbitrary pipeline depth for a
#     pattern this narrow.
#   - segmenting/tokenizing otherwise shares checks/command_words.py's known limits (best-effort
#     PowerShell quoting, bounded recursion depth, a recursed sub-command's separators starting
#     fresh — see that module's header).
#   - a delete run from inside a program, a script file, or `xargs` fed from stdin with no command
#     of its own visible on the line, is invisible — matches shell_targets.py's own stated limits
#     for the same class of gap.

from __future__ import annotations

import sys

import actlib

from .command_words import _command_word_lists, _strip_command_prefix
from .common import _check_mode, _shell_command
from .shell_targets import _command_name

__all__ = [
    "_RECURSIVE_DELETE_MESSAGE", "_CMD_STYLE_DELETE_NAMES", "_PS_ONLY_DELETE_NAMES",
    "_LIST_RECURSE_NAMES", "_DELETE_SINK_NAMES", "_rm_is_recursive", "_has_cmd_slash_s",
    "_has_recurse_flag", "_segment_is_recursive_delete", "_is_recursive_listing",
    "_is_delete_sink", "check_recursive_delete",
]

_RECURSIVE_DELETE_MESSAGE = "[act] delete with shutil.rmtree or file by file (R-safe-no-shell-delete)"

# cmd.exe-style delete commands, where "/s" (recurse into subdirectories) is the marker; they are
# ALSO valid PowerShell aliases for Remove-Item, so a "-Recurse"-style flag counts too.
_CMD_STYLE_DELETE_NAMES = frozenset({"rmdir", "rd", "del", "erase"})
# PowerShell-only delete commands: "-Recurse"-style flag only, "/s" has no meaning here.
_PS_ONLY_DELETE_NAMES = frozenset({"remove-item", "ri"})
# Get-ChildItem and its common aliases, for the list-then-delete pipeline pattern.
_LIST_RECURSE_NAMES = frozenset({"get-childitem", "gci", "dir", "ls"})
# Every delete-capable command name, for the same pipeline pattern's second half.
_DELETE_SINK_NAMES = frozenset({"rm"}) | _CMD_STYLE_DELETE_NAMES | _PS_ONLY_DELETE_NAMES


def _rm_is_recursive(args: list[str]) -> bool:
    """True for POSIX `rm`'s own recursion markers: `--recursive`, or `-r`/`-R` anywhere in a
    short-flag cluster (`-rf`, `-fr`, ...)."""
    for arg in args:
        if arg == "--recursive":
            return True
        if arg.startswith("--"):
            continue
        if arg.startswith("-") and len(arg) > 1 and any(c in ("r", "R") for c in arg[1:]):
            return True
    return False


def _has_cmd_slash_s(args: list[str]) -> bool:
    return any(arg.lower() == "/s" for arg in args)


def _has_recurse_flag(args: list[str]) -> bool:
    """True if some argument is an unambiguous PowerShell-style prefix of "-Recurse" (`-r`,
    `-rec`, `-recurse`, ...), case-insensitive. A long POSIX-style `--xyz` flag is never read this
    way (that path is _rm_is_recursive's `--recursive`)."""
    for arg in args:
        if arg.startswith("--") or not arg.startswith("-"):
            continue
        rest = arg[1:].lower()
        if rest and "recurse".startswith(rest):
            return True
    return False


def _segment_is_recursive_delete(words: list[str]) -> bool:
    if not words:
        return False
    name = _command_name(words[0])
    args = words[1:]
    if name == "rm":
        return _rm_is_recursive(args) or _has_recurse_flag(args)  # POSIX rm, or PS's own "rm"
    if name in _CMD_STYLE_DELETE_NAMES:
        return _has_cmd_slash_s(args) or _has_recurse_flag(args) or "--recursive" in args
    if name in _PS_ONLY_DELETE_NAMES:
        return _has_recurse_flag(args)
    if name == "find":
        return "-delete" in args
    return False


def _is_recursive_listing(words: list[str]) -> bool:
    return bool(words) and _command_name(words[0]) in _LIST_RECURSE_NAMES and _has_recurse_flag(words[1:])


def _is_delete_sink(words: list[str]) -> bool:
    return bool(words) and _command_name(words[0]) in _DELETE_SINK_NAMES


def check_recursive_delete(payload: dict) -> int:
    """Check: deny a recursive delete run from the shell (R-safe-no-shell-delete) — for every
    caller, orchestrator included."""
    config = actlib.read_config()
    mode = _check_mode(config, "recursive-delete", default="block")
    if mode == "off":
        return 0

    shell = _shell_command(payload)
    if shell is None:
        return 0
    _, command = shell

    stripped = [
        (_strip_command_prefix(words), sep) for words, sep in _command_word_lists(command)
    ]
    stripped = [(words, sep) for words, sep in stripped if words]

    hit = False
    for index, (words, sep) in enumerate(stripped):
        if _segment_is_recursive_delete(words):
            hit = True
        elif sep == "|" and index > 0 and _is_delete_sink(words) and _is_recursive_listing(stripped[index - 1][0]):
            hit = True
        if hit:
            if mode == "warn":
                print(_RECURSIVE_DELETE_MESSAGE)
                return 0
            print(_RECURSIVE_DELETE_MESSAGE, file=sys.stderr)
            return 2
    return 0
