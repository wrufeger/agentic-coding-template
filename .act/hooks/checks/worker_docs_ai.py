#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check — a worker writing under docs/ai/ (PreToolUse, R-role-worker). AGENTS.md §
#          Rollen / CLAUDE.md § 1: only the orchestrator writes docs/ai/ — a worker returns its
#          result and lets the orchestrator record it. No exception for docs/ai/local/: that
#          directory holds the *project's* override of a template file (ADR-5), still something
#          only the orchestrator decides to write, not a worker's scratch space (a worker's
#          scratch space is scratchpad_dir, exempted the same way checks/write_scope.py exempts
#          it). The orchestrator's own calls are never checked here — it is exactly who is
#          *allowed* to write to docs/ai/.
#
#          Shape mirrors checks/write_guard.py (protected-path regex over a Write/Edit/MultiEdit/
#          NotebookEdit path field, or a Bash/PowerShell write-target scan via shell_targets),
#          scoped to workers only — write_guard.py already covers .act/ for everyone, including
#          the orchestrator; this check is the docs/ai/ analogue, worker-only.
#
# Known limits:
#   - _DOCS_AI_PATH_RE has no required left boundary before "docs" (same tradeoff write_guard.py's
#     own _PROTECTED_PATH_RE makes, for the same reason: enumerating every character that could
#     precede a path segment in a shell command — space, quote, "=", a redirect symbol, "(", ...
#     — is more fragile than requiring none). A directory literally named "somedocs" with an "ai"
#     child would over-block; accepted as the safe-side tradeoff, same as write_guard.py's.
#   - PowerShell commands are scanned with the same Bash-oriented tokenizer as Bash ones
#     (shell_targets._bash_write_targets) — best effort per this stage's assignment. A native
#     PowerShell write cmdlet that shell_targets does not know as a "write command"
#     (Set-Content, Out-File, Add-Content, New-Item, ...) is invisible to this check; the generic
#     `>`/`>>` redirection operators (which PowerShell also supports) and Unix-tool-alias writes
#     it does recognize (tee, cp, mv, ...) still are.
#   - a write made from inside a program (`python -c "..."`, a script file) is invisible, same
#     limit shell_targets.py's own docstring states for write targets generally.

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import actlib

from .common import _TOOL_PATH_FIELDS, _check_mode, _is_worker
from .shell_targets import _GIT_WRITES_WORKER_SCOPE, _bash_write_targets, _is_dynamic_target, _to_native_path

__all__ = [
    "_DOCS_AI_PATH_RE", "_DOCS_AI_MESSAGE", "_bash_targets_docs_ai", "_targets_docs_ai",
    "check_worker_docs_ai",
]

# "docs/ai" as a path segment pair: "docs/ai", "docs/ai/x", "docs\ai\x" — but not "docs/ai-notes"
# (the trailing boundary excludes a name that merely starts with "ai"). See this module's "Known
# limits" for why there is deliberately no required left boundary either.
_DOCS_AI_PATH_RE = re.compile(r"docs[\\/]ai(?:[\\/]|$)")

_DOCS_AI_MESSAGE = (
    "[act] only the orchestrator writes docs/ai/ — return the text instead (R-role-worker)"
)


def _bash_targets_docs_ai(command: str, base_cwd: str) -> bool:
    """True if a Bash/PowerShell command writes into docs/ai/, judged from the write targets the
    shared scanner finds (_bash_write_targets) — a mere mention (`cat docs/ai/x`, `grep -r x
    docs/ai/`) is a read and passes. git_writes is _GIT_WRITES_WORKER_SCOPE (mv/rm/checkout/
    restore, the same set checks/write_scope.py uses): those git subcommands' own operands are
    themselves paths worth checking here; a worker's `git add`/`git commit`/... is blocked outright
    by checks/worker_git_write.py regardless of what path it names, so this check does not need to
    special-case every write-ish git subcommand itself. A target whose base directory is unknown or
    that contains a shell variable/substitution is judged denied only if its own text names
    docs/ai — mirrors checks/write_guard.py's _bash_targets_protected_path exactly."""
    for raw, base in _bash_write_targets(command, base_cwd, _GIT_WRITES_WORKER_SCOPE):
        if _DOCS_AI_PATH_RE.search(raw):
            return True
        if base is None or _is_dynamic_target(raw):
            continue
        try:
            resolved = (Path(_to_native_path(base)) / _to_native_path(raw)).resolve()
        except (OSError, ValueError):
            return True  # cannot place it -- fail toward blocking, same as write_guard.py
        if _DOCS_AI_PATH_RE.search(resolved.as_posix()):
            return True
    return False


def _targets_docs_ai(tool_name: str, tool_input: dict, base_cwd: str) -> bool:
    """True if this tool call's write target lands under docs/ai/. Unknown tools never match —
    same convention as write_guard.py's _targets_protected_path. The Write/Edit/MultiEdit/
    NotebookEdit path field is run through os.path.normcase(os.path.normpath(...)) before the
    regex search (review, 2026-09-23): unlike a Bash/PowerShell target (already normalized via
    Path(...).resolve() in _bash_targets_docs_ai), the raw tool_input field is neither
    case-folded nor collapsed of "." segments, so `Docs/AI/x` (Windows' case-insensitive
    filesystem) or `docs/./ai/x` (a path built by joining pieces) would otherwise slip past the
    plain regex search unmatched."""
    if tool_name in ("Bash", "PowerShell"):
        command = tool_input.get("command")
        return isinstance(command, str) and _bash_targets_docs_ai(command, base_cwd)
    for field in _TOOL_PATH_FIELDS.get(tool_name, ()):
        value = tool_input.get(field)
        if isinstance(value, str) and value:
            normalized = os.path.normcase(os.path.normpath(value))
            if _DOCS_AI_PATH_RE.search(normalized):
                return True
    return False


def check_worker_docs_ai(payload: dict) -> int:
    """Check: deny a worker's write under docs/ai/ (R-role-worker). The orchestrator's own calls
    (no agent_id in the payload, see common._is_worker) are never checked — it is who is *allowed*
    to write there."""
    config = actlib.read_config()
    mode = _check_mode(config, "worker-docs-ai", default="block")
    if mode == "off" or not _is_worker(payload):
        return 0

    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
        return 0

    cwd_raw = payload.get("cwd")
    base_cwd = cwd_raw if isinstance(cwd_raw, str) and cwd_raw else os.getcwd()
    if not _targets_docs_ai(tool_name, tool_input, base_cwd):
        return 0

    if mode == "warn":
        print(_DOCS_AI_MESSAGE)
        return 0
    print(_DOCS_AI_MESSAGE, file=sys.stderr)
    return 2
