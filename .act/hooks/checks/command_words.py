#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
# *recursion* into a nested interpreter are this module's own. Backtick spans come from the same
# tokenizer: each word it returns carries the contents of the spans that were live in it (`subs`,
# quote context already applied — a backtick in single quotes or escaped is not one), and those
# contents are recursed into like any other nested command (shell_targets.py's "Known limits" say
# what is still approximated).
#
# Safety net: the public `_command_word_lists` is the union of this module's word-lexer reading
# (`_command_word_lists_new`) and the previous reading kept verbatim in command_words_legacy.py —
# the legacy entries first, in their own order, then whatever only the lexer found. The lexer can
# therefore only add commands for the checks to look at, never drop one the previous reading had; if
# it raises, the legacy list stands alone. Everything below describes the lexer's reading.
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
#     shell_targets.py's own write-target scanner: nothing here is unbounded. At the cap the nested
#     text is not tokenized any further but read coarsely (command_words_legacy._coarse_word_lists:
#     quote characters are blanks, every separator cuts, every word that opens a nested command starts
#     a piece of its own): it used to be dropped, which let a command pass that only nested its
#     `eval`/`sh -c` or a backtick span one level deeper than the cap. The cost is a false hit for
#     quoted text that merely looks like a command at that depth, which nobody legitimately uses.
#   - a word that is nothing but backtick spans, in front of the command (`` `echo "` env -u X rm
#     -rf d ``), is skipped like an assignment: the span prints nothing or a word this reading cannot
#     know, and the command behind it is read as the command (a span that prints a real command name
#     makes this over-read, never under-read). A redirection in front of or inside the command
#     (`> f rm -rf d`, `git 2>/dev/null commit`) is read twice: once with its operand among the words
#     (how the lexer hands it back) and once with the operand left out, which is what bash runs.
#   - a write made from inside a program (`python -c "...git..."`, a script file) is invisible,
#     same limit shell_targets.py's own docstring states for its write-target scan.
#   - `find -exec ... {} \;` / `+`: the escaped `\;` form is recognized as shlex would hand it
#     back (a literal `;` token, since shlex's own backslash handling already strips the escape in
#     POSIX mode) as well as a raw `\;` string (seen from a whole-command fallback tokenization,
#     where the backslash can survive); both terminate the exec tail the same way.

from __future__ import annotations

from typing import Optional

from . import command_words_legacy as _legacy_words
# The coarse reading of text nested beyond the cap is shared with the legacy half: both halves must
# fail the same way there.
from .command_words_legacy import _coarse_word_lists

from .shell_targets import (
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
    _is_span_word,
    _line_mode_tokens,
    _shell_tokens,
)

__all__ = [
    "_PS_NAMES", "_SEGMENT_SPLIT_RE_FALLBACK", "_command_word_lists_new", "_command_word_lists",
    "_nested_word_lists", "_strip_command_prefix",
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
        elif _is_span_word(word):
            index += 1  # a word of backtick spans only: it prints nothing or something unknowable
        elif _command_name(word) in _WRAPPER_COMMANDS:
            wrapper_value_flags = _WRAPPER_VALUE_FLAGS.get(_command_name(word), frozenset())
            index += 1
            while index < len(words):
                arg = words[index]
                if arg in wrapper_value_flags:
                    index += 2 if index + 1 < len(words) else 1
                elif _WRAPPER_ARG_RE.match(arg) or _ASSIGNMENT_RE.match(arg) or _is_span_word(arg):
                    index += 1
                else:
                    break
        else:
            break
    return words[index:]


def _nested_word_lists(text: str, depth: int) -> list[tuple[list[str], Optional[str]]]:
    """The commands of a nested command text found at nesting `depth`: scanned one level further down
    by the word lexer, or — at _MAX_SCAN_DEPTH, where the previous code stopped looking and let the
    rest pass — read coarsely (command_words_legacy._coarse_word_lists), which fails toward seeing
    too much."""
    if depth >= _MAX_SCAN_DEPTH:
        return _coarse_word_lists(text)
    return _command_word_lists_new(text, depth + 1)


def _command_word_lists_new(command: str, depth: int = 0) -> list[tuple[list[str], Optional[str]]]:
    """The word lexer's half of _command_word_lists: every simple command in `command`, as (argv,
    preceding-separator) pairs — see this module's docstring for the contract and known limits. Recurses into `sh|bash|zsh|dash|ksh -c ...`,
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

    pairs: list[tuple[list[str], Optional[str], bool, list[str]]] = []
    words: list[str] = []
    plain: list[str] = []  # the same words without the operands of redirections
    redirected = False
    operand_next = False
    plain_word_last = False
    pending_sep: Optional[str] = None
    for text, is_op in tokens + [("\n", True)]:
        if not is_op:
            words.append(text)
            if operand_next:
                operand_next = False
            else:
                plain.append(text)
                plain_word_last = True
            continue
        operand_next = False
        if text not in _SEPARATOR_OPS:
            # A redirection or other non-separator operator -- not a command boundary. Its operand
            # (the file, the heredoc delimiter, the here-string) is not an argument of the command: bash
            # runs `> f rm -rf d` and `git 2>/dev/null commit` as `rm -rf d` and `git commit`. A bare
            # number right before the operator is its file descriptor.
            redirected = True
            if plain_word_last and plain and str(plain[-1]).isdigit():
                plain.pop()
            operand_next = True
            plain_word_last = False
            continue
        if words:
            pairs.append((words, pending_sep, redirected, plain))
        words, plain, redirected, plain_word_last = [], [], False, False
        pending_sep = None if text == "\n" else text

    result: list[tuple[list[str], Optional[str]]] = []
    for words, sep, redirected, plain in pairs:
        # With a redirection in the command the words are read both ways: as the lexer hands them back
        # (the operand among them, the way every earlier version read them) and without the operands.
        variants = [words]
        if redirected and plain and plain != words:
            variants.append(plain)
        result.extend((variant, sep) for variant in variants)
        nested: list[str] = []  # the texts of the commands this command runs, in the order found
        for word in words:
            if "$(" in word:
                nested.append(word[word.index("$(") + 2:])
        for word in words:
            nested.extend(getattr(word, "subs", ()))
        found_exec: list[list[str]] = []
        for variant in variants:
            stripped = _strip_command_prefix(variant)
            if not stripped:
                continue
            name, args = _command_name(stripped[0]), stripped[1:]
            if name == "eval":
                nested.append(" ".join(args))
            elif name in _SHELL_NAMES or name in _PS_NAMES:
                for i, arg in enumerate(args[:-1]):
                    is_c_flag = arg.lower() in ("-c", "-command", "/c") or (
                        arg.startswith("-") and not arg.startswith("--") and "c" in arg[1:]
                        and name in _SHELL_NAMES
                    )
                    if is_c_flag:
                        nested.append(" ".join(args[i + 1:]) if name in _PS_NAMES else args[i + 1])
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
                            found_exec.append(tail)
                        break
        seen_nested: list[str] = []
        for text in nested:
            if text not in seen_nested:
                seen_nested.append(text)
                result.extend(_nested_word_lists(text, depth))
        result.extend((tail, None) for tail in found_exec)
    return result


def _word_key(words: list[str]) -> tuple:
    """What makes two word lists the same for _command_word_lists' union: the words' text AND the
    lexer facts a plain `str` lacks (`bare`, `subs`), so an entry the lexer annotated is never
    dropped as a duplicate of the legacy entry with the same text."""
    key = []
    for word in words:
        bare = getattr(word, "bare", None)
        key.append((str(word), None if bare == word else bare, getattr(word, "subs", None) or None))
    return tuple(key)


def _command_word_lists(command: str, depth: int = 0) -> list[tuple[list[str], Optional[str]]]:
    """Every simple command in `command`, as (argv, preceding-separator) pairs — the contract and
    known limits are in this module's docstring.

    The result is the UNION of command_words_legacy's (the previous scanner, kept verbatim: its
    entries come first and in its own order, so anything that reads a position — the first command,
    a pipeline neighbour — sees what it always saw) and the word lexer's (_command_word_lists_new),
    whose entries not already present follow. The union is what keeps the lexer from ever weakening
    a check: whatever the previous scanner found is still found. An exception in the lexer's half
    — ValueError, RecursionError, a bug — is swallowed and the legacy half returned alone; one in
    the legacy half propagates, exactly as it did before the lexer existed."""
    legacy = _legacy_words._command_word_lists(command, depth)
    try:
        current = _command_word_lists_new(command, depth)
    except Exception:  # noqa: BLE001 — the legacy half stands alone, see the docstring
        return legacy
    merged = list(legacy)
    seen = {(_word_key(words), sep) for words, sep in legacy}
    for words, sep in current:
        key = (_word_key(words), sep)
        if key not in seen:
            seen.add(key)
            merged.append((words, sep))
    return merged


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
