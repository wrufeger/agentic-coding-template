#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check — a worker running a git command that changes the tree or history (PreToolUse,
#          R-role-worker): a worker only ever reads git (status, diff, log, show) — every subcommand
#          in _GIT_WRITE_SUBCOMMANDS is a write for this check's purposes, plus `branch` unless it only
#          lists (_branch_lists_only); `stash` is one too, except `stash list` / `stash show` with plain
#          words only (_stash_reads_only); `status`, `diff`, `log`, `show`, `rev-parse`, `ls-files` and
#          `blame` are never in the write set. Split from checks/git_discard.py: this one asks WHO runs a
#          mutating git command (workers only, outside the project exempt), that one WHAT is lost (anyone).
#
#          Command decomposition (finding every `git ...` invocation despite quoting, heredocs,
#          `bash -c`/`pwsh -c`/`cmd /c`/`eval`/`$(...)`/backticks) is checks/command_words.py's
#          job, shared with checks/commit_pathspec.py and checks/recursive_delete.py — see that
#          module's own header for why the first version of this stage's segmenting (a bare
#          operator-character regex split) was wrong and got replaced (review, 2026-09-23).
#
#          Exempt: git run against a directory outside the project — a worker's own throwaway
#          repo for a probe or a test build (`git -C <tmp> commit`, `cd <tmp> && git init`). See
#          _leading_cd_outside_project and _parse_git_invocation's `-C` handling for exactly what
#          is recognized, and "Known limits" below for what is deliberately NOT — the exemption
#          only ever *widens* what is allowed, so anything ambiguous fails toward still checking
#          the call, never toward skipping it.
#
# Review fixes (2026-09-23, on top of the command_words.py rewrite):
#   - every `-C <dir>` on one invocation is applied in order against the running directory
#     (`git -C .git -C .. commit` ends up back where it started), not just the last one.
#   - the exemption never applies at all when the invocation's own `--git-dir`/`--work-tree`
#     (either form) is present, or a `GIT_DIR=`/`GIT_WORK_TREE=` assignment precedes `git` in the
#     same simple command (directly, or through an `env` wrapper) — those name git's working
#     directory independently of `-C`/`cd`, defeating the assumption this exemption's `-C`/`cd`
#     tracking relies on. Checked regardless of what `-C`/`cd` might otherwise have said.
#   - `pushd`, `chdir`, `Set-Location`/`sl`, `Push-Location` count as `cd` for both halves of the
#     leading-cd exemption (the leading segment itself, and "a later cd-like command disables it
#     entirely"); `popd`/`Pop-Location` count only for the second half — they change directory
#     unpredictably, so they can disable the exemption but never grant it.
#   - `git -c alias.<name>=<value> ...` is treated as a write outright, regardless of what
#     subcommand name follows: an alias can itself resolve to any git subcommand, including a
#     write one, and this check has no way to look up what the alias actually expands to.
#
# Known limits:
#   - PowerShell quoting is approximated the same way checks/command_words.py's tokenizer
#     approximates it generally — best effort, see that module's own header.
#   - the outside-project exemption only recognizes a literal `-C <dir>` chain on the git
#     invocation itself, or a literal `cd <dir>`-family command as the *whole command's own first
#     simple command* with no later cd-like command anywhere after it
#     (_leading_cd_outside_project) — both shapes named in the assignment's own examples. A `cd` inside
#     `( ... )` counts only when every command of the line is inside that group (`(cd x && git commit)`);
#     `(cd x) && git commit` runs the commit where the shell was (_group_closes_before_end). A `cd`
#     buried deeper, inside a function, guarded by `if`, or naming a dynamic directory ($VAR,
#     `` `...` ``, `$(...)`, a leading `~`) never grants the exemption: the git call is then still
#     checked normally.
#   - a write made from inside a program (`python -c "...git..."`, a script file) is invisible,
#     same limit as shell_targets.py's own docstring states.

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

import actlib

from .command_parse import Parse, parse_for
from .common import _check_mode, _is_worker, _shell_command
from .shell_targets import (
    _GIT_GLOBAL_VALUE_FLAGS,
    _command_name,
    _is_dynamic_target,
    _to_native_path,
)

__all__ = [
    "_GIT_WRITE_SUBCOMMANDS", "_branch_lists_only", "_CD_LIKE_NAMES", "_CD_UNKNOWN_NAMES",
    "_parse_git_invocation", "_is_git_write_subcommand", "_resolve_dir", "_is_outside_root",
    "_resolve_dash_c_chain", "_prefix_has_dir_override", "_first_operand",
    "_leading_cd_directory", "_leading_cd_outside_project", "_worker_git_write_message", "check_worker_git_write",
]

# Every git subcommand that changes the tree or history for this check's purposes. "init" is
# included beyond the assignment's own enumerated list: it creates a new history in whatever
# directory it targets, and the assignment's own worked example for the outside-project exemption
# ("cd <tmp> && git init") only exercises that exemption if `init` is itself a write here — inside
# the project it would otherwise reinitialize repository metadata, which is exactly the kind of
# change this check exists to keep a worker from doing unsupervised.
_GIT_WRITE_SUBCOMMANDS = frozenset({
    "commit", "add", "stash", "checkout", "switch", "reset", "restore", "merge", "rebase",
    "clean", "push", "pull", "cherry-pick", "revert", "am", "apply", "rm", "mv", "init",
})

_BRANCH_SHORT_RE = re.compile(r"-[alrvi]+")
_BRANCH_PLAIN = frozenset({
    "--show-current", "--list", "--all", "--remotes", "--verbose", "--ignore-case", "--color", "--no-color",
    "--column", "--no-column", "--abbrev", "--no-abbrev",
})
_BRANCH_VALUE = ("--contains", "--no-contains", "--merged", "--no-merged", "--points-at", "--sort", "--format")


def _branch_lists_only(sub_args: list[str]) -> bool:
    """True for a `branch` that only lists: listing switches, listing filters with their value, and bare
    words only as patterns (after `--list`/`-l` or a filter, else they would create a branch). A value
    never starts with `-`, so `--contains -D x` stays a delete."""
    listing, bare, index = False, 0, 0
    while index < len(sub_args):
        arg = sub_args[index]
        index += 1
        name, equals, _ = arg.partition("=")
        if _BRANCH_SHORT_RE.fullmatch(arg):
            listing = listing or "l" in arg
        elif name in _BRANCH_PLAIN:
            listing = listing or name == "--list"
        elif name in _BRANCH_VALUE:
            listing = listing or name not in ("--sort", "--format")
            if not equals and index < len(sub_args) and not sub_args[index].startswith("-"):
                index += 1
        elif not arg.startswith("-"):
            bare += 1
        else:
            return False
    return bare == 0 or listing


# Directory-change command names for the outside-project exemption (see this module's header).
# _CD_LIKE_NAMES take a literal directory operand the same way `cd` does; _CD_UNKNOWN_NAMES change
# directory without naming one (back to wherever a previous push left off) and so can only ever
# disable the exemption, never grant it.
_CD_LIKE_NAMES = frozenset({"cd", "pushd", "chdir", "set-location", "sl", "push-location"})
_CD_UNKNOWN_NAMES = frozenset({"popd", "pop-location"})


def _parse_git_invocation(
    args: list[str],
) -> tuple[Optional[str], list[str], list[str], bool, bool]:
    """Skip git's own global options ahead of the subcommand. Returns (subcommand or None if the
    invocation never reaches one, that subcommand's own remaining args, every `-C` value in the
    order it appeared, whether `--git-dir`/`--work-tree` appeared in any form, whether a
    `-c alias.<name>=<value>` global option defines a custom alias)."""
    index = 0
    dash_c_dirs: list[str] = []
    has_dir_override = False
    alias_defined = False
    while index < len(args):
        arg = args[index]
        if not arg.startswith("-"):
            break
        if arg == "-C" and index + 1 < len(args):
            dash_c_dirs.append(args[index + 1])
            index += 2
            continue
        if arg == "-c" and index + 1 < len(args):
            if args[index + 1].lower().startswith("alias."):
                alias_defined = True
            index += 2
            continue
        if arg.startswith("-c") and not arg.startswith("--") and "=" in arg:
            if arg[2:].lower().startswith("alias."):
                alias_defined = True
            index += 1
            continue
        if arg in ("--git-dir", "--work-tree"):
            has_dir_override = True
            index += 2 if index + 1 < len(args) else 1
            continue
        if arg.startswith("--git-dir=") or arg.startswith("--work-tree="):
            has_dir_override = True
            index += 1
            continue
        if arg in _GIT_GLOBAL_VALUE_FLAGS:
            index += 2
            continue
        index += 1
    if index >= len(args):
        return None, [], dash_c_dirs, has_dir_override, alias_defined
    return args[index], args[index + 1:], dash_c_dirs, has_dir_override, alias_defined


def _stash_reads_only(sub_args: list[str]) -> bool:
    """True for `git stash list` / `git stash show`: the first argument is exactly that word (a bare `stash`,
    `-p`, `push`, `pop`, `drop` … is a write) and every later word is plain: none starts with `--ou` (an
    abbreviation of the log/diff option `--output`, which writes its result to a file) and none holds a character
    the shell or PowerShell expands or unquotes (`$`, a backtick, `\\`, `'`, `"`), which could build that option."""
    if not sub_args or sub_args[0] not in ("list", "show"):
        return False
    return not any(a.startswith("--ou") or any(c in a for c in "$`\\'\"") for a in sub_args[1:])


def _is_git_write_subcommand(subcommand: str, args: list[str]) -> bool:
    if subcommand == "stash":
        return not _stash_reads_only(args)
    return subcommand in _GIT_WRITE_SUBCOMMANDS or (subcommand == "branch" and not _branch_lists_only(args))


def _prefix_has_dir_override(prefix: list[str]) -> bool:
    """True if a GIT_DIR=/GIT_WORK_TREE= assignment precedes `git` in the same simple command —
    directly, or as an `env VAR=... git ...` wrapper's own argument (both land in `prefix`
    unstripped, see `Parse.git_invocations_with_prefix`)."""
    return any(w.startswith("GIT_DIR=") or w.startswith("GIT_WORK_TREE=") for w in prefix)


def _resolve_dir(raw: str, base: str) -> Optional[Path]:
    """A literal directory argument resolved to an absolute Path, or None if it is dynamic
    ($VAR, `` `...` ``, $(...), a leading ~) or fails to resolve at all — either way the caller
    must treat it as "not known to be outside the project" (see this module's Known limits)."""
    if _is_dynamic_target(raw):
        return None
    native = _to_native_path(raw)
    try:
        path = Path(native)
        if not path.is_absolute():
            path = Path(_to_native_path(base)) / native
        return path.resolve()
    except (OSError, ValueError):
        return None


def _is_outside_root(path: Optional[Path], root: Path) -> bool:
    if path is None:
        return False  # unresolved -- never grants the exemption
    try:
        path.relative_to(root.resolve())
        return False
    except ValueError:
        return True


def _resolve_dash_c_chain(dash_c_dirs: list[str], base_cwd: str) -> Optional[Path]:
    """Every `-C` value applied in order against the running directory, starting at `base_cwd`
    (`git -C .git -C .. commit` ends up back at `base_cwd` itself) — None as soon as any step is
    unresolvable (dynamic, or fails to resolve), same "unknown, never grants the exemption" rule
    _resolve_dir itself follows."""
    current = base_cwd
    for raw in dash_c_dirs:
        resolved = _resolve_dir(raw, current)
        if resolved is None:
            return None
        current = str(resolved)
    return Path(current)


def _first_operand(args: list[str]) -> Optional[str]:
    for arg in args:
        if not arg.startswith("-"):
            return arg
    return None


def _group_closes_before_end(parse: Parse) -> bool:
    """True when the command's first word stands inside `( ... )` and a word follows the `)` that closes its
    innermost group (or that group never closes, or the command does not tokenize but holds a `(`): a `cd` there
    changes the directory of that subshell only, so the commands after the group run elsewhere and one directory
    for the whole command is not determinable. False for a command whose first word is not inside a group, and
    for one whose every command is inside it (`(cd x && git commit -m y)`)."""
    if parse.tool_name == "PowerShell" or "(" not in parse.command:
        return False  # PowerShell has no subshell (`(cd x); git commit` keeps the location); no group: no tokens needed
    tokens = parse.chain_tokens()
    if tokens is None:
        return True
    depth = 0
    start = 0
    for start, (text, is_op) in enumerate(tokens):
        if not is_op:
            break
        depth += text == "("
    if depth == 0:
        return False
    level, closed = depth, False
    for text, is_op in tokens[start:]:
        if is_op:
            level += (text == "(") - (text == ")")
            closed = closed or level < depth
        elif closed:
            return True
    return not closed


def _leading_cd_directory(
    commands: list[list[str]], base_cwd: str, parse: Optional[Parse] = None,
) -> tuple[bool, Optional[Path]]:
    """How a leading `cd` decides the directory a command runs in, read from `commands` (the
    prefix-stripped argv of every simple command, in order) -- (determinable, directory).
    (True, None): no leading cd (nothing, or a first command that is not cd-like) and no later one.
    (True, path): the first simple command is `cd`-like (_CD_LIKE_NAMES) with a literal operand
    resolving to `path` (against `base_cwd`) and no later simple command changes directory again
    (_CD_LIKE_NAMES or _CD_UNKNOWN_NAMES). (False, None): not determinable -- a later directory
    change anywhere, a leading cd without an operand or with a dynamic or unresolvable one, and (when `parse`
    is given) a leading cd inside `( ... )` while other commands follow the group: `(cd x) && git commit`
    runs the commit where the shell was, not in `x` (_group_closes_before_end). Each
    caller maps these three answers to its own verdict: git_discard.py refuses on not determinable,
    this module's exemption is simply not granted."""
    for later in commands[1:]:
        # A directory-change form anywhere after the first command already makes the directory
        # impossible to pin down: `true && cd ../other && git reset --hard` is exactly as unknown as
        # a leading `cd` followed by a second one.
        if _command_name(later[0]) in _CD_LIKE_NAMES | _CD_UNKNOWN_NAMES:
            return False, None
    if not commands or _command_name(commands[0][0]) not in _CD_LIKE_NAMES:
        return True, None
    if parse is not None and _group_closes_before_end(parse):
        return False, None
    directory = _first_operand(commands[0][1:])
    resolved = None if directory is None else _resolve_dir(directory, base_cwd)
    if resolved is None:
        return False, None
    return True, resolved


def _leading_cd_outside_project(
    command: str, base_cwd: Optional[str], root: Optional[Path], parse: Optional[Parse] = None,
) -> bool:
    """True only when the whole command's very first simple command is a `cd`-family invocation
    (_CD_LIKE_NAMES) with a literal directory operand resolving outside `root`, AND no later
    simple command changes directory again (_CD_LIKE_NAMES or _CD_UNKNOWN_NAMES) -- see this
    module's Known limits for why a second directory change anywhere disables the exemption
    entirely rather than tracking which git call comes after which cd. `parse` is the dispatcher's
    reading of `command`; without it the command is read here."""
    if base_cwd is None or root is None:
        return False
    if parse is None:
        parse = Parse("Bash", command)
    determinable, directory = _leading_cd_directory(parse.stripped(), base_cwd, parse)
    return determinable and directory is not None and _is_outside_root(directory, root)


def _worker_git_write_message(subcommand: str) -> str:
    return (
        f"[act] git is read-only for workers (status/diff/log/show, ...) — git {subcommand} "
        "changes the tree or history (R-role-worker)"
    )


def check_worker_git_write(payload: dict) -> int:
    """Check: deny a worker running a git subcommand that changes the tree or history
    (R-role-worker), unless that git call is demonstrably against a directory outside the project
    (see this module's header comment). The orchestrator's own calls are never checked here."""
    config = actlib.read_config()
    mode = _check_mode(config, "worker-git-write", default="block")
    if mode == "off" or not _is_worker(payload):
        return 0

    shell = _shell_command(payload)
    if shell is None:
        return 0
    _, command = shell

    try:
        root: Optional[Path] = actlib.repo_root()
    except RuntimeError:
        root = None

    cwd_raw = payload.get("cwd")
    base_cwd = cwd_raw if isinstance(cwd_raw, str) and cwd_raw else None
    parse = parse_for(payload, command)
    leading_cd_outside = _leading_cd_outside_project(command, base_cwd, root, parse)

    invocations = parse.git_invocations_with_prefix()
    if parse.tool_name == "PowerShell":
        invocations += parse.assigned_git_invocations()  # `$r = git commit -m x`: the Bash reader sees `$r`
    for prefix, args in invocations:
        subcommand, sub_args, dash_c_dirs, has_dir_override, alias_defined = _parse_git_invocation(args)
        if subcommand is None:
            continue
        if not (alias_defined or _is_git_write_subcommand(subcommand, sub_args)):
            continue

        never_exempt = has_dir_override or _prefix_has_dir_override(prefix)
        if not never_exempt:
            if leading_cd_outside:
                continue
            if root is not None and base_cwd is not None and dash_c_dirs:
                chain = _resolve_dash_c_chain(dash_c_dirs, base_cwd)
                if _is_outside_root(chain, root):
                    continue

        message = _worker_git_write_message(subcommand)
        if mode == "warn":
            print(message)
            return 0
        print(message, file=sys.stderr)
        return 2
    return 0
