#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check 1 — template write-guard (PreToolUse), checked before every other check. Denies
#          an AI write under .act/**, pointing at docs/ai/local/<path> instead (ADR-5).
#
# Exit-code contract specific to this check: a mechanism error while checking a candidate write is
# NOT swallowed the way most other checks fail open. Every other check in this template fails open
# (never blocks the session on its own bug); this one is the exception — "when in doubt, deny"
# — because a false allow here means the template silently loses its own
# files to an edit the next update overwrites anyway.

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Optional

import actlib

from .common import _TOOL_PATH_FIELDS, _check_mode
from .powershell_targets import _powershell_write_targets
from .shell_targets import (
    _GIT_WRITES_TEMPLATE_GUARD, _bash_write_targets, _is_absolute_target, _is_dynamic_target,
    _to_native_path,
)

__all__ = [
    "_PROTECTED_PATH_RE", "_WRITE_GUARD_MESSAGE", "_bash_targets_protected_path",
    "_powershell_targets_protected_path", "_targets_protected_path", "_is_under_project_act",
    "_resolve_against", "_guard_root", "check_write_guard",
]

# ".act" as a whole path segment: ".act/" or ".act\" anywhere in the string, or ".act" at the
# very end — never as a prefix of another name. Deliberately no required prefix character
# before ".act" (a shell command has it after a space, quote, "=", redirect symbol, "(", and
# so on — enumerating all of those is more fragile than just not requiring one). The suffix
# check is what excludes ".act-lock.json" and ".act-local/", both project-level state next to
# the template tree rather than inside it, from this guard.
_PROTECTED_PATH_RE = re.compile(r"\.act(?:[\\/]|$)")


def _is_under_project_act(resolved: Path, root: Path) -> bool:
    """True if `resolved` (an absolute, already-resolved path) lies inside `root`'s own .act/ —
    the only tree this check protects (B137, 2026-09-25): a target outside `root` entirely, even
    one whose own path happens to contain a `.act/` segment (a sibling checkout's template tree,
    edited on purpose from a template-maintenance project), is not this check's business."""
    act_root = (root / ".act").resolve()
    return resolved == act_root or act_root in resolved.parents


def _resolve_against(base_cwd: str, raw: str) -> Optional[Path]:
    """`raw` resolved to an absolute path: as-is if already absolute, else joined onto
    `base_cwd` first. None on any error resolving it (never raises) — the caller then falls back
    to the raw-text check."""
    try:
        candidate = Path(_to_native_path(raw))
        if not candidate.is_absolute():
            candidate = Path(_to_native_path(base_cwd)) / candidate
        return candidate.resolve()
    except (OSError, ValueError):
        return None


def _bash_targets_protected_path(command: str, base_cwd: str, root: Optional[Path]) -> bool:
    """True if a Bash command writes to a path under `root`'s own .act/ — judged from the write
    targets the shared scanner finds (_bash_write_targets), not from a mere mention: `cat .act/x >
    /tmp/y`, `python .act/scripts/doctor.py 2>&1 | tail` and `grep -rn x .act/ 2>/dev/null` are
    reads and pass. Of the git subcommands only `git mv`/`git rm` count here
    (_GIT_WRITES_TEMPLATE_GUARD): `git checkout`/`git restore` stay allowed, since the orchestrator
    uses them to switch branches, unstage, and fetch the template's own version of a .act/ file
    back. A target whose directory is unknown (after `pushd`, a `cd $VAR`, inside a subshell, ...),
    that contains a variable, or whose own project `root` could not be determined is denied only
    if its own text names .act/ — everything else about it cannot be decided here (B137: a
    *determinable* target is resolved and checked against `root`'s own .act/ only, never against
    the raw text — a sibling checkout's .act/ is not this project's to protect)."""
    for raw, base in _bash_write_targets(command, base_cwd, _GIT_WRITES_TEMPLATE_GUARD):
        if base is None or _is_dynamic_target(raw) or root is None:
            if _PROTECTED_PATH_RE.search(raw):
                return True
            continue
        try:
            resolved = (Path(_to_native_path(base)) / _to_native_path(raw)).resolve()
        except (OSError, ValueError):
            return True  # cannot place it — fail closed, see the module docstring
        if _is_under_project_act(resolved, root):
            return True
    return False


_WRITE_GUARD_MESSAGE = (
    "[act] .act/ belongs to the template and is replaced on update. Put your version in "
    "docs/ai/local/<same path> — it wins over the template (ADR-5)."
)


def _powershell_targets_protected_path(command: str, base_cwd: str, root: Optional[Path]) -> bool:
    """True if a PowerShell command writes to a path under `root`'s own .act/ — same judgment as
    _bash_targets_protected_path, via powershell_targets._powershell_write_targets with
    `broad=True` (only git mv/rm count, _GIT_WRITES_TEMPLATE_GUARD, same split as the Bash side;
    `broad` is check 1's own deliberately over-inclusive extra pass, see that module's docstring).
    None back from that scanner (Invoke-Expression/iex, an unterminated quote/here-string) denies
    outright if .act/ is mentioned anywhere in the raw command text — "when in doubt, deny"
    (2026-09-23 review, BLOCK): unlike check 1c's own None fallback (_ps_raw_redirect_targets, the
    same operator-based approximation Bash's own scanner falls back to), check 1 cannot afford to
    miss a write it could not parse, since a false allow here survives until the next template
    update silently overwrites it. A *determinable* target (already resolved to an absolute path
    by the scanner) is checked against `root`'s own .act/ only (B137), same as the Bash side."""
    targets = _powershell_write_targets(command, base_cwd, _GIT_WRITES_TEMPLATE_GUARD, broad=True)
    if targets is None:
        return bool(_PROTECTED_PATH_RE.search(command))
    for target in targets:
        if _is_dynamic_target(target) or root is None:
            if _PROTECTED_PATH_RE.search(target):
                return True
            continue
        try:
            resolved = (
                Path(_to_native_path(target)).resolve() if _is_absolute_target(target)
                else (Path(_to_native_path(base_cwd)) / _to_native_path(target)).resolve()
            )
        except (OSError, ValueError):
            return True  # cannot place it — fail closed, see the module docstring
        if _is_under_project_act(resolved, root):
            return True
    return False


def _targets_protected_path(
    tool_name: str, tool_input: dict, base_cwd: str, root: Optional[Path],
) -> bool:
    """True if this tool call writes somewhere under `root`'s own .act/, based on the
    write-target field(s) that specific tool uses. Unknown tools never match — this guard only
    needs to understand the tools named in the PreToolUse matcher in settings.hooks.json.
    `base_cwd` is the directory a relative Bash/PowerShell/file-tool target is resolved against
    (the tool's own cwd); `root` is the project whose .act/ this check protects (None when it
    could not be determined, e.g. `base_cwd` sits outside any template-managed project) — see
    _is_under_project_act (B137)."""
    if tool_name == "Bash":
        command = tool_input.get("command")
        return isinstance(command, str) and _bash_targets_protected_path(command, base_cwd, root)
    if tool_name == "PowerShell":
        command = tool_input.get("command")
        return isinstance(command, str) and _powershell_targets_protected_path(command, base_cwd, root)
    for field in _TOOL_PATH_FIELDS.get(tool_name, ()):
        value = tool_input.get(field)
        if not isinstance(value, str):
            continue
        if root is None:
            if _PROTECTED_PATH_RE.search(value):
                return True
            continue
        resolved = _resolve_against(base_cwd, value)
        if resolved is None:
            if _PROTECTED_PATH_RE.search(value):
                return True
            continue
        if _is_under_project_act(resolved, root):
            return True
    return False


def _guard_root() -> Optional[Path]:
    """The project root this check protects — never derived from the tool call's own `cwd`
    (B137: a worker or the running Claude Code session can sit in a sibling project's directory
    while still writing an absolute path into *this* project's `.act/`, and the guard must catch
    that write regardless of where the process happens to be sitting). Preferred order: the
    `CLAUDE_PROJECT_DIR` environment variable Claude Code sets for every hook invocation, when it
    points at a real template-managed project; else the location dispatch.py itself was loaded
    from (`.act/hooks/dispatch.py`'s own directory tells us unambiguously which project's `.act/`
    is running this hook, independent of `cwd`); `cwd` is only the last resort, for a manual
    invocation with neither of those available."""
    env_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_dir:
        candidate = Path(env_dir)
        if (candidate / ".act").is_dir():
            return candidate.resolve()
    dispatch_root = Path(__file__).resolve().parents[3]
    if (dispatch_root / ".act").is_dir():
        return dispatch_root
    return None


def check_write_guard(payload: dict) -> int:
    """Check 1: deny an AI write under <project root>/.act/**, pointing at
    docs/ai/local/<path> instead (ADR-5) — never a write outside that root, even one whose path
    happens to contain a `.act/` segment (B137: a sibling checkout's template tree, deliberately
    edited from a template-maintenance project, is not this check's business). See this module's
    docstring for why this check's error handling — fail closed, not open — differs from the rest
    of the checks."""
    config = actlib.read_config()
    mode = _check_mode(config, "template-write-guard", default="block")
    if mode == "off":
        return 0

    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
        return 0  # nothing to check a write target against

    cwd_raw = payload.get("cwd")
    base_cwd = cwd_raw if isinstance(cwd_raw, str) and cwd_raw else os.getcwd()
    root = _guard_root()
    if root is None:
        try:
            root = actlib.repo_root(Path(base_cwd))
        except RuntimeError:
            root = None  # base_cwd is not inside any template-managed project either
    if not _targets_protected_path(tool_name, tool_input, base_cwd, root):
        return 0

    if mode == "warn":
        print(_WRITE_GUARD_MESSAGE)
        return 0

    print(_WRITE_GUARD_MESSAGE, file=sys.stderr)
    return 2
