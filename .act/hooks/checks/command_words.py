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
# One reading: the public `_command_word_lists` is the word lexer's reading (`_command_word_lists_new`)
# alone; an exception in it propagates and the calling check decides what that means.
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
#     text is not tokenized any further but read coarsely (_coarse_word_lists:
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

import shlex
from typing import Optional

from .shell_targets import (
    _join_line_continuations,
    _MAX_SCAN_DEPTH,
    _PIPE_OPS,
    _SEPARATOR_OPS,
    _SHELL_NAMES,
    _ASSIGNMENT_RE,
    _RESERVED_PREFIXES,
    _WRAPPER_ARG_RE,
    _WRAPPER_COMMANDS,
    _WRAPPER_VALUE_FLAGS,
    _ansi_c_unquote,
    _command_name,
    _is_span_word,
    _line_mode_tokens,
    _literal_output,
    _ps_reads_stdin,
    _reads_script_from_stdin,
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
# PowerShell's eval: the argument is read as a command line, like `eval`'s (not blocked wholesale).
_IEX_NAMES = frozenset({"iex", "invoke-expression"})

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


_UNQUOTE = {ord(char): " " for char in "'\"\\"} | {ord("`"): ";"}  # a backtick span is a command of its own
_NESTED_FLAG_WORDS = frozenset({"-c", "-command", "/c", "-exec", "-execdir", "-ok", "-okdir"})


def _coarse_word_lists(text: str) -> list[tuple[list[str], Optional[str]]]:
    """The remainder of a command nested deeper than _MAX_SCAN_DEPTH, read without any further tokenizing
    or recursion and without trusting a single thing in it: quote characters are blanks, a backtick is a
    separator, the text is cut at every separator (`_SEGMENT_SPLIT_RE_FALLBACK`, keeping which one), each piece's
    words are one command, and a piece is also read again from every word that opens a nested command
    (`eval`, a shell's `-c`, `find -exec`) — so `eval eval rm -rf d` still yields `rm -rf d`. The checks
    that consume the lists look at the command names and flags only, so a quoted `rm` in this text is
    seen as a command: a false hit for a nesting depth nobody legitimately uses, never a miss."""
    result: list[tuple[list[str], Optional[str]]] = []
    pieces = _re.split(r"(&&|\|\||[;&|()\n])", text.translate(_UNQUOTE))
    separator: Optional[str] = None
    for position, piece in enumerate(pieces):
        if position % 2:
            separator = None if piece == "\n" else piece
            continue
        words = piece.split()
        if not words:
            continue
        result.append((words, separator))
        for index, word in enumerate(words[:-1]):
            lowered = word.lower()
            if (
                _command_name(word) in ("eval", "iex", "invoke-expression")
                or lowered in _NESTED_FLAG_WORDS
                or (lowered.startswith("-") and not lowered.startswith("--") and "c" in lowered[1:])
            ):
                result.append((words[index + 1:], None))
    return result


def _nested_word_lists(
    text: str, depth: int, plain_only: bool = False,
) -> list[tuple[list[str], Optional[str]]]:
    """The commands of a nested command text found at nesting `depth`: scanned one level further down
    by the word lexer, or — at _MAX_SCAN_DEPTH, where the previous code stopped looking and let the
    rest pass — read coarsely (_coarse_word_lists), which fails toward seeing
    too much."""
    if depth >= _MAX_SCAN_DEPTH:
        return _coarse_word_lists(text)
    return _command_word_lists_new(text, depth + 1, plain_only=plain_only)


# A command whose arguments are only printed. Its single-quoted `$(...)` is then text, not a command to read -
# but only on a command line that prints and does nothing else (see _print_only_line): as soon as anything on
# the line could read the printed text (a pipe, a redirection, a group, a process substitution, a nested
# command, `$_`, any other command), the text is judged as before.
_TEXT_ONLY_COMMANDS = frozenset({"echo", "printf"})
# What may join the printing commands of such a line: a list separator or a line break. Any other operator (a
# pipe, a redirection, `&`, a parenthesis, `;;`) makes the line one that is judged as before.
_PRINT_ONLY_SEPARATORS = frozenset({";", "&&", "||", "\n"})


def _is_quoted_text_substitution(word: str) -> bool:
    """True when every `$(` in `word` stood inside single quotes or an ANSI-C `$'...'` (the lexer marks such a
    character "'" in `live`): nothing there is expanded. A plain `str` word, or one without `live`, is not."""
    live = getattr(word, "live", None)
    if live is None or len(live) != len(word):
        return False
    start = word.find("$(")
    while start >= 0:
        if live[start:start + 2] != "''":
            return False
        start = word.find("$(", start + 1)
    return True


def _is_print_only_word(word: str) -> bool:
    """True when the shell acts on nothing in `word` but plain characters: every `$` and backtick in it stood
    inside single quotes (the lexer's live mark "'"), or is the `$` that opens an ANSI-C `$'...'` (a live `$`
    right before single-quoted text), and no backtick span. A word without live marks (a plain `str`)
    qualifies only when it holds neither character. Allow-list: `'$(cmd)'` and `$'$(cmd)'` qualify; `"$(cmd)"`,
    `$_`, `${x}`, `\\$(cmd)` and `` `cmd` `` do not."""
    if getattr(word, "subs", ()):
        return False
    live = getattr(word, "live", None)
    if live is None or len(live) != len(word):
        return "$" not in word and "`" not in word
    for index, char in enumerate(word):
        if char not in "$`" or live[index] == "'":
            continue
        if char == "$" and live[index] == "L" and index + 1 < len(word) and live[index + 1] == "'":
            continue  # the `$` of `$'...'`
        return False
    return True


def _print_only_line(tokens: list, pairs: list) -> bool:
    """True when the whole command line prints and does nothing else, so that a single-quoted `$(` among its
    words is text nothing can read: every simple command of the line is a bare `echo` or `printf` (the word
    itself leads it - not `./echo`, no prefix, no keyword -, `printf` without `-v`), the commands are joined
    by nothing but `;`, `&&`, `||` or a line break (_PRINT_ONLY_SEPARATORS), and every word is plain
    (_is_print_only_word). Allow-list over the whole line: a pipe, a redirection, `&`, a group, a process
    substitution, a compound command (`for`, `if`, `{ ...; }`), `exec`, `trap`, an alias, function or variable
    definition, a nested shell, `$_`, `printf -v` and every other command on the line make it one that is
    judged as before."""
    if not pairs:
        return False
    for text, is_op in tokens:
        if is_op:
            if text not in _PRINT_ONLY_SEPARATORS:
                return False
        elif not _is_print_only_word(text):
            return False
    for words, _sep, _redirected, _plain in pairs:
        name = str(words[0]) if words else ""
        if name not in _TEXT_ONLY_COMMANDS:
            return False
        if name == "printf" and any(str(word).startswith("-v") for word in words[1:]):
            return False
    return True


def _piped_text(words: list[str]) -> Optional[str]:
    """The text a pipeline stage prints when that is literally known: `echo`/`printf` (shell_targets.
    _literal_output), `Write-Output`/`Write-Host` with literal arguments, or a lone string word (PowerShell
    sends a bare string down the pipe; quoting is gone from the word, so a lone word that is really a command
    name counts as text too, which only means it is read once more as a command). A PowerShell here-string
    word (`@'`, a line break, the body, a line break, `'@`) is unwrapped."""
    stripped = _strip_command_prefix(words)
    if not stripped:
        return None
    if len(stripped) == 1:
        word = str(stripped[0])
        for opener, closer in (("@\n", "\n@"), ("@\r\n", "\r\n@"), ("@'", "'@"), ('@"', '"@')):
            if word.startswith(opener) and word.endswith(closer) and len(word) >= len(opener) + len(closer):
                inner = word[len(opener):len(word) - len(closer)]
                return inner[inner.find("\n") + 1:] if opener in ("@'", '@"') and "\n" in inner else inner
        return _ansi_c_unquote(stripped[0])
    if _command_name(stripped[0]) in ("write-output", "write-host"):
        return " ".join(_ansi_c_unquote(word) for word in stripped[1:])
    return _literal_output(words, None)


def _is_bare_cat(words: list[str]) -> bool:
    """True for a `cat` stage with no file operand (only options, or `-`): it passes its input on."""
    stripped = _strip_command_prefix(words)
    return bool(stripped) and _command_name(stripped[0]) == "cat" and all(
        str(arg) == "-" or str(arg).startswith("-") for arg in stripped[1:]
    )


def _piped_script_texts(previous: list[str], words: list[str]) -> list[str]:
    """The text the stage before this one prints, when this stage runs it as a script: a POSIX shell that
    reads its script from standard input (`echo 'cmd' | bash`), `powershell`/`pwsh` that does (`| powershell
    -`, `-Command -`), or `Invoke-Expression`/`iex` without an argument. Empty otherwise. The text is read as
    a command line of its own, like the text behind `eval`."""
    stripped = _strip_command_prefix(words)
    if not stripped:
        return []
    name = _command_name(stripped[0])
    if name in _SHELL_NAMES:
        reads = _reads_script_from_stdin(words)
    elif name in ("powershell", "pwsh"):
        reads = _ps_reads_stdin([str(arg) for arg in stripped[1:]])
    elif name in _IEX_NAMES:
        reads = len(stripped) == 1
    else:
        return []
    if not reads:
        return []
    text = _piped_text(previous)
    return [text] if text else []


def _command_word_lists_new(
    command: str, depth: int = 0, print_only_text: bool = False, plain_only: bool = False,
) -> list[tuple[list[str], Optional[str]]]:
    """Every simple command in `command`, as (argv, preceding-separator) pairs — see this module's
    docstring for the contract and known limits. Recurses into `sh|bash|zsh|dash|ksh -c ...`,
    `pwsh|powershell -Command ...`, `cmd /c ...`, `eval ...`, `$(...)`, `` `...` `` and
    `find ... -exec ... ;|+`. With `print_only_text`, the text behind a single-quoted `$(` of an `echo` or
    `printf` on a top-level command line that prints and does nothing else (_print_only_line) is not read
    as commands. With `plain_only`, a command with a redirection comes back once, without the operands of its
    redirections, not also as the lexer hands it back (for a reader that takes the operands of a command)."""
    command = _join_line_continuations(command)
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

    # Only the top-level command line, and only when the whole of it prints and does nothing else, keeps a
    # single-quoted `$(` as text (_print_only_line); judged once for the line, since every command on such a
    # line is a printing one.
    print_only = print_only_text and depth == 0 and _print_only_line(tokens, pairs)

    result: list[tuple[list[str], Optional[str]]] = []
    for pair_index, (words, sep, redirected, plain) in enumerate(pairs):
        next_pair = pairs[pair_index + 1] if pair_index + 1 < len(pairs) else None
        # With a redirection in the command the words are read both ways: as the lexer hands them back
        # (the operand among them, the way every earlier version read them) and without the operands.
        variants = [words]
        if redirected and plain and plain != words:
            if plain_only:
                variants = [plain]
            else:
                variants.append(plain)
        result.extend((variant, sep) for variant in variants)
        nested: list[str] = []  # the texts of the commands this command runs, in the order found
        for word in words:
            if "$(" in word:
                if print_only and _is_quoted_text_substitution(word):
                    continue
                nested.append(word[word.index("$(") + 2:])
        for word in words:
            nested.extend(getattr(word, "subs", ()))
        if sep in _PIPE_OPS and pair_index > 0:
            source = pair_index - 1
            # a `cat` without a file hands its input on unchanged: `echo 'cmd' | cat | bash`
            while source > 0 and pairs[source][1] in _PIPE_OPS and _is_bare_cat(pairs[source][0]):
                source -= 1
            nested.extend(_piped_script_texts(pairs[source][0], words))
        found_exec: list[list[str]] = []
        for variant in variants:
            stripped = _strip_command_prefix(variant)
            if not stripped:
                continue
            name, args = _command_name(stripped[0]), stripped[1:]
            if len(stripped) < len(variant) and any(
                _command_name(w) == "parallel" for w in variant[:len(variant) - len(stripped)]
            ):
                # parallel runs its command text once per argument: the words up to `:::`/`::::` are a
                # command line (`parallel 'rm -rf {}' ::: x`), read like eval's text.
                command_words: list[str] = []
                for w in stripped:
                    if w.startswith(":::"):
                        break
                    command_words.append(w)
                if command_words:
                    nested.append(" ".join(command_words))
            if name == "eval":
                nested.append(" ".join(_ansi_c_unquote(arg) for arg in args))
            elif name in _IEX_NAMES:
                # PowerShell's eval: the argument text is a command line; an optional leading
                # -Command (or a prefix of it) names the parameter and is not part of it.
                if args and args[0].lower().startswith("-command:"):
                    args = [args[0][len("-command:"):]] + args[1:]  # `-Command:"..."`, value glued on
                elif args and len(args[0]) > 1 and args[0].startswith("-") and "-command".startswith(args[0].lower()):
                    args = args[1:]
                if not args and next_pair is not None and next_pair[1] == "(":
                    args = list(next_pair[0])  # `iex("...")`: the parenthesis is a separator, the text follows it
                nested.append(" ".join(args))
            elif name in _SHELL_NAMES or name in _PS_NAMES:
                for i, arg in enumerate(args[:-1]):
                    is_c_flag = arg.lower() in ("-c", "-command", "/c") or (
                        arg.startswith("-") and not arg.startswith("--") and "c" in arg[1:]
                        and name in _SHELL_NAMES
                    )
                    if is_c_flag:
                        nested.append(
                            " ".join(_ansi_c_unquote(rest) for rest in args[i + 1:]) if name in _PS_NAMES
                            else _ansi_c_unquote(args[i + 1])
                        )
                        break
            elif name == "find":
                i = 0
                while i < len(args):  # every -exec/-execdir/-ok/-okdir block, not only the first
                    if args[i] in ("-exec", "-execdir", "-ok", "-okdir"):
                        tail: list[str] = []
                        i += 1
                        while i < len(args) and args[i] not in (";", "+", "\\;"):
                            tail.append(args[i])
                            i += 1
                        if tail:
                            found_exec.append(tail)
                    i += 1
        seen_nested: list[str] = []
        for text in nested:
            if text not in seen_nested:
                seen_nested.append(text)
                result.extend(_nested_word_lists(text, depth, plain_only))
        result.extend((tail, None) for tail in found_exec)
        # The command behind -exec may itself run a command line (`-exec sh -c 'rm -rf {}' \;`): read
        # it again as text, so the same nesting rules (sh -c, eval, find -exec, ...) apply to it.
        for tail in found_exec:
            result.extend(_nested_word_lists(shlex.join(tail), depth, plain_only))
    return result


def _command_word_lists(
    command: str, depth: int = 0, plain_only: bool = False,
) -> list[tuple[list[str], Optional[str]]]:
    """Every simple command in `command`, as (argv, preceding-separator) pairs — the contract and
    known limits are in this module's docstring. One reading, the word lexer's, with the text of a
    single-quoted `$(` of a printing command left alone (_command_word_lists_new); `plain_only` as there."""
    return _command_word_lists_new(command, depth, print_only_text=True, plain_only=plain_only)


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
