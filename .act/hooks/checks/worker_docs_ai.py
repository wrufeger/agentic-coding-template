#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check — a worker writing under docs/ai/ (PreToolUse, R-role-worker):
#          only the orchestrator writes docs/ai/ — a worker returns its
#          result and lets the orchestrator record it. No exception for docs/ai/local/: that
#          directory holds the *project's* override of a template file, still something
#          only the orchestrator decides to write, not a worker's scratch space (a worker's
#          scratch space is scratchpad_dir, exempted the same way checks/write_scope.py exempts
#          it via _within_scratchpad — reused here, not copied). The orchestrator's own calls are
#          never checked here — it is exactly who is *allowed* to write to docs/ai/.
#
#          Shape mirrors checks/write_guard.py (protected-path regex over a Write/Edit/MultiEdit/
#          NotebookEdit path field, or a Bash/PowerShell write-target scan via shell_targets),
#          scoped to workers only — write_guard.py already covers .act/ for everyone, including
#          the orchestrator; this check is the docs/ai/ analogue, worker-only. Like write_guard.py,
#          only the *calling* project's own <root>/docs/ai/ is protected — a determinable
#          target outside `root` (a sibling checkout's docs/ai/) is not this check's business, and
#          `root` is found the same way (checks.write_guard._guard_root, reused here): the
#          `CLAUDE_PROJECT_DIR` a hook always receives, else dispatch.py's own location, `cwd` only
#          as a last resort.
#
# Known limits:
#   - _DOCS_AI_PATH_RE has no required left boundary before "docs" (same tradeoff write_guard.py's
#     own _PROTECTED_PATH_RE makes, for the same reason: enumerating every character that could
#     precede a path segment in a shell command — space, quote, "=", a redirect symbol, "(", ...
#     — is more fragile than requiring none). A directory literally named "somedocs" with an "ai"
#     child would over-block; accepted as the safe-side tradeoff, same as write_guard.py's. This
#     text-only match is also the fallback used whenever a target's base/root cannot be
#     determined at all (fail toward blocking, same as write_guard.py).
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
from typing import Optional

import actlib

from .common import _TOOL_PATH_FIELDS, _check_mode, _is_worker
from .shell_targets import _GIT_WRITES_WORKER_SCOPE, _bash_write_targets, _is_dynamic_target, _resolve_path
from .write_guard import _guard_root, _resolve_against
from .write_scope import _within_scratchpad

__all__ = [
    "_DOCS_AI_PATH_RE", "_DOCS_AI_MESSAGE", "_is_under_project_docs_ai", "_bash_targets_docs_ai",
    "_targets_docs_ai", "check_worker_docs_ai",
]

# "docs/ai" as a path segment pair: "docs/ai", "docs/ai/x", "docs\ai\x" — but not "docs/ai-notes"
# (the trailing boundary excludes a name that merely starts with "ai"). See this module's "Known
# limits" for why there is deliberately no required left boundary either.
_DOCS_AI_PATH_RE = re.compile(r"docs[\\/]ai(?:[\\/]|$)")

_DOCS_AI_MESSAGE = (
    "[act] only the orchestrator writes docs/ai/ — return the text instead (R-role-worker)"
)


def _is_under_project_docs_ai(resolved: Path, root: Path) -> bool:
    """True if `resolved` (an absolute, already-resolved path, from shell_targets._resolve_path)
    lies inside `root`'s own docs/ai/ — the only tree this check protects (mirrors
    write_guard.py's _is_under_project_act, including its normalization of both sides): a target
    outside `root` entirely (a sibling checkout's docs/ai/, deliberately edited from a
    template-maintenance project) is not this check's business."""
    docs_ai_root = _resolve_path(str(root / "docs" / "ai"))
    if docs_ai_root is None:
        docs_ai_root = (root / "docs" / "ai").resolve()
    return resolved == docs_ai_root or docs_ai_root in resolved.parents


def _bash_targets_docs_ai(
    command: str, base_cwd: str, root: Optional[Path], scratchpad_dir: object,
) -> bool:
    """True if a Bash/PowerShell command writes into `root`'s own docs/ai/, judged from the write
    targets the shared scanner finds (_bash_write_targets) — a mere mention (`cat docs/ai/x`, `grep
    -r x docs/ai/`) is a read and passes. git_writes is _GIT_WRITES_WORKER_SCOPE (mv/rm/checkout/
    restore, the same set checks/write_scope.py uses): those git subcommands' own operands are
    themselves paths worth checking here; a worker's `git add`/`git commit`/... is blocked outright
    by checks/worker_git_write.py regardless of what path it names, so this check does not need to
    special-case every write-ish git subcommand itself. A target inside the worker's own
    scratchpad_dir (write_scope._within_scratchpad) is exempt, same as check_worker_write_
    scope treats it — a worker's scratch space is never "docs/ai/" in the sense R-role-worker
    means. A target whose base directory is unknown, that contains a shell variable/substitution,
    or whose own project `root` could not be determined is judged denied only if its own text
    names docs/ai — mirrors checks/write_guard.py's _bash_targets_protected_path exactly (a
    *determinable* target is resolved and checked against `root`'s own docs/ai/ only,
    never against the raw text — a sibling checkout's docs/ai/ is not this project's to protect)."""
    for raw, base in _bash_write_targets(command, base_cwd, _GIT_WRITES_WORKER_SCOPE):
        if (
            not _is_dynamic_target(raw)
            and isinstance(scratchpad_dir, str)
            and scratchpad_dir
            and _within_scratchpad(raw, scratchpad_dir)
        ):
            continue
        if base is None or _is_dynamic_target(raw) or root is None:
            if _DOCS_AI_PATH_RE.search(raw):
                return True
            continue
        resolved = _resolve_path(raw, base)
        if resolved is None:
            return True  # cannot place it -- fail toward blocking, same as write_guard.py
        if _is_under_project_docs_ai(resolved, root):
            return True
    return False


def _targets_docs_ai(
    tool_name: str, tool_input: dict, base_cwd: str, root: Optional[Path], scratchpad_dir: object,
) -> bool:
    """True if this tool call's write target lands under `root`'s own docs/ai/. Unknown tools
    never match — same convention as write_guard.py's _targets_protected_path. A target inside the
    worker's own scratchpad_dir is exempt first (see _bash_targets_docs_ai). The Write/Edit/
    MultiEdit/NotebookEdit path field, once past that exemption, is resolved against `base_cwd` and
    checked against `root`'s own docs/ai/ the same way write_guard.py's _targets_protected_path
    does it (_resolve_against) — falling back to a plain, normcase/normpath'd regex search
    (review, 2026-09-23: `Docs/AI/x` on Windows' case-insensitive filesystem, or `docs/./ai/x`
    built by joining pieces, would otherwise slip past the regex unmatched) whenever `root` is
    unknown or the path cannot be resolved at all."""
    if tool_name in ("Bash", "PowerShell"):
        command = tool_input.get("command")
        return isinstance(command, str) and _bash_targets_docs_ai(command, base_cwd, root, scratchpad_dir)
    for field in _TOOL_PATH_FIELDS.get(tool_name, ()):
        value = tool_input.get(field)
        if not isinstance(value, str) or not value:
            continue
        if isinstance(scratchpad_dir, str) and scratchpad_dir and _within_scratchpad(value, scratchpad_dir):
            continue
        if root is not None:
            resolved = _resolve_against(base_cwd, value)
            if resolved is not None:
                if _is_under_project_docs_ai(resolved, root):
                    return True
                continue
        normalized = os.path.normcase(os.path.normpath(value))
        if _DOCS_AI_PATH_RE.search(normalized):
            return True
    return False


def check_worker_docs_ai(payload: dict) -> int:
    """Check: deny a worker's write under `root`'s own docs/ai/ (R-role-worker). The orchestrator's
    own calls (no agent_id in the payload, see common._is_worker) are never checked — it is who is
    *allowed* to write there. `root` is found the same way write_guard.py's check 1 finds it
    (_guard_root): CLAUDE_PROJECT_DIR when it names a real template-managed project,
    else dispatch.py's own location, `base_cwd` only as a last resort via actlib.repo_root — so an
    unresolvable root falls back to the raw-text judgment everywhere above, never to a crash."""
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
    root = _guard_root()
    if root is None:
        try:
            root = actlib.repo_root(Path(base_cwd))
        except RuntimeError:
            root = None  # base_cwd is not inside any template-managed project either
    scratchpad_dir = payload.get("scratchpad_dir")
    if not _targets_docs_ai(tool_name, tool_input, base_cwd, root, scratchpad_dir):
        return 0

    if mode == "warn":
        print(_DOCS_AI_MESSAGE)
        return 0
    print(_DOCS_AI_MESSAGE, file=sys.stderr)
    return 2
