#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# LEGACY COPY — do not edit and do not import from outside checks/. This module is the previous
# command-word decomposition, kept verbatim except that it imports shell_targets_legacy (the
# previous tokenizer) instead of the live one. It is the safety net for the word lexer in
# shell_targets.py: every public result of command_words.py (command word lists) and of
# shell_targets.py (write targets) is the UNION of what the legacy scanner finds and what the new
# lexer finds, so the new lexer can only ever add findings, never remove one the previous scanner
# had — a blocking check is never weaker than before. If this module itself raises, the caller sees
# that exception exactly as it did before the lexer was replaced. Remove this file only together
# with shell_targets_legacy.py.
#
# Purpose: Shared, quote-/heredoc-aware decomposition of a shell command into its individual
#          simple commands (argv lists) — used by every shell-command check in this stage
#          (checks/worker_git_write.py, checks/commit_pathspec.py, checks/recursive_delete.py)
#          instead of each rolling its own. Replaces the first version of this stage's own
#          operator-*character* regex split (`re.split(r"&&|\|\||[;&|()\n]", command)`), which a
#          review (2026-09-23) found ignores quoting and heredocs entirely: `git commit -m "fix;
#          rm -r stuff"` split on the `;` *inside the quoted message* and misread it as a second
#          command, and a heredoc commit message such as
#            git commit -m "$(cat <<'EOF'
#            fix
#
#            rm -r removed
#            EOF
#            )"
#          — an ordinary way to write a multi-line commit message, and something Claude Code
#          itself does routinely — split on operator-*looking* text inside the heredoc body. Both
#          are false positives: text that only resembles a dangerous command because a naive split
#          tore it out of its quotes. The same regex approach also could not see through
#          `bash -c '...'`, `sh -c "..."`, `pwsh -c '...'`, `cmd /c ...`, `eval ...`, `` `...` ``,
#          `$(...)` or `find ... -exec ... ;`/`+` — each a way to run a write command one recursion
#          level down from the shell's own top-level parsing, and therefore invisible to a check
#          that only looks at the top level.
#
# This module reuses shell_targets.py's own tokenizer (_line_mode_tokens, its heredoc-aware line
# mode, with _shell_tokens as the whole-command fallback for anything that does not tokenize line
# by line — an unclosed quote spanning lines, `$'...'` ANSI-C quoting) rather than re-deriving
# quoting/heredoc handling a second time; only the *grouping* into simple commands and the
# *recursion* into a nested interpreter are this module's own. Backtick spans are found the same
# way shell_targets._scan_tokens finds them — a regex over each simple command's dequoted words
# joined back together (shell_targets.py's "Known limits" name what that cannot tell apart).
#
# Contract: `_command_word_lists(command)` returns one (words, separator) pair per simple command
# found at any recursion depth — words is that command's own argv (its own name included as
# words[0]), separator is the operator token that joined it to the PREVIOUS entry in this same
# return list (`"|"`, `"&&"`, `";"`, ... — see shell_targets._SEPARATOR_OPS) or None for the first
# entry of a command / of a recursed sub-command. The separator lets
# checks/recursive_delete.py recognize a *pipeline-shaped* pattern (`Get-ChildItem ... -Recurse |
# Remove-Item ...`) that no single command's own words show by itself; checks/worker_git_write.py
# and checks/commit_pathspec.py, which only care about individual commands, use
# `_stripped_word_lists()` instead, which drops the separator and applies `_strip_command_prefix`.
#
# Known limits:
#   - a recursed sub-command's own separator sequence starts fresh (at None) and is *appended* to
#     the outer result list at the point where the recursion was found — for a top-level command
#     that itself triggers no recursion (the common case, and the only case
#     checks/recursive_delete.py's pipeline pattern is built to look for), adjacent top-level
#     entries in the returned list are exactly adjacent in the original command; a command whose
#     immediate pipeline neighbor itself contains a `$(...)`/backtick/eval substitution has its
#     recursed entries spliced in between the two, which would defeat a pipeline check spanning
#     that neighbor — accepted, since the pattern this module was asked to support
#     (list-then-delete) never itself needs that.
#   - PowerShell quoting (backtick escapes, here-strings `@"..."@`, `-and`/`-or`, splatting
#     `@args`) is approximated with the same POSIX-oriented tokenizer used for Bash — best effort
#     per this stage's own assignment; a command that relies on PowerShell-only quoting can
#     mis-tokenize. `pwsh`/`powershell -Command`/`cmd /c` recursion is still recognized by name.
#   - recursion depth is capped at shell_targets._MAX_SCAN_DEPTH, same cap and same reasoning as
#     shell_targets.py's own write-target scanner: nothing here is unbounded.
#   - a write made from inside a program (`python -c "...git..."`, a script file) is invisible,
#     same limit shell_targets.py's own docstring states for its write-target scan.
#   - `find -exec ... {} \;` / `+`: the escaped `\;` form is recognized as shlex would hand it
#     back (a literal `;` token, since shlex's own backslash handling already strips the escape in
#     POSIX mode) as well as a raw `\;` string (seen from a whole-command fallback tokenization,
#     where the backslash can survive); both terminate the exec tail the same way.

from __future__ import annotations

from typing import Optional

from .shell_targets_legacy import (
    _BACKTICK_SPAN_RE,
    _LINE_CONTINUATION_RE,
    _MAX_SCAN_DEPTH,
    _SEPARATOR_OPS,
    _SHELL_NAMES,
    _ASSIGNMENT_RE,
    _RESERVED_PREFIXES,
    _WRAPPER_ARG_RE,
    _WRAPPER_COMMANDS,
    _WRAPPER_VALUE_FLAGS,
    _command_name,
    _line_mode_tokens,
    _shell_tokens,
)

__all__ = [
    "_PS_NAMES", "_SEGMENT_SPLIT_RE_FALLBACK", "_command_word_lists", "_strip_command_prefix",
    "_stripped_word_lists", "_git_invocations_with_prefix", "_git_invocations",
]

# Interpreter names this module recognizes for a `-c`/`-Command`/`/c` recursion, beyond the POSIX
# shells shell_targets._SHELL_NAMES already lists (sh, bash, zsh, dash, ksh).
_PS_NAMES = frozenset({"pwsh", "powershell", "cmd"})

# Only used when nothing tokenizes at all (should be rare — _line_mode_tokens/_shell_tokens
# together cover everything except a truly malformed command) — the same coarse operator-
# character split this module replaces as the *primary* mechanism, kept as a last-resort fallback
# so a pathological command still yields *something* rather than nothing (fail toward seeing more
# candidate commands, not fewer, same principle shell_targets.py's own scanner uses).
import re as _re  # local, only for this one fallback regex

_SEGMENT_SPLIT_RE_FALLBACK = _re.compile(r"&&|\|\||[;&|()\n]")


def _strip_command_prefix(words: list[str]) -> list[str]:
    """Drop leading VAR=value assignments and known wrapper commands (sudo, env, exec, time,
    xargs, ...) plus their own flags — including a flag's separate value word (`env -u VAR`,
    `env -C dir`, `timeout -s KILL`, `sudo -u name`; shell_targets._WRAPPER_VALUE_FLAGS,
    without which that value was read as the command's own name and the real command behind it
    went unseen) — mirroring shell_targets._simple_command_targets's own prefix-skipping loop (not
    itself exported there, since it is entangled with write-target/cd bookkeeping this module does
    not need)."""
    index = 0
    while index < len(words):
        word = words[index]
        if _ASSIGNMENT_RE.match(word):
            index += 1
        elif word in _RESERVED_PREFIXES:
            index += 1
        elif _command_name(word) in _WRAPPER_COMMANDS:
            wrapper_value_flags = _WRAPPER_VALUE_FLAGS.get(_command_name(word), frozenset())
            index += 1
            while index < len(words):
                arg = words[index]
                if arg in wrapper_value_flags:
                    index += 2 if index + 1 < len(words) else 1
                elif _WRAPPER_ARG_RE.match(arg) or _ASSIGNMENT_RE.match(arg):
                    index += 1
                else:
                    break
        else:
            break
    return words[index:]


def _command_word_lists(command: str, depth: int = 0) -> list[tuple[list[str], Optional[str]]]:
    """Every simple command in `command`, as (argv, preceding-separator) pairs — see this module's
    docstring for the contract and known limits. Recurses into `sh|bash|zsh|dash|ksh -c ...`,
    `pwsh|powershell -Command ...`, `cmd /c ...`, `eval ...`, `$(...)`, `` `...` `` and
    `find ... -exec ... ;|+`."""
    command = _LINE_CONTINUATION_RE.sub("", command)
    tokens = None
    for attempt in (lambda: _line_mode_tokens(command), lambda: _shell_tokens(command, True)):
        try:
            tokens = attempt()
            break
        except ValueError:
            continue
    if tokens is None:
        return [
            (seg.split(), None) for seg in _SEGMENT_SPLIT_RE_FALLBACK.split(command) if seg.strip()
        ]

    pairs: list[tuple[list[str], Optional[str]]] = []
    words: list[str] = []
    pending_sep: Optional[str] = None
    for text, is_op in tokens + [("\n", True)]:
        if not is_op:
            words.append(text)
            continue
        if text not in _SEPARATOR_OPS:
            continue  # a redirection or other non-separator operator -- not a command boundary
        if words:
            pairs.append((words, pending_sep))
            words = []
        pending_sep = None if text == "\n" else text

    result: list[tuple[list[str], Optional[str]]] = []
    for words, sep in pairs:
        result.append((words, sep))
        if depth >= _MAX_SCAN_DEPTH:
            continue
        for word in words:
            if "$(" in word:
                result.extend(_command_word_lists(word[word.index("$(") + 2:], depth + 1))
        for span in _BACKTICK_SPAN_RE.findall(" ".join(words)):
            result.extend(_command_word_lists(span, depth + 1))
        stripped = _strip_command_prefix(words)
        if not stripped:
            continue
        name, args = _command_name(stripped[0]), stripped[1:]
        if name == "eval":
            result.extend(_command_word_lists(" ".join(args), depth + 1))
        elif name in _SHELL_NAMES or name in _PS_NAMES:
            for i, arg in enumerate(args[:-1]):
                is_c_flag = arg.lower() in ("-c", "-command", "/c") or (
                    arg.startswith("-") and not arg.startswith("--") and "c" in arg[1:]
                    and name in _SHELL_NAMES
                )
                if is_c_flag:
                    tail = " ".join(args[i + 1:]) if name in _PS_NAMES else args[i + 1]
                    result.extend(_command_word_lists(tail, depth + 1))
                    break
        elif name == "find":
            for i, arg in enumerate(args):
                if arg in ("-exec", "-execdir", "-ok", "-okdir"):
                    tail: list[str] = []
                    for w in args[i + 1:]:
                        if w in (";", "+", "\\;"):
                            break
                        tail.append(w)
                    if tail:
                        result.append((tail, None))
                    break
    return result


def _stripped_word_lists(command: str) -> list[list[str]]:
    """The argv of every simple command in `command`, prefix-stripped (see
    _strip_command_prefix), separators dropped, empty results left out — the convenience shape
    checks/worker_git_write.py and checks/commit_pathspec.py want; checks/recursive_delete.py
    uses _command_word_lists directly instead, for the separator information."""
    return [
        stripped
        for words, _ in _command_word_lists(command)
        for stripped in [_strip_command_prefix(words)]
        if stripped
    ]


def _git_invocations_with_prefix(command: str) -> list[tuple[list[str], list[str]]]:
    """Every `git ...` invocation, as (the raw words consumed as a prefix before "git" —
    assignments and wrapper commands/flags, deliberately left UNstripped so a `GIT_DIR=`/
    `GIT_WORK_TREE=` assignment is still visible there, and git's own argv with its own name
    dropped). checks/worker_git_write.py's outside-project exemption needs the prefix (a
    GIT_DIR=/GIT_WORK_TREE= assignment there must disable that exemption, see its own module);
    checks/commit_pathspec.py, which does not care about that, uses `_git_invocations` instead."""
    result = []
    for words, _ in _command_word_lists(command):
        stripped = _strip_command_prefix(words)
        if stripped and _command_name(stripped[0]) == "git":
            prefix = words[: len(words) - len(stripped)]
            result.append((prefix, stripped[1:]))
    return result


def _git_invocations(command: str) -> list[list[str]]:
    """Every `git ...` invocation's own argv (its name dropped) — the simpler shape
    checks/commit_pathspec.py wants; see _git_invocations_with_prefix for the richer one."""
    return [args for _, args in _git_invocations_with_prefix(command)]
