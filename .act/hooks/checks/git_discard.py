#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check — git commands that throw away work without an undo, other than `git reset --hard`
#          (PreToolUse): a guardrail next to `R-safe-git-reset` (checks/git_reset_hard.py, which keeps
#          `reset --hard` for itself). The matching rule text (`R-safe-git-discard`) is authored
#          elsewhere; this module only enforces it. Applies to **everyone**, orchestrator included.
#
#          What is refused:
#            - `git clean -f...` (not `-n`) when `git clean -n` with the same switches and operands
#              would delete something;
#            - `git checkout -- <folder>`, `git checkout .`, `git restore <folder>` (working tree) when
#              tracked changes lie below that folder, and `git checkout -f` / `git switch -f` /
#              `--discard-changes` when the tree has tracked changes. A single file stays free; the
#              file/folder decision is made on the file system of the target directory, and a glob or
#              a path that does not exist counts as a folder;
#            - `git stash drop`, `git stash clear` always;
#            - a forced push (`-f`, `--force`, `--force-with-lease`, `+refspec`, `--mirror`) whose
#              target is the default branch;
#            - `git branch -D` (and `-d -f`) of a branch that `git branch --no-merged` lists.
#
#          The default branch is read from `git symbolic-ref refs/remotes/origin/HEAD`, else
#          `init.defaultBranch`, else both `main` and `master`.
#
#          Command decomposition, alias handling and target-directory resolution are shared with
#          checks/git_reset_hard.py (`_alias_definitions`, `_alias_expansion`,
#          `_resolve_cwd_after_leading_cd`, `_resolve_target_dir`, `_has_find_execdir`) — see that
#          module's header for how `cd`, `-C`, `--git-dir`, `env -C` and `find -execdir` are treated:
#          a directory that cannot be pinned down is refused, never assumed clean.
#
#          All git calls made here share one time budget well under the hook timeout; a call that
#          fails or runs out of budget counts as "unknown" and is refused (deny by default).
#
# Known limits:
#   - an alias that lives in a git config file (not defined inline with `-c alias.x=...`) is
#     invisible here, as in checks/git_reset_hard.py.
#   - a push without a refspec is judged by the current branch, `push.default=matching` and any
#     configured `remote.<name>.push`; other ways config can redirect a push are not followed.
#   - `git clean` without `-f` is not examined (git itself refuses unless `clean.requireForce` is
#     off); other destructive commands (`update-ref -d`, `worktree remove -f`, `reflog expire`,
#     `tag -d`, `gc --prune`) are out of scope.
#   - a checkout operand that is neither `.`, a glob nor an existing folder is read as a branch or
#     revision when no `--` separates it from the options.

from __future__ import annotations

import fnmatch
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

import actlib

from .command_words import _git_invocations_with_prefix
from .common import _check_mode, _shell_command
from .git_reset_hard import (
    _alias_definitions,
    _alias_expansion,
    _has_find_execdir,
    _resolve_cwd_after_leading_cd,
    _resolve_target_dir,
)
from .shell_targets import _to_native_path
from .worker_git_write import _parse_git_invocation

__all__ = ["check_git_discard"]

_TIME_BUDGET = 7.0  # seconds for every git call of one hook run together (the hook timeout is 10)
_CALL_LIMIT = 4.0   # seconds for a single git call
_HOOK_BUDGET = 7.5  # seconds after dispatch.py's own start (payload["_act_hook_started"]) at the latest

_RULE = "R-safe-git-discard"
_UNKNOWN_DIR_MESSAGE = (
    "[act] git {what} refused -- could not determine (or read the state of) the repository it "
    f"targets ({_RULE}): check with git status / git branch --no-merged first"
)
_ALIAS_MESSAGE = (
    "[act] git alias refused -- a git alias defined inline can hide a command that discards work "
    f"({_RULE}): run the expanded command directly"
)
_REFUSED = "[act] git {what} refused -- {why} ({rule}): {hint}"


class _Unknown(Exception):
    """Raised when a fact the verdict depends on cannot be established."""


class _Budget:
    """The shared time budget of one hook run; every git call draws from it."""

    def __init__(self, hook_started: Optional[float] = None) -> None:
        deadline = time.monotonic() + _TIME_BUDGET
        if isinstance(hook_started, (int, float)) and not isinstance(hook_started, bool):
            deadline = min(deadline, float(hook_started) + _HOOK_BUDGET)
        self._deadline = deadline

    def expired(self) -> bool:
        return time.monotonic() >= self._deadline

    def run(self, args: list[str], cwd: Path) -> subprocess.CompletedProcess:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0.2:
            raise _Unknown("time budget used up")
        try:
            return subprocess.run(
                ["git", *args], cwd=str(cwd), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=min(_CALL_LIMIT, remaining),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise _Unknown(f"git {args[0]} could not run: {error}") from error

    def out(self, args: list[str], cwd: Path) -> str:
        """stdout of a git call that must succeed."""
        result = self.run(args, cwd)
        if result.returncode != 0 or result.stdout is None:
            raise _Unknown(f"git {args[0]} failed with exit code {result.returncode}")
        return result.stdout

    def soft(self, args: list[str], cwd: Path) -> str:
        """stdout of a git call that may legitimately fail (an unset config key): "" then."""
        result = self.run(args, cwd)
        if result.stdout is None:
            raise _Unknown(f"git {args[0]} gave no readable output")
        return result.stdout if result.returncode == 0 else ""


# ---------------------------------------------------------------------------------------------
# option helpers


def _long_is(arg: str, name: str, min_len: int) -> bool:
    """True if `arg` is `--<name>` or an abbreviation of it of at least `min_len` characters
    (git resolves an unambiguous option prefix), with or without `=value`."""
    if not arg.startswith("--"):
        return False
    head = arg.split("=", 1)[0]
    return len(head) >= min_len and f"--{name}".startswith(head)


def _letters(arg: str, value_letters: str = "") -> set[str]:
    """The option letters of a short-option cluster (`-fdx`); empty for a long option or a plain
    word. The cluster ends at a letter that takes a value (its rest is that value)."""
    if not arg.startswith("-") or arg.startswith("--") or len(arg) < 2:
        return set()
    found: set[str] = set()
    for letter in arg[1:]:
        found.add(letter)
        if letter in value_letters:
            break
    return found


def _has_letter(args: list[str], letter: str, value_letters: str = "") -> bool:
    for arg in args:
        if arg == "--":
            break
        if letter in _letters(arg, value_letters):
            return True
    return False


# ---------------------------------------------------------------------------------------------
# per-command verdicts; each returns a reason text for a refusal, or None for "free"


def _clean_verdict(sub_args: list[str], target: Path, budget: _Budget, force_by_config: bool) -> Optional[str]:
    """`force_by_config`: `clean.requireForce` is switched off for this call, so no `-f` is needed."""
    force = force_by_config
    dry = False
    probe: list[str] = []
    skip_value = False
    for arg in sub_args:
        if skip_value:
            skip_value = False
            probe.append(arg)
            continue
        if arg == "--":
            probe.append(arg)
            continue
        if arg in ("-e", "--exclude"):
            skip_value = True
            probe.append(arg)
            continue
        if arg.startswith("-") and not arg.startswith("--"):
            letters = _letters(arg, "e")
            force = force or "f" in letters
            dry = dry or "n" in letters
            if "e" in letters:  # the rest of the word (or the next one) is a pattern: keep it as is
                skip_value = arg.endswith("e")
                probe.append(arg)
                continue
            kept = "".join(ch for ch in arg[1:] if ch != "q")
            if kept:
                probe.append("-" + kept)
            continue
        if arg.startswith("--"):
            if _long_is(arg, "force", 4):
                force = True
            elif _long_is(arg, "dry-run", 4):
                dry = True
            elif _long_is(arg, "quiet", 4):
                continue
        probe.append(arg)
    if not force or dry:
        return None
    probe = [a for a in probe if a not in ("-i", "--interactive")]
    listing = budget.out(["clean", "-n", *probe], target).strip()
    if not listing:
        return None
    lines = listing.splitlines()
    return f"it would delete {len(lines)} untracked path(s), e.g. `{lines[0]}`"


def _is_folder(raw: str, base: Path) -> bool:
    """A path given to checkout/restore is a folder unless it names an existing file; a glob, a
    pathspec with magic, `.` or a path that does not exist counts as a folder."""
    if not raw or raw.startswith(":") or any(ch in raw for ch in "*?["):
        return True
    path = Path(_to_native_path(raw))
    if not path.is_absolute():
        path = base / path
    try:
        return not path.is_file()
    except OSError:
        return True


def _tracked_changes(paths: list[str], target: Path, budget: _Budget) -> str:
    args = ["status", "--porcelain", "--untracked-files=no"]
    if paths:
        args += ["--", *paths]
    return budget.out(args, target).strip()


def _checkout_verdict(sub_args: list[str], target: Path, budget: _Budget) -> Optional[str]:
    value_letters = "bB"
    before = sub_args[: sub_args.index("--")] if "--" in sub_args else sub_args
    after = sub_args[sub_args.index("--") + 1:] if "--" in sub_args else []
    if any(a == "--patch" for a in before) or _has_letter(before, "p", value_letters):
        return None  # interactive hunk selection
    if any(_long_is(a, "force", 4) for a in before) or _has_letter(before, "f", value_letters):
        if _tracked_changes([], target, budget):
            return "the working tree has uncommitted changes that -f would throw away"
        return None
    paths = list(after)
    if any(a.startswith("--pathspec-from-file") for a in before):
        paths.append(".")
    if "--" not in sub_args:
        creates = _has_letter(before, "b", value_letters) or _has_letter(before, "B", value_letters) \
            or any(_long_is(a, "orphan", 4) for a in before)
        if not creates:
            skip_next = False
            for arg in before:
                if skip_next:
                    skip_next = False
                    continue
                if arg in ("--conflict", "--pathspec-from-file"):
                    skip_next = True
                    continue
                if arg.startswith("-"):
                    continue
                if (arg == "." or arg.startswith(":") or any(ch in arg for ch in "*?[")
                        or _is_existing_dir(arg, target)):
                    paths.append(arg)
    folders = [p for p in paths if _is_folder(p, target)]
    if not folders:
        return None
    if _tracked_changes(folders, target, budget):
        return "tracked changes lie below " + ", ".join(f"`{p}`" for p in folders)
    return None


def _is_existing_dir(raw: str, base: Path) -> bool:
    path = Path(_to_native_path(raw))
    if not path.is_absolute():
        path = base / path
    try:
        return path.is_dir()
    except OSError:
        return False


def _restore_verdict(sub_args: list[str], target: Path, budget: _Budget) -> Optional[str]:
    value_letters = "s"
    before = sub_args[: sub_args.index("--")] if "--" in sub_args else sub_args
    after = sub_args[sub_args.index("--") + 1:] if "--" in sub_args else []
    if any(a == "--patch" for a in before) or _has_letter(before, "p", value_letters):
        return None  # interactive hunk selection
    staged = any(_long_is(a, "staged", 4) for a in before) or _has_letter(before, "S", value_letters)
    worktree = any(_long_is(a, "worktree", 4) for a in before) or _has_letter(before, "W", value_letters)
    if staged and not worktree:
        return None  # index only; the working tree is not touched
    paths = list(after)
    skip_next = False
    for arg in before:
        if skip_next:
            skip_next = False
            continue
        if arg == "--pathspec-from-file":
            skip_next = True
            paths.append(".")
            continue
        if arg in ("--source", "-s"):
            skip_next = True
            continue
        if arg.startswith("--pathspec-from-file"):
            paths.append(".")
            continue
        if arg.startswith("-"):
            continue
        paths.append(arg)
    folders = [p for p in paths if _is_folder(p, target)]
    if not folders:
        return None
    if _tracked_changes(folders, target, budget):
        return "tracked changes lie below " + ", ".join(f"`{p}`" for p in folders)
    return None


def _switch_verdict(sub_args: list[str], target: Path, budget: _Budget) -> Optional[str]:
    head = sub_args[: sub_args.index("--")] if "--" in sub_args else sub_args
    forced = (
        any(_long_is(a, "force", 4) or _long_is(a, "discard-changes", 6) for a in head)
        or _has_letter(head, "f", "cC")
    )
    if not forced:
        return None
    if _tracked_changes([], target, budget):
        return "the working tree has uncommitted changes that the switch would throw away"
    return None


def _default_branches(target: Path, budget: _Budget) -> list[str]:
    ref = budget.soft(["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], target).strip()
    if ref.startswith("refs/remotes/origin/"):
        return [ref[len("refs/remotes/origin/"):]]
    configured = budget.soft(["config", "--get", "init.defaultBranch"], target).strip()
    if configured:
        return [configured]
    return ["main", "master"]


def _current_branch(target: Path, budget: _Budget) -> Optional[str]:
    name = budget.soft(["symbolic-ref", "--quiet", "--short", "HEAD"], target).strip()
    return name or None


def _push_verdict(
    sub_args: list[str], target: Path, budget: _Budget, config_words: Optional[list[str]] = None,
) -> Optional[str]:
    """`config_words`: git's global options and the words ahead of `git`, searched for an inline
    `push.default=...`."""
    value_names = ("repo", "receive-pack", "exec", "push-option")
    force = False
    delete = False
    everything = False
    mirror = False
    repo_given = False
    operands: list[str] = []
    index = 0
    after_dashes = False
    while index < len(sub_args):
        arg = sub_args[index]
        index += 1
        if after_dashes or not arg.startswith("-"):
            operands.append(arg)
            continue
        if arg == "--":
            after_dashes = True
            continue
        letters = _letters(arg, "o")
        if _long_is(arg, "dry-run", 4) or "n" in letters:
            return None  # nothing is sent
        if _long_is(arg, "repo", 6):
            repo_given = True
        if _long_is(arg, "mirror", 4):
            mirror = True
        elif _long_is(arg, "all", 5) or _long_is(arg, "branches", 5):
            everything = True
        elif _long_is(arg, "delete", 5) or "d" in letters:
            delete = True
        elif _long_is(arg, "force", 4) or _long_is(arg, "force-with-lease", 8) or "f" in letters:
            force = True
        takes_value = "=" not in arg and (
            (arg.startswith("--") and len(arg) >= 5 and any(f"--{n}".startswith(arg) for n in value_names))
            or ("o" in letters and arg.endswith("o"))
        )
        if takes_value:
            index += 1

    refspecs = operands if repo_given else operands[1:]
    deleting = delete or any(spec.startswith(":") for spec in refspecs)
    forced_specs = [spec for spec in refspecs if spec.startswith("+")]
    if not force and not forced_specs and not mirror and not deleting:
        return None
    defaults = _default_branches(target, budget)
    if mirror:
        return "--mirror overwrites every remote ref, the default branch included"
    if everything and force:
        return "a forced push of all branches includes the default branch"

    verb = "deletes" if deleting and not force and not forced_specs else "overwrites"
    targets: list[str] = []
    if refspecs:
        for spec in refspecs:
            if not (force or delete or spec.startswith("+") or spec.startswith(":")):
                continue
            body = spec.lstrip("+")
            src, colon, dst = body.partition(":")
            name = dst if colon and dst else (body if delete else src)
            if name in ("", "HEAD", "@"):
                name = _current_branch(target, budget) or ""
                if not name:
                    raise _Unknown("current branch unknown")
            targets.append(name)
    else:
        branch = _current_branch(target, budget)
        if branch is None:
            raise _Unknown("current branch unknown")
        upstream_mode = False
        for word in config_words or []:
            lowered = word.lower()
            if "push.default=matching" in lowered:
                return "push.default=matching pushes every matching branch, the default branch included"
            if "push.default=upstream" in lowered or "push.default=tracking" in lowered:
                upstream_mode = True
        for line in budget.soft(
            ["config", "--get-regexp", r"^(push\.default|remote\..*\.push)$"], target
        ).splitlines():
            key, _, value = line.partition(" ")
            if key == "push.default" and value.strip() == "matching":
                return "push.default=matching pushes every matching branch, the default branch included"
            if key == "push.default" and value.strip() in ("upstream", "tracking"):
                upstream_mode = True
            if key.endswith(".push"):
                return f"`{key}` redirects what a push without refspec sends"
        if upstream_mode:
            merge = budget.soft(["config", "--get", f"branch.{branch}.merge"], target).strip()
            if not merge:
                raise _Unknown("upstream of the current branch unknown")
            targets.append(merge)
        else:
            targets.append(branch)

    for name in targets:
        if name.startswith("refs/") and not name.startswith("refs/heads/"):
            continue
        short = name[len("refs/heads/"):] if name.startswith("refs/heads/") else name
        if any(fnmatch.fnmatchcase(default, short) for default in defaults):
            return f"it {verb} the default branch ({' / '.join(defaults)}) on the remote"
    return None


def _branch_verdict(sub_args: list[str], target: Path, budget: _Budget) -> Optional[str]:
    head = sub_args[: sub_args.index("--")] if "--" in sub_args else sub_args
    delete = any(_long_is(a, "delete", 5) for a in head) or _has_letter(head, "d", "")
    force = any(_long_is(a, "force", 4) for a in head) or _has_letter(head, "f", "")
    move = any(_long_is(a, "move", 4) or _long_is(a, "copy", 4) for a in head) \
        or _has_letter(head, "m", "") or _has_letter(head, "c", "")
    force_delete = _has_letter(head, "D", "") or (delete and force)
    overwrite = _has_letter(head, "M", "") or _has_letter(head, "C", "") or (move and force)
    if not (force_delete or overwrite):
        return None
    remote = any(_long_is(a, "remotes", 4) for a in head) or _has_letter(head, "r", "")
    names = [a for a in sub_args if a != "--" and not a.startswith("-")]
    if not names:
        return None
    if overwrite and not force_delete:
        names = names[-1:]  # a move or copy overwrites only its destination
    listing_args = ["branch", "--format=%(refname:short)", "--no-merged", "HEAD"]
    if remote:
        listing_args.insert(1, "-r")
    fold = sys.platform in ("win32", "darwin")  # ref names are looked up without regard to case there
    unmerged = {name.lower() if fold else name for name in budget.out(listing_args, target).split()}
    blocked = [name for name in names if (name.lower() if fold else name) in unmerged]
    if blocked:
        return "not merged into HEAD: " + ", ".join(f"`{n}`" for n in blocked)
    return None


# what -> verdict function (clean takes one more argument, see _judge)
_VERDICTS: dict[str, Callable[..., Optional[str]]] = {
    "clean": _clean_verdict,
    "checkout": _checkout_verdict,
    "restore": _restore_verdict,
    "switch": _switch_verdict,
    "push": _push_verdict,
    "branch": _branch_verdict,
}

_HINTS = {
    "clean": "run `git clean -n` and review the list, move what you need away, or `git stash -u` first",
    "checkout": "commit or `git stash` the changes first, or name single files",
    "restore": "commit or `git stash` the changes first, or name single files",
    "switch": "commit or `git stash` the changes first",
    "push": "push to a feature branch, or ask the owner to force-push",
    "branch": "merge the branch first, or check `git log <branch>` and ask the owner",
    "stash": "apply it with `git stash pop`/`apply` or commit it first, or ask the owner",
}


def _stash_verdict(sub_args: list[str]) -> Optional[tuple[str, str]]:
    """(what, why) for `stash drop`/`stash clear`, else None."""
    action = next((a for a in sub_args if not a.startswith("-")), None)
    if action == "drop":
        return "stash drop", "it deletes a stash entry for good"
    if action == "clear":
        return "stash clear", "it deletes every stash entry for good"
    return None


_TIMEOUT_MESSAGE = (
    "[act] git refused -- ran out of time before every git command in this call could be checked "
    f"({_RULE}): split the command into smaller calls"
)
_ERROR_MESSAGE = (
    "[act] git refused -- the check itself failed ({error}) "
    f"({_RULE}): run the git commands one at a time"
)


def check_git_discard(payload: dict) -> int:
    """Check: deny a git command that discards work without an undo (see this module's header),
    for every caller. `warn` prints the reason and lets the call through, `off` skips the check."""
    config = actlib.read_config()
    mode = _check_mode(config, "git-discard", default="block")
    if mode == "off":
        return 0

    shell = _shell_command(payload)
    if shell is None:
        return 0
    _, command = shell

    try:
        message = _first_refusal(payload, command)
    except Exception as error:  # a check that fails must not let the command through
        message = _ERROR_MESSAGE.format(error=f"{type(error).__name__}: {error}"[:120])
    if message is None:
        return 0
    if mode == "warn":
        print(message)
        return 0
    print(message, file=sys.stderr)
    return 2


def _first_refusal(payload: dict, command: str) -> Optional[str]:
    """The message for the first git invocation in `command` that is refused, else None."""
    cwd_raw = payload.get("cwd")
    base_cwd = cwd_raw if isinstance(cwd_raw, str) and cwd_raw else None

    budget = _Budget(payload.get("_act_hook_started"))
    find_execdir = _has_find_execdir(command)
    cwd_cache: list[tuple[Optional[str], bool]] = []  # the same for every invocation of the command
    for prefix, args in _git_invocations_with_prefix(command):
        if budget.expired():
            return _TIMEOUT_MESSAGE
        subcommand, sub_args, dash_c_dirs, has_dir_override, _ = _parse_git_invocation(args)
        if subcommand is None:
            continue

        global_args = args[: len(args) - len(sub_args) - 1]
        definitions = _alias_definitions(global_args)
        expansion = _alias_expansion(definitions, subcommand, sub_args)
        if expansion is None:
            return _ALIAS_MESSAGE
        subcommand, sub_args = expansion[0], expansion[1:]
        if subcommand != "stash" and subcommand not in _VERDICTS:
            continue
        if subcommand != "stash" and not cwd_cache:
            cwd_cache.append(_resolve_cwd_after_leading_cd(command, base_cwd))
        message = _judge(subcommand, sub_args, prefix, global_args, dash_c_dirs, has_dir_override,
                         cwd_cache[0] if cwd_cache else (None, True), find_execdir, budget)
        if message is not None:
            return message
    return None


def _config_switches_force_off(words: list[str]) -> bool:
    """True if one of `words` (git's global options, or the words ahead of `git`) sets
    `clean.requireForce` to anything but a plain true -- by `-c`, `--config-env` or GIT_CONFIG_*."""
    for word in words:
        lowered = word.lower()
        if "clean.requireforce" in lowered and not lowered.endswith(("=true", "=yes", "=on", "=1")):
            return True
    return False


def _judge(
    subcommand: str, sub_args: list[str], prefix: list[str], global_args: list[str],
    dash_c_dirs: list[str], has_dir_override: bool, resolved_cwd: tuple[Optional[str], bool],
    find_execdir: bool, budget: _Budget,
) -> Optional[str]:
    """The refusal message for one git invocation, or None if it is free."""
    what = subcommand
    if subcommand == "stash":
        verdict = _stash_verdict(sub_args)
        if verdict is None:
            return None
        return _REFUSED.format(what=verdict[0], why=verdict[1], rule=_RULE, hint=_HINTS["stash"])
    effective_cwd, determinable = resolved_cwd
    if not determinable or find_execdir:
        return _UNKNOWN_DIR_MESSAGE.format(what=what)
    target = _resolve_target_dir(prefix, dash_c_dirs, has_dir_override, effective_cwd)
    if target is None:
        return _UNKNOWN_DIR_MESSAGE.format(what=what)
    try:
        if subcommand == "clean":
            force_off = _config_switches_force_off(global_args + prefix)
            if not force_off:
                value = budget.soft(["config", "--bool", "--get", "clean.requireForce"], target).strip()
                force_off = value == "false"
            why = _clean_verdict(sub_args, target, budget, force_off)
        elif subcommand == "push":
            why = _push_verdict(sub_args, target, budget, global_args + prefix)
        else:
            why = _VERDICTS[subcommand](sub_args, target, budget)
    except _Unknown:
        return _UNKNOWN_DIR_MESSAGE.format(what=what)
    if why is None:
        return None
    return _REFUSED.format(what=what, why=why, rule=_RULE, hint=_HINTS[subcommand])
