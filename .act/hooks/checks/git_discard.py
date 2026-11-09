#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check -- git commands that throw work away without an undo (PreToolUse), for everyone,
#          orchestrator included: `git reset --hard` (config row `git-reset-hard`, `R-safe-git-reset`) and
#          the others (row `git-discard`, `R-safe-git-discard`). _TABLE below is the one place that says
#          which subcommand discards work, under which row and rule, and what decides it. Applies the
#          neighbour split in checks/worker_git_write.py: that one asks WHO runs a mutating git command
#          (workers only, with an outside-the-project exemption); this one asks WHAT is lost.
#
#          Refused:
#            - `reset --hard` (any abbreviation of `--hard`) while `git status --porcelain` shows anything,
#              untracked files included;
#            - `clean -f...` (not `-n`) when `git clean -n` with the same switches would delete something;
#            - `checkout -- <folder>`, `checkout .`, `restore <folder>` (working tree) with tracked changes
#              below that folder, and `checkout -f` / `switch -f` / `--discard-changes` with tracked changes
#              in the tree. A single file stays free; a glob or a path that does not exist counts as a
#              folder, except a missing path that git knows as exactly one tracked file;
#            - `stash drop`, `stash clear` always;
#            - a forced push (`-f`, `--force`, `--force-with-lease`, `+refspec`, `--mirror`) or a delete whose
#              target is the default branch (`origin/HEAD`, else `init.defaultBranch`, else main and master);
#            - `branch -D` (and `-d -f`, `-M`/`-C` over an existing branch) of a branch HEAD does not
#              contain (`git branch --no-merged HEAD` lists it); `@{-N}` is resolved first.
#
#          Free without looking at the repository (_FREE_FORMS, a positive pattern per word, everything
#          else is judged as before): a `branch` that only lists (`--show-current`, `--list`, `-a`, `-r`, `-v`,
#          `--contains X` ...) and a `reset` without `--hard`. status, log, diff, show and rev-parse are
#          not in the table at all.
#
#          Which tree is meant: a leading `cd` (_resolve_cwd_after_leading_cd), then the `-C` chain, else the
#          call's own `cwd`. A tree that cannot be pinned down -- no `cwd`, a dynamic `-C` or `cd` target,
#          a second directory change, `--git-dir`/`--work-tree`/`GIT_DIR=`, `env -C`, `find -execdir` -- is
#          refused, as is a git call that fails or runs out of the shared time budget (deny by default).
#          An inline alias is judged by what it expands to (the call's own arguments appended, nested
#          aliases followed); one that cannot be expanded (`!shell`, `--config-env`, a cycle) or that
#          expands to `reset`/`--hard` is refused outright.
#
# Known limits:
#   - an alias in a git config file (not defined inline with `-c alias.x=...`) is invisible here.
#   - a push without a refspec is judged by the current branch, `push.default` and `remote.<name>.push`;
#     other ways config can redirect a push are not followed.
#   - `clean` without `-f` is not examined (git refuses unless `clean.requireForce` is off); `update-ref -d`,
#     `worktree remove -f`, `reflog expire`, `tag -d`, `gc --prune` are out of scope.
#   - a checkout operand that is neither `.`, a glob nor an existing folder is read as a branch or revision
#     when no `--` separates it from the options.
#   - a heredoc body written into a file is data and not judged; one fed to a shell (`bash <<EOF`) or a command
#     word inside `bash -c '...'` is a script and judged like a command (checks/command_words.py).

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Iterator, Optional

import actlib

from .command_parse import Parse, parse_for
from .common import _check_mode, _shell_command
from .shell_targets import _command_name, _to_native_path
from .worker_git_write import (
    _branch_lists_only,
    _leading_cd_directory,
    _parse_git_invocation,
    _prefix_has_dir_override,
    _resolve_dash_c_chain,
)

__all__ = ["check_git_discard", "_resolve_cwd_after_leading_cd", "_resolve_target_dir"]

_TIME_BUDGET = 7.0  # seconds for every git call of one hook run together (the hook timeout is 10)
_CALL_LIMIT = _TIME_BUDGET  # seconds for a single git call: at most the whole budget (a clean large repo's `status`)
_LOOKUP_LIMIT = 2.0  # seconds for the one git call that looks up a missing path in the index
_HOOK_BUDGET = 7.5  # seconds after dispatch.py's own start (payload["_act_hook_started"]) at the latest

_RESET_ROW, _DISCARD_ROW = "git-reset-hard", "git-discard"
_RESET_RULE, _DISCARD_RULE = "R-safe-git-reset", "R-safe-git-discard"
_REFUSED = "[act] git {what} refused -- {why} ({rule}): {hint}"
_UNKNOWN_WHY = "could not determine (or read the state of) the repository it targets"
_UNKNOWN_HINT = "check with git status / git log -1 first"
_ALIAS_WHY = "a git alias defined inline can hide a command that discards work"
_ALIAS_HINT = "run the expanded command directly"


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

    def run(self, args: list[str], cwd: Path, limit: float = _CALL_LIMIT) -> subprocess.CompletedProcess:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0.2:
            raise _Unknown("time budget used up")
        try:
            return subprocess.run(
                ["git", *args], cwd=str(cwd), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=min(limit, remaining),
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
# tree and alias helpers

def _alias_definitions(global_args: list[str]) -> dict[str, Optional[str]]:
    """name (lowercased) -> replacement text for every alias the git global options in
    `global_args` (the words ahead of the subcommand, see `_parse_git_invocation`) define inline:
    `-c alias.<name>=<value>` in the split or joined (`-calias.x=...`) form, and
    `--config-env=alias.<name>=<VAR>` (or the split `--config-env alias.<name>=<VAR>`), whose value
    lives in an environment variable this check cannot read -- recorded as None, "unknown".
    Best-effort like the rest of this module's tokenizing (see "Known limits"): a `-c`-shaped word
    that is really some other global option's own argument could be picked up too -- that only
    ever adds a definition, never a silent allowance."""
    definitions: dict[str, Optional[str]] = {}
    index = 0
    while index < len(global_args):
        arg = global_args[index]
        candidate: Optional[str] = None
        from_environment = False
        if arg in ("-c", "--config-env") and index + 1 < len(global_args):
            candidate = global_args[index + 1]
            from_environment = arg == "--config-env"
            index += 1
        elif arg.startswith("--config-env="):
            candidate = arg[len("--config-env="):]
            from_environment = True
        elif arg.startswith("-c") and not arg.startswith("--") and "=" in arg:
            candidate = arg[2:]
        index += 1
        if candidate is None or not candidate.lower().startswith("alias."):
            continue
        name, sep, value = candidate[len("alias."):].partition("=")
        if sep and name:
            definitions[name.lower()] = None if from_environment else value
    return definitions


def _alias_expansion(
    definitions: dict[str, Optional[str]], subcommand: str, sub_args: list[str]
) -> Optional[list[str]]:
    """The words git actually runs for `git <subcommand> <sub_args>` once every inline alias in
    `definitions` is applied -- the alias's replacement text with the call's own arguments
    appended, nested aliases followed (git resolves an alias whose expansion names another alias)
    -- or None when that cannot be known here: an alias whose value is unknown (--config-env), a
    shell alias (`!...`, whose text git hands to a shell as-is), or an alias cycle. A subcommand
    that is no inline alias expands to itself plus its own arguments."""
    words = [subcommand] + sub_args
    seen: set[str] = set()
    while words and words[0].lower() in definitions:
        name = words[0].lower()
        value = definitions[name]
        if name in seen or value is None or value.startswith("!"):
            return None
        seen.add(name)
        words = value.split() + words[1:]
    return words


def _prefix_changes_directory(prefix: list[str]) -> bool:
    """True if a wrapper ahead of `git` in the same simple command (`prefix`: the unstripped words
    `Parse.git_invocations_with_prefix` hands back) runs it in a directory of its own
    choosing rather than the shell's current one -- `env -C <dir>`/`env --chdir[=]<dir> git ...`.
    Which directory is knowable in principle but not followed here (the same answer
    shell_targets.py gives for its write targets); the caller refuses the call as "not
    determinable"."""
    if not any(_command_name(word) == "env" for word in prefix):
        return False
    return any(word in ("-C", "--chdir") or word.startswith("--chdir=") for word in prefix)


def _has_find_execdir(command: str, parse: Optional[Parse] = None) -> bool:
    """True if any `find` in `command` carries `-execdir`/`-okdir`, which run their command inside
    whichever directory find happens to match -- one this check cannot pin down. Judged for the
    whole command rather than the one exec tail (command_words.py hands that tail back as a simple
    command of its own, without saying where it came from), so a `reset --hard` anywhere in such a
    command is refused as "not determinable" -- over-refusing a `find -execdir` that has nothing to
    do with the git call is the accepted price. `parse` is the dispatcher's reading of `command`;
    without it the command is read here."""
    if parse is None:
        parse = Parse("Bash", command)
    return any(
        _command_name(words[0]) == "find" and any(arg in ("-execdir", "-okdir") for arg in words[1:])
        for words in parse.stripped()
    )


def _has_hard_flag(sub_args: list[str]) -> bool:
    """True for `--hard` or any abbreviation of it git itself accepts (`--ha`, `--har`, ...) --
    git resolves an unambiguous option prefix, confirmed at runtime; `--h`/`-h` alone stay
    ambiguous with `--help`/`-h` and are not counted as `--hard`."""
    for arg in sub_args:
        if arg == "--hard":
            return True
        if arg.startswith("--") and len(arg) >= 4 and "--hard".startswith(arg):
            return True
    return False


def _resolve_cwd_after_leading_cd(
    command: str, base_cwd: Optional[str], parse: Optional[Parse] = None, group_scoped: bool = False,
) -> tuple[Optional[str], bool]:
    """The effective cwd a `git reset --hard` invocation in `command` runs against, after a
    possible leading `cd`-family command -- (effective_cwd, determinable). No leading cd at all:
    (base_cwd, True), unchanged. A literal leading cd with a literal directory operand, and no
    later simple command changing directory again: (that resolved directory, True). Anything else
    a leading cd could mean (a dynamic operand, a later cd-like/`popd`-like command anywhere) is
    not determinable: (None, False) -- the caller then refuses the call outright rather than
    falling back to the unchanged `cwd`, since `cwd` is exactly what pinning down the leading cd
    was supposed to override. `parse` is the dispatcher's reading of `command`; without it the
    command is read here. With `group_scoped` (git-discard's own judgment of a `reset --hard`), a leading
    `cd` inside `( ... )` ends with the group (worker_git_write._group_closes_before_end); without it
    (git-metadata-guard's copy targets) the leading `cd` is read as applying to the whole line, which
    keeps that check at least as strict as before."""
    if base_cwd is None:
        return None, True
    if parse is None:
        parse = Parse("Bash", command)
    determinable, directory = _leading_cd_directory(parse.stripped(), base_cwd, parse if group_scoped else None)
    if not determinable:
        return None, False
    return (base_cwd if directory is None else str(directory)), True


def _resolve_target_dir(
    prefix: list[str], dash_c_dirs: list[str], has_dir_override: bool, base_cwd: Optional[str]
) -> Optional[Path]:
    """The working tree a `git reset --hard` invocation targets, or None if it cannot be pinned
    down (see this module's header). `--git-dir`/`--work-tree` (either form) name the tree
    independently of `-C`/`cwd`, and an `env -C <dir>` wrapper moves it somewhere this check does
    not follow, so their presence always means "unknown" here."""
    if has_dir_override or _prefix_has_dir_override(prefix) or _prefix_changes_directory(prefix):
        return None
    if dash_c_dirs:
        if base_cwd is None:
            return None
        return _resolve_dash_c_chain(dash_c_dirs, base_cwd)
    if base_cwd is None:
        return None
    try:
        return Path(_to_native_path(base_cwd))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------------------------
# per-command verdicts: a reason text for a refusal, or None for "free"


def _config_switches_force_off(words: list[str]) -> bool:
    """True if one of `words` (git's global options, or the words ahead of `git`) sets
    `clean.requireForce` to anything but a plain true -- by `-c`, `--config-env` or GIT_CONFIG_*."""
    return any("clean.requireforce" in w.lower() and not w.lower().endswith(("=true", "=yes", "=on", "=1"))
               for w in words)


def _clean_verdict(sub_args: list[str], target: Path, budget: _Budget, words: list[str]) -> Optional[str]:
    # with `clean.requireForce` switched off for this call no `-f` is needed
    force = _config_switches_force_off(words) or budget.soft(["config", "--bool", "--get", "clean.requireForce"], target).strip() == "false"
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


_FILE_MODES = ("100644", "100755", "120000")  # a regular file or a symlink; not a submodule (160000)


def _is_folder(raw: str, base: Path, budget: _Budget) -> bool:
    """A path given to checkout/restore is a folder unless it names an existing file; a glob, a
    pathspec with magic, `.` or a path that does not exist counts as a folder -- except a missing
    path that git knows as exactly one tracked file (see _is_deleted_tracked_file)."""
    if not raw or raw.startswith(":") or any(ch in raw for ch in "*?["):
        return True
    path = Path(_to_native_path(raw))
    if not path.is_absolute():
        path = base / path
    try:
        if path.is_file():
            return False
        if os.path.lexists(path):  # a folder, or anything else that is there: as before
            return True
    except OSError:
        return True
    return not _is_deleted_tracked_file(raw, path, base, budget)


def _is_deleted_tracked_file(raw: str, path: Path, base: Path, budget: _Budget) -> bool:
    """True only if `raw` (missing on disk) is, spelled exactly like that, the one tracked file in the
    index of the repository at `base`: `git ls-files --stage --error-unmatch` with case-insensitive
    pathspecs (the widest reading the command's own `--icase-pathspecs` or `GIT_ICASE_PATHSPECS` could
    give; globbing stays on, so a pattern word yields another name or several entries) answers with one stage-0 entry of a regular file or symlink whose path is the path itself. A
    folder (several entries, or one entry with a longer path), a pattern, an unknown or untracked
    path, a trailing slash, a submodule, an unmerged entry, a git failure or a used-up budget: False."""
    if raw.endswith(("/", "\\")) or any(ch in raw for ch in "\n\r\0"):
        return False
    try:
        wanted = path.relative_to(base).as_posix()
    except ValueError:
        return False  # outside the directory git runs in (or another drive): not judged here
    if not wanted or wanted == "." or wanted.startswith(("-", ":")):
        return False
    try:
        result = budget.run(
            ["--icase-pathspecs", "ls-files", "--stage", "--error-unmatch", "-z", "--", wanted],
            base, limit=_LOOKUP_LIMIT,
        )
    except _Unknown:
        return False
    if result.returncode != 0 or not isinstance(result.stdout, str):
        return False
    entries = [entry for entry in result.stdout.split("\0") if entry]
    if len(entries) != 1:
        return False
    meta, tab, name = entries[0].partition("\t")
    fields = meta.split(" ")
    return bool(tab) and name == wanted and len(fields) == 3 and fields[0] in _FILE_MODES and fields[2] == "0"


def _tracked_changes(paths: list[str], target: Path, budget: _Budget) -> str:
    args = ["status", "--porcelain", "--untracked-files=no"]
    if paths:
        args += ["--", *paths]
    return budget.out(args, target).strip()


def _checkout_verdict(sub_args: list[str], target: Path, budget: _Budget, words: list[str]) -> Optional[str]:
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
    folders = [p for p in paths if _is_folder(p, target, budget)]
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


def _restore_verdict(sub_args: list[str], target: Path, budget: _Budget, words: list[str]) -> Optional[str]:
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
    folders = [p for p in paths if _is_folder(p, target, budget)]
    if not folders:
        return None
    if _tracked_changes(folders, target, budget):
        return "tracked changes lie below " + ", ".join(f"`{p}`" for p in folders)
    return None


def _switch_verdict(sub_args: list[str], target: Path, budget: _Budget, words: list[str]) -> Optional[str]:
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
    sub_args: list[str], target: Path, budget: _Budget, config_words: list[str],
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
        for word in config_words:
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


_PREVIOUS_BRANCH_RE = re.compile(r"@\{-\d+\}")


def _resolve_previous(name: str, target: Path, budget: _Budget) -> str:
    """`@{-N}` (the branch checked out N switches ago) as the branch name it stands for; the listing
    of unmerged branches never holds the spelling `@{-N}`. Anything else, or a name git cannot place,
    is returned as it is."""
    if not _PREVIOUS_BRANCH_RE.fullmatch(name):
        return name
    full = budget.soft(["rev-parse", "--symbolic-full-name", name], target).strip()
    return full[len("refs/heads/"):] if full.startswith("refs/heads/") else name



def _branch_verdict(sub_args: list[str], target: Path, budget: _Budget, words: list[str]) -> Optional[str]:
    """`branch -D` / `-d -f` / `-M` / `-C` / `--move --force`: refused for a branch HEAD does not contain."""
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
    if overwrite and not force_delete:
        names = names[-1:]  # a move or copy overwrites only its destination
    if not remote:
        names = [_resolve_previous(name, target, budget) for name in names]
    # lstrip=2, not short: `short` prints `heads/x` when a tag `x` exists too, and the name would no longer match
    listing_args = ["branch", "--format=%(refname:lstrip=2)", "--no-merged", "HEAD"]
    if remote:
        listing_args.insert(1, "-r")
    fold = sys.platform in ("win32", "darwin")  # ref names are looked up without regard to case there
    unmerged = {name.lower() if fold else name for name in budget.out(listing_args, target).split()}
    blocked = [name for name in names if (name.lower() if fold else name) in unmerged]
    return ("not merged into HEAD: " + ", ".join(f"`{n}`" for n in blocked)) if blocked else None


def _reset_verdict(sub_args: list[str], target: Path, budget: _Budget, words: list[str]) -> Optional[str]:
    """Called for `reset --hard` only (_FREE_FORMS lets the rest through). Untracked files count: a
    `reset --hard <rev>` can overwrite them silently."""
    if budget.out(["status", "--porcelain"], target).strip():
        return "the working tree has uncommitted changes, including untracked files, which `reset --hard` would overwrite silently"
    return None


def _stash_verdict(sub_args: list[str], target: Path, budget: _Budget, words: list[str]) -> Optional[str]:
    action = next((a for a in sub_args if not a.startswith("-")), None)
    if action in ("drop", "clear"):
        return f"`stash {action}` deletes " + ("a stash entry" if action == "drop" else "every stash entry") + " for good"
    return None


# ---------------------------------------------------------------------------------------------
# forms that are free without looking at the repository (a positive pattern per word, anything else is
# judged as before); `branch` shares worker_git_write._branch_lists_only

_FREE_FORMS: dict[str, Callable[[list[str]], bool]] = {
    "branch": _branch_lists_only,
    "reset": lambda sub_args: not _has_hard_flag(sub_args),
}

# ---------------------------------------------------------------------------------------------
# the table: subcommand -> (label in the message, config row, rule, verdict, hint)

_Verdict = Callable[[list[str], Path, _Budget, list[str]], Optional[str]]
_TABLE: dict[str, tuple[str, str, str, _Verdict, str]] = {
    "reset": ("reset --hard", _RESET_ROW, _RESET_RULE, _reset_verdict,
              "run `git stash -u` or `git reset --soft` as its own call first; check `git log -1` / `git reflog` "
              "if you are unsure what you would lose"),
    "clean": ("clean", _DISCARD_ROW, _DISCARD_RULE, _clean_verdict,
              "run `git clean -n` and review the list, move what you need away, or `git stash -u` first"),
    "checkout": ("checkout", _DISCARD_ROW, _DISCARD_RULE, _checkout_verdict,
                 "commit or `git stash` the changes first, or name single files"),
    "restore": ("restore", _DISCARD_ROW, _DISCARD_RULE, _restore_verdict,
                "commit or `git stash` the changes first, or name single files"),
    "switch": ("switch", _DISCARD_ROW, _DISCARD_RULE, _switch_verdict, "commit or `git stash` the changes first"),
    "push": ("push", _DISCARD_ROW, _DISCARD_RULE, _push_verdict,
             "push to a feature branch, or ask the owner to force-push"),
    "branch": ("branch", _DISCARD_ROW, _DISCARD_RULE, _branch_verdict,
               "merge the branch first, or check `git log <branch>` and ask the owner"),
    "stash": ("stash", _DISCARD_ROW, _DISCARD_RULE, _stash_verdict,
              "apply it with `git stash pop`/`apply` or commit it first, or ask the owner"),
}

_TIMEOUT_MESSAGE = (
    "[act] git refused -- ran out of time before every git command in this call could be checked "
    f"({_DISCARD_RULE}): split the command into smaller calls"
)
_ERROR_MESSAGE = (
    "[act] git refused -- the check itself failed ({error}) "
    f"({_DISCARD_RULE}): run the git commands one at a time"
)


def check_git_discard(payload: dict) -> int:
    """Check: deny a git command that discards work without an undo (see this module's header), for every
    caller. Each row (`git-reset-hard`, `git-discard`) keeps its own mode: a refusal under a `block` row denies
    the call, one under a `warn` row is printed and the scan goes on (a later refusal under a `block` row still
    denies), a refusal under an `off` row is not made. A refusal that belongs to no row (an alias that cannot
    be expanded, a used-up time budget, a failed check) follows the stricter mode of the rows that are not off."""
    config = actlib.read_config()
    modes = {row: _check_mode(config, row, default="block") for row in (_RESET_ROW, _DISCARD_ROW)}
    if all(mode == "off" for mode in modes.values()):
        return 0
    shell = _shell_command(payload)
    if shell is None:
        return 0
    warnings: list[str] = []
    try:
        for row, message in _refusals(payload, shell[1], modes):
            if _mode_of(row, modes) == "block":
                print(message, file=sys.stderr)
                return 2
            warnings.append(message)
    except Exception as error:  # a check that fails must not let the command through
        message = _ERROR_MESSAGE.format(error=f"{type(error).__name__}: {error}"[:120])
        if _mode_of(None, modes) == "block":
            print(message, file=sys.stderr)
            return 2
        warnings.append(message)
    for message in warnings:
        print(message)
    return 0


def _mode_of(row: Optional[str], modes: dict[str, str]) -> str:
    """The mode that decides a refusal: its own row's, or for no row the stricter one that is not `off`."""
    if row:
        return modes[row]
    return "block" if "block" in modes.values() else "warn"


def _refusals(payload: dict, command: str, modes: dict[str, str]) -> Iterator[tuple[Optional[str], str]]:
    """(config row or None, message) for every git invocation in `command` that is refused, in order."""
    cwd_raw = payload.get("cwd")
    base_cwd = cwd_raw if isinstance(cwd_raw, str) and cwd_raw else None
    budget = _Budget(payload.get("_act_hook_started"))
    parse = parse_for(payload, command)
    find_execdir = _has_find_execdir(command, parse)
    resolved_cwd: list[tuple[Optional[str], bool]] = []  # the same for every invocation of the command
    for prefix, args in parse.git_invocations_with_prefix():
        if budget.expired():
            yield None, _TIMEOUT_MESSAGE
            return
        subcommand, sub_args, dash_c_dirs, has_dir_override, _ = _parse_git_invocation(args)
        if subcommand is None:
            continue
        global_args = args[: len(args) - len(sub_args) - 1]
        expansion = _alias_expansion(_alias_definitions(global_args), subcommand, sub_args)
        if expansion is None or (expansion != [subcommand, *sub_args] and ("reset" in expansion or _has_hard_flag(expansion))):
            row = _RESET_ROW if expansion is not None else None  # no row: it could be any command
            if row is not None and modes[row] == "off":
                continue
            rule = _RESET_RULE if row == _RESET_ROW else f"{_RESET_RULE}, {_DISCARD_RULE}"
            yield row, _REFUSED.format(what="alias", why=_ALIAS_WHY, rule=rule, hint=_ALIAS_HINT)
            continue
        subcommand, sub_args = expansion[0], expansion[1:]
        if subcommand not in _TABLE or _FREE_FORMS.get(subcommand, lambda _: False)(sub_args):
            continue
        label, row, rule, verdict, hint = _TABLE[subcommand]
        if modes[row] == "off":
            continue
        unknown = _REFUSED.format(what=label, why=_UNKNOWN_WHY, rule=rule, hint=_UNKNOWN_HINT)
        target = None
        if subcommand != "stash":  # a stash drop is refused wherever it runs
            if not resolved_cwd:
                resolved_cwd.append(_resolve_cwd_after_leading_cd(command, base_cwd, parse, group_scoped=True))
            effective_cwd, determinable = resolved_cwd[0]
            if determinable and not find_execdir:
                target = _resolve_target_dir(prefix, dash_c_dirs, has_dir_override, effective_cwd)
            if target is None:
                yield row, unknown
                continue
        try:
            why = verdict(sub_args, target, budget, global_args + prefix)
        except _Unknown:
            yield row, unknown
            continue
        if why is not None:
            yield row, _REFUSED.format(what=label, why=why, rule=rule, hint=hint)
