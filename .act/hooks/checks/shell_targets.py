#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Bash write-target scanner — shared by checks/write_guard.py (check 1) and
#          checks/write_scope.py (check 1c). Both need the same answer for a Bash command: which
#          paths does it write to, and against which directory is a relative one resolved. Two
#          earlier versions answered that with regexes over the raw text and failed review both
#          times (2026-09-23): the first read a `>` inside quotes or a heredoc body as a
#          redirection, the second masked quotes and heredocs by regex and thereby hid real
#          redirections (`echo \" > f \"`, `echo don\'t > f`, a quoted "<<EOF", ...). This version
#          tokenizes instead — a small POSIX-style word lexer (_shell_tokens: the quoting rules of
#          shlex plus backticks) with the operator characters as their own tokens — so quoting and
#          escaping are decided by one tokenizer, and operators are read from the token stream,
#          never from raw text. That tokenizer also knows backtick command substitution: a backtick
#          outside single quotes and not escaped opens a span that runs to the next unescaped
#          backtick, whatever quotes the span itself contains (bash finds the end that way); the
#          span stays part of its word (whitespace and operators inside it do not split the word) and
#          its content is attached to that word (_Word.subs) to be scanned as a command of its own.
#          A backtick inside single quotes or escaped is plain text. Steps (_scan_command):
#   1. backslash-newline continuations are joined where bash joins them (_join_line_continuations):
#      not in a comment, not in single quotes, not in the body of a heredoc with a quoted delimiter;
#      a `$(...)` inside double quotes is read as a text of its own there;
#   2. line mode: every line is tokenized on its own; a line whose token stream carries a real
#      `<<`/`<<-` operator plus delimiter has the heredoc body skipped up to its terminator line —
#      several heredocs on one line in turn, and nothing at all if a terminator line is missing
#      (_line_mode_tokens); the `$(...)`/backtick parts of an unquoted-delimiter body, which bash
#      does run, are kept as commands of their own; the body of a heredoc fed to a shell
#      (`bash <<EOF`, `sh -s <<EOF`, `sh - <<EOF`, `cat <<EOF | bash`, `{ bash; } <<EOF`, not
#      `bash -c ... <<EOF`) is a script and is scanned whole as a command text of its own
#      (_heredoc_shell_flags), quoted delimiter or not;
#   3. conservative fallback when a line does not tokenize on its own (an unclosed quote, typically
#      a string spanning lines) or the command may use ANSI-C quoting `$'...'`, which this lexer does
#      not know (a `$'` that is only text — in quotes, escaped, in a comment, in a quoted heredoc body —
#      does not count, see the known limits): the whole command is tokenized in one go (newline as an
#      operator, a multi-line string becomes one token, no heredoc skipping except that the bodies of
#      quoted-delimiter heredocs are cut out first); if that fails too, or for `$'...'` in any case,
#      every word after a `>`-style operator in the raw text also counts as a target
#      (_raw_redirect_targets) — over-blocking is the accepted price there — and the tokens each
#      attempt had read before the word that broke it (an earlier line, a command before the
#      unclosed quote) are scanned as well (_TokenizeError.partial);
#   4. the token stream is walked command by command (_scan_tokens): redirections, the write
#      commands of _simple_command_targets, `cd` for the base directory, and the contents of
#      `sh -c "..."`, `eval`, `$(...)` and backtick spans (the words' own `subs`) scanned
#      recursively.
#
# Safety net: the lexer is newer than the scanner it replaced, and a blocking check must never be
# weaker than before. So the public result, _bash_write_targets, is the union of this scan and the
# previous scanner kept verbatim in shell_targets_legacy.py (command_words.py does the same with
# command_words_legacy.py for its word lists, secret_scan.py with its commit detection). Anything
# this lexer reads differently or fails on (an exception of any kind, a recursion bound) therefore
# costs nothing: the legacy half still reports what it always did. The known limits below describe
# the lexer's half; the union only ever adds to them.
#
# Known limits (a target missed here is simply not checked — resolved toward over-blocking wherever
# the command itself is ambiguous):
#   - writes made from inside a program are invisible: `python -c "open(...)"`, a script file,
#     `find -exec`, `xargs` fed from stdin, an alias or shell function;
#   - a target containing a variable, a command substitution, a brace expansion or a leading `~` is
#     never resolved (_is_dynamic_target): check 1c denies it, check 1 passes it unless its text
#     names .act/;
#   - an fd number glued to a redirection (`2>`) cannot be told apart from a separate word (`echo
#     2 > f`) once tokenized, so a bare number right before a redirection is dropped as fd;
#   - only the directory changes listed in _scan_tokens are followed; anything else there makes
#     the base unknown rather than guessed;
#   - not recognized as writers at all: `patch`, a `tar`/`unzip` extraction into the
#     implicit current directory (no explicit `-C`/`-d`), `find -delete` with no leading path
#     operand, `git apply`/`stash`/`reset --hard`/`clean`. `tar -x -C <dir>`, `unzip -d <dir>` and
#     `find <path> ... -delete` *are* recognized (see _simple_command_targets) since their target
#     is then determinable the same cheap way `cd`/`-C` already is; the rest is genuinely open-
#     ended (`patch`'s target is named inside the diff text itself, `git apply`'s likewise) and
#     is only ever caught by the raw-redirect fallback if it happens to also redirect;
#   - `git checkout <ref> -- .act/x` (or `git restore --source=<ref> -- .act/x`) is recognized as a
#     write to `.act/x` (both are in _GIT_WRITES_WORKER_SCOPE, and check 1's own
#     _GIT_WRITES_TEMPLATE_GUARD leaves them out on purpose so the orchestrator can restore a
#     template file this way) but not as what it actually does: replace `.act/x` with whatever
#     content `<ref>` happens to hold, including content a worker itself committed earlier in the
#     same session — a restore, not a rewrite from scratch. Accepted as a residual risk of trusting
#     the orchestrator's own git history rather than a gap in target detection;
#   - a line opening a heredoc (`<<`/`<<-`) that also contains `[`, `${`, `$[` or a backtick opens
#     no heredoc at all here (_NO_HEREDOC_MARKERS, since 2026-09-23) — safe on the side that matters
#     (a real heredoc body is never mistakenly skipped as something else), but its actual body lines
#     are then scanned as ordinary commands instead of being skipped, which can raise a spurious
#     target from body text that was never going to run as a command (over-scanning, not a missed
#     write);
#   - backtick spans are cut out by the tokenizer itself (_read_word), so their quote context is
#     known. Inside double quotes a backtick normally opens a span, but a `$(...)`, `$((...))`,
#     `${...}` or `$[...]` is consumed whole first (_collect_dq_expansion): bash reads the inside of
#     those with their own quoting, where a single-quoted run is literal, so a backtick in such a
#     run opens no span (and therefore cannot swallow a redirection after the string). An unquoted
#     `$(...)` is still handled by the operator mechanism (`$` a word character, the parentheses
#     operators) and a word that contains `$(` after dequoting is scanned again as text, so a `$(`
#     inside single quotes outside double quotes is still recursed into as if bash ran it (a false
#     block, never a miss). An `$((...))` is treated like a `$(...)` command substitution for
#     scanning (over-scanning its arithmetic as if it were a command — the safe side). A line
#     tokenized on its own that ends inside an unquoted span does not tokenize at all (bash ends the
#     span in a later line, which only the whole-command fallback sees); in whole-command mode a span
#     with no closing backtick runs to the end of the command and is scanned as a command. The word
#     is kept verbatim, so a target made of a span is dynamic (_is_dynamic_target) and check 1c
#     denies it; its command name is read from the word with the spans cut out (_Word.bare), since
#     `` `;`rm `` runs `rm` — and for the same reason a span glued to a `cd`/`pushd`/`popd` name
#     leaves the base directory unknown rather than following a move bash does not make. When a span
#     is instead an *operand* of a last-operand writer (`cp`/`install`/`ln`/`rsync`), it can expand
#     to empty and shift which word is the destination, so every operand of that command is then
#     treated as a possible target (_simple_command_targets);
#   - a command name that is a *separate* word which is itself a backtick span (space-separated,
#     `` `echo x` rm -rf d `` / `` `echo "` touch .act/x ``): bash runs whatever the span prints, or —
#     when it prints nothing — the word after it. Such a word is skipped like an assignment
#     (_is_span_word), so the word behind it is read as the command: the "prints nothing" case is
#     caught, and a span that does print a command name is over-read (its first operand taken for the
#     command), never under-read. What stays open is the command the span itself prints: `` `echo rm`
#     -rf d `` runs `rm -rf d`, the name being whatever the span's output is — unknowable here, the
#     span's own content is still scanned. Resolved toward over-blocking only when some other,
#     determinable part of the command names a target;
#   - ANSI-C quoting `$'...'` is told from a `$'` that is only text by a pass over the whole command
#     (shell_targets_legacy._QuoteScan, shared by both halves) that follows bash's quoting. Wherever
#     that pass does not model something it gives up and counts the `$'` as live, so the answer errs
#     toward the raw-redirect search: arithmetic `((`/`$((`/`$[`, a `${...}` beyond a plain name, a
#     `$(...)` in a command that also has a `case`, a comment holding any quote/expansion character,
#     a backtick span holding `$'`, an unterminated quote or span, a heredoc line that cannot be
#     placed, nesting beyond 32 levels. Bodies of heredocs with a quoted delimiter are cut out before
#     the whole-command fallback (bash never runs them); a body terminated only by a line the
#     tokenizer accepts but bash does not (` EOF` with a blank in front) stays in;
#   - text nested deeper than _MAX_SCAN_DEPTH (`eval` inside `eval` ..., `$(...)` and backtick spans
#     count too) is not read any further: it is reported as one target that names no knowable path
#     (`$(` plus the remainder) next to its raw redirections, which check 1c denies and check 1 denies
#     when the remainder names .act/.

from __future__ import annotations

import bisect
import functools
import os
import re
import socket
import sys
from pathlib import Path
from typing import Optional

from . import shell_targets_legacy as _legacy_targets
# The `$'` / quoted-heredoc pass is shared with the legacy half: one definition of what bash reads as
# ANSI-C quoting, so the two halves of the union never disagree on it.
from .shell_targets_legacy import (
    _may_use_ansi_c_quoting, _quote_model_applies, _without_quoted_heredoc_bodies,
)

__all__ = [
    "_SHELL_OPERATOR_CHARS", "_SHELL_OPERATORS", "_LIST_END_OPS", "_PIPE_OPS", "_SEPARATOR_OPS",
    "_WRITE_REDIRECT_OPS", "_FD_DUP_WORD_RE", "_LINE_CONTINUATION_RE",
    "_join_line_continuations", "_RAW_REDIRECT_RE", "_HEREDOC_OPEN_RE",
    "_MAX_SCAN_DEPTH", "_GITBASH_DRIVE_RE", "_WIN32_PREFIXED_DRIVE_RE", "_WIN32_PREFIXED_UNC_RE",
    "_WIN32_ADMIN_SHARE_RE", "_LOCAL_HOST_NAMES", "_IGNORABLE_TARGETS", "_DYNAMIC_TARGET_RE",
    "_SIMPLE_DIR_RE", "_ASSIGNMENT_RE", "_RESERVED_PREFIXES", "_WRAPPER_COMMANDS",
    "_WRAPPER_ARG_RE", "_WRAPPER_VALUE_FLAGS", "_SHELL_NAMES", "_ALL_OPERAND_WRITERS",
    "_LAST_OPERAND_WRITERS", "_VALUE_FLAGS", "_SED_INPLACE_FLAG_RE", "_GIT_GLOBAL_VALUE_FLAGS",
    "_GIT_WRITES_TEMPLATE_GUARD", "_GIT_WRITES_WORKER_SCOPE", "_Token", "_Target", "_Bases",
    "_NO_HEREDOC_MARKERS", "_local_host_names", "_to_native_path", "_is_remote_unc", "_resolve_path",
    "_is_ignorable_write_target", "_is_dynamic_target",
    "_is_absolute_target", "_Word", "_TokenizeError", "_backtick_span", "_closed_backtick_spans",
    "_EXPANSION_CLOSERS", "_skip_squote", "_collect_dq_nested", "_collect_dq_expansion", "_read_word",
    "_split_operator_run", "_shell_tokens", "_heredoc_delimiters", "_heredoc_shell_flags",
    "_heredoc_may_feed_shell", "_command_prefix_end", "_heredoc_terminator", "_body_substitutions",
    "_line_mode_tokens", "_may_use_ansi_c_quoting", "_quote_model_applies",
    "_without_quoted_heredoc_bodies",
    "_raw_redirect_targets", "_command_name", "_is_span_word", "_operands", "_cd_bases",
    "_pairs", "_git_targets", "_download_targets", "_simple_command_targets", "_scan_tokens",
    "_scan_command", "_bash_write_targets_new", "_bash_write_targets",
]

_SHELL_OPERATOR_CHARS = "();<>|&"
# Longest first: a run of operator characters from shlex ("2>&1" yields ">&", "x;>f" yields ";>")
# is split greedily into these (_split_operator_run).
_SHELL_OPERATORS = (
    "&>>", "<<<", ";;&", ">>", ">|", "&>", ">&", "<&", "<>", "<<", "&&", "||", "|&", ";;", ";&",
    ">", "<", "|", "&", ";", "(", ")", "\n",
)
_LIST_END_OPS = frozenset({";", "&", "\n", ";;", ";&", ";;&"})
_PIPE_OPS = frozenset({"|", "|&"})
_SEPARATOR_OPS = _LIST_END_OPS | _PIPE_OPS | {"&&", "||", "(", ")"}
_WRITE_REDIRECT_OPS = frozenset({">", ">>", ">|", "&>", "&>>", "<>"})
# `>&N`, `>&N-`, `>&-`: a file-descriptor duplication/close, never a file. `>& word` with any other
# word is bash's "stdout and stderr to file" and therefore a target.
_FD_DUP_WORD_RE = re.compile(r"^(?:\d+-?|-)$")

# Backslash-newline (an odd number of backslashes before the newline) is a line continuation.
_LINE_CONTINUATION_RE = re.compile(r"(?<!\\)((?:\\\\)*)\\\n")
# What _join_line_continuations stops at: a backslash, a quote, a possible comment, a possible heredoc
# operator, a newline. Everything between is copied as it is.
_JOIN_SPECIAL_RE = re.compile(r"[\\'\"#<\n]")
# Inside a `$(...)` the parentheses count too: the substitution ends at the `)` that closes it.
_JOIN_NESTED_SPECIAL_RE = re.compile(r"[\\'\"#<\n()]")
# `$(...)` inside double quotes inside `$(...)` ...: deeper than this the rest is copied unjoined.
_JOIN_MAX_NESTING = 8
# A `#` starts a comment after one of these (or at the very start), as the tokenizer reads it.
_JOIN_WORD_END = " \t\r\n;&|()<>"


def _join_heredoc_bodies(
    text: str, start: int, pending: list[tuple[str, bool, bool]], out: list[str]
) -> int:
    """Copy the bodies of the heredocs a finished line opened (`pending`: delimiter, quoted, dash) to
    `out`, starting at `text[start]`, and return the index where ordinary reading goes on. The body of
    a heredoc with a quoted delimiter is copied as it stands: bash keeps a backslash-newline there. An
    unquoted body is joined, and its terminator is compared after joining, as bash does. A heredoc with
    no terminator line is none: the text from `start` on stays ordinary text."""
    index = start
    for delimiter, quoted, dash in pending:
        copied: list[str] = []
        position = index
        line_end = -1
        found = False
        while True:
            newline = text.find("\n", position)
            line_end = len(text) if newline < 0 else newline
            line = text[position:line_end]
            if not quoted:
                while (len(line) - len(line.rstrip("\\"))) % 2 == 1 and line_end < len(text):
                    next_newline = text.find("\n", line_end + 1)
                    next_end = len(text) if next_newline < 0 else next_newline
                    line = line[:-1] + text[line_end + 1:next_end]
                    line_end = next_end
            copied.append(line)
            if (line.lstrip("\t") if dash else line) == delimiter:
                found = True
                break
            if line_end >= len(text):
                break
            position = line_end + 1
        if not found:
            return index
        out.append("\n".join(copied) + ("\n" if line_end < len(text) else ""))
        index = min(line_end + 1, len(text))
    return index


def _heredoc_delimiter_at(text: str, start: int) -> tuple[Optional[tuple[str, bool, bool]], int]:
    """Read the delimiter of the heredoc whose `<<` sits at `text[start]`: ((delimiter, quoted, dash),
    index after it), or (None, start + 2) when there is none this pass can place (an empty word, an
    unterminated quote, a trailing backslash, or a word holding a backtick — a line with a backtick
    opens no heredoc anyway, _opens_no_heredoc, so its pending list is dropped). Bash performs no
    expansion on the delimiter word, so an unquoted `$` is a literal part of it: `<<'E'$x` is a quoted
    heredoc with the delimiter `E$x`, and its body keeps a backslash-newline. `quoted` is set when any
    part of the word was single-, double- or backslash-quoted — which is what both bash's body
    expansion and this join pass's continuation handling turn on, so the two agree on the body."""
    size = len(text)
    index = start + 2
    dash = index < size and text[index] == "-"
    if dash:
        index += 1
    while index < size and text[index] in " \t":
        index += 1
    parts: list[str] = []
    quoted = False
    while index < size and text[index] not in _JOIN_WORD_END:
        char = text[index]
        if char == "'":
            end = text.find(char, index + 1)
            if end < 0:
                return None, start + 2
            parts.append(text[index + 1:end])
            quoted = True
            index = end + 1
        elif char == '"':
            # Inside double quotes `$` and a backtick are literal in a delimiter, a backslash escapes
            # only `$`, a backtick, `"` and itself (and removes a newline); the delimiter is what is left.
            inner_parts: list[str] = []
            cursor = index + 1
            while cursor < size and text[cursor] != '"':
                if text[cursor] == "\\" and cursor + 1 < size and text[cursor + 1] in '$`"\\\n':
                    if text[cursor + 1] != "\n":
                        inner_parts.append(text[cursor + 1])
                    cursor += 2
                else:
                    inner_parts.append(text[cursor])
                    cursor += 1
            if cursor >= size:
                return None, start + 2
            parts.append("".join(inner_parts))
            quoted = True
            index = cursor + 1
        elif char == "\\":
            if index + 1 >= size:
                return None, start + 2
            parts.append(text[index + 1])
            quoted = True
            index += 2
        elif char == "$":
            # No expansion happens on the delimiter word, so an unquoted `$` is a literal part of it.
            parts.append(char)
            index += 1
        elif char == "`":
            # A backtick could open a span running over spaces and newlines; a line holding one opens
            # no heredoc at all (_opens_no_heredoc) and drops its pending list, so give up on it here.
            return None, start + 2
        else:
            parts.append(char)
            index += 1
    delimiter = "".join(parts)
    if not delimiter:
        return None, start + 2
    return (delimiter, quoted, dash), index


def _join_line_continuations(command: str) -> str:
    """`command` with every backslash-newline removed that bash removes, and only those. Bash keeps
    the pair in a comment (the comment ends at the newline), in single quotes, and in the body of a
    heredoc with a quoted delimiter; everywhere else — unquoted, in double quotes, in an unquoted
    heredoc body — it is a line continuation and leaves nothing. An escaped backslash before the
    newline (`\\\\` + newline) is no continuation and stays. One pass over the text with just enough
    of bash's quoting to tell those places apart; a `$(...)` inside double quotes is read again as a
    text of its own (its comments, quotes and heredocs count there), as bash does. A line that opens no
    heredoc for the line-wise tokenizer (`$((1<<2))`, see _opens_no_heredoc) opens none here either, and
    the delimiter that decides whether a body is kept is read by _heredoc_delimiter_at the same way the
    tokenizer reads it — an unquoted `$` is literal, `quoted` turns only on real quoting — so a mixed
    delimiter like `<<'E'$x` counts as a quoted heredoc in both passes and its body is left alone.
    Not modelled: a `)` that is part of a `case` pattern inside such a `$(...)` ends it early, and a
    backtick span or a `$(...)` nested deeper than _JOIN_MAX_NESTING is copied with its pairs left in
    — there the tokenizers read the pair for themselves, and the scan of that nested text joins again."""
    if "\\\n" not in command:
        return command
    return _join_scan(command, 0, 0)[0]


def _join_scan(command: str, index: int, level: int) -> tuple[str, int, bool]:
    """The joining pass of _join_line_continuations from `command[index]`. `level` 0 reads to the end of
    the text; a higher level is the inside of a `$(...)` and stops after the `)` that closes it. Returns
    (joined text without that `)`, index where the caller goes on, whether the closing `)` was found)."""
    out: list[str] = []
    last = ""
    pending: list[tuple[str, bool, bool]] = []
    depth = 0
    line_first = 0  # index in `out` of the first piece of the line being read
    size = len(command)
    special = _JOIN_NESTED_SPECIAL_RE if level else _JOIN_SPECIAL_RE
    while index < size:
        match = special.search(command, index)
        if match is None:
            out.append(command[index:])
            index = size
            break
        position = match.start()
        if position > index:
            out.append(command[index:position])
            last = command[position - 1]
        char = command[position]
        if char == "\\":
            if position + 1 >= size:
                out.append(char)
                index = size
            elif command[position + 1] == "\n":
                index = position + 2  # a line continuation: nothing is emitted
            else:
                out.append(command[position:position + 2])
                last = command[position + 1]
                index = position + 2
        elif char == "'":
            end = command.find("'", position + 1)
            end = size if end < 0 else end + 1
            out.append(command[position:end])
            last = command[end - 1]
            index = end
        elif char == '"':
            piece = ['"']
            cursor = position + 1
            while cursor < size:
                inner = command[cursor]
                if inner == "\\" and cursor + 1 < size:
                    if command[cursor + 1] != "\n":
                        piece.append(command[cursor:cursor + 2])
                    cursor += 2
                elif inner == '"':
                    piece.append(inner)
                    cursor += 1
                    break
                elif inner == "$" and command.startswith("$(", cursor):
                    if level >= _JOIN_MAX_NESTING:
                        piece.append(command[cursor:])
                        cursor = size
                        break
                    text, cursor, closed = _join_scan(command, cursor + 2, level + 1)
                    piece.append("$(" + text + (")" if closed else ""))
                elif inner == "`":
                    end = cursor + 1
                    while end < size and command[end] != "`":
                        end += 2 if command[end] == "\\" else 1
                    end = min(end + 1, size)
                    piece.append(command[cursor:end])
                    cursor = end
                else:
                    piece.append(inner)
                    cursor += 1
            out.append("".join(piece))
            last = out[-1][-1]
            index = cursor
        elif char == "#":
            if last == "" or last in _JOIN_WORD_END:
                end = command.find("\n", position)
                end = size if end < 0 else end
                out.append(command[position:end])
                last = command[end - 1]
                index = end
            else:
                out.append("#")
                last = "#"
                index = position + 1
        elif char == "<":
            if command.startswith("<<<", position):
                out.append("<<<")
                last = "<"
                index = position + 3
            elif command.startswith("<<", position):
                spec, end = _heredoc_delimiter_at(command, position)
                if spec is not None:
                    pending.append(spec)
                out.append(command[position:end])
                last = command[end - 1]
                index = end
            else:
                out.append("<")
                last = "<"
                index = position + 1
        elif char == "(":
            depth += 1
            out.append("(")
            last = "("
            index = position + 1
        elif char == ")":
            if depth == 0:
                return "".join(out), position + 1, True
            depth -= 1
            out.append(")")
            last = ")"
            index = position + 1
        else:  # a newline outside every quote: heredocs opened on the line just ended start here
            if pending and _opens_no_heredoc("".join(out[line_first:])):
                pending = []
            out.append("\n")
            last = "\n"
            index = position + 1
            if pending:
                index = _join_heredoc_bodies(command, index, pending, out)
                pending = []
            line_first = len(out)
    return "".join(out), index, False


_RAW_REDIRECT_RE = re.compile(r"(?:&>>|&>|>>|>\||>&|<>|>)\s*([^\s;&|()<>]+)")
# The word right after a heredoc operator in the raw line (not `<<<`), to see whether it was quoted.
_HEREDOC_OPEN_RE = re.compile(r"(?<!<)<<(?!<)-?[ \t]*(\S*)")
_MAX_SCAN_DEPTH = 4

# A Git-Bash-style absolute path ("/c/work/...", the MSYS form a worker's own Bash commands often
# use on Windows) rewritten to the native drive form ("C:/work/...") so Path() and glob matching
# treat it the same as a Windows-native absolute path. Only ever rewritten on win32 — elsewhere a
# leading "/x/..." is an ordinary absolute path and must be left alone.
_GITBASH_DRIVE_RE = re.compile(r"^[\\/]([A-Za-z])[\\/](.*)$")
# Three more spellings Windows accepts for a path on a local drive, each of which Path.resolve()
# hands back *verbatim* rather than as the plain drive form every check compares against (review,
# 2026-09-26, finding M-c: a `Write` of `\\?\D:\proj\.act\x.md` or of
# `\\localhost\D$\proj\.act\x.md` resolved to exactly that text, so `_is_under_project_act`'s
# prefix test against `D:\proj\.act` never matched and the write-guard let it through — the same
# hole for the docs/ai/ guard and, in the other direction, a worker's in-scope path judged out of
# scope). All three are mapped to the plain drive form by _to_native_path, before *and* after
# resolving (a `\\?\Volume{...}\` path resolves to `\\?\D:\...`, i.e. the prefix can appear on the
# way out even when it was not on the way in):
#   - the extended-length / device prefix in front of a drive: `\\?\D:\x`, `\\.\D:\x` -> `D:\x`
#     (only with a drive letter right behind it — `\\.\pipe\x` and friends are not file paths and
#     stay as they are);
#   - the extended-length UNC form: `\\?\UNC\host\share\x` -> `\\host\share\x` (then judged like
#     any other UNC path, i.e. by the next rule when it is an administrative share);
#   - an administrative share of *this* machine: `\\localhost\D$\x`, `\\127.0.0.1\D$\x`,
#     `\\<this computer's name>\D$\x` -> `D:\x`. A share on any other host is left alone: it is not
#     this project (a worker's write there is out of its root-relative scope anyway), and no check
#     ever touches the network to find out more — an unreachable host would stall the hook, which
#     the harness reads as "allow".
_WIN32_PREFIXED_DRIVE_RE = re.compile(r"^[\\/]{2}[?.][\\/](?=[A-Za-z]:)")
_WIN32_PREFIXED_UNC_RE = re.compile(r"^[\\/]{2}\?[\\/]UNC(?=[\\/])", re.IGNORECASE)
_WIN32_ADMIN_SHARE_RE = re.compile(r"^[\\/]{2}(?P<host>[^\\/]+)[\\/](?P<drive>[A-Za-z])\$(?=[\\/]|$)")
_LOCAL_HOST_NAMES = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})

# A "target" that is not a file in the project: the null device in its Unix and Windows spellings
# and the standard streams (`ls src 2>/dev/null`, `cmd >NUL 2>&1`, `echo x >/dev/stderr`).
_IGNORABLE_TARGETS = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty", "nul", "nul:"}
# A target whose text the shell still expands: variable, command substitution, brace expansion,
# home directory. Its real path is unknown here (see _is_dynamic_target).
_DYNAMIC_TARGET_RE = re.compile(r"[$`{]|^~")
# A literal directory operand for `cd`/`git -C` — anything else leaves the base unknown.
_SIMPLE_DIR_RE = re.compile(r"^[\w./:-]+$")

_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
_RESERVED_PREFIXES = frozenset(
    {"!", "{", "}", "if", "then", "else", "elif", "fi", "do", "done", "while", "until", "time"}
)
_WRAPPER_COMMANDS = frozenset(
    {"sudo", "env", "command", "builtin", "exec", "nohup", "nice", "timeout", "xargs", "stdbuf",
     "busybox", "setsid", "caffeinate", "parallel"}  # last four: list modelled on cc-safety-net (MIT, github.com/kenryu42/cc-safety-net)
)
# A wrapper's own option or number/duration (`nice -n 5`, `timeout 10s`), skipped before its command.
_WRAPPER_ARG_RE = re.compile(r"^(?:-.*|\d+(?:\.\d+)?[smhd]?)$")
# A wrapper's own option that takes a separate following word as its value (`env -u VAR rm`,
# `timeout -s KILL 5 rm`, `sudo -u name rm`) — that value word must be skipped too, not
# mistaken for the wrapped command itself: on its own it matches neither _WRAPPER_ARG_RE (it does
# not start with "-" and is not a bare number/duration) nor an assignment, so the skip loop in
# _simple_command_targets used to stop right there and read the option's value as if it were the
# command name, hiding the real one (and its write targets) after it. `--flag=value` needs no entry
# here — it is already one word, already matched by _WRAPPER_ARG_RE.
_WRAPPER_VALUE_FLAGS = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}),
    "timeout": frozenset({"-s", "--signal", "-k", "--kill-after"}),
    "sudo": frozenset({"-u", "--user", "-g", "--group", "-p", "--prompt", "-h", "--host",
                        "-r", "--role", "-t", "--type"}),
    "nice": frozenset({"-n", "--adjustment"}),
    "stdbuf": frozenset({"-i", "--input", "-o", "--output", "-e", "--error"}),
    # GNU parallel: job count / argument file / replace string given as a separate word (`-j 50%`).
    "parallel": frozenset({"-a", "--arg-file", "-j", "--jobs", "-n", "--max-args", "-N", "-L",
                            "-S", "--sshlogin", "-I", "--joblog", "--colsep", "-C", "--results", "--tmpdir",
                            "--workdir", "--wd", "--timeout", "-d", "--delimiter", "-E"}),
    # GNU xargs's lowercase `-i`/`-l` take their argument only glued on (`-ifoo`, `-l5`), never as a
    # separate following word — unlike `-I`/`-L`, which do (`-I {}`, `-L 5`); listing `-i`/`-l` here
    # too used to make the loop below eat the next *real* argument as if it were their value
    # (`xargs -i rm .act/rules/a.md` hid `rm` as `-i`'s value, target invisible; found in review,
    # 2026-09-25) — the general "starts with -" skip already handles the glued form correctly on its
    # own, so they are deliberately left out of this set.
    "xargs": frozenset({"-a", "--arg-file", "-d", "--delimiter", "-E", "-I",
                         "-L", "--max-lines", "-n", "--max-args", "-P", "--max-procs",
                         "-s", "--max-chars"}),
}
# Besides the shells by name, the shell named by a variable (`$SHELL -c '...'`, `${SHELL} -c`, `$0 -c`):
# its value is unknown here, and a shell is what such a line is written to run. `_command_name`
# lower-cases, so the entries are lower-case.
_SHELL_NAMES = frozenset({"sh", "bash", "zsh", "dash", "ksh", "$shell", "${shell}", "$0", "${0}"})
# Every non-option operand is a target (mv: the sources vanish, so they count too).
_ALL_OPERAND_WRITERS = frozenset({"tee", "touch", "mkdir", "rm", "rmdir", "unlink", "mv", "truncate", "shred"})
# The last operand (or an explicit -t/--target-directory) is the target.
_LAST_OPERAND_WRITERS = frozenset({"cp", "install", "ln", "rsync"})
# Options that consume the next word, per command — so that word is neither mistaken for an operand
# nor lost as a target (-t/--target-directory are read back as targets).
_VALUE_FLAGS = {
    "touch": frozenset({"-r", "--reference", "-d", "--date", "-t"}),
    "mkdir": frozenset({"-m", "--mode"}),
    "mv": frozenset({"-t", "--target-directory", "-S", "--suffix"}),
    "truncate": frozenset({"-s", "--size", "-r", "--reference"}),
    "shred": frozenset({"-n", "--iterations", "-s", "--size"}),
    "cp": frozenset({"-t", "--target-directory", "-S", "--suffix"}),
    "install": frozenset({"-t", "--target-directory", "-m", "--mode", "-o", "--owner", "-g", "--group", "-S", "--suffix"}),
    "ln": frozenset({"-t", "--target-directory", "-S", "--suffix"}),
    "rsync": frozenset({"-e", "--rsh", "--exclude", "--include", "-f", "--filter"}),
    "sed": frozenset({"-e", "--expression", "-f", "--file", "-l", "--line-length"}),
    "checkout": frozenset({"-b", "-B", "--orphan", "--conflict"}),
    "restore": frozenset({"-s", "--source"}),
}
_SED_INPLACE_FLAG_RE = re.compile(r"^-[A-Za-z]*i")
_GIT_GLOBAL_VALUE_FLAGS = frozenset({"-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"})
# Which git subcommands count as writes: check 1 only mv/rm (the orchestrator restores .act/ files
# with checkout/restore on purpose), check 1c also checkout/restore (a worker never needs them).
_GIT_WRITES_TEMPLATE_GUARD = frozenset({"mv", "rm"})
_GIT_WRITES_WORKER_SCOPE = frozenset({"mv", "rm", "checkout", "restore"})

_Token = tuple[str, bool]  # (text, is_operator)
_Target = tuple[str, Optional[str]]  # (raw target, base directory for a relative one; None = unknown)
_Bases = frozenset  # frozenset[Optional[str]] — the directories the shell may be in at that point


def _local_host_names() -> frozenset:
    """Every name under which a UNC path can address *this* machine without touching the network
    (see _WIN32_ADMIN_SHARE_RE): the loopback spellings in _LOCAL_HOST_NAMES plus this computer's
    own name (`COMPUTERNAME`, `socket.gethostname()` — both local lookups, never DNS). Lower-case,
    since Windows host names are case-insensitive."""
    names = set(_LOCAL_HOST_NAMES)
    for candidate in (os.environ.get("COMPUTERNAME"), _safe_hostname()):
        if candidate:
            names.add(candidate.lower())
    return frozenset(names)


def _safe_hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return ""


def _to_native_path(raw: str) -> str:
    """Rewrite an absolute path to the one native Windows drive form every check compares
    against, on win32 only; left unchanged everywhere else. Handles a Git-Bash-style path
    (`/c/work/x` -> `C:/work/x`, _GITBASH_DRIVE_RE) and the three alternative spellings of a local
    drive path listed above _WIN32_PREFIXED_DRIVE_RE (`\\\\?\\D:\\x`, `\\\\?\\UNC\\localhost\\D$\\x`,
    `\\\\localhost\\D$\\x` -> `D:\\x`). Idempotent, and meant to be applied both to a raw target and
    to what Path.resolve() returns for it — see _resolve_path."""
    if sys.platform != "win32":
        return raw
    match = _GITBASH_DRIVE_RE.match(raw)
    if match:
        drive, rest = match.groups()
        return f"{drive.upper()}:/{rest}"
    text = _WIN32_PREFIXED_DRIVE_RE.sub("", raw, count=1)
    # `\\?\UNC\host\...` -> `\\host\...`: the match ends right before the separator that follows
    # "UNC", so one backslash plus that separator gives the two a UNC path starts with.
    text = _WIN32_PREFIXED_UNC_RE.sub(lambda _m: "\\", text, count=1)
    share = _WIN32_ADMIN_SHARE_RE.match(text)
    if share and share.group("host").lower().rstrip(".") in _local_host_names():
        rest = text[share.end():]
        text = f"{share.group('drive').upper()}:{rest or chr(92)}"
    return text


def _is_remote_unc(path: Path) -> bool:
    """True for a UNC path (`\\\\host\\share\\...`) whose host is not this machine (see
    _local_host_names) — a `\\\\?\\`/`\\\\.\\` device-namespace path is *not* remote (its "host" is
    `?` or `.`). Such a path must never be handed to Path.resolve(): on Windows that opens the
    path to ask the filesystem for its final name, i.e. a network round trip — measured at 21 s
    for an unroutable host on 2026-09-26, longer than a hook has, and a hook that times out reads
    as "allow" to the harness."""
    drive = path.drive
    if not drive.startswith(("\\\\", "//")):
        return False
    host = re.split(r"[\\/]", drive.lstrip("\\/"), maxsplit=1)[0]
    return host not in ("?", ".") and host.lower().rstrip(".") not in _local_host_names()


def _resolve_path(raw: str, base: Optional[str] = None) -> Optional[Path]:
    """`raw` as one absolute, resolved, native path — the single way every check turns a write
    target into something it can compare against a project directory (write-guard, docs/ai/
    guard, worker write scope, scratchpad exemption, the PowerShell scanner's own resolution and
    checks/mcp_ide.py's translated targets all go through here). A relative `raw` is joined onto
    `base` first (None back when there is no `base` to join it onto — the caller decides what an
    unplaceable target means for it); both sides pass through _to_native_path before resolving,
    and the *resolved* text passes through it once more, since Path.resolve() itself can hand
    back the `\\\\?\\` form (see _WIN32_PREFIXED_DRIVE_RE). A UNC path to another host
    (_is_remote_unc) is only normalized lexically (os.path.normpath: `.`/`..` collapsed), never
    resolved — no network round trip from a hook; it is out of this project's root either way,
    unless the project itself lives on that share, in which case the same lexical form is what its
    root compares as too. None on any error resolving it (never raises) — again the caller's own
    fail-closed/fail-open choice, exactly as before."""
    try:
        candidate = Path(_to_native_path(raw))
        if not candidate.is_absolute():
            if base is None:
                return None
            candidate = Path(_to_native_path(base)) / candidate
        if _is_remote_unc(candidate):
            return Path(os.path.normpath(str(candidate)))
        resolved = candidate.resolve()
    except (OSError, ValueError):
        return None
    return Path(_to_native_path(str(resolved)))


def _is_ignorable_write_target(raw: str) -> bool:
    """True for a captured "target" that is not a project file — see _IGNORABLE_TARGETS."""
    stripped = raw.strip()
    return not stripped or stripped.lower() in _IGNORABLE_TARGETS


def _is_dynamic_target(raw: str) -> bool:
    """True if the shell would still expand `raw` ($VAR, $(...), `...`, {a,b}, ~) — its real path
    cannot be known here, so no directory check on its literal text is trustworthy."""
    return bool(_DYNAMIC_TARGET_RE.search(raw))


def _is_absolute_target(raw: str) -> bool:
    return Path(_to_native_path(raw)).is_absolute()


class _Word(str):
    """A dequoted word plus the contents of the backtick spans that stood in it unquoted or inside
    double quotes (`subs`, already unescaped the way bash does before running them). The word's own
    text keeps each span verbatim, backticks included, so `_is_dynamic_target` and every text
    fallback still see it; `bare` is the same text with every span cut out (what the word is when
    each span expands to nothing — `` `;`rm `` is the command `rm`). A plain `str` anywhere (a word
    rebuilt by `join`, `replace`, a slice) has neither — read them with `getattr(word, "subs", ())`
    and `getattr(word, "bare", word)`.

    `live` is a string as long as the word, one character per character of its text: "L" where the
    character is syntax the shell still acts on (written unquoted and unescaped; a `$` and the name
    after it inside double quotes), "." where quoting or an escape made it a plain character (and
    for the text of a backtick span or of a `$(...)`/`${...}` construct, which are judged by their
    own rules). A plain `str` has no `live` (`getattr(word, "live", None)`), and neither has a word
    that came out of a nested scan (`sh -c`, `eval`, `$(...)`, a backtick span — _scan_command drops
    it there): then nothing is known about its quoting and a caller treats a `$`, `{` or `,` in it
    as not provably live."""

    subs: tuple[str, ...]
    bare: str
    live: Optional[str]

    def __new__(
        cls, text: str, subs: tuple[str, ...] = (), bare: Optional[str] = None, live: Optional[str] = None
    ) -> "_Word":
        word = super().__new__(cls, text)
        word.subs = subs
        word.bare = text if bare is None else bare
        word.live = live if live is not None and len(live) == len(text) else None
        return word


class _TokenizeError(ValueError):
    """A ValueError from the tokenizers that also carries `partial`, the tokens read before the word
    that failed (an unclosed quote or span, a trailing backslash). Whatever came before that word is
    a real command prefix — a caller whose complete tokenization failed still scans it."""

    def __init__(self, message: str, partial: Optional[list] = None) -> None:
        super().__init__(message)
        self.partial: list = partial or []


def _backtick_span(text: str, pos: int, in_double: bool) -> tuple[str, int, bool]:
    """The backtick span whose opening backtick sits just before `text[pos]`, as (content, index
    after the closing backtick, closed). The span ends at the next backtick that is not escaped,
    whatever quotes its own text contains — bash looks for the end that way, and a quote inside the
    span belongs to the span, not to the surrounding command. Inside the span a backslash before
    `` ` ``, `\\` or `$` (and, within double quotes, `"`) is removed, exactly the unescaping bash
    does before it runs the content. Without a closing backtick the span runs to the end of
    `text` (closed False): scanning more is the safe side."""
    parts: list[str] = []
    index = pos
    while index < len(text):
        char = text[index]
        if char == "`":
            return "".join(parts), index + 1, True
        if char == "\\" and index + 1 < len(text):
            following = text[index + 1]
            parts.append(following if following in "`\\$" or (in_double and following == '"') else char + following)
            index += 2
            continue
        parts.append(char)
        index += 1
    return "".join(parts), len(text), False


def _closed_backtick_spans(text: str) -> list[str]:
    """The contents of the closed backtick spans in `text` that has no quote context of its own (a
    heredoc body: single quotes mean nothing there, only a backslash escapes a backtick)."""
    spans: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
        elif char == "`":
            content, index, closed = _backtick_span(text, index + 1, in_double=False)
            if closed:
                spans.append(content)
        else:
            index += 1
    return spans


_EXPANSION_CLOSERS = {"(": ")", "{": "}", "[": "]"}
# How deep `$(`/`${`/`$[` constructs may nest inside one word before the walk gives up with a
# ValueError. An explicit bound, so the walk never depends on Python raising RecursionError (which
# would not be a ValueError and would escape every caller that handles a tokenizing failure).
_MAX_EXPANSION_DEPTH = 64


def _skip_squote(text: str, index: int) -> int:
    """The index just after the single-quoted run opening at `text[index]` (`'`). Inside a
    `$(...)`/`${...}`/`$[...]` construct a single-quoted run is literal — a backtick in it opens no
    command substitution — so the span logic must skip it whole. Runs to the end of `text` when the
    quote is never closed (the construct is malformed then; _read_word's caller handles that through
    its tokenize-error fallback)."""
    end = text.find("'", index + 1)
    return len(text) if end < 0 else end + 1


def _collect_dq_nested(text: str, index: int, subs: list[str], depth: int = 0) -> int:
    """Walk a nested double-quoted run (inside a `$(...)`/`${...}` that is itself inside double
    quotes) from `text[index]` (the first character after its opening `"`) to its closing `"`,
    appending the contents of every live backtick span to `subs` and following any nested
    `$(...)`/`${...}`. A single quote is an ordinary character here (literal inside `"..."`).
    Returns the index after the closing quote (end of `text` if it is unclosed)."""
    while index < len(text):
        char = text[index]
        if char == '"':
            return index + 1
        if char == "\\" and index + 1 < len(text):
            index += 2
        elif char == "`":
            content, index, _closed = _backtick_span(text, index + 1, in_double=True)
            subs.append(content)
        elif char == "$" and index + 1 < len(text) and text[index + 1] in _EXPANSION_CLOSERS:
            index = _collect_dq_expansion(text, index + 1, subs, depth + 1)
        else:
            index += 1
    return index


def _collect_dq_expansion(text: str, index: int, subs: list[str], depth: int = 0) -> int:
    """Walk a `$(...)`, `$((...))`, `${...}` or `$[...]` expansion whose opener is at `text[index]`
    (one of `([{`) to its matching closer, appending to `subs` the contents of every backtick span
    that really runs inside it. The point of the walk: bash parses the inside of these constructs
    with their own quoting, which differs from the surrounding `"..."` where every backtick opens a
    span — so a backtick must not open a span that swallows a real redirection after the string.

    Two quoting regimes inside:
      - command substitution `$(...)` and parameter expansion `${...}`: a single-quoted run is
        literal (a backtick in it runs nothing), so it is skipped whole (_skip_squote);
      - arithmetic `$((...))` and `$[...]`: a single quote is an ordinary character, so a backtick
        inside what looks like `'...'` IS a live command substitution and must be collected — not
        skipped (a `$(( '` + backtick + `> .act/x` + backtick + `' ))` really writes `.act/x`).

    Nested `"..."` runs are followed (_collect_dq_nested) and nested expansions of the same kind
    (`$(( ))`) and of another kind (`${x:-$(...)}`) are followed too. A `$(...)` command is not
    itself added here — the construct stays in the word verbatim, so the `"$("` re-scan in
    _scan_tokens/command_words still reaches it. Returns the index after the matching closer (end of
    `text` if the construct is unterminated — the safe side: the word then runs to the end and the
    caller's unclosed-quote fallback takes over). Constructs nested deeper than
    _MAX_EXPANSION_DEPTH raise ValueError (`depth` counts the nesting this walk is already at)."""
    if depth > _MAX_EXPANSION_DEPTH:
        raise ValueError(f"expansions nested deeper than {_MAX_EXPANSION_DEPTH} levels")
    opener = text[index]
    closer = _EXPANSION_CLOSERS[opener]
    arithmetic = opener == "[" or (opener == "(" and index + 1 < len(text) and text[index + 1] == "(")
    same_depth = 0
    j = index + 1
    while j < len(text):
        char = text[j]
        if char == opener:
            same_depth += 1
            j += 1
        elif char == closer:
            if same_depth == 0:
                return j + 1
            same_depth -= 1
            j += 1
        elif char == "'" and not arithmetic:
            j = _skip_squote(text, j)
        elif char == '"':
            j = _collect_dq_nested(text, j + 1, subs, depth + 1)
        elif char == "`":
            content, j, _closed = _backtick_span(text, j + 1, in_double=False)
            subs.append(content)
        elif char == "$" and j + 1 < len(text) and text[j + 1] in _EXPANSION_CLOSERS:
            j = _collect_dq_expansion(text, j + 1, subs, depth + 1)
        elif char == "\\" and j + 1 < len(text):
            j += 2
        else:
            j += 1
    return j


# `${NAME}` as one construct inside double quotes: nothing but a plain variable name in braces.
_PLAIN_BRACED_NAME_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")


def _read_word(
    text: str, start: int, operator_chars: str, blank: str, spans_must_close: bool = False
) -> tuple[_Word, int]:
    """One word from `text[start:]` (which begins with a character that is neither blank nor an
    operator), as (word, index after it). Quoting as POSIX shlex had it: `'...'` literal, `"..."`
    with a backslash only before `"`, a backslash or a backtick (any other backslash stays), an unquoted
    backslash escapes the next character; an unquoted or double-quoted backslash before a newline is a
    line continuation and leaves nothing in the word (_scan_command joins those before tokenizing
    already, except where bash keeps the pair — this keeps a word read on its own true to bash). Beyond that, an unquoted or double-quoted backtick opens a
    span (_backtick_span) that stays in the word verbatim and is recorded in `subs`; a backtick
    inside single quotes or escaped is an ordinary character. Raises ValueError on an unclosed
    quote or a trailing backslash, and — with `spans_must_close`, the tokenizing of one line on its
    own — on an unquoted span without its closing backtick: bash ends such a span in a later line,
    so this line alone does not show where the quoting goes on (the whole-command tokenizing does).
    Without it, an unclosed span runs to the end of `text`."""
    parts: list[str] = []
    bare: list[str] = []
    live: list[str] = []  # one character per character of `parts`, see _Word
    subs: list[str] = []
    index = start
    while index < len(text):
        char = text[index]
        if char in blank or char in operator_chars:
            break
        if char == "'":
            end = text.find("'", index + 1)
            if end < 0:
                raise ValueError("No closing quotation")
            parts.append(text[index + 1:end])
            bare.append(text[index + 1:end])
            live.append("." * (end - index - 1))
            index = end + 1
        elif char == '"':
            index += 1
            in_name = False  # inside the name of a `$NAME` that is live
            while True:
                if index >= len(text):
                    raise ValueError("No closing quotation")
                inner = text[index]
                if inner == '"':
                    index += 1
                    break
                if inner == "\\":
                    if index + 1 >= len(text):
                        raise ValueError("No escaped character")
                    following = text[index + 1]
                    if following == "\n":
                        index += 2  # a line continuation: bash drops both characters, in double quotes too
                        continue
                    # `\`` inside double quotes is a plain backtick for this command, but the
                    # word's text is what a nested `sh -c "..."`/`eval` re-parses, and there that
                    # backtick opens a span — so the backslash must go, as in bash.
                    piece = following if following in '"\\`' else inner + following
                    parts.append(piece)
                    bare.append(piece)
                    live.append("." * len(piece))
                    in_name = False
                    index += 2
                elif inner == "$" and index + 1 < len(text) and text[index + 1] in _EXPANSION_CLOSERS:
                    # $(...), $((...)), ${...}, $[...]: bash reads the inside of these with their own
                    # quoting, where a single-quoted run is literal and a backtick in it opens no
                    # span — unlike this surrounding "...", where a bare backtick does. Consume the
                    # whole construct so such a backtick cannot open a span that eats a real
                    # redirection after the string; the construct stays in the word verbatim (so a
                    # `$(` still drives the re-scan in _scan_tokens), and the backtick commands that
                    # do run inside it go to `subs`.
                    end = _collect_dq_expansion(text, index + 1, subs)
                    parts.append(text[index:end])
                    bare.append(text[index:end])
                    construct = text[index:end]
                    live.append("L" * len(construct) if _PLAIN_BRACED_NAME_RE.match(construct) else "." * len(construct))
                    in_name = False
                    index = end
                elif inner == "`":
                    content, end, _closed = _backtick_span(text, index + 1, in_double=True)
                    subs.append(content)
                    parts.append(text[index:end])
                    live.append("." * (end - index))
                    in_name = False
                    index = end
                else:
                    parts.append(inner)
                    bare.append(inner)
                    # A `$` followed by a name character expands inside double quotes, as do the
                    # name characters after it; every other character here is quoted.
                    name_char = inner.isascii() and (inner.isalnum() or inner == "_")
                    if inner == "$" and index + 1 < len(text) and text[index + 1].isascii() and (
                        text[index + 1].isalpha() or text[index + 1] == "_"
                    ):
                        in_name = True
                        live.append("L")
                    elif in_name and name_char:
                        live.append("L")
                    else:
                        in_name = False
                        live.append(".")
                    index += 1
        elif char == "\\":
            if index + 1 >= len(text):
                raise ValueError("No escaped character")
            if text[index + 1] == "\n":
                index += 2  # a line continuation: bash drops both characters, nothing enters the word
                continue
            parts.append(text[index + 1])
            bare.append(text[index + 1])
            live.append(".")
            index += 2
        elif char == "$" and index + 1 < len(text) and (
            text[index + 1] == "["
            or (text[index + 1] == "(" and index + 2 < len(text) and text[index + 2] == "(")
        ):
            # Unquoted arithmetic $((...)) / $[...]: the normal tokenizer would read `((` as two
            # subshell operators and a single quote inside as a real quote — but in arithmetic a
            # single quote is an ordinary character, so a backtick inside what looks like `'...'` is
            # a live command substitution (`$(( '`...`> .act/x`...`' ))` really writes). Consume the
            # construct here, as one word, collecting those spans (_collect_dq_expansion's arithmetic
            # regime). An unquoted `$(...)` command substitution is deliberately *not* intercepted —
            # the operator/subshell mechanism already scans it with single quotes honored correctly.
            end = _collect_dq_expansion(text, index + 1, subs)
            parts.append(text[index:end])
            bare.append(text[index:end])
            live.append("." * (end - index))
            index = end
        elif char == "`":
            content, end, closed = _backtick_span(text, index + 1, in_double=False)
            if not closed and spans_must_close:
                raise ValueError("No closing backtick")
            subs.append(content)
            parts.append(text[index:end])
            live.append("." * (end - index))
            index = end
        else:
            parts.append(char)
            bare.append(char)
            live.append("L")
            index += 1
    return _Word("".join(parts), tuple(subs), "".join(bare), "".join(live)), index


def _split_operator_run(run: str) -> list[str]:
    ops: list[str] = []
    pos = 0
    while pos < len(run):
        op = next((candidate for candidate in _SHELL_OPERATORS if run.startswith(candidate, pos)), run[pos])
        ops.append(op)
        pos += len(op)
    return ops


def _shell_tokens(text: str, newline_is_operator: bool) -> list[_Token]:
    """Tokenize `text` into (text, is_operator) pairs; a word's text is a `_Word`. Whitespace
    separates words, a run of operator characters (`_SHELL_OPERATOR_CHARS`, plus a newline when
    `newline_is_operator`) is split into operators (_split_operator_run), an unquoted `#` at the
    start of a word comments out the rest of the line (the newline itself stays), and `#` inside a
    word is just a character. Raises ValueError (a _TokenizeError with the tokens before the failing
    word) on an unclosed quote or a trailing backslash, and — one line on its own, i.e. without
    `newline_is_operator` — on a backtick span left open at the end of the line."""
    operator_chars = _SHELL_OPERATOR_CHARS + ("\n" if newline_is_operator else "")
    blank = " \t\r" if newline_is_operator else " \t\r\n"
    tokens: list[_Token] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char in blank:
            index += 1
        elif char == "\\" and text.startswith("\\\n", index):
            index += 2  # a line continuation between words: bash drops it, it is no word of its own
        elif char in operator_chars:
            end = index
            while end < len(text) and text[end] in operator_chars:
                end += 1
            tokens.extend((op, True) for op in _split_operator_run(text[index:end]))
            index = end
        elif char == "#":
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline
        else:
            try:
                word, index = _read_word(text, index, operator_chars, blank, not newline_is_operator)
            except ValueError as error:
                raise _TokenizeError(str(error), tokens) from error
            tokens.append((word, False))
    return tokens


# Constructs in which bash does not read `<<` as a heredoc (or reads it as one that ends early):
# arithmetic `$[1<<2]`, `${arr[1<<2]}`, an array index `a[1<<2]=x`, and a heredoc opened inside
# backticks, whose body ends at the closing backtick. A line containing any of them opens no
# heredoc here, so its following lines are scanned as commands — over-scanning is the safe side.
_NO_HEREDOC_MARKERS = ("$[", "${", "[", "`")


def _opens_no_heredoc(line: str) -> bool:
    """True for a line that opens no heredoc as far as the line-wise reading goes: `((` in it (arithmetic
    like `$((1<<2))`, where `<<` is a shift) or one of _NO_HEREDOC_MARKERS. _heredoc_delimiters and
    _join_scan use this one test, so they never disagree about which lines have a body."""
    return "((" in line or any(marker in line for marker in _NO_HEREDOC_MARKERS)


def _heredoc_delimiters(tokens: list[_Token], line: str) -> list[tuple[set[str], bool]]:
    """Every heredoc a line opens, in order, as (terminator candidates, whether its body is
    expanded). A line with `((` in it (arithmetic like `$((1<<2))`, where `<<` is a shift) or with
    one of _NO_HEREDOC_MARKERS opens none — skipping nothing is the safe side — unless every heredoc on
    it has a quoted delimiter (its body is then plain text, never run by the line's own command). `<<-EOF` reaches
    here as `<<` plus `-EOF`; both "EOF" and "-EOF" are accepted as the terminator, whichever comes first, since ending a body early only
    ever scans more. A body is expanded (so `$(...)` and backticks in it run) unless the delimiter
    was quoted; the tokens no longer show quoting, so that is read from the raw line, and if the two
    do not line up the body is treated as expanded."""
    marked = _opens_no_heredoc(line)
    delimiters = []
    for index, (text, is_op) in enumerate(tokens[:-1]):
        next_text, next_is_op = tokens[index + 1]
        if is_op and text == "<<" and not next_is_op:
            candidates = {next_text}
            if next_text.startswith("-") and len(next_text) > 1:
                candidates.add(next_text[1:])
            delimiters.append(candidates)
    raw_words = _HEREDOC_OPEN_RE.findall(line)
    aligned = len(raw_words) == len(delimiters)
    found = [
        (candidates, not aligned or not any(char in raw_words[position] for char in "'\"\\"))
        for position, candidates in enumerate(delimiters)
    ]
    if marked and (not aligned or any(expands for _candidates, expands in found)):
        # On a marked line only a heredoc that is certain is opened: every delimiter quoted, so no body
        # is expanded and none can be a `<<` of arithmetic or of text inside an expansion. Any doubt
        # keeps the old reading (no heredoc, the body is scanned as commands).
        return []
    return found


def _command_prefix_end(words: list[str]) -> int:
    """Index of the command name in a simple command's words: assignments, `if`/`{`-style prefixes,
    backtick-span words and wrappers (`env`, `sudo`, `time` ... with their options) skipped, as
    _simple_command_targets skips them."""
    index = 0
    while index < len(words):
        word = words[index]
        if _ASSIGNMENT_RE.match(word) or word in _RESERVED_PREFIXES or _is_span_word(word):
            index += 1
        elif _command_name(word) in _WRAPPER_COMMANDS:
            value_flags = _WRAPPER_VALUE_FLAGS.get(_command_name(word), frozenset())
            index += 1
            while index < len(words):
                arg = words[index]
                if arg in value_flags:
                    index += 2 if index + 1 < len(words) else 1
                elif _WRAPPER_ARG_RE.match(arg) or _ASSIGNMENT_RE.match(arg) or _is_span_word(arg):
                    index += 1
                else:
                    break
        else:
            break
    return index


# Shell options that take the next word as their value (`bash -o pipefail`, `bash -O extglob`).
_SHELL_VALUE_OPTIONS = frozenset({"-o", "+o", "-O", "+O", "--rcfile", "--init-file"})


def _segment_words(tokens: list[_Token], start: int, end: int) -> list[str]:
    """The words of `tokens[start:end]` that are arguments of a command: every redirection operator and
    its operand is left out."""
    words: list[str] = []
    skip_next = False
    for position in range(start, end):
        token_text, token_is_op = tokens[position]
        if token_is_op:
            skip_next = True  # the operand of a redirection is no argument of the command
        elif skip_next:
            skip_next = False
        else:
            words.append(token_text)
    return words


def _reads_script_from_stdin(words: list[str]) -> bool:
    """True if the simple command with these words is a shell that reads its script from standard
    input: no `-c` among its options (with `-c` the script is the option's value and a heredoc is plain
    input). Options end at `--`, at `-` and at the first word that is no option — from there on every
    word is the script file or a positional parameter, so a later `-c` means nothing. A shell given a
    file name is taken as running that file, which is not told apart here (the body is read as a script
    then — over-reading, never a miss)."""
    name_at = _command_prefix_end(words)
    if name_at >= len(words) or _command_name(words[name_at]) not in _SHELL_NAMES:
        return False
    args = words[name_at + 1:]
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in ("--", "-") or not arg.startswith(("-", "+")):
            break
        if arg in _SHELL_VALUE_OPTIONS:
            index += 2
            continue
        if arg.startswith("-") and not arg.startswith("--") and "c" in arg[1:]:
            return False
        index += 1
    return True


def _group_reads_script_from_stdin(tokens: list[_Token], first: int, stop: int) -> bool:
    """True if some simple command in `tokens[first:stop]` (the inside of a `{ ...; }` or `( ... )` group
    whose standard input a heredoc replaces) is a shell reading its script from standard input."""
    position = first
    while position < stop:
        end = position
        while end < stop and not (tokens[end][1] and tokens[end][0] in _SEPARATOR_OPS):
            end += 1
        if _reads_script_from_stdin(_segment_words(tokens, position, end)):
            return True
        position = end + 1
    return False


# A line opening more heredocs than this — far more than any real command, which has one or two —
# skips the per-heredoc analysis below and counts every body as a shell's script (the blocking side).
# That caps the work the group lookback can do per line, so an adversarial line of thousands of `<<`
# cannot make this quadratic.
_MAX_HEREDOCS_PER_LINE = 64


def _heredoc_shell_flags(tokens: list[_Token]) -> list[bool]:
    """For each heredoc a line opens (a `<<` operator followed by a word, in order, as
    _heredoc_delimiters finds them): whether its body is a script for a shell — the command it feeds is
    a shell reading its script from standard input (`bash <<EOF`, `sh -s <<EOF`, `sh - <<EOF`, behind a
    wrapper or after a pipe too; _reads_script_from_stdin), the group it feeds holds one (`{ bash; }
    <<EOF`, `(bash) <<EOF`), or a later stage of its pipeline is one (`cat <<EOF | bash`: the body
    is what the first stage prints). Not covered: a pipe that ends the line with the shell on a later
    line, and a group as a later stage.

    The line is split into segments (maximal runs between separator operators) once, so each segment's
    "reads a script from stdin" value and the pipeline-suffix flag are computed a single time and the
    per-heredoc loop only looks them up (plus a local group lookback). Scanning the whole segment and
    pipeline afresh for every `<<` used to be quadratic in the number of heredocs on the line."""
    heredocs = [index for index in range(len(tokens) - 1)
                if tokens[index][1] and tokens[index][0] == "<<" and not tokens[index + 1][1]]
    if not heredocs:
        return []
    if len(heredocs) > _MAX_HEREDOCS_PER_LINE:
        return [True] * len(heredocs)
    size = len(tokens)

    def is_separator(position: int) -> bool:
        return tokens[position][1] and tokens[position][0] in _SEPARATOR_OPS

    # One pass splits the line into segments: each a maximal run of non-separator tokens, paired with
    # the operator that follows it (for the pipeline chain). seg_start maps a token to its segment's
    # start, and a start is unique, so it also names the segment.
    seg_start = [-1] * size
    segments: list[tuple[int, int, str]] = []  # (start, end, the following separator operator or "")
    position = 0
    while position < size:
        start = position
        while position < size and not is_separator(position):
            seg_start[position] = start
            position += 1
        following = tokens[position][0] if position < size else ""
        segments.append((start, position, following))
        if position < size:
            position += 1
    order_of_start = {start: order for order, (start, _end, _sep) in enumerate(segments)}
    words_of = [_segment_words(tokens, start, end) for start, end, _sep in segments]
    base = [_reads_script_from_stdin(words) for words in words_of]
    # Pipeline suffix: within a run of segments joined by pipe operators, whether a later stage reads a
    # script (`cat <<EOF | bash`). pipe_later[k] = base[k+1] or pipe_later[k+1] when k feeds k+1 through
    # a pipe, else False.
    pipe_later = [False] * len(segments)
    for order in range(len(segments) - 2, -1, -1):
        if segments[order][2] in _PIPE_OPS:
            pipe_later[order] = base[order + 1] or pipe_later[order + 1]

    flags: list[bool] = []
    for index in heredocs:
        order = order_of_start[seg_start[index]]
        start = segments[order][0]
        words = words_of[order]
        feeds = base[order]
        if not feeds and not words and start > 0 and tokens[start - 1] == (")", True):
            depth = 1
            open_at = start - 2
            while open_at >= 0 and depth:
                if tokens[open_at][1] and tokens[open_at][0] in ("(", ")"):
                    depth += 1 if tokens[open_at][0] == ")" else -1
                open_at -= 1
            feeds = depth == 0 and _group_reads_script_from_stdin(tokens, open_at + 2, start - 1)
        elif not feeds and words == ["}"]:
            depth = 1
            open_at = start - 1
            while open_at >= 0 and depth:
                if not tokens[open_at][1] and tokens[open_at][0] in ("{", "}"):
                    depth += 1 if tokens[open_at][0] == "}" else -1
                open_at -= 1
            feeds = depth == 0 and _group_reads_script_from_stdin(tokens, open_at + 2, start)
        if not feeds:
            feeds = pipe_later[order]
        flags.append(feeds)
    return flags


_SHELL_WORD_IN_LINE_RE = re.compile(r"(?<![\w.-])(?:ba|z|da|k)?sh(?![\w.-])|\$\{?(?:shell|0)\}?", re.IGNORECASE)


def _heredoc_may_feed_shell(command: str) -> bool:
    """True if some line of `command` opens a heredoc and names a shell — a coarse test (a path, a
    longer command line, a word that only looks like one all count) for the whole-command fallback,
    which must not cut out a quoted heredoc body that a shell may run."""
    return any("<<" in line and _SHELL_WORD_IN_LINE_RE.search(line) for line in command.split("\n"))


def _body_substitutions(body_lines: list[str]) -> list[str]:
    """The command substitutions an expanded heredoc body runs: each backtick span as a subshell
    `( ... )`, and the rest of a line from its first `$(`."""
    snippets = []
    for body_line in body_lines:
        snippets.extend(f"( {span} )" for span in _closed_backtick_spans(body_line))
        if "$(" in body_line:
            snippets.append(body_line[body_line.index("$("):])
    return snippets


def _heredoc_terminator(line_positions: dict[str, list[int]], candidates: set[str], start: int) -> Optional[int]:
    """The smallest line index >= `start` whose stripped text is one of `candidates`, read from
    `line_positions` (every line's stripped text mapped to its own sorted occurrence indices,
    built once per command by _line_mode_tokens) via a binary search per candidate rather than
    rescanning the remaining lines from `start` to the end (that rescan made an unterminated
    heredoc on every line of a large command quadratic overall — one heredoc per line, each one
    scanning to the end again, 1.4s for 10,000 lines; a lookup here is O(log n) per candidate
    instead)."""
    best: Optional[int] = None
    for candidate in candidates:
        positions = line_positions.get(candidate)
        if not positions:
            continue
        idx = bisect.bisect_left(positions, start)
        if idx < len(positions) and (best is None or positions[idx] < best):
            best = positions[idx]
    return best


def _line_mode_tokens(command: str) -> list[_Token]:
    """Tokenize line by line with heredoc bodies skipped (step 2 of the section comment). A body is
    skipped only up to a terminator line that exists (found via _heredoc_terminator);
    without one, nothing is skipped, so the rest is scanned as commands. The command substitutions
    of an expanded body are kept (as commands of their own after the heredoc line). Raises
    ValueError if any line does not tokenize on its own — a _TokenizeError whose `partial` holds the
    tokens before the failing word."""
    lines = command.split("\n")
    line_positions: dict[str, list[int]] = {}
    for position, raw_line in enumerate(lines):
        line_positions.setdefault(raw_line.strip(), []).append(position)
    tokens: list[_Token] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        try:
            line_tokens = _shell_tokens(line, newline_is_operator=False)
        except _TokenizeError as error:
            raise _TokenizeError(str(error), tokens + error.partial) from error
        tokens.extend(line_tokens)
        tokens.append(("\n", True))
        index += 1
        delimiters = _heredoc_delimiters(line_tokens, line)
        feeds_shell = _heredoc_shell_flags(line_tokens) if delimiters else []
        for position, (candidates, expands) in enumerate(delimiters):
            end = _heredoc_terminator(line_positions, candidates, index)
            if end is None:
                break
            if position < len(feeds_shell) and feeds_shell[position]:
                # The body is a script for a shell: scanned as a command text of its own (the same
                # route a `sh -c` text takes), so the commands in it count, an expansion in an
                # unquoted body (`$(...)`, `$VAR`) shows up as the dynamic target it is there.
                body = "\n".join(lines[index:end])
                tokens.append((_Word("`heredoc`", (body,), "", "." * len("`heredoc`")), False))
                tokens.append(("\n", True))
            # An unquoted body is expanded before any reader sees it - by bash, even inside what the
            # shell reading it later takes as a comment or a quoted string - so its substitutions
            # count on their own as well, whether or not the body then goes to a shell.
            if expands:
                for snippet in _body_substitutions(lines[index:end]):
                    try:
                        tokens.extend(_shell_tokens(snippet, newline_is_operator=False))
                    except _TokenizeError as error:
                        raise _TokenizeError(str(error), tokens + error.partial) from error
                    tokens.append(("\n", True))
            index = end + 1
    return tokens


def _raw_redirect_targets(command: str) -> list[str]:
    """Coarse last resort: every word after a `>`-style operator anywhere in the raw text, quotes
    stripped off its ends, fd duplications (`>&2`) left out. Over-inclusive by design."""
    targets = []
    for match in _RAW_REDIRECT_RE.finditer(command):
        word = match.group(1).strip("'\"")
        if not _FD_DUP_WORD_RE.match(word):
            targets.append(word)
    return targets


def _command_name(word: str) -> str:
    """The command a word names, lower-case, directory and `.exe` dropped. A backtick span in the
    word is cut out first (`getattr(word, "bare", ...)`): `` `;`rm `` and `` `true`rm `` run `rm`,
    the span itself expanding to nothing. Leading backticks of what is left are dropped as the
    previous scanner did (a plain `str` word, as shell_targets_legacy and command_words_legacy hand
    them back, has no `bare`), so a word either lexer produced is named at least as the previous
    scanner named it."""
    text = getattr(word, "bare", word).lstrip("`")
    name = text.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def _is_span_word(word: str) -> bool:
    """True for a word that is nothing but backtick spans (and quotes around nothing): `` `echo "` ``,
    `` `true` ``. In front of a command it prints nothing or something this scanner cannot know, so
    the command is read as the word behind it — over-reading when the span prints a real command name,
    never under-reading. A plain `str` word (the legacy scanners hand those back) has no `bare` and is
    never one."""
    return "`" in word and getattr(word, "bare", None) == ""


def _operands(args: list[str], value_flags: frozenset = frozenset()) -> tuple[list[str], dict[str, list[str]]]:
    """Split a command's arguments into operands and the values of `value_flags` (`-t DIR`,
    `--target-directory=DIR`, `-tDIR`). Other options are dropped; `--` ends option parsing."""
    operands: list[str] = []
    values: dict[str, list[str]] = {}
    index = 0
    options_done = False
    while index < len(args):
        arg = args[index]
        index += 1
        if options_done or arg == "-" or not arg.startswith("-"):
            operands.append(arg)
        elif arg == "--":
            options_done = True
        elif arg.startswith("--") and "=" in arg:
            name, value = arg.split("=", 1)
            if name in value_flags:
                values.setdefault(name, []).append(value)
        elif arg in value_flags:
            if index < len(args):
                values.setdefault(arg, []).append(args[index])
                index += 1
        elif not arg.startswith("--") and len(arg) > 2 and arg[:2] in value_flags:
            values.setdefault(arg[:2], []).append(arg[2:])
    return operands, values


@functools.lru_cache(maxsize=1 << 16)
def _joined_base(base: Optional[str], native: str) -> Optional[str]:
    """One base directory with a relative `cd` target appended; None (unknown) stays None. Cached,
    since a long `cd a; cd a; ...` chain asks for the same join once per base on every step, and
    the set of bases grows by one per step, so uncached the cost grew with the cube of the chain."""
    if base is None:
        return None
    return str(Path(_to_native_path(base)) / native)


def _cd_bases(bases: _Bases, directory: str) -> _Bases:
    """The possible directories after `cd <directory>` from each of `bases`. A rooted path without
    a drive on Windows (`/tmp`, Git Bash's own mount points) has no knowable native location."""
    native = _to_native_path(directory)
    if Path(native).is_absolute():
        return frozenset({native})
    if native.startswith(("/", "\\")):
        return frozenset({None})
    return frozenset(_joined_base(base, native) for base in bases)


def _pairs(raw_targets: list[str], bases: _Bases) -> list[_Target]:
    if not raw_targets:
        return []  # nothing to pair: skip sorting a set that grows with a long `cd` chain
    ordered = sorted(bases, key=lambda base: (base is None, base or ""))
    return [(raw, base) for raw in raw_targets for base in ordered]


def _git_targets(args: list[str], bases: _Bases, git_writes: frozenset) -> list[_Target]:
    """Targets of `git [-C dir] [global options] <sub> ...` for a sub in `git_writes`: every operand
    (checkout/restore without `--` cannot tell a branch from a path, so both count). `-C dir` moves
    the base like a `cd`; `--work-tree` makes it unknown."""
    target_bases = bases
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "-C" and index + 1 < len(args):
            directory = args[index + 1]
            simple = _SIMPLE_DIR_RE.match(directory) and not directory.startswith("-")
            target_bases = _cd_bases(target_bases, directory) if simple else frozenset({None})
            index += 2
        elif arg in _GIT_GLOBAL_VALUE_FLAGS:
            if arg == "--work-tree":
                target_bases = frozenset({None})
            index += 2
        elif arg.startswith("-"):
            if arg.startswith("--work-tree="):
                target_bases = frozenset({None})
            index += 1
        else:
            break
    if index >= len(args) or args[index] not in git_writes:
        return []
    operands, _ = _operands(args[index + 1:], _VALUE_FLAGS.get(args[index], frozenset()))
    return _pairs(operands, target_bases)


def _download_targets(name: str, args: list[str]) -> list[str]:
    """curl -o/--output, wget -O/--output-document (also clustered: `curl -sSLo f`). A download into
    the current directory under the remote's own name (curl -O, wget without -O) is reported as
    "*" there — every file of that directory. "-" (stdout) is no file."""
    out_flag, remote_flag = ("o", "O") if name == "curl" else ("O", None)
    long_out = "--output" if name == "curl" else "--output-document"
    targets: list[str] = []
    named = False
    for index, arg in enumerate(args):
        if arg == long_out and index + 1 < len(args):
            targets.append(args[index + 1])
            named = True
        elif arg.startswith(long_out + "="):
            targets.append(arg.split("=", 1)[1])
            named = True
        elif arg.startswith("-") and not arg.startswith("--") and out_flag in arg[1:]:
            rest = arg[1:].split(out_flag, 1)[1]
            if rest:
                targets.append(rest)
            elif index + 1 < len(args):
                targets.append(args[index + 1])
            named = True
    if name == "curl":
        if any(arg in ("--remote-name", "--remote-name-all")
               or (remote_flag and arg.startswith("-") and not arg.startswith("--") and remote_flag in arg[1:])
               for arg in args):
            targets.append("*")
    elif not named:
        prefix = next((args[i + 1] for i, arg in enumerate(args[:-1]) if arg in ("-P", "--directory-prefix")), None)
        targets.append(f"{prefix}/*" if prefix else "*")
    return [target for target in targets if target != "-"]


def _simple_command_targets(
    words: list[str], bases: _Bases, git_writes: frozenset, depth: int
) -> tuple[list[_Target], Optional[tuple[Optional[str], bool]]]:
    """Write targets of one simple command (its words, redirections already taken out), and — for
    `cd`/`pushd`/`popd` — the directory change as (literal directory or None if unknown, whether a
    prefix like `if`/`{`/`env` made it conditional)."""
    index = 0
    prefixed = False
    bases_unknown = False
    while index < len(words):
        word = words[index]
        if _ASSIGNMENT_RE.match(word):
            index += 1
        elif word in _RESERVED_PREFIXES:
            prefixed = True
            index += 1
        elif _is_span_word(word):
            prefixed = True  # whatever the span prints, the command behind it may not run at all
            index += 1
        elif _command_name(word) in _WRAPPER_COMMANDS:
            wrapper_name = _command_name(word)
            wrapper_value_flags = _WRAPPER_VALUE_FLAGS.get(wrapper_name, frozenset())
            prefixed = True
            index += 1
            while index < len(words):
                arg = words[index]
                if wrapper_name == "env" and (arg.startswith("--chdir=") or arg in ("-C", "--chdir")):
                    # `env -C dir`/`env --chdir=dir cmd` runs cmd in `dir`, not `bases` — the exact
                    # directory is knowable in principle, but resolving a wrapper's own change of
                    # directory the way `cd`/`git -C` already do would need `dir` threaded back into
                    # `_scan_tokens`'s own bases tracking, which never sees inside a simple command's
                    # own words; simplest correct answer here is "unknown", same as a `cd` this
                    # module already cannot resolve (review, 2026-09-25).
                    bases_unknown = True
                    index += 1 if arg.startswith("--chdir=") else (2 if index + 1 < len(words) else 1)
                elif arg in wrapper_value_flags:
                    # `env -u VAR`, `timeout -s KILL`, `sudo -u name` — the value is its own
                    # word, matching neither _WRAPPER_ARG_RE nor an assignment, so it must be
                    # skipped explicitly too or it gets read as the wrapped command's own name.
                    index += 2 if index + 1 < len(words) else 1
                elif _WRAPPER_ARG_RE.match(arg) or _ASSIGNMENT_RE.match(arg) or _is_span_word(arg):
                    index += 1
                else:
                    break
        else:
            break
    if bases_unknown:
        bases = frozenset({None})
    if index >= len(words):
        return [], None
    name = _command_name(words[index])
    args = words[index + 1:]

    if name == "cd":
        # A backtick span glued to the command name (`` `echo x`cd ``) makes bash run a *different*
        # command (`xcd`), not `cd` — the span's output is concatenated onto `cd` before the word
        # becomes a command name. _command_name reads the name with the spans cut out, so it would
        # see `cd` and move the base directory for a `cd` bash never ran, letting a later write
        # resolve outside the project. With a span in the name word the directory is left unknown
        # instead (fail closed): the base then also holds None, so a protected-path write after it
        # is still caught by its text (check 1) and denied as unplaceable (check 1c).
        if not getattr(words[index], "subs", ()):
            operands, _ = _operands(args)
            if len(operands) == 1 and _SIMPLE_DIR_RE.match(operands[0]) and not operands[0].startswith("-"):
                return [], (operands[0], prefixed)
        return [], (None, prefixed)
    if name in ("pushd", "popd"):
        return [], (None, prefixed)

    raw_targets: list[str] = []
    if name in _ALL_OPERAND_WRITERS:
        value_flags = _VALUE_FLAGS.get(name, frozenset())
        operands, values = _operands(args, value_flags)
        raw_targets = operands + values.get("--target-directory", [])
        if name != "touch":  # touch -t is a timestamp, everywhere else a target directory
            raw_targets += values.get("-t", [])
    elif name in _LAST_OPERAND_WRITERS:
        operands, values = _operands(args, _VALUE_FLAGS[name])
        explicit = values.get("-t", []) + values.get("--target-directory", [])
        if explicit:
            raw_targets = explicit
        elif any(getattr(op, "subs", ()) for op in operands):
            # A backtick span among the operands can expand to empty (or to several words) and so
            # shift which word ends up as the destination (`cp a .act/x `` `echo "` `` runs `cp a
            # .act/x`, destination .act/x — the span drops out). The last-operand rule is then
            # unreliable, so every operand counts as a possible target (over-inclusive, the safe
            # side). The span operand itself is dynamic and judged by its own text as usual.
            raw_targets = operands
        elif name == "install" and any(arg in ("-d", "--directory") for arg in args):
            raw_targets = operands
        elif len(operands) >= 2:
            raw_targets = [operands[-1]]
        elif len(operands) == 1 and name == "ln":
            raw_targets = [operands[0].replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]]
    elif name == "sed":
        if any(arg == "--in-place" or arg.startswith("--in-place=") or _SED_INPLACE_FLAG_RE.match(arg) for arg in args):
            operands, values = _operands(args, _VALUE_FLAGS["sed"])
            has_script = any(flag in values for flag in ("-e", "--expression", "-f", "--file"))
            raw_targets = operands if has_script else operands[1:]
    elif name == "dd":
        raw_targets = [arg[3:] for arg in args if arg.startswith("of=")]
    elif name == "tar":
        # Only the explicit-directory case is worth the cheap detection here — `tar -x`
        # into the implicit current directory is still invisible (see the module's Known limits).
        extracting = any(
            arg in ("-x", "--extract", "--get")
            or (arg.startswith("-") and not arg.startswith("--") and "x" in arg[1:])
            for arg in args
        )
        if extracting:
            _, values = _operands(args, frozenset({"-C", "--directory"}))
            directories = values.get("-C", []) + values.get("--directory", [])
            raw_targets = [directory.rstrip("/") + "/*" for directory in directories]
    elif name == "unzip":
        # Same tradeoff as tar above: only `-d <dir>` is recognized; extraction into the implicit
        # current directory is not (Known limits). -l/-t/-v list/test the archive without writing.
        if not any(arg in ("-l", "-t", "-v") for arg in args):
            _, values = _operands(args, frozenset({"-d"}))
            raw_targets = [directory.rstrip("/") + "/*" for directory in values.get("-d", [])]
    elif name == "find" and "-delete" in args:
        # Only the leading path operand(s) — find's own operand/expression split is otherwise too
        # ambiguous to parse generically here; no leading operand at all (bare "find -delete",
        # implicit ".") stays undetected (Known limits).
        roots = []
        for arg in args:
            if arg.startswith("-"):
                break
            roots.append(arg)
        raw_targets = [root.rstrip("/") + "/*" for root in roots]
    elif name in ("curl", "wget"):
        raw_targets = _download_targets(name, args)
    elif name == "git":
        return _git_targets(args, bases, git_writes), None
    elif name in _SHELL_NAMES:
        for position, arg in enumerate(args):
            if arg.startswith("-") and not arg.startswith("--") and "c" in arg[1:]:
                if position + 1 < len(args):
                    return _scan_command(args[position + 1], bases, git_writes, depth + 1), None
                break
    elif name == "eval":
        return _scan_command(" ".join(args), bases, git_writes, depth + 1), None
    return _pairs(raw_targets, bases), None


def _scan_tokens(tokens: list[_Token], start_bases: _Bases, git_writes: frozenset, depth: int) -> list[_Target]:
    """Walk a token stream command by command (step 4 of the section comment). Directory tracking,
    as a set of possible directories (None = unknown):
      - `cd <literal dir>` as the first command of a list, into a directory that exists, replaces
        the set; after `&&`/`||` or a prefix (`if`, `{`, ...) it is conditional, so the commands
        after it in the same `&&` chain see only the new directory, but after the list ends both
        old and new remain possible; a `||` makes everything seen in that list possible;
      - `cd` without a literal directory (`cd`, `cd -`, `cd $X`, `cd ~`), `pushd`/`popd`, any `cd`
        inside a subshell or `$(...)`, and a `cd` next to a pipe or `&` add "unknown";
      - `( ... )` restores the outer directories when it closes."""
    found: list[_Target] = []
    bases = start_bases
    list_start = start_bases
    after_list = start_bases
    saved: list[tuple[_Bases, _Bases, _Bases]] = []
    words: list[str] = []
    redirect_targets: list[str] = []
    other_redirect_words: list[str] = []
    prev_sep: Optional[str] = None
    index = 0
    while True:
        at_end = index >= len(tokens)
        text, is_op = tokens[index] if not at_end else ("", True)
        if not at_end and not is_op:
            words.append(text)
            index += 1
            continue
        if not at_end and text not in _SEPARATOR_OPS:
            # A redirection. A bare number glued before it (`2>`) is its fd, not an argument.
            if index > 0 and not tokens[index - 1][1] and tokens[index - 1][0].isdigit() and words:
                words.pop()
            has_word = index + 1 < len(tokens) and not tokens[index + 1][1]
            if has_word:
                word = tokens[index + 1][0]
                if text in _WRITE_REDIRECT_OPS or (text == ">&" and not _FD_DUP_WORD_RE.match(word)):
                    redirect_targets.append(word)
                else:
                    other_redirect_words.append(word)  # an input redirect has no target, a span in it still runs
            index += 2 if has_word else 1
            continue

        separator = None if at_end else text
        if words or redirect_targets or other_redirect_words:
            found.extend(_pairs(redirect_targets, bases))
            for word in words + redirect_targets:
                if "$(" in word:
                    found.extend(_scan_command(word, bases, git_writes, depth + 1))
            # Backtick spans the tokenizer found in these words (quote context already applied).
            for word in words + redirect_targets + other_redirect_words:
                for span in getattr(word, "subs", ()):
                    found.extend(_scan_command(span, bases, git_writes, depth + 1))
            targets, cd_change = _simple_command_targets(words, bases, git_writes, depth)
            found.extend(targets)
            if cd_change is not None:
                directory, prefixed = cd_change
                near_pipe = prev_sep in _PIPE_OPS or separator in _PIPE_OPS or separator == "&"
                if directory is None or saved or near_pipe:
                    bases = bases | {None}
                    after_list = after_list | {None}
                else:
                    new_bases = _cd_bases(bases, directory)
                    first_in_list = prev_sep is None or prev_sep in _LIST_END_OPS or prev_sep == "("
                    exists = all(base is None or Path(base).is_dir() for base in new_bases)
                    if first_in_list and not prefixed and exists:
                        after_list = new_bases
                    else:
                        after_list = after_list | new_bases
                    bases = new_bases
        words = []
        redirect_targets = []
        other_redirect_words = []
        if separator is None:
            return found
        if separator == "||":
            bases = bases | list_start | after_list
        elif separator in _LIST_END_OPS:
            bases = list_start = after_list
        elif separator == "(":
            saved.append((bases, list_start, after_list))
            list_start = after_list = bases
        elif separator == ")" and saved:
            bases, list_start, after_list = saved.pop()
        prev_sep = separator
        index += 1


def _scan_command(command: str, bases: _Bases, git_writes: frozenset, depth: int) -> list[_Target]:
    """All write targets of `command` (steps 1-4 of the section comment). Recursion depth is capped
    for nested `sh -c`/`eval`/`$(...)`; beyond it only the raw-text search runs. When neither
    tokenizing manages the whole command, the tokens each read before it failed are scanned too,
    next to the raw-text search."""
    quote_model = _quote_model_applies(command)
    command = _join_line_continuations(command)
    if depth > _MAX_SCAN_DEPTH:
        # Nested deeper than anything real: not read any further, and not passed either — the whole
        # remainder is one target that names no knowable path (a `$(` text), which check 1c denies and
        # check 1 denies when the remainder names .act/.
        return [(target, None) for target in _raw_redirect_targets(command)] + [(f"$({command})", None)]
    found: list[_Target] = []
    tokens: Optional[list[_Token]] = None
    prefixes: list[list[_Token]] = []  # what came before the word that broke a tokenizing attempt
    ansi_c_quoting = _may_use_ansi_c_quoting(command) if quote_model else "$'" in command
    if not ansi_c_quoting:
        try:
            tokens = _line_mode_tokens(command)
        except ValueError as error:
            tokens = None
            prefixes.append(getattr(error, "partial", []))
    if tokens is None:
        # The whole-command fallback skips no heredoc itself: the bodies of quoted-delimiter heredocs,
        # which bash never runs, are cut out first (unless `$'` may be live, where nothing is trusted).
        # A body that may be a shell's script (`bash <<'EOF'`) is not cut out either: it is scanned.
        keep_bodies = ansi_c_quoting or not quote_model or _heredoc_may_feed_shell(command)
        whole = command if keep_bodies else _without_quoted_heredoc_bodies(command)
        try:
            tokens = _shell_tokens(whole, newline_is_operator=True)
        except ValueError as error:
            tokens = None
            prefixes.append(getattr(error, "partial", []))
        if tokens is None or ansi_c_quoting:
            found.extend((target, None) for target in _raw_redirect_targets(whole))
    if tokens is not None:
        found.extend(_scan_tokens(tokens, bases, git_writes, depth))
    else:
        # Neither tokenizing reached the end: the commands before the word that broke each attempt
        # are still real (an earlier line of the command), so they are scanned like any other. For a
        # single-line command the line-mode and whole-command attempts break at the same word and
        # hand back identical prefixes — scan each distinct prefix once, not twice.
        scanned: list[list[_Token]] = []
        for prefix in prefixes:
            if prefix and prefix not in scanned:
                scanned.append(prefix)
                found.extend(_scan_tokens(prefix, bases, git_writes, depth))
    if depth > 0:
        # The text of a nested shell (`sh -c`, which may be dash with no brace expansion at all, or a
        # bash started with `+B`), of an `eval` or of a `$(...)`/backtick span is read again by a parser
        # of its own: what this lexer saw of its quoting does not say what expands there, so its words
        # carry no `live` and a brace list in them stays dynamic for the write-scope check.
        found = [(_without_live(target), base) for target, base in found]
    return found


def _without_live(target: str) -> str:
    """`target` with what the lexer knew about its quoting dropped (`_Word.live` None); text, `subs`
    and `bare` stay as they were. A plain `str` comes back as it is."""
    if getattr(target, "live", None) is None:
        return target
    return _Word(str(target), getattr(target, "subs", ()), getattr(target, "bare", None))


def _bash_write_targets_new(command: str, base_cwd: str, git_writes: frozenset) -> list[_Target]:
    """The write targets the word lexer's scan finds — one half of what _bash_write_targets returns.
    Any exception propagates: the caller drops this half then and keeps the legacy half alone."""
    pairs = _scan_command(command, frozenset({base_cwd}), git_writes, depth=0)
    result: list[_Target] = []
    seen: set[tuple] = set()
    for pair in pairs:
        key = _pair_key(pair)
        if not _is_ignorable_write_target(pair[0]) and key not in seen:
            seen.add(key)
            result.append(pair)
    return result


def _pair_key(pair: _Target) -> tuple:
    """What makes two targets the same one: text and base, and for a word of the lexer also which of
    its characters were live (`_Word.live`) — `'{a,b}'` and `{a,b}` read alike but are not the same
    word to the shell."""
    return (str(pair[0]), pair[1], getattr(pair[0], "live", None))


def _bash_write_targets(command: str, base_cwd: str, git_writes: frozenset) -> list[_Target]:
    """The paths a Bash command writes to, each paired with the directory a relative one resolves
    against (`base_cwd`, the Bash tool's own cwd, moved by any `cd` the scanner can follow) or None
    where that directory is unknown — see the module docstring for how and its known limits. A
    target reachable from several possible directories is listed once per directory. Null devices
    and standard streams are dropped. `git_writes` names the git subcommands that count as writes
    for the calling check (_GIT_WRITES_TEMPLATE_GUARD / _GIT_WRITES_WORKER_SCOPE).

    The result is the UNION of two scanners: shell_targets_legacy's (the previous, shlex-based one,
    first and in its own order) and this module's word lexer (_bash_write_targets_new), each target
    pair once. The union is what keeps the lexer from ever weakening a check: whatever the previous
    scanner reported is still reported, however the lexer reads the same text. An exception in the
    lexer's half — ValueError, RecursionError, a bug — is swallowed and the legacy half alone
    returned; one in the legacy half propagates, exactly as it did before the lexer existed (the
    legacy function itself falls back to the raw-text search on its own failures)."""
    legacy = _legacy_targets._bash_write_targets(command, base_cwd, git_writes)
    try:
        current = _bash_write_targets_new(command, base_cwd, git_writes)
    except Exception:  # noqa: BLE001 — the legacy half stands alone, see the docstring
        return legacy
    # A target both scanners report appears once, as the lexer's word: only that one knows which of its
    # characters were quoted (`_Word.live`). The legacy half still adds everything the lexer missed,
    # as plain text with no such knowledge.
    by_text: dict[tuple, list[_Target]] = {}
    for pair in current:
        by_text.setdefault((str(pair[0]), pair[1]), []).append(pair)
    merged: list[_Target] = []
    seen: set[tuple] = set()
    for pair in legacy:
        for candidate in by_text.get((str(pair[0]), pair[1]), [pair]):
            key = _pair_key(candidate)
            if key not in seen:
                seen.add(key)
                merged.append(candidate)
    for pair in current:
        key = _pair_key(pair)
        if key not in seen:
            seen.add(key)
            merged.append(pair)
    return merged
