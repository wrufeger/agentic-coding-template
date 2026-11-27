#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check — a worker running a git command that changes the tree or history (PreToolUse,
#          R-role-worker): a worker only ever reads git (status, diff, log, show) — every subcommand
#          in _GIT_WRITE_SUBCOMMANDS is a write for this check's purposes, plus `branch` unless it only
#          lists (_branch_lists_only); `stash` is one too, except `stash list` / `stash show` with plain
#          words only (_stash_reads_only); so are `update-ref` (every form), `symbolic-ref` unless it only reads one
#          name (_symbolic_ref_reads_only), `tag` unless it only lists or verifies (_tag_lists_only) and `config`
#          when it writes (_config_writes; a write with `--global`, `--system` or `--file` is never exempt, see
#          _config_escapes_repo); `status`, `diff`, `log`, `show`, `rev-parse`, `ls-files` and
#          `blame` are never in the write set. Commands with a reading form beside a writing one are decided by
#          the helpers behind _READ_FORMS (`notes`, `replace`, `worktree`, `remote`, `reflog`, `prune`,
#          `hash-object`, `history`, `sparse-checkout`, `bisect`, `rerere`, `apply`, `submodule`, `lfs`): the reading
#          forms are named, every other form is a write; `fetch`, `clone`, `backfill`, `fetch-pack`, `send-pack`,
#          `submodule--helper`, `receive-pack`, `index-pack`, `unpack-objects` (also with `-n`) and `http-fetch` have
#          no reading form. Every program `git-<name>` (also `git-lfs`) is judged like `git <name>`, without global
#          options (_git_program_invocations), in PowerShell read the way PowerShell reads it (Parse.ps_calls: the
#          backslashes stay, `.\git-lfs.exe pull`, `& ..\bin\git-commit.exe`; behind an assignment or the dot
#          operator, inside a script block or a group, behind `cmd /c`); `update-git-for-windows` changes the Git installation, outside the project
#          and every repository, and is refused in every form, an exemption included. The deny-list
#          stays: a subcommand this check does not know is free (`upload-pack`, which only reads, is not in it).
#          Split from checks/git_discard.py: this one asks WHO runs a
#          mutating git command (workers only, outside the project exempt), that one WHAT is lost (anyone).
#
#          Command decomposition (finding every `git ...` invocation despite quoting, heredocs,
#          `bash -c`/`eval`/`$(...)`/backticks in a Bash call) is checks/command_words.py's
#          job, shared with checks/commit_pathspec.py and checks/recursive_delete.py; in a PowerShell
#          call the invocations come from PowerShell's own reader (Parse.ps_calls, command_parse.py,
#          powershell_targets.py: backslash kept, backtick, `.`/`&`, script block, group, `cmd /c`) — see that
#          module's own header for why the first version of this stage's segmenting (a bare
#          operator-character regex split) was wrong and got replaced (review, 2026-09-23).
#
#          Exempt: git run against a directory outside the project — a worker's own throwaway
#          repo for a probe or a test build (`git -C <tmp> commit`, `cd <tmp> && git init`). See
#          _leading_cd_run_directory and _parse_git_invocation's `-C` handling for exactly what
#          is recognized, and "Known limits" below for what is deliberately NOT — the exemption
#          only ever *widens* what is allowed, so anything ambiguous fails toward still checking
#          the call, never toward skipping it. A `-C` after a leading `cd` counts from that `cd` folder, inside the
#          project or outside it, and the exemption holds only when the result lies outside the project. The
#          exemption does not cover a `clone` or `init` whose target
#          folder (or `--separate-git-dir`), resolved against the `-C`/`cd` directory, lies inside the project or
#          cannot be resolved (_target_enters_project): the repository would be created in the project. The same holds
#          for the paths of `worktree add` (the first positional only, not the commit-ish), `move` and `remove`
#          (_worktree_targets). git takes the `<worktree>` word of `remove` and the first word of `move` also as
#          the last path components of ANY worktree of the repository (`ghi` for `/abc/def/ghi`), so there only a word
#          that cannot be read that way keeps the exemption: an absolute one, or one that starts with `./` or `../` (in a
#          PowerShell call also `.\` and `..\`, which that reading keeps; in a Bash call a backslash form is no anchor:
#          the shell reader consumes the backslash), and it must lie outside the project.
#          Every `worktree repair` from outside is refused, with or without a path: besides the paths named it repairs
#          the `.git` file of every linked worktree, wherever it lies, so one inside the project is written too.
#          A `-C` chain with an absolute value is decided from the last absolute one, whatever folder the call runs in
#          (_last_absolute_index); only the values after it count. Only literal values may stand before it: a variable
#          or a substitution there (`-C $D -C /abs`) takes the relaxation away, as before.
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
#     unpredictably, so they can disable the exemption but never grant it. In a PowerShell call these
#     are read from the PowerShell words (Parse.commands), so `Set-Location ..\proj` keeps its backslash.
#   - `git -c alias.<name>=<value> ...` is treated as a write outright, regardless of what
#     subcommand name follows: an alias can itself resolve to any git subcommand, including a
#     write one, and this check has no way to look up what the alias actually expands to.
#
# Known limits:
#   - a PowerShell call is read with PowerShell's own reader (Parse.ps_calls, powershell_targets.py), which
#     tokenizes quoting, backtick and `--%` as PowerShell does; a form that reader cannot tokenize falls
#     back to the Bash reader, and checks/command_words.py's approximation applies there (see its header).
#   - the outside-project exemption only recognizes a literal `-C <dir>` chain on the git
#     invocation itself, or a literal `cd <dir>`-family command as the *whole command's own first
#     simple command* with no later cd-like command anywhere after it
#     (_leading_cd_run_directory) — both shapes named in the assignment's own examples. A `cd` inside
#     `( ... )` counts only when every command of the line is inside that group (`(cd x && git commit)`);
#     `(cd x) && git commit` runs the commit where the shell was (_group_closes_before_end). A `cd`
#     buried deeper, inside a function, guarded by `if`, or naming a dynamic directory ($VAR,
#     `` `...` ``, `$(...)`, a leading `~`) never grants the exemption: the git call is then still
#     checked normally.
#   - a write made from inside a program (`python -c "...git..."`, a script file) is invisible,
#     same limit as shell_targets.py's own docstring states.
#   - an alias from the repository's or the user's git configuration is invisible: the check reads the words
#     typed, so `git zz` with `alias.zz = commit` in a config file passes (only a `-c alias.<name>=` typed on the
#     call itself is caught). A word is read as typed: a variable that expands to an option is not seen.
#   - when the folder a call runs in is not determinable (_leading_cd_unresolvable: a leading `cd` to a variable, a
#     substitution, a leading `~` or with no operand, a later `cd`, `Set-Location`, `Push-Location` or `Pop-Location`,
#     a group such as `(cd $X) && git ...`), the exemption does not hold for a call whose `-C` chain has no absolute
#     value: it may count from that folder. A `-C` chain with an absolute value (and only literal values before it)
#     does not depend on the folder: it counts from the last absolute one (_last_absolute_index). A `cd` inside the
#     text of `pwsh -c '...'` is read like a later `cd` (the inner commands are read into the same list,
#     _leading_cd_directory), so a `-C` chain without an absolute value behind it is refused.
#   - a directory change that is not determinable counts also BEHIND the git call (`git -C ../x commit -m y && cd src`
#     is refused): a loop can run the `cd` before the next git call, and this check knows no loops. A `-C` chain with
#     an absolute value (literal values before it) stays free.
#   - `/tmp/x` as a `-C` value is no absolute path on Windows (it names a folder of the current drive, not the system
#     temp), so behind a directory change that is not determinable it counts as relative and is refused; without one
#     it counts from the working folder and stays free. Throwaway material belongs under `.act-local/tmp/`.

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

import actlib

from .command_parse import Parse, parse_for
from .command_words import _strip_command_prefix
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
    "_leading_cd_directory", "_leading_cd_run_directory", "_leading_cd_outside_project",
    "_worker_git_write_message", "check_worker_git_write",
    "_git_program_invocations", "_target_enters_project", "_leading_cd_unresolvable", "_worktree_targets",
    "_last_absolute_index", "_is_anchored_path_word",
]

# Every git subcommand that changes the tree or history for this check's purposes. "init" is
# included beyond the assignment's own enumerated list: it creates a new history in whatever
# directory it targets, and the assignment's own worked example for the outside-project exemption
# ("cd <tmp> && git init") only exercises that exemption if `init` is itself a write here — inside
# the project it would otherwise reinitialize repository metadata, which is exactly the kind of
# change this check exists to keep a worker from doing unsupervised.
#
# The second row has no reading form at all (maintenance and history rewriting, plumbing that writes
# objects, the index or the working tree, the commands that fetch from, push to or clone a remote, `fetch-pack` and
# `send-pack` behind them and the internal `submodule--helper`: the orchestrator provides a remote's state; the plumbing
# that writes objects, an index file or a ref: `receive-pack`, `index-pack`, `unpack-objects` (also `-n`) and
# `http-fetch`; `upload-pack` only reads and is not here); `apply` is not here, it is read through _apply_reads_only.
_GIT_WRITE_SUBCOMMANDS = frozenset({
    "commit", "add", "stash", "checkout", "switch", "reset", "restore", "merge", "rebase",
    "clean", "push", "pull", "cherry-pick", "revert", "am", "rm", "mv", "init",
    "gc", "repack", "pack-refs", "maintenance", "filter-branch", "fast-import", "update-index", "read-tree",
    "write-tree", "commit-tree", "mktag", "mktree", "checkout-index",
    "fetch", "clone", "backfill", "fetch-pack", "send-pack", "submodule--helper",
    "receive-pack", "index-pack", "unpack-objects", "http-fetch",
    "update-git-for-windows",
})

# Subcommands refused in every form, a folder outside the project included: they change something no `-C` or `cd`
# can move out of the project. `update-git-for-windows` replaces the Git installation of the machine.
_NEVER_EXEMPT_SUBCOMMANDS = frozenset({"update-git-for-windows"})

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


_SYMBOLIC_REF_READ_FLAGS = frozenset({"-q", "--quiet", "--short", "--no-recurse"})
_TAG_LIST_FLAGS = frozenset({"-i", "--ignore-case", "--column", "--no-column", "--color", "--no-color"})
_TAG_LIST_VALUE_FLAGS = ("--contains", "--no-contains", "--points-at", "--merged", "--no-merged", "--sort", "--format")
_TAG_LISTING_VALUE_FLAGS = frozenset({"--contains", "--no-contains", "--points-at", "--merged", "--no-merged"})
_TAG_NUM_RE = re.compile(r"-n\d*")
_CONFIG_WRITE_FLAGS = ("--add", "--unset", "--unset-all", "--replace-all", "--rename-section", "--remove-section",
                       "--edit")
_CONFIG_READ_FLAGS = frozenset({"--get", "--get-all", "--get-regexp", "--get-urlmatch", "--get-color",
                                "--get-colorbool", "-l", "--list"})
_CONFIG_VALUE_FLAGS = frozenset({"--file", "-f", "--blob", "--type", "--default", "--comment"})
_CONFIG_NEW_READ = frozenset({"get", "list"})
_CONFIG_NEW_WRITE = frozenset({"set", "unset", "rename-section", "remove-section", "edit"})
_CONFIG_OUTSIDE_LONG = ("--global", "--system", "--file")  # an abbreviation of two characters or more counts


def _symbolic_ref_reads_only(sub_args: list[str]) -> bool:
    """True for `git symbolic-ref <name>` with only `-q`/`--quiet`/`--short`/`--no-recurse`: it reads where a ref
    points. Two names, `-d`/`--delete`, `-m` and any other word make it a write (an allow-list: an abbreviation of
    a long option is read as the write it might be)."""
    names = [arg for arg in sub_args if not arg.startswith("-")]
    return len(names) == 1 and all(arg in _SYMBOLIC_REF_READ_FLAGS for arg in sub_args if arg.startswith("-"))


def _tag_lists_only(sub_args: list[str]) -> bool:
    """True for a `tag` that only reads: no arguments, or only listing switches (with their values) and, as
    patterns, bare words only when listing is on: `-l`/`--list`, `-v`/`--verify`, `-n` (with or without a number)
    or a filter (`--contains`, `--no-contains`, `--points-at`, `--merged`, `--no-merged`) imply it. A write switch
    (`-d`, `-a`, `-s`, `-u`, `-f`, `-m`, `-F`, `-e`, `--create-reflog`, an abbreviation of a long one or any other
    word that starts with `-`) or a bare word without listing makes it a write: `git tag v1` creates a tag. A
    value never starts with `-`, except the key of `--sort` (`--sort -v:refname`), which always takes the next
    word."""
    listing, bare, index = False, 0, 0
    while index < len(sub_args):
        arg = sub_args[index]
        index += 1
        name, equals, _ = arg.partition("=")
        if arg in ("-l", "--list", "-v", "--verify") or _TAG_NUM_RE.fullmatch(arg):
            listing = True
        elif arg in _TAG_LIST_FLAGS or name in ("--column", "--color"):
            continue
        elif name in _TAG_LIST_VALUE_FLAGS:
            listing = listing or name in _TAG_LISTING_VALUE_FLAGS
            if not equals and index < len(sub_args) and (name == "--sort" or not sub_args[index].startswith("-")):
                index += 1
        elif arg.startswith("-"):
            return False
        else:
            bare += 1
    return bare == 0 or listing


def _config_scan(sub_args: list[str]) -> tuple[list[str], bool, bool, bool]:
    """Reads the words after `config`: (the words that are no switch and no switch's value, a reading switch seen,
    a write switch seen, a switch naming the user's or the machine's configuration or a file seen). A long switch
    counts as the write or the file switch it abbreviates (git takes an unambiguous prefix); a short switch may
    carry its value (`-f../p/x.cfg`) and may sit in a bundle (`-ze` is `-z -e`)."""
    positional: list[str] = []
    reading = writing = outside = False
    index = 0
    while index < len(sub_args):
        arg = sub_args[index]
        index += 1
        name = arg.partition("=")[0]
        if arg.startswith("--"):
            if len(name) > 2 and any(item.startswith(name) for item in _CONFIG_WRITE_FLAGS):
                writing = True
            if len(name) > 3 and any(item.startswith(name) for item in _CONFIG_OUTSIDE_LONG):
                outside = True
            if arg in _CONFIG_READ_FLAGS:
                reading = True
            elif arg in _CONFIG_VALUE_FLAGS:
                index += 1
        elif arg.startswith("-"):
            for position in range(1, len(arg)):
                char = arg[position]
                if char == "e":
                    writing = True
                elif char == "l":
                    reading = True
                elif char == "f":
                    outside = True
                    index += 1 if position + 1 == len(arg) else 0  # the value is the next word, or the rest of this one
                    break
        else:
            positional.append(arg)
    return positional, reading, writing, outside


def _config_writes(sub_args: list[str]) -> bool:
    """True for a `config` that writes: a write switch (`--add`, `--unset`, `--unset-all`, `--replace-all`,
    `--rename-section`, `--remove-section`, `-e`/`--edit`, also as an abbreviation of a long one or in a bundle of
    short ones), the new syntax `set`/`unset`/`rename-section`/`remove-section`/`edit`, or a key with a value (two or
    more words that are neither a switch nor the value of `--file`/`-f`, `--blob`, `--type`, `--default`,
    `--comment`) unless a reading switch (`--get*`, `-l`/`--list`) or the new syntax `get`/`list` is there. One key
    alone, `--get`, `--list` read."""
    positional, reading, writing, _outside = _config_scan(sub_args)
    if writing:
        return True
    if positional and positional[0] in _CONFIG_NEW_WRITE:
        return True
    if reading or (positional and positional[0] in _CONFIG_NEW_READ):
        return False
    return len(positional) >= 2


def _config_escapes_repo(sub_args: list[str]) -> bool:
    """True for a writing `config` that names the user's or the machine's configuration or a file of its own
    (`--global`, `--system`, `--file`, `-f`, also abbreviated or with an attached value): it never writes the
    repository a `-C`/`cd` target stands for, so that target does not make it a throwaway-repository call."""
    return _config_scan(sub_args)[3] and _config_writes(sub_args)


def _subcommand_after_options(args: list[str], value_flags: tuple[str, ...] = ()) -> tuple[Optional[str], list[str]]:
    """The first word that is no option, and the words after it (None and [] when every word is an option). A word
    that starts with `-` is skipped; a long one that is a prefix of one of `value_flags` (git takes an unambiguous
    abbreviation) and has no `=` takes the next word as its value, which is skipped with it."""
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if not arg.startswith("-"):
            return arg, args[index:]
        if "=" not in arg and len(arg) > 2 and any(flag.startswith(arg) for flag in value_flags):
            index += 1
    return None, []


_END_OF_OPTIONS = ("--", "--end-of-options")  # git reads every word after either as no option
_DRY_RUN_FLAGS = frozenset({"-n", "--dry-run"})
_DRY_RUN_VALUE_FLAG = "--expire-unreachable"  # `--expire <time>` and `--expire-unreachable <time>` take the next word


def _is_dry_run(args: list[str]) -> bool:
    """True when a word is exactly `-n` or `--dry-run` (and is no option's value) and no word starts with `--no-`
    (parse-options makes `--no-dry-run` from it). An abbreviation such as `--dry` or a bundle such as `-nv` is read
    as the write it might be. The words after a `--` or `--end-of-options` are no options. `--expire`/
    `--expire-unreachable` (also abbreviated) take the next word as their value, so `--expire -n` stays a write."""
    if any(arg.startswith("--no-") for arg in args):
        return False
    dry, index = False, 0
    while index < len(args):
        arg = args[index]
        index += 1
        if arg in _END_OF_OPTIONS:
            break
        if arg in _DRY_RUN_FLAGS:
            dry = True
        elif "=" not in arg and arg.startswith("--") and len(arg) > 2 and _DRY_RUN_VALUE_FLAG.startswith(arg):
            index += 1
    return dry


_NOTES_READ_SUBCOMMANDS = frozenset({"list", "show", "get-ref"})


def _notes_reads_only(args: list[str]) -> bool:
    """True for `git notes` bare or with `list`, `show` or `get-ref`; options before the subcommand are skipped
    (`--ref` takes the next word as its value). Every other subcommand (`add`, `append`, `copy`, `edit`, `merge`,
    `remove`, `prune`) and any other word writes."""
    subcommand, _ = _subcommand_after_options(args, ("--ref",))
    return subcommand is None or subcommand in _NOTES_READ_SUBCOMMANDS


def _replace_lists_only(args: list[str]) -> bool:
    """True for `git replace` bare or only listing: `-l`/`--list` and `--format` (with its value), bare words only
    as patterns once listing is on. `-d`, `-e`, `-g`, `-f`, `--convert-graft-file`, an abbreviated long option, a bundle
    and a bare word without listing make it a write. `--format` always takes the next word as its value, also one that
    starts with `-` (`--format -l a b` has the format `-l` and replaces `a` with `b`)."""
    listing, bare, index = False, 0, 0
    while index < len(args):
        arg = args[index]
        index += 1
        if arg in ("-l", "--list"):
            listing = True
        elif arg == "--format":
            index += 1
        elif arg.startswith("--format="):
            continue
        elif arg.startswith("-"):
            return False
        else:
            bare += 1
    return bare == 0 or listing


def _worktree_reads_only(args: list[str]) -> bool:
    """True for `git worktree list` only; `add`, `lock`, `move`, `prune`, `remove`, `repair`, `unlock` and a bare
    `worktree` are writes here."""
    return _subcommand_after_options(args)[0] == "list"


def _sparse_checkout_reads_only(args: list[str]) -> bool:
    """True for `git sparse-checkout list` only."""
    return _subcommand_after_options(args)[0] == "list"


def _remote_reads_only(args: list[str]) -> bool:
    """True for `git remote` bare, with `-v`, `show` or `get-url`, and `remote prune` as a dry run (_is_dry_run).
    `add`, `rename`, `remove`, `set-head`, `update`, `set-branches`, `set-url` and a `prune` that deletes write."""
    subcommand, _ = _subcommand_after_options(args)
    if subcommand is None or subcommand in ("show", "get-url"):
        return True
    return subcommand == "prune" and _is_dry_run(args)


_SUBMODULE_READ_SUBCOMMANDS = frozenset({"status", "summary"})
_LFS_READ_SUBCOMMANDS = frozenset({"ls-files", "status", "env", "version", "locks"})


def _submodule_reads_only(args: list[str]) -> bool:
    """True for `git submodule` bare (options only, `--quiet`, `--cached`), `status` and `summary`; options before the
    subcommand are skipped. Every other subcommand (`add`, `init`, `deinit`, `update`, `set-branch`, `set-url`, `sync`,
    `absorbgitdirs`, `foreach`) and any other word writes or fetches."""
    subcommand, _ = _subcommand_after_options(args)
    return subcommand is None or subcommand in _SUBMODULE_READ_SUBCOMMANDS


def _lfs_reads_only(args: list[str]) -> bool:
    """True for `git lfs ls-files`, `status`, `env`, `version` and `locks` only, as the very first word after `lfs`.
    An option before the subcommand refuses (`git lfs -X ls-files pull`: lfs may read the next word as the value of
    an option it does not know and then run `pull`), and so does a bare `git lfs` and every other subcommand
    (`pull`, `fetch`, `push`, `checkout`, `install`, `track`, `lock`, `unlock`, `prune`, `migrate` …)."""
    return bool(args) and args[0] in _LFS_READ_SUBCOMMANDS


def _reflog_reads_only(args: list[str]) -> bool:
    """True for every `reflog` form but `expire`, `delete`, `drop` and `write` as the first word that is no option;
    `expire` and `delete` as a dry run (_is_dry_run) read. Bare, `show`, `list`, `exists` and a ref name read."""
    subcommand, _ = _subcommand_after_options(args)
    if subcommand in ("expire", "delete"):
        return _is_dry_run(args)
    return subcommand not in ("drop", "write")


def _hash_object_reads_only(args: list[str]) -> bool:
    """False when `-w` is set: a word `-w`, or a bundle of short options where `w` comes before `t` (`-wt blob`;
    `-t` takes the rest of its word as the type, so `-tw` is the type `w`; a bundle that ends in `t` takes the next
    word as the type, so `-t -- -w f` still sets `-w`). Words after `--` or `--end-of-options` are files."""
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if arg in _END_OF_OPTIONS:
            break
        if arg.startswith("-") and not arg.startswith("--"):
            for position, char in enumerate(arg[1:], 1):
                if char == "w":
                    return False
                if char == "t":
                    index += position + 1 == len(arg)  # the type is the next word
                    break
    return True


def _history_reads_only(args: list[str]) -> bool:
    """True for a bare `git history` or `git history -h` (usage only), and for any form with a word exactly
    `--dry-run` before the first `--`/`--end-of-options` and no word that starts with `--no-`. `drop`, `fixup`,
    `reword` and `split` rewrite commits; `history` has no `-n`, so only the long word counts."""
    if not args or args == ["-h"]:
        return True
    options = []
    for arg in args:
        if arg in _END_OF_OPTIONS:
            break
        options.append(arg)
    return "--dry-run" in options and not any(arg.startswith("--no-") for arg in args)


_BISECT_READ_SUBCOMMANDS = frozenset({"log", "visualize", "view", "terms", "help"})
_RERERE_READ_SUBCOMMANDS = frozenset({"status", "diff", "remaining"})


def _bisect_reads_only(args: list[str]) -> bool:
    """True for `git bisect` bare, `log`, `visualize`/`view`, `terms` and `help`; `start`, `bad`, `good`, `skip`,
    `next`, `reset`, `replay`, `run` and any other word write (move HEAD or the bisect state)."""
    subcommand, _ = _subcommand_after_options(args)
    return subcommand is None or subcommand in _BISECT_READ_SUBCOMMANDS


def _rerere_reads_only(args: list[str]) -> bool:
    """True for `git rerere status`, `diff` and `remaining`; bare `rerere` records resolutions, `clear`, `forget` and
    `gc` delete them."""
    return _subcommand_after_options(args)[0] in _RERERE_READ_SUBCOMMANDS


_APPLY_ANALYSIS_FLAGS = frozenset({"--check", "--stat", "--numstat", "--summary"})
_APPLY_PLAIN_FLAGS = frozenset({
    "-v", "--verbose", "-q", "--quiet", "-z", "-R", "--reverse", "--recount", "--allow-empty", "--unidiff-zero", "-",
    "--index", "--cached", "--ignore-whitespace", "--ignore-space-change",
})
_APPLY_NUMBER_RE = re.compile(r"-[pC]\d+")
_APPLY_VALUE_PREFIXES = ("--include=", "--exclude=", "--directory=")
_APPLY_WHITESPACE_RE = re.compile(r"--whitespace=(?:nowarn|warn|fix|error|error-all)")


def _apply_reads_only(args: list[str]) -> bool:
    """True for an `apply` that only analyses a patch: at least one of `--check`, `--stat`, `--numstat`, `--summary`,
    and every other word is `-v`, `--verbose`, `-q`, `--quiet`, `-z`, `-R`, `--reverse`, `--recount`,
    `--allow-empty`, `--unidiff-zero`, `--index`, `--cached`, `--ignore-whitespace`, `--ignore-space-change`,
    `--whitespace=<action>` (`nowarn`, `warn`, `fix`, `error`, `error-all`, the glued form only), `-p<n>`, `-C<n>`,
    `--include=`, `--exclude=`, `--directory=`, `-` or a word that is no option (a patch file). Any other word
    (`--apply`, `--reject`, `--build-fake-ancestor`, `--3way`, `--no-…`, `--whitespace` with a separate value, an
    abbreviation) makes it a write: an allow-list, per word. `-h` as the only word prints the usage and is free (a
    bare `apply`, `-h` with another word and `--help` are not)."""
    if args == ["-h"]:
        return True
    if not any(arg in _APPLY_ANALYSIS_FLAGS for arg in args):
        return False
    return all(
        not arg.startswith("-") or arg in _APPLY_ANALYSIS_FLAGS or arg in _APPLY_PLAIN_FLAGS
        or _APPLY_NUMBER_RE.fullmatch(arg) is not None or arg.startswith(_APPLY_VALUE_PREFIXES)
        or _APPLY_WHITESPACE_RE.fullmatch(arg) is not None
        for arg in args
    )


# Commands with a reading form beside a writing one: each returns True for the forms that only read; every other
# form is a write (an allow-list per command, the command itself is on the deny-list).
_READ_FORMS = {
    "apply": _apply_reads_only,
    "notes": _notes_reads_only,
    "replace": _replace_lists_only,
    "worktree": _worktree_reads_only,
    "remote": _remote_reads_only,
    "reflog": _reflog_reads_only,
    "prune": _is_dry_run,
    "hash-object": _hash_object_reads_only,
    "history": _history_reads_only,
    "sparse-checkout": _sparse_checkout_reads_only,
    "bisect": _bisect_reads_only,
    "rerere": _rerere_reads_only,
    "submodule": _submodule_reads_only,
    "lfs": _lfs_reads_only,
}

_WRITE_FORM_TEXT = {
    "update-ref": "changes a ref",
    "symbolic-ref": "changes where a symbolic ref (HEAD) points",
    "tag": "creates, changes or deletes a tag; a worker may list tags with `git tag -l`",
    "config": "writes git configuration; a worker may read it with `git config <key>`, `--get` or `--list`",
    "apply": ("applies a patch; a worker may check one with `git apply --check`, `--stat`, `--numstat` or `--summary`, "
              "also with `--index`, `--cached`, `--ignore-whitespace`, `--ignore-space-change` or "
              "`--whitespace=<action>`, but never with `--apply`, `--reject` or `--build-fake-ancestor`; "
              "`git apply -h` alone prints the usage"),
    "notes": "changes notes; a worker may read them with `git notes`, `git notes list`, `show` or `get-ref`",
    "replace": "creates, changes or deletes a replace ref; a worker may list them with `git replace -l`",
    "worktree": "changes worktrees; a worker may list them with `git worktree list`",
    "remote": ("changes remotes; a worker may read them with `git remote`, `-v`, `show` or `get-url`, or run "
               "`remote prune --dry-run`"),
    "reflog": ("expires, deletes or writes reflog entries; a worker may read it with `git reflog`, `show`, `list`, "
               "`exists` or a ref, or run `expire`/`delete` with `--dry-run`"),
    "prune": "deletes unreachable objects; a worker may run `git prune --dry-run`",
    "hash-object": "writes an object with -w; a worker may hash without `-w`",
    "history": "rewrites commits; a worker may run `git history <subcommand> --dry-run`",
    "sparse-checkout": "changes the sparse-checkout; a worker may read it with `git sparse-checkout list`",
    "bisect": ("changes HEAD or the bisect state; a worker may read it with `git bisect log`, `visualize`, `terms` "
               "or `help`"),
    "rerere": "changes recorded resolutions; a worker may read them with `git rerere status`, `diff` or `remaining`",
    "fetch": "fetches from a remote; the orchestrator provides a remote's state, not a worker",
    "clone": "clones a remote; the orchestrator provides a remote's state, not a worker",
    "backfill": "downloads objects from a remote; the orchestrator provides a remote's state, not a worker",
    "submodule": ("fetches, changes or runs commands in submodules; a worker may read them with `git submodule`, "
                  "`status` or `summary`"),
    "lfs": ("downloads, changes or locks large files; a worker may read them with `git lfs ls-files`, `status`, "
            "`env`, `version` or `locks` as the first word after `lfs` (an option before it is refused); `git-lfs` "
            "is judged the same way"),
    "fetch-pack": "fetches from a remote; the orchestrator provides a remote's state, not a worker",
    "send-pack": "pushes to a remote; the orchestrator publishes, not a worker",
    "submodule--helper": ("is the internal helper of `git submodule` and fetches or changes submodules; a worker may "
                          "read them with `git submodule status` or `summary`"),
    "receive-pack": "writes objects and refs into a repository; the orchestrator changes the repository, not a worker",
    "index-pack": ("writes an index file and, with `--stdin`, objects; the orchestrator changes the repository, not a "
                   "worker"),
    "unpack-objects": "writes loose objects, also with `-n`; the orchestrator changes the repository, not a worker",
    "http-fetch": ("downloads objects and, with `-w`, writes a ref; the orchestrator provides a remote's state, not a "
                   "worker"),
    "update-git-for-windows": ("replaces the Git installation of the machine, a place outside the project and every "
                               "repository, in every form, also against a folder outside the project; the orchestrator "
                               "updates tools, not a worker"),
}

# What is refused when `clone` or `init` runs from a folder outside the project but its target lies inside the
# project or cannot be resolved (_target_enters_project), in the same table form.
_TARGET_IN_PROJECT_TEXT = {
    "clone": ("clones into a folder inside the project, or one that cannot be resolved (a variable, `~`), although "
              "`-C` or `cd` points outside it; give a literal target folder outside the project, or none"),
    "init": ("creates a repository in a folder inside the project, or one that cannot be resolved (a variable, `~`), "
             "although `-C` or `cd` points outside it; give a literal target folder outside the project, or none"),
    "worktree": ("adds, moves, removes or repairs a worktree at a path inside the project, or at one that cannot be "
                 "resolved (a variable, `~`), names a worktree to remove or move by a relative word (git reads it as the "
                 "end of the path of any worktree) or repairs worktrees (it also rewrites the `.git` file of every "
                 "linked worktree, wherever it lies), although `-C` or `cd` points outside it; give literal paths "
                 "outside the project, and for `remove` and the first word of `move` one that is absolute or starts "
                 "with `./` or `../` (in PowerShell also `.\\` or `..\\`)"),
}


def _is_git_write_subcommand(subcommand: str, args: list[str]) -> bool:
    if subcommand == "stash":
        return not _stash_reads_only(args)
    if subcommand == "update-ref":
        return True
    if subcommand == "symbolic-ref":
        return not _symbolic_ref_reads_only(args)
    if subcommand == "tag":
        return not _tag_lists_only(args)
    if subcommand == "config":
        return _config_writes(args)
    if subcommand in _READ_FORMS:
        return not _READ_FORMS[subcommand](args)
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
    prefix-stripped argv of every simple command, in order; `Parse.commands()`, which for a PowerShell call is read
    from the PowerShell words, so `Set-Location ..\\proj` keeps its backslash) -- (determinable, directory).
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


def _leading_cd_run_directory(
    command: str, base_cwd: Optional[str], parse: Optional[Parse] = None,
) -> Optional[Path]:
    """The directory of the whole command's very first simple command when that is a `cd`-family invocation
    (_CD_LIKE_NAMES) with a literal directory operand, inside the project or outside it, AND no later
    simple command changes directory again (_CD_LIKE_NAMES or _CD_UNKNOWN_NAMES) -- see this
    module's Known limits for why a second directory change anywhere disables the exemption
    entirely rather than tracking which git call comes after which cd; None otherwise. A `-C` of a git call
    after such a `cd` counts from this directory. `parse` is the dispatcher's reading of `command`; without it
    the command is read here."""
    if base_cwd is None:
        return None
    if parse is None:
        parse = Parse("Bash", command)
    determinable, directory = _leading_cd_directory(parse.commands(), base_cwd, parse)
    return directory if determinable else None


def _leading_cd_outside_project(
    command: str, base_cwd: Optional[str], root: Optional[Path], parse: Optional[Parse] = None,
) -> bool:
    """True only when _leading_cd_run_directory names a directory outside `root`: the whole command's very first
    simple command is a `cd` to a literal directory outside the project and no later command changes directory."""
    if root is None:
        return False
    directory = _leading_cd_run_directory(command, base_cwd, parse)
    return directory is not None and _is_outside_root(directory, root)


def _leading_cd_unresolvable(command: str, base_cwd: Optional[str], parse: Optional[Parse] = None) -> bool:
    """True when the folder the whole command runs in is not determinable (_leading_cd_directory says so): a leading
    `cd`-family command (_CD_LIKE_NAMES) without an operand or with a variable, a substitution, a backtick, a leading
    `~` or an operand that does not resolve, a later `cd`, `Set-Location`, `Push-Location`, `Pop-Location` and the like
    anywhere in the command, or a `cd` inside a group that closes before the git call (`(cd $X) && git ...`). A
    relative `-C` of a git call may then count from an unknown folder, so the exemption for a folder outside the
    project does not hold for it, unless its `-C` chain has an absolute value with only literal values before it (that
    one does not depend on the folder). False without a working
    directory, and for a command without any directory change or with a determinable one. `parse` is the dispatcher's
    reading of `command`; without it the command is read here."""
    if base_cwd is None:
        return False
    if parse is None:
        parse = Parse("Bash", command)
    determinable, _ = _leading_cd_directory(parse.commands(), base_cwd, parse)
    return not determinable


def _is_absolute_path_word(raw: str) -> bool:
    """True when `raw` (a `-C` value as typed) names a folder independently of the folder the call runs in: a literal
    absolute path (a drive or a leading `/` that the platform reads as absolute). A variable, a substitution, a leading
    `~` and everything relative is not, nor is a `/tmp/x` that Windows reads as relative to the current drive: the
    check fails toward refusing."""
    return not _is_dynamic_target(raw) and Path(_to_native_path(raw)).is_absolute()


_PROGRAM_PREFIX = "git-"


def _last_absolute_index(dash_c_dirs: list[str]) -> Optional[int]:
    """The index of the last `-C` value that is an absolute path (_is_absolute_path_word), None without one. An
    absolute `-C` starts git in that folder whatever came before, so the values up to it do not matter and only the
    ones after it are applied on top of it."""
    found = None
    for index, raw in enumerate(dash_c_dirs):
        if _is_absolute_path_word(raw):
            found = index
    return found


def _is_anchored_path_word(raw: str, powershell: bool = False) -> bool:
    """True when `raw` cannot be read as the last path components of some worktree (git's identification of a
    `<worktree>` word, see `git worktree`): an absolute path (_is_absolute_path_word), or a word that starts with `./`
    or `../` (PowerShell takes the slash too). In a Bash call a backslash form (dot, backslash) is no anchor: the
    Bash reader consumes the backslash, so such a word cannot be told from a name that starts with a dot. In a
    PowerShell call (`powershell`) the word is read with its backslash, and `.\\` and `..\\` anchor like `./` and
    `../`. Any other relative word, also `.` and `..` alone, is not anchored: it may name a worktree anywhere."""
    if powershell and raw.startswith((".\\", "..\\")):
        return True
    return _is_absolute_path_word(raw) or raw.startswith(("./", "../"))


def _git_program_name(word: str) -> Optional[str]:
    """The `<name>` of a program `git-<name>` (also `git-<name>.exe`, with a directory in front, in any case), None for
    any other command word and for `git-` alone."""
    name = _command_name(word)
    rest = name[len(_PROGRAM_PREFIX):] if name.startswith(_PROGRAM_PREFIX) else ""
    return rest if rest and not rest.startswith("-") else None  # a leading `-` would read as an option, not a name


def _git_program_invocations(parse: Parse) -> list[tuple[list[str], list[str]]]:
    """Every call of a program `git-<name>` (`git-lfs`, `git-commit`, `git-receive-pack`, `git-update-git-for-windows`;
    also with `.exe`, a directory in front, in any case) as (prefix words, argv) like Parse.git_invocations_with_prefix
    gives a git call, with the argv rewritten to `<name> <arguments>`: the program is `git <name>` under another name,
    without the global options a git call takes, so the loop of check_worker_git_write judges it the same way,
    exemptions included. A PowerShell call is read with the PowerShell reader (Parse.ps_calls): the program is seen
    behind a variable assignment (`$r = git-lfs pull`), `&` or the dot operator (`. .\\git-lfs.exe pull`), inside a
    script block (`ForEach-Object { .\\git-lfs.exe pull }`) or a group (`(git-lfs pull)`), behind `cmd /c`, and with
    its backslashes (`.\\git-lfs.exe`, `& ..\\bin\\git-lfs.exe pull`). The calls the Bash reader gives with every word
    as written in the text (Parse.bash_calls_as_written) come on top; a line that does not tokenize is read by the
    Bash reader alone."""
    if parse.tool_name == "PowerShell" and parse.ps_words():
        calls = parse.ps_calls() + parse.bash_calls_as_written()
    else:
        calls = []
        for words, _ in parse.words():
            stripped = _strip_command_prefix(words)
            if stripped:
                calls.append((words[: len(words) - len(stripped)], stripped))
    found = []
    for prefix, call in calls:
        name = _git_program_name(call[0])
        if name:
            found.append((prefix, [name, *call[1:]]))
    return found


# Options of `clone` and `init` that take a value as the next word, by the full long name git knows, and the short
# ones (`-o`, `-b`, `-u`, `-j`, `-c`: the value is the rest of the word or, as the last character of a bundle, the next
# word). An abbreviated long option never takes the next word here: it may be an option that takes a value only glued
# with `=` (`--sh` is `init --shared`), and swallowing a word that is the target would hide it. Only an abbreviation
# of `--separate-git-dir` counts, and its value is a target.
_TARGET_VALUE_OPTIONS = (
    "--origin", "--branch", "--upload-pack", "--reference", "--reference-if-able", "--depth", "--shallow-since",
    "--shallow-exclude", "--jobs", "--template", "--config", "--server-option", "--filter", "--bundle-uri",
    "--ref-format", "--object-format", "--initial-branch", "--revision",
)
_SEPARATE_GIT_DIR = "--separate-git-dir"
_TARGET_VALUE_SHORT = frozenset("obujc")
_MIN_ABBREVIATION = 4  # `--se` is ambiguous in git, `--sep` is not; shorter words stay flags here


def _clone_init_targets(subcommand: str, sub_args: list[str]) -> list[str]:
    """The folders a `clone` or `init` writes into, as typed: for `clone` the words after the repository, for
    `init` every non-option word, and the value of `--separate-git-dir` (also abbreviated, glued or separate). The
    separate value of every other option that takes one, by its full name, is skipped; an abbreviated one takes no
    next word (its next word counts as a target, which only ever refuses more), and a word after `--` is no option. A
    clone without a folder names it from the URL under the working directory: no word, no target."""
    positional: list[str] = []
    separate: list[str] = []
    options_over = False
    index = 0
    while index < len(sub_args):
        arg = sub_args[index]
        index += 1
        if options_over or not arg.startswith("-") or arg == "-":
            positional.append(arg)
        elif arg in _END_OF_OPTIONS:
            options_over = True
        elif arg.startswith("--"):
            name, equals, value = arg.partition("=")
            abbreviation = len(name) >= _MIN_ABBREVIATION
            if name == _SEPARATE_GIT_DIR or (abbreviation and _SEPARATE_GIT_DIR.startswith(name)):
                if equals:
                    separate.append(value)
                elif index < len(sub_args):
                    separate.append(sub_args[index])
                    index += 1
            elif not equals and name in _TARGET_VALUE_OPTIONS:
                index += 1
        else:
            for position, char in enumerate(arg[1:], 1):
                if char in _TARGET_VALUE_SHORT:
                    index += position + 1 == len(arg)  # the value is the next word
                    break
    return (positional[1:] if subcommand == "clone" else positional) + separate


_WORKTREE_PATH_SUBCOMMANDS = frozenset({"add", "move", "remove", "repair"})
_WORKTREE_ADD_VALUE_OPTIONS = frozenset({"-b", "-B", "--reason"})


def _worktree_targets(sub_args: list[str]) -> list[str]:
    """The paths a `worktree add`, `move`, `remove` or `repair` works on, as typed (`sub_args` are the words after
    `worktree`): every word after the subcommand that is no option, and every word after a `--` or
    `--end-of-options`. For `add` only the first of them is the path: the separate value of `-b`, `-B` and `--reason`
    is skipped (a branch name or a text), and the commit-ish behind the path is no target. `move` and `repair` take
    every path word, `remove` its one. `lock`, `unlock`, `prune`, `list` and a bare `worktree` have no target: they
    write only in the repository they run in."""
    subcommand, rest = _subcommand_after_options(sub_args)
    if subcommand not in _WORKTREE_PATH_SUBCOMMANDS:
        return []
    found: list[str] = []
    options_over = False
    index = 0
    while index < len(rest):
        arg = rest[index]
        index += 1
        if options_over or not arg.startswith("-") or arg == "-":
            found.append(arg)
        elif arg in _END_OF_OPTIONS:
            options_over = True
        elif subcommand == "add" and arg in _WORKTREE_ADD_VALUE_OPTIONS:
            index += 1
    return found[:1] if subcommand == "add" else found


def _worktree_identifiers(sub_args: list[str]) -> list[str]:
    """The words of a `worktree remove` or `worktree move` that name an EXISTING worktree (`<worktree>` in git's
    synopsis): the one word of `remove` and the first of `move`. git matches such a word against the last path
    components of every worktree of the repository before it reads it as a path, so a bare relative word may reach a
    worktree anywhere. The second word of `move` is the new path, `repair` takes paths, `lock` and `unlock` write only
    in the repository they run in: none of them is listed."""
    subcommand = _subcommand_after_options(sub_args)[0]
    targets = _worktree_targets(sub_args)
    return targets if subcommand == "remove" else targets[:1] if subcommand == "move" else []


def _target_enters_project(
    subcommand: str, sub_args: list[str], run_dir: Optional[Path], root: Path, powershell: bool = False,
) -> bool:
    """True when a `clone`, `init` or `worktree` call that runs from `run_dir` (outside the project) writes into the
    project or somewhere not known to be outside it: a target (_clone_init_targets; for `worktree` the paths of
    _worktree_targets) resolving, against `run_dir`, to a path inside `root`, or one that cannot be resolved (a
    variable, a leading `~`), or an unknown `run_dir`. No target (the folder comes from the URL, a bare `init`,
    `worktree lock`) stays outside. A `worktree` call is also in the project when the word that names the worktree of
    a `remove` or the first word of a `move` is not anchored (_is_anchored_path_word): git may read it as the end of
    the path of a worktree inside the project. And every `repair` is, with or without a path: besides the paths named
    it repairs the `.git` file of every linked worktree, wherever it lies."""
    if subcommand == "worktree":
        if _subcommand_after_options(sub_args)[0] == "repair":
            return True
        if not all(_is_anchored_path_word(raw, powershell) for raw in _worktree_identifiers(sub_args)):
            return True
    targets = _worktree_targets(sub_args) if subcommand == "worktree" else _clone_init_targets(subcommand, sub_args)
    for raw in targets:
        resolved = None if run_dir is None else _resolve_dir(raw, str(run_dir))
        if resolved is None or not _is_outside_root(resolved, root):
            return True
    return False


def _worker_git_write_message(subcommand: str, target_in_project: bool = False) -> str:
    form = (_TARGET_IN_PROJECT_TEXT if target_in_project else _WRITE_FORM_TEXT).get(subcommand)
    return (
        f"[act] git is read-only for workers (status/diff/log/show, ...) — git {subcommand} "
        + (form if form else "changes the tree or history")
        + " (R-role-worker)"
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
    leading_cd_directory = _leading_cd_run_directory(command, base_cwd, parse)
    leading_cd_unknown = _leading_cd_unresolvable(command, base_cwd, parse)

    invocations = parse.git_invocations_with_prefix()  # in PowerShell read with PowerShell's own reader
    invocations += _git_program_invocations(parse)  # `git-lfs pull` is `git lfs pull`, `git-commit` is `git commit`
    for prefix, args in invocations:
        subcommand, sub_args, dash_c_dirs, has_dir_override, alias_defined = _parse_git_invocation(args)
        if subcommand is None:
            continue
        if not (alias_defined or _is_git_write_subcommand(subcommand, sub_args)):
            continue

        never_exempt = (has_dir_override or _prefix_has_dir_override(prefix)
                        or subcommand in _NEVER_EXEMPT_SUBCOMMANDS
                        or (subcommand == "config" and _config_escapes_repo(sub_args)))
        target_in_project = False
        if not never_exempt:
            # where the call runs: a leading `cd` (inside the project too) is the start of the `-C` chain, else the
            # working directory; the exemption holds only when that lies outside the project
            run_dir: Optional[Path] = None
            last_absolute = _last_absolute_index(dash_c_dirs)
            if last_absolute is not None and not any(_is_dynamic_target(raw) for raw in dash_c_dirs[:last_absolute]):
                # an absolute `-C` starts git in that folder whatever folder the call runs in and whatever `-C` came
                # before it: the chain counts from the last absolute one (an unknown folder does not matter). Only
                # when every value before it is literal: a variable or a substitution there is not trusted away
                run_dir = _resolve_dash_c_chain(dash_c_dirs[last_absolute:], base_cwd or "")
            elif leading_cd_directory is not None:
                run_dir = (_resolve_dash_c_chain(dash_c_dirs, str(leading_cd_directory))
                           if dash_c_dirs else leading_cd_directory)
            elif base_cwd is not None and dash_c_dirs and not leading_cd_unknown:
                # a relative first `-C` counts from the folder the call runs in; when a directory change leaves that
                # folder not determinable there is no known run directory
                run_dir = _resolve_dash_c_chain(dash_c_dirs, base_cwd)
            exempt = root is not None and _is_outside_root(run_dir, root)
            if exempt:
                # a clone, init or worktree call from outside still writes into the project when its target lies there
                target_in_project = (subcommand in _TARGET_IN_PROJECT_TEXT and root is not None
                                     and _target_enters_project(
                                         subcommand, sub_args, run_dir, root, parse.tool_name == "PowerShell"))
                if not target_in_project:
                    continue

        message = _worker_git_write_message(subcommand, target_in_project)
        if mode == "warn":
            print(message)
            return 0
        print(message, file=sys.stderr)
        return 2
    return 0
