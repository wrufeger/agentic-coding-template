#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check — `git add -A`/`--all`/`.`/`:/`/`./`/`:/:`/`:(top)`/`*` and `git commit -a`/
#          `--all`/`-am ...` (PreToolUse, R-code-commit); `git stage` counts as `git add` (an
#          alias some git tutorials configure by hand — this check does not care whether it is
#          actually configured in the target repo, only that the word means "add" if it is).
#          R-code-commit: "Commits exclusively by pathspec (never a catch-all like
#          `git add -A`/`git add .`)" — for **everyone**, the orchestrator included, unlike
#          checks/worker_git_write.py in this same wave (which is worker-only). `git add -u`/
#          `--update` stays free (named explicitly in the assignment): it stages changes to
#          already-tracked files, not an unreviewed catch-all of new ones. `git add <path>` /
#          `git add ./<path>` also stay free — only the exact catch-all markers below trigger this
#          check, not "add"/"stage" or "commit" as such.
#
#          Command decomposition reuses checks/command_words.py's `_git_invocations`, shared with
#          checks/worker_git_write.py and checks/recursive_delete.py (review, 2026-09-23 — see
#          command_words.py's own header for why the first version's plain operator-character
#          regex split was wrong). Skipping git's own global options ahead of the subcommand
#          reuses checks/worker_git_write.py's `_parse_git_invocation`.
#
# Known limits:
#   - `git commit`'s catch-all short-flag cluster (`-am`, `-ma`, ...) is recognized through a
#     small fixed alphabet (_COMMIT_CLUSTER_RE: a, m, v, q, n, e, i, o, t, S) rather than real
#     getopt-style parsing of git's own option table. A commit message glued directly onto such a
#     cluster with no space (`git commit -amFixed typo`, unusual but valid git syntax where "-am"
#     eats "Fixed" as -m's value) is misread as part of the cluster only if that glued text
#     happens to consist solely of the same few letters — in practice this only risks a false
#     "catch-all" note/block on an oddly-spelled unquoted message, never a missed real `-a`/`-am`.
#   - `:(top)`/`:(top).` (git's pathspec "magic" syntax for "from the top of the working tree") is
#     matched on the RAW command text (_RAW_TOP_MAGIC_RE), not through the tokenized argv like
#     every other marker here: command_words.py's shared tokenizer treats "(" and ")" as command-
#     boundary operators even glued mid-word (needed elsewhere, for real subshells), which tears
#     `:(top)` into fragments no per-invocation operand check can reassemble. The raw-text check is
#     therefore only loosely bound to "some `git add`/`git stage` invocation exists in this
#     command", not to the exact invocation that carries the pattern — accepted, over-inclusive by
#     design for a pattern this specific and this rare.
#   - segmenting/tokenizing otherwise shares checks/command_words.py's known limits (best-effort
#     PowerShell quoting, bounded recursion depth).
#   - a write made from inside a program (`python -c "...git add -A..."`) is invisible, same limit
#     stated throughout this stage's checks.

from __future__ import annotations

import re
import sys

import actlib

from .command_words import _git_invocations
from .common import _check_mode, _shell_command
from .worker_git_write import _parse_git_invocation

__all__ = [
    "_ADD_CATCHALL_FLAGS", "_ADD_CATCHALL_OPERANDS", "_COMMIT_CLUSTER_RE", "_RAW_TOP_MAGIC_RE",
    "_PATHSPEC_MESSAGES", "_add_is_catchall", "_commit_is_catchall", "check_commit_pathspec",
]

_ADD_CATCHALL_FLAGS = frozenset({"-A", "--all"})
_ADD_CATCHALL_OPERANDS = frozenset({".", ":/", "./", ":/:", "*"})

# A short-flag cluster built only from these letters, containing "a" -- see this module's Known
# limits for the tradeoff.
_COMMIT_CLUSTER_RE = re.compile(r"^-[amvqneiotS]+$")

# `:(top)` / `:(top).` as a whole word (not glued onto other text) anywhere in the raw command —
# see this module's Known limits for why this one marker is matched on raw text instead of argv.
_RAW_TOP_MAGIC_RE = re.compile(r"""(?<![^\s"'])(:\(top\)\.?)(?![^\s"'])""")

_PATHSPEC_MESSAGES = {
    "add": "[act] stage by pathspec: git add <path> (R-code-commit)",
    "commit": "[act] stage by pathspec first, then git commit -m <message> (R-code-commit)",
}


def _add_is_catchall(args: list[str]) -> bool:
    return any(arg in _ADD_CATCHALL_FLAGS for arg in args) or any(
        arg in _ADD_CATCHALL_OPERANDS for arg in args
    )


def _commit_is_catchall(args: list[str]) -> bool:
    for arg in args:
        if arg in ("-a", "--all"):
            return True
        if _COMMIT_CLUSTER_RE.match(arg) and "a" in arg[1:]:
            return True
    return False


def check_commit_pathspec(payload: dict) -> int:
    """Check: deny a catch-all `git add`/`git stage`/`git commit` in favor of staging by pathspec
    (R-code-commit) — for every caller, orchestrator included."""
    config = actlib.read_config()
    mode = _check_mode(config, "commit-pathspec", default="block")
    if mode == "off":
        return 0

    shell = _shell_command(payload)
    if shell is None:
        return 0
    _, command = shell

    for args in _git_invocations(command):
        subcommand, sub_args, _, _, _ = _parse_git_invocation(args)
        if subcommand in ("add", "stage") and (
            _add_is_catchall(sub_args) or _RAW_TOP_MAGIC_RE.search(command)
        ):
            message = _PATHSPEC_MESSAGES["add"]
        elif subcommand == "commit" and _commit_is_catchall(sub_args):
            message = _PATHSPEC_MESSAGES["commit"]
        else:
            continue
        if mode == "warn":
            print(message)
            return 0
        print(message, file=sys.stderr)
        return 2
    return 0
