#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check — `git reset --hard` run against a working tree that has open changes
#          (PreToolUse): a guardrail next to `R-safe-no-shell-delete` — `reset --hard`
#          throws away uncommitted work exactly the way a recursive delete throws away files, and
#          this check exists for the same reason that one does. The matching rule text
#          (`R-safe-git-reset`) is authored elsewhere; this module only enforces it. Unlike
#          checks/worker_git_write.py, this applies to **everyone** — orchestrator included — since
#          a clean working tree is what decides whether the command is safe, not who runs it.
#
#          Command decomposition and git-invocation parsing are shared with
#          checks/worker_git_write.py (`_parse_git_invocation`, `_resolve_dash_c_chain`,
#          `_prefix_has_dir_override`, `_resolve_dir`, `_first_operand`, `_CD_LIKE_NAMES`,
#          `_CD_UNKNOWN_NAMES`) and checks/command_words.py (`_git_invocations_with_prefix`,
#          `_stripped_word_lists`) — see those modules' own headers for why the
#          segmenting/parsing works the way it does.
#
#          The affected working tree is the directory a leading `cd`/`pushd`/... command (see
#          `_resolve_cwd_after_leading_cd`), then a `-C <dir>` chain, or absent both, the call's own
#          `cwd`, resolves to; `git status --porcelain` there decides clean vs. dirty — untracked
#          files count as "dirty" too, since `reset --hard <rev>` can overwrite them silently. A
#          directory that cannot be pinned down at all — no `cwd` in the payload, a dynamic `-C`
#          target or leading-`cd` target, a second directory change anywhere in the command, or
#          `--git-dir`/`--work-tree`/`GIT_DIR=`/`GIT_WORK_TREE=` naming the tree some other way this
#          check does not attempt to follow — is refused the same as a dirty tree (deny by default,
#          like every neighbour check in this module).
#
# Review fixes (2026-09-25, first round):
#   - a leading `cd`/`pushd`/`Set-Location`/... before the git call (`cd ../other && git reset
#     --hard`) is now resolved the same way checks/worker_git_write.py's own leading-cd exemption
#     is: a literal directory operand on the command's very first simple command becomes the base
#     that `-C`/`cwd` resolve against; any other directory-change form anywhere in the same command
#     (a dynamic target, a second `cd`-family command, `popd`/`Pop-Location`) makes the target
#     "not determinable" and the call is refused, never assumed clean.
#   - any abbreviation of `--hard` git itself accepts (`--ha`, `--har`, ...) is recognized, not just
#     the literal `--hard` spelling (see `_has_hard_flag`).
#   - `git -c alias.<name>=<value> ...` is now refused outright rather than ignored: the alias could
#     itself expand to `reset --hard`, and this check has no way to look up what it actually
#     resolves to (same treatment as checks/worker_git_write.py gives it for its own purposes).
#   - the dirty-tree message now names `git stash -u` (not plain `git stash`, which leaves
#     untracked files behind for `reset --hard` to overwrite) and says to run it "as its own call
#     first" — `git stash && git reset --hard` in one invocation is still refused, since the status
#     check runs before either half executes.
#
# Review fixes (2026-09-25, second round):
#   - a directory-change form anywhere in the command other than its very first simple command —
#     not only a *second* one after an already-recognized leading `cd` — now makes the target "not
#     determinable": `true && cd ../other && git reset --hard` used to fall through the leading-cd
#     check entirely (its first simple command, `true`, is not `cd`-like, so the function returned
#     the unchanged, possibly-clean `cwd` without ever looking at the later `cd`) and is refused
#     now, same as a leading `cd` followed by a second one already was.
#   - `git -c alias.<name>=<value> ...` is refused only when that alias is both defined *and*
#     actually invoked (the subcommand run is the alias's own name) *and* its own replacement text
#     literally names `reset` or an abbreviation of `--hard` (`_alias_definitions`,
#     `_value_mentions_reset_hard`) — an unrelated alias (`git -c alias.st=status st`) is no longer
#     refused, and the message no longer claims "git reset --hard refused" for a call that may not
#     touch reset at all.
#
# Review fixes (2026-09-25, third round):
#   - an inline alias is judged by what it actually runs — its replacement text *with the call's
#     own arguments appended*, nested aliases followed (`_alias_expansion`) — not by the replacement
#     text alone: `git -c 'alias.x=!git' x reset --hard` and `git -c alias.a=reset -c alias.b=a b
#     --hard` used to pass, since neither value on its own named `reset --hard`.
#   - a shell alias (`!...`) is refused outright whenever one is defined inline, invoked or not —
#     git hands its text to a shell as-is, and what that shell does is not knowable here; so is an
#     alias defined via `--config-env=alias.<name>=<VAR>` (either form), whose value sits in an
#     environment variable this check cannot read (`R='reset --hard' git --config-env=alias.x=R x`
#     used to pass).
#   - `env -C <dir> git reset --hard` (`--chdir`, either form) runs git in `<dir>`, not the shell's
#     own directory — refused as "not determinable" (`_prefix_changes_directory`), the same answer
#     shell_targets.py gives for its write targets; before, the `-C` value was even read as the
#     command name itself and the call never seen as git at all (command_words.py).
#   - `find ... -execdir git reset --hard ;` runs git inside whichever directory find matches
#     (`-okdir` likewise) — refused as "not determinable" (`_has_find_execdir`) for every
#     `reset --hard` in the same command, since command_words.py hands the exec tail back as a
#     simple command of its own without saying where it came from.
#
# Known limits:
#   - only the directory-change forms `_CD_LIKE_NAMES`/`_CD_UNKNOWN_NAMES` (worker_git_write.py)
#     name are recognized for the leading-cd/later-cd case, and only as a literal operand on the
#     command's own first simple command — a `cd` buried deeper (inside a function, guarded by
#     `if`) or naming a dynamic directory never resolves; the call is then refused, not silently
#     checked against the unchanged `cwd`.
#   - a custom alias's expansion is only checked as literal text (`_words_mention_reset_hard`)
#     against the aliases defined *in the same command line* — a plain `.gitconfig` alias that
#     expands to `reset --hard` without ever being (re)defined via `-c alias....=` on the command
#     line itself is invisible here, and so is an alias chain that leaves the command line (an
#     inline alias expanding to a `.gitconfig` alias name). `_alias_definitions` only reads git's
#     global-option words ahead of the subcommand `_parse_git_invocation` found, without
#     replicating its full option-skipping — best-effort like the rest of this module.
#   - shares checks/command_words.py's and checks/worker_git_write.py's own stated limits for
#     tokenizing/`-C` resolution otherwise (best-effort PowerShell quoting, a dynamic path never
#     resolvable).
#   - a `git status --porcelain` that itself fails (not a git repository, git missing, timeout) is
#     treated as "unknown" and refused rather than assumed clean — see _git_status_is_clean.

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

import actlib

from .command_words import _git_invocations_with_prefix, _stripped_word_lists
from .common import _check_mode, _shell_command
from .shell_targets import _command_name, _to_native_path
from .worker_git_write import (
    _CD_LIKE_NAMES,
    _CD_UNKNOWN_NAMES,
    _first_operand,
    _parse_git_invocation,
    _prefix_has_dir_override,
    _resolve_dash_c_chain,
    _resolve_dir,
)

__all__ = [
    "_DIRTY_MESSAGE", "_UNKNOWN_DIR_MESSAGE", "_ALIAS_MESSAGE", "_alias_definitions",
    "_alias_expansion", "_words_mention_reset_hard", "_has_hard_flag", "_prefix_changes_directory",
    "_has_find_execdir", "_resolve_cwd_after_leading_cd", "_resolve_target_dir",
    "_git_status_is_clean", "check_git_reset_hard",
]

_DIRTY_MESSAGE = (
    "[act] git reset --hard refused -- the working tree has uncommitted changes, including "
    "untracked files, which `git reset --hard` would overwrite silently (R-safe-git-reset): run "
    "`git stash -u` or `git reset --soft` as its own call first; check `git log -1` / "
    "`git reflog` if you are unsure what you would lose"
)
_UNKNOWN_DIR_MESSAGE = (
    "[act] git reset --hard refused -- could not determine (or read the status of) the working "
    "tree it targets (R-safe-git-reset): check with git status / git log -1 first"
)
_ALIAS_MESSAGE = (
    "[act] git alias refused -- a git alias defined inline can hide `reset --hard` -- run the "
    "plain command (R-safe-git-reset): run the expanded command directly, or check git status / "
    "git log -1 first"
)


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


def _words_mention_reset_hard(words: list[str]) -> bool:
    """True if `words` -- an inline alias's expansion with the call's own arguments appended (see
    _alias_expansion) -- literally name `reset` or `--hard` (or an abbreviation of it) anywhere:
    the same literal, best-effort test `_has_hard_flag` applies to a plain invocation, applied to
    the text an alias hides. Either word alone is enough: the alias route is refused on the
    mention, never checked against the tree."""
    return "reset" in words or _has_hard_flag(words)


def _prefix_changes_directory(prefix: list[str]) -> bool:
    """True if a wrapper ahead of `git` in the same simple command (`prefix`: the unstripped words
    command_words._git_invocations_with_prefix hands back) runs it in a directory of its own
    choosing rather than the shell's current one -- `env -C <dir>`/`env --chdir[=]<dir> git ...`.
    Which directory is knowable in principle but not followed here (the same answer
    shell_targets.py gives for its write targets); the caller refuses the call as "not
    determinable"."""
    if not any(_command_name(word) == "env" for word in prefix):
        return False
    return any(word in ("-C", "--chdir") or word.startswith("--chdir=") for word in prefix)


def _has_find_execdir(command: str) -> bool:
    """True if any `find` in `command` carries `-execdir`/`-okdir`, which run their command inside
    whichever directory find happens to match -- one this check cannot pin down. Judged for the
    whole command rather than the one exec tail (command_words.py hands that tail back as a simple
    command of its own, without saying where it came from), so a `reset --hard` anywhere in such a
    command is refused as "not determinable" -- over-refusing a `find -execdir` that has nothing to
    do with the git call is the accepted price."""
    return any(
        _command_name(words[0]) == "find" and any(arg in ("-execdir", "-okdir") for arg in words[1:])
        for words in _stripped_word_lists(command)
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


def _resolve_cwd_after_leading_cd(command: str, base_cwd: Optional[str]) -> tuple[Optional[str], bool]:
    """The effective cwd a `git reset --hard` invocation in `command` runs against, after a
    possible leading `cd`-family command -- (effective_cwd, determinable). No leading cd at all:
    (base_cwd, True), unchanged. A literal leading cd with a literal directory operand, and no
    later simple command changing directory again: (that resolved directory, True). Anything else
    a leading cd could mean (a dynamic operand, a later cd-like/`popd`-like command anywhere) is
    not determinable: (None, False) -- the caller then refuses the call outright rather than
    falling back to the unchanged `cwd`, since `cwd` is exactly what pinning down the leading cd
    was supposed to override."""
    if base_cwd is None:
        return None, True
    commands = _stripped_word_lists(command)
    if not commands:
        return base_cwd, True
    first = commands[0]
    first_is_cd = _command_name(first[0]) in _CD_LIKE_NAMES
    # A directory-change form anywhere else in the same command -- not only after a leading cd --
    # already makes the target impossible to pin down: `true && cd ../other && git reset --hard`
    # is exactly as "not determinable" as a leading `cd` followed by a second one.
    for later in commands[1:]:
        if _command_name(later[0]) in _CD_LIKE_NAMES | _CD_UNKNOWN_NAMES:
            return None, False
    if not first_is_cd:
        return base_cwd, True
    directory = _first_operand(first[1:])
    if directory is None:
        return None, False
    resolved = _resolve_dir(directory, base_cwd)
    if resolved is None:
        return None, False
    return str(resolved), True


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


def _git_status_is_clean(directory: Path) -> Optional[bool]:
    """True/False for a clean/dirty working tree at `directory`; None if `git status` itself could
    not be run or failed (not a git repository, git missing, timed out) -- the caller treats None
    the same as "dirty" (deny by default)."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(directory),
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return not result.stdout.strip()


def check_git_reset_hard(payload: dict) -> int:
    """Check: deny `git reset --hard` while the working tree it targets has uncommitted changes,
    or while that working tree (or the command itself, behind an alias) cannot be determined at
    all. Runs for every caller."""
    config = actlib.read_config()
    mode = _check_mode(config, "git-reset-hard", default="block")
    if mode == "off":
        return 0

    shell = _shell_command(payload)
    if shell is None:
        return 0
    _, command = shell

    cwd_raw = payload.get("cwd")
    base_cwd = cwd_raw if isinstance(cwd_raw, str) and cwd_raw else None

    find_execdir = _has_find_execdir(command)
    for prefix, args in _git_invocations_with_prefix(command):
        subcommand, sub_args, dash_c_dirs, has_dir_override, _ = _parse_git_invocation(args)
        if subcommand is None:
            continue

        # Inline aliases: a shell alias or one with an unknown value is refused as soon as it is
        # defined; a plain one only when invoked and its expansion (the call's own arguments
        # appended, nested aliases followed) names reset/--hard.
        definitions = _alias_definitions(args[: len(args) - len(sub_args) - 1])
        expansion = _alias_expansion(definitions, subcommand, sub_args)
        alias_risk = (
            expansion is None
            or any(value is None or value.startswith("!") for value in definitions.values())
            or (subcommand.lower() in definitions and _words_mention_reset_hard(expansion))
        )

        if alias_risk:
            message = _ALIAS_MESSAGE
        else:
            if subcommand != "reset" or not _has_hard_flag(sub_args):
                continue
            effective_cwd, determinable = _resolve_cwd_after_leading_cd(command, base_cwd)
            if not determinable or find_execdir:
                message = _UNKNOWN_DIR_MESSAGE
            else:
                target_dir = _resolve_target_dir(prefix, dash_c_dirs, has_dir_override, effective_cwd)
                if target_dir is None:
                    message = _UNKNOWN_DIR_MESSAGE
                else:
                    clean = _git_status_is_clean(target_dir)
                    if clean is None:
                        message = _UNKNOWN_DIR_MESSAGE
                    elif clean:
                        continue  # this invocation is fine; keep scanning the rest of the command
                    else:
                        message = _DIRTY_MESSAGE

        if mode == "warn":
            print(message)
            return 0
        print(message, file=sys.stderr)
        return 2
    return 0
