#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check — write protection for the files that make the NEXT git command run code or switch
#          the safeguards off (PreToolUse), checked right after the template write-guard. Rule text:
#          `R-safe-git-metadata`. Two parts:
#
#          1. For everyone: a write under `.git/hooks/**` or to `.git/config` / `.git/config.worktree`
#             (file tools and the write targets of a Bash/PowerShell command, found by the shared
#             scanners shell_targets / powershell_targets), and `git config` / `git -c` /
#             `GIT_CONFIG_KEY_<n>` with a key that runs code (`_dangerous_reason`). A hook or such a
#             key runs at the next git command, past every other check and beyond the session.
#          2. For workers only (the payload carries `agent_id`): a write to `.claude/settings*.json`,
#             `.claude/agents/**`, `.claude/skills/**` in the project or in the user's home. They
#             switch hooks, permissions and roles; the orchestrator changes them on the human's
#             request and stays free to do so.
#
# Decisions:
#   - Read stays free: `git config --get`, `--list`, a Read of `.git/config`, `git config --global`
#     and `--system` (outside the repository), `--file <path outside .git>`.
#   - A local `git config` write is refused only for a key from the list below (or a key that cannot
#     be determined); `git config user.name x` stays free. Unsetting a key stays free.
#   - A `.git` that is a FILE (linked worktree, submodule, `--separate-git-dir`): its `gitdir:` target
#     and that directory's `commondir` are protected like a `.git` directory (`_extra_gitdirs`), on top
#     of the textual rule that any path with a `.git` segment followed by `hooks`/`config`/... counts
#     (also in a sibling checkout: nobody writes hooks by hand there either). A write to a `.git` that
#     is an existing FILE is refused too (re-pointing it moves the hooks elsewhere).
#   - Windows spellings: a path segment is compared lower-case, without trailing dots/spaces, without
#     an `:stream` suffix, and `git~1` counts as `.git`.
#   - `git init`/`git clone` with `--template <dir>` is refused: the template's hooks are copied
#     into the repository's `.git/hooks`.
#
# Keys that run code (the full list, with the reason), compared case-insensitively on section and
# variable name, subsection kept out of the comparison (see `_dangerous_reason`):
#   core.hooksPath, core.fsmonitor        hook directory / program run by almost every git command
#   core.sshCommand, core.gitProxy        program run for ssh / git:// connections
#   core.editor, core.pager, core.askPass, sequence.editor, pager.<cmd>
#                                         programs git starts for commits, output, credentials
#   core.alternateRefsCommand             program run to list alternate refs
#   alias.<name> with a value starting `!`  (or one that cannot be read)  shell command
#   include.path, includeIf.<cond>.path  pulls in a file whose content is not checked here
#   hook.<name>.*                         config-defined hooks
#   filter.<n>.clean|smudge|process, diff.<n>.textconv|command, diff.external, merge.<n>.driver,
#   difftool|mergetool.<n>.cmd|path, interactive.diffFilter, trailer.<n>.cmd|command,
#   browser.<n>.cmd, web.browser, man.<n>.cmd, submodule.<n>.update
#                                         external programs for the matching operation
#   credential.helper, credential.<url>.helper, gpg.program, gpg.<fmt>.program
#                                         programs that see secrets / sign
#   uploadpack.packObjectsHook, remote.<n>.uploadpack|receivepack
#                                         command run by a fetch/push, also from a local path
#   init.templateDir                      hooks copied into every repository created afterwards
#   protocol.ext.allow                    enables `ext::<command>` URLs
# The list is not exhaustive (git adds keys); it names the ones whose purpose is to start a program.
#
# Known limits:
#   - What a program or script writes itself (`pre-commit install`, `python -c "open(...)"`, a script
#     file) is invisible to every write check — same limit as the scanners this module uses.
#   - The one-shot environment variables GIT_SSH_COMMAND, GIT_EXTERNAL_DIFF, GIT_PAGER, GIT_EDITOR,
#     GIT_ASKPASS are not refused (common, visible on the command line); `GIT_CONFIG_KEY_<n>` and
#     `GIT_CONFIG_PARAMETERS` are, as they are `-c` in another spelling. A separate `export` is not
#     followed.
#   - `git config --global core.hooksPath` is free by decision and applies to every repository.
#   - A `git config` inside an alias, a script or an `eval` text the scanners cannot open is judged
#     only as far as command_words reads it. Not followed: `xargs ... git config`, `git submodule
#     foreach '...'`, an archive unpacked into the git directory (`tar -C .git`, `Expand-Archive`).
#   - A `git` started through `Start-Process` is read from its text only (`_start_process_git_args`).
#   - Failure mode: a scanner error is NOT swallowed into an allow — it falls back to a raw-text
#     search for the protected names (`_RAW_GIT_RE`/`_RAW_CLAUDE_RE`), like checks/write_guard.py.

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Optional

import actlib

from .command_words import _git_invocations_with_prefix
from .common import _TOOL_PATH_FIELDS, _check_mode, _is_worker
from .git_reset_hard import _resolve_cwd_after_leading_cd, _resolve_target_dir
from .powershell_targets import _powershell_write_targets
from .shell_targets import (
    _GIT_WRITES_TEMPLATE_GUARD, _bash_write_targets, _is_dynamic_target, _resolve_path,
)
from .worker_git_write import _parse_git_invocation
from .write_guard import _guard_root

__all__ = [
    "_RAW_GIT_RE", "_RAW_CLAUDE_RE", "_dangerous_reason", "_path_reason", "_config_issue",
    "_invocation_reason", "check_git_metadata_guard",
]

_RULE = "R-safe-git-metadata"

_GIT_NAMES = frozenset({".git", "git~1"})
_CONFIG_NAMES = frozenset({"config", "config.worktree"})

# Raw-text fallback for a target that cannot be placed (dynamic, unknown base, scanner failure).
_RAW_GIT_RE = re.compile(r"\.git(?::[^\\/]*)?[\\/](?:hooks|config|modules|worktrees)", re.IGNORECASE)
_RAW_CLAUDE_RE = re.compile(r"\.claude[\\/](?:settings[^\\/]*\.json|agents|skills|commands)", re.IGNORECASE)

# Sections that appear in the key list: a section renamed INTO one of these may carry such keys.
_RISKY_SECTIONS = frozenset({
    "core", "alias", "include", "includeif", "hook", "pager", "filter", "diff", "merge", "difftool",
    "mergetool", "interactive", "trailer", "browser", "web", "man", "submodule", "credential", "gpg",
    "sequence", "uploadpack", "remote", "init", "protocol",
})

_CORE_KEYS = frozenset({
    "hookspath", "fsmonitor", "sshcommand", "gitproxy", "editor", "pager", "askpass",
    "alternaterefscommand",
})
# section -> variable names (last key part) that name a program; subsection is ignored
_PROGRAM_KEYS = {
    "filter": {"clean", "smudge", "process"},
    "diff": {"textconv", "command", "external"},
    "merge": {"driver"},
    "difftool": {"cmd", "path"},
    "mergetool": {"cmd", "path"},
    "trailer": {"cmd", "command"},
    "browser": {"cmd", "path"},
    "man": {"cmd"},
    "web": {"browser"},
    "interactive": {"difffilter"},
    "submodule": {"update"},
    "credential": {"helper"},
    "gpg": {"program", "defaultkeycommand"},
    "sequence": {"editor"},
    "uploadpack": {"packobjectshook"},
    "remote": {"uploadpack", "receivepack"},
    "init": {"templatedir"},
}

# git config options: value-taking long names, flag-only long names, short flags
_CONFIG_VALUE_LONG = frozenset({"file", "blob", "default", "type", "comment", "value", "url"})
_CONFIG_FLAG_LONG = frozenset({
    "global", "system", "local", "worktree", "get", "get-all", "get-regexp", "get-urlmatch", "list",
    "add", "replace-all", "unset", "unset-all", "rename-section", "remove-section", "edit",
    "fixed-value", "includes", "no-includes", "show-origin", "show-scope", "null", "name-only",
    "bool", "int", "bool-or-int", "path", "expiry-date", "get-color", "get-colorbool", "no-type",
    "literally", "help",
})
_CONFIG_READ_MODES = frozenset({"get", "get-all", "get-regexp", "get-urlmatch", "list", "get-color",
                                "get-colorbool"})
_CONFIG_FREE_MODES = frozenset({"unset", "unset-all", "remove-section"})
_CONFIG_SUBCOMMANDS = frozenset({"get", "set", "unset", "list", "edit", "rename-section", "remove-section"})

_PARAMETERS_ENTRY_RE = re.compile(r"'([^'=]+)'(?:='([^']*)')?|'([^'=]+)=([^']*)'")
# `export A=1 NAME=value`, `NAME=value;` and PowerShell `$env:NAME = value`: environment set ahead of a git call
_ENV_ASSIGN_RE = re.compile(
    r"(?:^|[\s;(])(?:\$env:)?(GIT_CONFIG\w*)\s*=\s*(?:'([^']*)'|\"([^\"]*)\"|([^\s;]+))", re.IGNORECASE,
)
# the key operand of a `git ... config` that is an expression the word scanners do not evaluate
# (PowerShell `('core.hooks'+'Path')`, `$key`, a backtick escape)
_CONFIG_EXPR_KEY_RE = re.compile(r"\bgit(?:\.exe)?\b[^;|\n]*?\bconfig\b\s+(?:-\S+\s+)*[(\$`]", re.IGNORECASE)
_START_PROCESS_RE = re.compile(
    r"\b(?:start-process|saps|start)\s+(?:-FilePath\s+)?['\"]?git(?:\.exe)?['\"]?\s+(.*)", re.IGNORECASE,
)
_ARG_WORD_RE = re.compile(r"'([^']*)'|\"([^\"]*)\"|([^\s,'\"]+)")


def _norm_part(part: str) -> str:
    """One path segment as the file system sees it: no `:stream` suffix, no trailing dots/spaces,
    lower-case."""
    return part.split(":")[0].rstrip(" .").lower()


def _rest_protected(rest: tuple[str, ...]) -> bool:
    """True for the part of a path below a git directory that is protected: `hooks` (the directory and
    anything in it), `config`, `config.worktree`; below `modules/` and `worktrees/` (the git
    directories of submodules and linked worktrees) a `hooks` segment anywhere or a final
    `config`/`config.worktree`."""
    if not rest:
        return False
    if rest[0] == "hooks" or (len(rest) == 1 and rest[0] in _CONFIG_NAMES):
        return True
    if rest[0] in ("modules", "worktrees"):
        return "hooks" in rest[1:] or rest[-1] in _CONFIG_NAMES
    return False


def _is_inner_gitdir(rest: tuple[str, ...], resolved: Path) -> bool:
    """True when `rest` (below a git directory) names the git directory of a submodule or linked
    worktree itself -- `modules/<name>`, `worktrees/<name>`, or a deeper one holding a HEAD file --
    so a copy INTO it (`cp payload/config .git/modules/lib/`) reaches its hooks and config."""
    if not rest or rest[0] not in ("modules", "worktrees"):
        return False
    if len(rest) <= 2:
        return True
    try:
        return (resolved / "HEAD").exists()
    except OSError:
        return False


def _under(path: Path, base: Path) -> Optional[tuple[str, ...]]:
    """The normalized segments of `path` below `base`, or None if it lies elsewhere."""
    try:
        rel = Path(os.path.normcase(str(path))).relative_to(Path(os.path.normcase(str(base))))
    except ValueError:
        return None
    return tuple(_norm_part(part) for part in rel.parts)


def _extra_gitdirs(start: Optional[Path]) -> list[Path]:
    """The real git directories behind a `.git` FILE found at `start` or above it (at most 12
    levels): its `gitdir:` target and that directory's `commondir`. A plain `.git` directory needs
    no entry — the textual `.git` segment rule covers it. Empty when nothing is found or readable."""
    found: list[Path] = []
    if start is None:
        return found
    try:
        current = start.resolve()
        for _ in range(12):
            dot_git = current / ".git"
            if dot_git.is_file():
                text = dot_git.read_text(encoding="utf-8", errors="replace").strip()
                if text.lower().startswith("gitdir:"):
                    target = Path(text[len("gitdir:"):].strip())
                    gitdir = (target if target.is_absolute() else current / target).resolve()
                    found.append(gitdir)
                    common_file = gitdir / "commondir"
                    if common_file.is_file():
                        common = Path(common_file.read_text(encoding="utf-8", errors="replace").strip())
                        found.append((common if common.is_absolute() else gitdir / common).resolve())
                break
            if dot_git.is_dir() or current.parent == current:
                break
            current = current.parent
    except (OSError, ValueError):
        pass
    return found


def _path_reason(resolved: Path, gitdirs: list[Path], claude_dirs: list[Path]) -> Optional[str]:
    """Why a write to the absolute, resolved `resolved` is refused, or None. `claude_dirs` is empty
    for the orchestrator (the worker-only part)."""
    parts = tuple(_norm_part(part) for part in resolved.parts)
    for index, part in enumerate(parts):
        if part in _GIT_NAMES:
            below = parts[index + 1:]
            if _rest_protected(below) or _is_inner_gitdir(below, resolved):
                return "a git hook or the repository config"
            if index == len(parts) - 1:
                return "the `.git` directory or file itself (a copy into it reaches hooks and config)"
    for gitdir in gitdirs:
        rest = _under(resolved, gitdir)
        if rest is not None and (_rest_protected(rest) or rest == () or _is_inner_gitdir(rest, resolved)):
            return "a git hook or the repository config"
    for claude_dir in claude_dirs:
        rest = _under(resolved, claude_dir)
        if rest is not None and (
            rest == ()
            or (len(rest) == 1 and rest[0].startswith("settings") and rest[0].endswith(".json"))
            or rest[0] in ("agents", "skills", "commands")
        ):
            return "the Claude settings, roles or skills (workers may not change them)"
    return None


def _dangerous_reason(key: str, value: Optional[str]) -> Optional[str]:
    """Why setting git config `key` (to `value`; None = unknown) is refused, or None. See the
    module header for the list and the reasons."""
    if not key or re.search(r"[$`*?\[()]", key):
        return f"config key {key!r} cannot be determined"
    parts = key.split(".")
    section, variable = parts[0].lower(), parts[-1].lower()
    if len(parts) < 2:
        return None
    if section == "core" and variable in _CORE_KEYS:
        return f"config key {key} runs a program or hook directory"
    if section == "alias" and len(parts) == 2:
        if value is None or value.startswith("!") or re.match(r"[$`]", value):
            return f"config key {key} defines a shell alias"
        return None
    if section in ("include", "includeif") and variable == "path":
        return f"config key {key} includes a file that is not checked here"
    if section in ("hook", "pager"):
        return f"config key {key} runs a program"
    if "ext::" in key.lower():
        return f"config key {key} rewrites URLs to ext::, which runs a command"
    if section == "protocol" and variable == "allow":
        if len(parts) == 3 and parts[1].lower() == "ext":
            return f"config key {key} enables ext:: URLs, which run a command"
        if value is None or value.strip().lower() == "always":
            return f"config key {key} allows a transport unconditionally (ext:: runs a command)"
        return None
    if section == "remote" and variable in ("url", "pushurl"):
        if value is None or value.strip().lower().startswith("ext::"):
            return f"config key {key} points at an ext:: URL, which runs a command"
        return None
    if variable in _PROGRAM_KEYS.get(section, ()):
        return f"config key {key} names a program git runs"
    return None


def _expand_long(name: str) -> str:
    """A long `git config` option name with git's unique-prefix abbreviation resolved; an exact
    name wins, an ambiguous or unknown one stays as typed."""
    known = _CONFIG_VALUE_LONG | _CONFIG_FLAG_LONG
    if name in known:
        return name
    matches = [option for option in known if option.startswith(name)]
    return matches[0] if len(matches) == 1 else name


def _config_issue(
    sub_args: list[str], base: Optional[Path], env: Optional[dict[str, str]] = None,
) -> Optional[str]:
    """Why a `git config ...` call (`sub_args`: the words after `config`) is refused, or None.
    `base` is the directory the call runs in (None = unknown), used only for `--file`."""
    modes: set[str] = set()
    scope = "local"
    file_value: Optional[str] = None
    operands: list[str] = []
    index = 0
    only_operands = False
    while index < len(sub_args):
        arg = sub_args[index]
        index += 1
        if only_operands or not arg.startswith("-") or arg == "-":
            operands.append(arg)
            continue
        if arg == "--":
            only_operands = True
            continue
        if arg.startswith("--"):
            name, has_eq, value = arg[2:].partition("=")
            name = _expand_long(name)
            if name in _CONFIG_VALUE_LONG:
                if not has_eq and index < len(sub_args):
                    value = sub_args[index]
                    index += 1
                if name == "file":
                    scope, file_value = "file", value
                continue
            if name in ("global", "system"):
                scope = name
            elif name in ("local", "worktree"):
                scope = "local"
            elif name == "edit" or name in _CONFIG_READ_MODES or name in _CONFIG_FREE_MODES or name in (
                "add", "replace-all", "rename-section",
            ):
                modes.add(name)
            continue
        position = 1
        while position < len(arg):
            letter = arg[position]
            position += 1
            if letter in "ft":
                value = arg[position:]
                if not value and index < len(sub_args):
                    value = sub_args[index]
                    index += 1
                if letter == "f":
                    scope, file_value = "file", value
                break
            if letter == "l":
                modes.add("list")
            elif letter == "e":
                modes.add("edit")

    if operands and operands[0] in _CONFIG_SUBCOMMANDS:
        sub = operands.pop(0)
        if sub == "set":
            modes.add("set")
        elif sub in ("get", "list"):
            modes.add(sub)
        elif sub == "unset":
            modes.add("unset")
        else:
            modes.add(sub)

    env = env or {}
    if scope in ("global", "system") and env.get("GIT_CONFIG_" + scope.upper()):
        scope, file_value = "file", env["GIT_CONFIG_" + scope.upper()]  # the scope points at that file
    elif scope == "local" and env.get("GIT_CONFIG"):
        scope, file_value = "file", env["GIT_CONFIG"]
    if scope in ("global", "system"):
        return None
    if scope == "file" and file_value and not _is_dynamic_target(file_value):
        resolved = _resolve_path(file_value, str(base) if base is not None else None)
        if resolved is not None and _path_reason(resolved, _extra_gitdirs(base), []) is None:
            return None  # a config file elsewhere; anything else falls through to the local rules
    if modes & (_CONFIG_READ_MODES | _CONFIG_FREE_MODES):
        return None
    if "edit" in modes:
        return "`git config --edit` opens the repository config for free editing"
    if "rename-section" in modes:
        new_name = operands[1] if len(operands) > 1 else ""
        if re.search(r"[$`]", new_name) or new_name.split(".")[0].lower() in _RISKY_SECTIONS:
            return f"renaming a config section to {new_name!r} can bring in a key that runs code"
        return None
    if not operands:
        return None
    if len(operands) == 1 and not (modes & {"add", "replace-all", "set"}):
        return None  # `git config <key>` reads
    value = operands[1] if len(operands) > 1 else None
    return _dangerous_reason(operands[0], value)


def _override_keys(global_args: list[str]) -> list[tuple[str, Optional[str]]]:
    """(key, value) for every `-c key=value` / `-ckey=value` / `--config-env=key=VAR` among git's
    global options; the value of a `--config-env` pair is unknown (None), a `-c key` without `=`
    is the empty string."""
    found: list[tuple[str, Optional[str]]] = []
    index = 0
    while index < len(global_args):
        arg = global_args[index]
        index += 1
        candidate: Optional[str] = None
        from_env = False
        if arg == "-c" and index < len(global_args):
            candidate = global_args[index]
            index += 1
        elif arg == "--config-env" and index < len(global_args):
            candidate, from_env = global_args[index], True
            index += 1
        elif arg.startswith("--config-env="):
            candidate, from_env = arg[len("--config-env="):], True
        elif arg.startswith("-c") and not arg.startswith("--") and len(arg) > 2:
            candidate = arg[2:]
        if candidate is None:
            continue
        key, _, value = candidate.partition("=")
        found.append((key, None if from_env else value))
    return found


def _env_words(prefix: list[str], command: str) -> dict[str, str]:
    """NAME -> value of every environment assignment ahead of a git call: the words in front of it
    (also behind `env`) and `export NAME=...` / `$env:NAME = ...` anywhere in the command."""
    found: dict[str, str] = {}
    for word in prefix:
        name, sep, value = word.partition("=")
        if sep:
            found[name.upper()] = value
    for match in _ENV_ASSIGN_RE.finditer(command):
        found[match.group(1).upper()] = next(group for group in match.groups()[1:] if group is not None)
    return found


def _prefix_reason(env: dict[str, str]) -> Optional[str]:
    """Environment assignments in front of a git call that set config the way `-c` does."""
    for name, value in env.items():
        if re.fullmatch(r"GIT_CONFIG_KEY_\d+", name):
            reason = _dangerous_reason(value, None)
            if reason:
                return reason
        elif name == "GIT_CONFIG_PARAMETERS":
            for entry in _PARAMETERS_ENTRY_RE.finditer(value):
                reason = _dangerous_reason(entry.group(1) or entry.group(3), entry.group(2) or entry.group(4))
                if reason:
                    return reason
    return None


def _start_process_git_args(command: str) -> list[list[str]]:
    """The argument lists of `Start-Process git -ArgumentList 'a','b'` calls, read from the text
    (the word scanners do not open Start-Process). Best effort: quotes and commas separate words."""
    found = []
    for match in _START_PROCESS_RE.finditer(command):
        tail = re.sub(r"-ArgumentList\b", " ", match.group(1), flags=re.IGNORECASE)
        tail = re.split(r"[;|\n]", tail, maxsplit=1)[0]
        words = [next(g for g in m.groups() if g is not None) for m in _ARG_WORD_RE.finditer(tail)]
        found.append([w for w in words if w])
    return found


def _invocation_reason(command: str, base_cwd: Optional[str]) -> Optional[str]:
    """Why a git call in the shell `command` is refused (key that runs code, template directory),
    or None."""
    if _CONFIG_EXPR_KEY_RE.search(command):
        return "contains a git config key that cannot be determined (an expression)"
    effective_cwd, determinable = _resolve_cwd_after_leading_cd(command, base_cwd)
    invocations = _git_invocations_with_prefix(command) + [
        ([], args) for args in _start_process_git_args(command)
    ]
    for prefix, args in invocations:
        env = _env_words(prefix, command)
        reason = _prefix_reason(env)
        if reason:
            return reason
        subcommand, sub_args, dash_c_dirs, has_dir_override, _ = _parse_git_invocation(args)
        if subcommand is None:
            continue
        global_args = args[: len(args) - len(sub_args) - 1]
        for key, value in _override_keys(global_args):
            reason = _dangerous_reason(key, value)
            if reason:
                return reason
        if subcommand in ("init", "clone"):
            for arg in sub_args:
                name, _, value = arg.partition("=")
                if name.startswith("--te") and "--template".startswith(name) and (value or "=" not in arg):
                    return "a git template directory copies its hooks into .git/hooks"
        elif subcommand == "config":
            base: Optional[Path] = None
            if determinable:
                base = _resolve_target_dir(prefix, dash_c_dirs, has_dir_override, effective_cwd)
            reason = _config_issue(sub_args, base, env)
            if reason:
                return reason
    return None


def _claude_dirs(root: Optional[Path]) -> list[Path]:
    dirs = []
    if root is not None:
        dirs.append(root / ".claude")
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        dirs.append(Path(config_dir))
    try:
        dirs.append(Path.home() / ".claude")
    except (RuntimeError, OSError, KeyError):
        expanded = os.path.expanduser("~")
        if expanded != "~":
            dirs.append(Path(expanded) / ".claude")
    return dirs


def _target_reason(
    raw: str, base: Optional[str], gitdirs: list[Path], claude_dirs: list[Path], worker: bool,
    literal: bool = False,
) -> Optional[str]:
    """Why a write to the (possibly relative or dynamic) target `raw` is refused, or None. A file
    tool's path is `literal`: `$` and `~` in it are ordinary characters, not shell syntax."""
    if base is None or (not literal and _is_dynamic_target(raw)):
        if _RAW_GIT_RE.search(raw):
            return "a git hook or the repository config"
        if worker and _RAW_CLAUDE_RE.search(raw):
            return "the Claude settings, roles or skills (workers may not change them)"
        return None
    resolved = _resolve_path(raw, base)
    if resolved is None:
        return "a target that cannot be placed" if (
            _RAW_GIT_RE.search(raw) or (worker and _RAW_CLAUDE_RE.search(raw))
        ) else None
    return _path_reason(resolved, gitdirs, claude_dirs if worker else [])


def _violation(payload: dict) -> Optional[str]:
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
        return None
    cwd_raw = payload.get("cwd")
    base_cwd = cwd_raw if isinstance(cwd_raw, str) and cwd_raw else os.getcwd()
    root = _guard_root()
    worker = _is_worker(payload)
    gitdirs = _extra_gitdirs(root) + _extra_gitdirs(Path(base_cwd))
    claude_dirs = _claude_dirs(root)

    if tool_name in _TOOL_PATH_FIELDS:
        for field in _TOOL_PATH_FIELDS[tool_name]:
            value = tool_input.get(field)
            if isinstance(value, str):
                reason = _target_reason(value, base_cwd, gitdirs, claude_dirs, worker, literal=True)
                if reason:
                    return f"writes {reason}"
        return None

    if tool_name not in ("Bash", "PowerShell"):
        return None
    command = tool_input.get("command")
    if not isinstance(command, str) or not command.strip():
        return None

    try:
        if tool_name == "Bash":
            targets = [(raw, base) for raw, base in
                       _bash_write_targets(command, base_cwd, _GIT_WRITES_TEMPLATE_GUARD)]
        else:
            found = _powershell_write_targets(command, base_cwd, _GIT_WRITES_TEMPLATE_GUARD, broad=True)
            if found is None:
                raise ValueError("PowerShell command not evaluable")
            targets = [(raw, base_cwd) for raw in found]
        for raw, base in targets:
            reason = _target_reason(raw, base, gitdirs, claude_dirs, worker)
            if reason:
                return f"writes {reason}"
    except Exception:  # noqa: BLE001 — never a silent allow: fall back to the raw text
        if _RAW_GIT_RE.search(command):
            return "mentions a git hook or the repository config in a command that cannot be analysed"
        if worker and _RAW_CLAUDE_RE.search(command):
            return "mentions the Claude settings in a command that cannot be analysed"

    try:
        return _invocation_reason(command, base_cwd)
    except Exception:  # noqa: BLE001 — see above
        if re.search(r"\bgit\b", command) and re.search(r"\bconfig\b|\s-c\s", command) and re.search(
            r"hookspath|fsmonitor|sshcommand|alias\.|include|core\.(?:editor|pager)", command, re.IGNORECASE,
        ):
            return "contains a git config key that runs code in a command that cannot be analysed"
    return None


def check_git_metadata_guard(payload: dict) -> int:
    """Check: deny a write to .git/hooks or .git/config, a `git config`/`git -c` key that runs
    code (everyone), and for workers a write to .claude settings, agents and skills. See the module
    header for the decisions and limits."""
    config = actlib.read_config()
    mode = _check_mode(config, "git-metadata-guard", default="block")
    if mode == "off":
        return 0
    reason = _violation(payload)
    if reason is None:
        return 0
    message = (
        f"[act] refused ({_RULE}) -- this call {reason}. Hooks, the repository config and, for "
        "workers, the Claude settings run code or switch the safeguards off; ask the human to make "
        "the change."
    )
    if mode == "warn":
        print(message)
        return 0
    print(message, file=sys.stderr)
    return 2
