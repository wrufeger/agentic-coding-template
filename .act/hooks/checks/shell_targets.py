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
#   - writes made from inside a program are invisible to _bash_write_targets: `python -c "open(...)"`,
#     a script file, `find -exec`, `xargs` fed from stdin, an alias or shell function. Only the worker
#     write scope reads inline interpreter code on top of that, through _bash_inline_code_targets (a
#     second walk of the same scan with a side channel, _INLINE_SINK; reading and limits in
#     inline_code.py), and the git-metadata guard reads the program text of inline Python through
#     _bash_inline_code (_INLINE_CODE_SINK, with the span where a top-level program stands, _SPAN_TEXT);
#     what _bash_write_targets returns is not changed by either;
#   - the command line of `wsl`/`wsl.exe` runs inside WSL and is read as such (_wsl_targets): without
#     `--exec` as the one text wsl hands to the distribution's shell (like `eval`), with `--exec` as the
#     words as they stand; `/mnt/<x>/...` found there is drive <X>: on win32 (_wsl_native_word), and
#     nowhere else - the call's own redirections run in the outer shell. Not read: a management
#     command (`wsl --export`, `--import`), a `--cd` into `~` or a Linux path (the directory is then
#     unknown), a heredoc the outer shell feeds to an interpreter inside WSL (its body is not the
#     line's), and the Linux side of the file system (`/home`, `/tmp` there) as a place of its own;
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
#     block, never a miss). The body of an `$((...))` is scanned as if it were a command (over-
#     scanning its arithmetic — the safe side: a `>` in it counts as a redirection), but the
#     expansion itself is no target and no command text (_rescan_word). A word of an `ssh [options]
#     <host> <command>` call that holds `$(` is not read as a local command either, when the call has
#     exactly a known, harmless form (_ssh_remote_start, an allow list: anything else is read as
#     before) - the program is `ssh` or the one of a system directory, a word in front is only a
#     reserved word or the bare name of a wrapper that runs its argument list itself (_SSH_ARGV_WRAPPERS,
#     a duration after `timeout`; never `parallel`, `xargs` or a wrapper's option), every word up to the destination is plain text (no `$`, backtick, `{`, `*`, `?`, `[`,
#     `~`), every option is one of `-4 -6 -a -C -n -q -T -t -v -x` (also combined) or `-p <port>`,
#     `-l <name>`, `-i <file>` (so never `-o`, `-F`, `-E`, `-J`, `-W`, `-L`, `-R`, `-D`), the
#     destination is `[user@]host` and not this machine (`localhost` and its variants, `127/8` and
#     `0/8` in any spelling, the IPv6 loopback, `ip6-*`, this computer's own name: _is_local_ssh_host),
#     the first word after it begins with a plain character other than `-` (ssh reads options after
#     the destination too, and an expansion there can become one), and nothing in the command sets
#     `PATH` or `BASH_ENV`, defines a function `ssh`, an alias, reads a file with `source` or `.`, uses
#     `enable` or `command_not_found_handle` or changes bash's command hash (_SSH_SHADOWED_RE). Only the
#     `$(...)` that are easy to cut out of such a word are scanned, one in single quotes included (it
#     cannot be told from one in double quotes, which runs here); a `$(...)` that is not easy to cut
#     out makes the whole word count as before - also one that ends later than its first `)` can (a
#     `case` pattern, a comment, a here-document: any `#`, `<<`, line break or `case` inside it, or a
#     `)` left over in the rest of the word that closes nothing). Such a word is read whole and
#     nothing of it is taken out of the legacy half. The command text of an ssh call without a `$(`
#     was never read. An alias in an ssh configuration that points at this machine cannot be seen.
#     A line
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
import ipaddress
import os
import re
import socket
import sys
from pathlib import Path
from typing import Optional

from . import inline_code as _inline_code
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
    "_HeredocOperand", "_InlineTarget", "_bash_inline_code_targets",
    "_InlineCode", "_bash_inline_code",
    "_WSL_VALUE_OPTIONS", "_WSL_FLAG_OPTIONS", "_WSL_MOUNT_RE", "_wsl_native_word", "_wsl_command_line",
    "_wsl_targets",
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

# `wsl`/`wsl.exe` runs its command line inside WSL, where the Windows drive <X>: is mounted at
# `/mnt/<x>/`. The form is a drive only there: a file tool resolves `/mnt/d/x` on Windows below the
# current drive (`D:\mnt\d\x`) and Git Bash below its own root, so the rewrite (_wsl_native_word) is
# applied to nothing but the words of a wsl command line (_wsl_targets). wsl's own options: the ones
# that take the next word as their value, the flags without one; any other `-...` word is a
# management command (`--list`, `--shutdown`, `--export`, ...) that runs no command line.
_WSL_VALUE_OPTIONS = frozenset({
    "-d", "--distribution", "--distribution-id", "-u", "--user", "--cd", "--shell-type",
})
_WSL_FLAG_OPTIONS = frozenset({"-e", "--exec", "--system"})
_WSL_MOUNT_RE = re.compile(r"^/mnt/([A-Za-z])(?=/|$)")

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
# here — it is already one word, already matched by _WRAPPER_ARG_RE. A cluster of short options whose
# last letter is one of these (`exec -la name`, `sudo -Hu name`) takes the next word too
# (_wrapper_value_follows).
_WRAPPER_VALUE_FLAGS = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}),
    "exec": frozenset({"-a"}),
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
    guard, worker write scope, the PowerShell scanner's own resolution and
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
    as not provably live.

    `span` is where the word stood in the command text, (start, end) offsets of its raw text with
    its quotes, set only by the line-wise tokenizer on the top-level text of an inline-code scan
    (_bash_inline_code, `_SPAN_TEXT`); None everywhere else - in a nested scan the offsets would
    point into another text."""

    subs: tuple[str, ...]
    bare: str
    live: Optional[str]
    span: Optional[tuple[int, int]] = None

    def __new__(
        cls, text: str, subs: tuple[str, ...] = (), bare: Optional[str] = None, live: Optional[str] = None
    ) -> "_Word":
        word = super().__new__(cls, text)
        word.subs = subs
        word.bare = text if bare is None else bare
        word.live = live if live is not None and len(live) == len(text) else None
        return word


# A backslash before a backslash, a dollar sign or a backtick: what bash resolves in the body of a heredoc
# with an unquoted delimiter.
_HEREDOC_ESCAPE_RE = re.compile(r"\\([\\$`])")


class _HeredocOperand(_Word):
    """The delimiter word of a heredoc, carrying the text bash hands to the command as its standard input
    (`heredoc_text`): the body lines, with the leading tabs of `<<-` removed and, for an unquoted
    delimiter, the backslash escapes bash resolves in an expanded body (_HEREDOC_ESCAPE_RE).
    Its own text is the delimiter as before. `expands` says whether the delimiter was unquoted;
    `body_span` is where the raw body lines stand in the command text, (start of the first body
    line, start of the end-word line), known only on the top-level text of an inline-code scan (see
    _Word.span), else None. Only built while _bash_inline_code_targets scans; no other caller ever
    sees one."""

    heredoc_text: str
    expands: bool
    body_span: Optional[tuple[int, int]]

    def __new__(
        cls, word: str, body_lines: list[str], expands: bool, body_span: Optional[tuple[int, int]] = None,
    ) -> "_HeredocOperand":
        operand = super().__new__(
            cls, str(word), getattr(word, "subs", ()), getattr(word, "bare", None), getattr(word, "live", None)
        )
        lines = [line.lstrip("\t") for line in body_lines] if str(word).startswith("-") else list(body_lines)
        text = "\n".join(lines)
        operand.heredoc_text = _HEREDOC_ESCAPE_RE.sub(r"\1", text) if expands else text
        operand.expands = expands
        operand.body_span = body_span
        return operand


# The write targets inline interpreter code names (see _bash_inline_code_targets), collected as a side
# channel while _scan_command walks a command; None outside that scan, so every other caller of the
# scanner gets exactly the result it always got. A hook process scans one command at a time.
_INLINE_SINK: Optional[list] = None
# The program texts themselves, (language, code, directory, source, span), for a check that reads such
# a program on its own (see _bash_inline_code); None outside that scan, same rule.
_INLINE_CODE_SINK: Optional[list] = None
# The top-level command text of a _bash_inline_code scan, after line continuations are joined: the one
# text whose words get a `span` (_Word.span) and whose heredoc bodies get a `body_span`. _scan_command
# compares the text it tokenizes against it, so a nested text (`sh -c`, `eval`, a `$(...)`, a heredoc
# body a shell runs, a wsl line) never carries offsets into the wrong text. None outside such a scan.
_SPAN_TEXT: Optional[str] = None
# Greater than zero while the scanner reads the command line of a `wsl`/`wsl.exe` call (_wsl_targets):
# every target and `cd` directory found there is a WSL path, so `/mnt/<x>/` is drive <X>: (_pairs,
# _cd_bases, the inline-code paths). Zero everywhere else, where the same text is no drive.
_WSL_DEPTH = 0


def _wsl_native_word(word: str) -> str:
    """A word that names the WSL mount of a Windows drive (`/mnt/d/x`, `/mnt/d`) rewritten to the drive
    form every check compares against (`D:/x`, `D:/`), on win32 only; any other word, and every word on
    another platform, comes back as it is. Called only while the scanner reads the command line of a
    `wsl`/`wsl.exe` call (_WSL_DEPTH) and by outside_root for the words of such a line: outside WSL the
    same text is no drive. A `_Word` keeps its spans and what the lexer knew about its quoting (`live`),
    the drive letter and colon counting as quoted text; a plain `str` comes back as a plain `str`."""
    if sys.platform != "win32":
        return word
    match = _WSL_MOUNT_RE.match(word)
    if match is None:
        return word
    rest = word[match.end():] or "/"
    text = f"{match.group(1).upper()}:{rest}"
    if not isinstance(word, _Word):
        return text
    bare = word.bare
    if bare.startswith(match.group(0)):
        bare = f"{match.group(1).upper()}:{bare[match.end():] or '/'}"
    live = word.live
    if live is not None:
        live = "." * (len(text) - len(live) + match.end()) + live[match.end():]
    return _Word(text, word.subs, bare, live)


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


def _shell_tokens(text: str, newline_is_operator: bool, with_spans: bool = False) -> list[_Token]:
    """Tokenize `text` into (text, is_operator) pairs; a word's text is a `_Word`. Whitespace
    separates words, a run of operator characters (`_SHELL_OPERATOR_CHARS`, plus a newline when
    `newline_is_operator`) is split into operators (_split_operator_run), an unquoted `#` at the
    start of a word comments out the rest of the line (the newline itself stays), and `#` inside a
    word is just a character. With `with_spans` every word carries its (start, end) offsets in
    `text` (_Word.span). Raises ValueError (a _TokenizeError with the tokens before the failing
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
            start = index
            try:
                word, index = _read_word(text, index, operator_chars, blank, not newline_is_operator)
            except ValueError as error:
                raise _TokenizeError(str(error), tokens) from error
            if with_spans:
                word.span = (start, index)
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


# `<<-` followed by blanks and the delimiter word (not `<<<-`, a here-string).
_DASH_HEREDOC_BLANK_RE = re.compile(r"(?<!<)<<-[ \t]+(?=\S)")


def _heredoc_operand_positions(tokens: list[_Token]) -> list[int]:
    """The index of the delimiter word of every heredoc a line opens, in the order and by the same
    reading as _heredoc_delimiters (a `<<` operator followed by a word)."""
    return [
        index + 1 for index in range(len(tokens) - 1)
        if tokens[index][1] and tokens[index][0] == "<<" and not tokens[index + 1][1]
    ]


_SHORT_OPTION_CLUSTER_RE = re.compile(r"-[A-Za-z]{2,}")


def _wrapper_value_follows(arg: str, value_flags: frozenset) -> bool:
    """True when the wrapper option `arg` takes the next word as its value: the option itself (`-u`,
    `--unset`) or a cluster of short options whose last letter takes one (`exec -la name`, `sudo -Hu
    name`, `xargs -tI {}`). A value letter earlier in a cluster takes the rest of the word instead
    (`env -uVAR`, `nice -n5`), so the next word is then the command."""
    if arg in value_flags:
        return True
    if _SHORT_OPTION_CLUSTER_RE.fullmatch(arg) is None:
        return False
    for position, letter in enumerate(arg[1:], start=1):
        if "-" + letter in value_flags:
            return position == len(arg) - 1
    return False


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
                if _wrapper_value_follows(arg, value_flags):
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


def _line_mode_tokens(command: str, with_spans: bool = False) -> list[_Token]:
    """Tokenize line by line with heredoc bodies skipped (step 2 of the section comment). A body is
    skipped only up to a terminator line that exists (found via _heredoc_terminator);
    without one, nothing is skipped, so the rest is scanned as commands. The command substitutions
    of an expanded body are kept (as commands of their own after the heredoc line). With
    `with_spans` (the top-level text of an inline-code scan) every word carries its offsets in
    `command` and every heredoc operand the offsets of its body (_Word.span,
    _HeredocOperand.body_span), except on a line this reading rewrites before tokenizing. Raises
    ValueError if any line does not tokenize on its own — a _TokenizeError whose `partial` holds the
    tokens before the failing word."""
    lines = command.split("\n")
    line_positions: dict[str, list[int]] = {}
    line_starts = [0]  # offset in `command` of each line, plus one past the end
    for position, raw_line in enumerate(lines):
        line_positions.setdefault(raw_line.strip(), []).append(position)
        line_starts.append(line_starts[-1] + len(raw_line) + 1)
    tokens: list[_Token] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if _INLINE_SINK is not None:
            # Inline-code reading only: `<<- 'EOF'` (blanks after the `-`) names its delimiter after them,
            # as bash does; the other callers keep reading `-` as the delimiter and scan the body.
            line = _DASH_HEREDOC_BLANK_RE.sub("<<-", line)
        line_spans = with_spans and line == lines[index]
        try:
            line_tokens = _shell_tokens(line, newline_is_operator=False, with_spans=line_spans)
        except _TokenizeError as error:
            raise _TokenizeError(str(error), tokens + error.partial) from error
        if line_spans:
            offset = line_starts[index]
            for word, is_op in line_tokens:
                if not is_op and word.span is not None:
                    word.span = (word.span[0] + offset, word.span[1] + offset)
        line_first = len(tokens)
        tokens.extend(line_tokens)
        tokens.append(("\n", True))
        index += 1
        delimiters = _heredoc_delimiters(line_tokens, line)
        feeds_shell = _heredoc_shell_flags(line_tokens) if delimiters else []
        operand_positions = _heredoc_operand_positions(line_tokens) if delimiters and _INLINE_SINK is not None else []
        for position, (candidates, expands) in enumerate(delimiters):
            end = _heredoc_terminator(line_positions, candidates, index)
            if end is None:
                break
            if position < len(operand_positions):
                # Inline-code reading only (_bash_inline_code_targets): the delimiter word carries its
                # body, so the command the heredoc feeds can read it. The word's text stays the same.
                at = line_first + operand_positions[position]
                body_span = (line_starts[index], line_starts[end]) if with_spans else None
                tokens[at] = (_HeredocOperand(tokens[at][0], lines[index:end], expands, body_span), False)
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
    a drive on Windows (`/tmp`, Git Bash's own mount points) has no knowable native location - except
    inside a wsl command line, where `/mnt/<x>/` is drive <X>: (_WSL_DEPTH)."""
    if _WSL_DEPTH:
        directory = _wsl_native_word(directory)
    native = _to_native_path(directory)
    if Path(native).is_absolute():
        return frozenset({native})
    if native.startswith(("/", "\\")):
        return frozenset({None})
    return frozenset(_joined_base(base, native) for base in bases)


def _pairs(raw_targets: list[str], bases: _Bases) -> list[_Target]:
    """Every raw target paired with every possible base directory. Inside a wsl command line
    (_WSL_DEPTH) a target `/mnt/<x>/...` is the drive it mounts (_wsl_native_word)."""
    if not raw_targets:
        return []  # nothing to pair: skip sorting a set that grows with a long `cd` chain
    if _WSL_DEPTH:
        raw_targets = [_wsl_native_word(raw) for raw in raw_targets]
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
                elif _wrapper_value_follows(arg, wrapper_value_flags):
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
    elif name == "wsl":
        return _wsl_targets(args, bases, git_writes, depth), None
    elif name in _SHELL_NAMES:
        for position, arg in enumerate(args):
            if arg.startswith("-") and not arg.startswith("--") and "c" in arg[1:]:
                if position + 1 < len(args):
                    return _scan_command(args[position + 1], bases, git_writes, depth + 1), None
                break
    elif name == "eval":
        return _scan_command(" ".join(args), bases, git_writes, depth + 1), None
    elif name == "cmd":
        # `cmd /c <line>` (also `/k`, any case, after cmd's own switches such as `/d` or `/q`): cmd.exe
        # parses the line anew by its own rules, so it is read like an `eval` of the words - as close
        # as this reading gets (cmd quotes and escapes differently: a guard rail, not a boundary).
        for position, arg in enumerate(args):
            if arg.lower() in ("/c", "/k"):
                return _scan_command(" ".join(args[position + 1:]), bases, git_writes, depth + 1), None
            if not arg.startswith("/"):
                break
    return _pairs(raw_targets, bases), None


def _wsl_command_line(args: list[str]) -> Optional[tuple[list[str], Optional[str], bool]]:
    """The arguments of a `wsl`/`wsl.exe` call split into (the command line WSL runs, the `--cd`
    directory or None, whether `--exec`/`-e` hands the words to the program without a shell), or None
    when the call runs no command line: a management command (`wsl --list`, `--shutdown`, `--export`,
    any other `-...` word that is not one of wsl's run options, _WSL_VALUE_OPTIONS/_WSL_FLAG_OPTIONS)
    or no word after the options. `--` ends the options, as wsl reads it."""
    cd_dir: Optional[str] = None
    exec_mode = False
    index = 0
    while index < len(args):
        arg = str(args[index])
        if arg == "--":
            index += 1
            break
        if arg in _WSL_VALUE_OPTIONS:
            if arg == "--cd" and index + 1 < len(args):
                cd_dir = args[index + 1]
            index += 2
            continue
        if arg in _WSL_FLAG_OPTIONS:
            exec_mode = exec_mode or arg in ("-e", "--exec")
            index += 1
            continue
        if arg.startswith("-"):
            return None
        break
    rest = args[index:]
    if not rest:
        return None
    return rest, cd_dir, exec_mode


def _wsl_targets(args: list[str], bases: _Bases, git_writes: frozenset, depth: int) -> list[_Target]:
    """Write targets of `wsl [options] [--] <command line>`. The line runs inside WSL: without `--exec`
    wsl joins the words with blanks and hands the text to the distribution's shell, which parses it
    anew - read like an `eval` of that text; with `--exec` the words are the program's arguments as they
    stand. `--cd <dir>` sets the directory the line runs in (a Windows path or `/mnt/<x>/...`; anything
    else, `~` or a Linux path, leaves it unknown). While the line is read (_WSL_DEPTH) every target and
    `cd` directory `/mnt/<x>/...` is drive <X>: (_wsl_native_word) - the words of the wsl call itself,
    its redirections and the rest of the command are read by the caller as before, outside WSL. The
    mapping is a win32 matter; the line is read as a command on every platform."""
    global _WSL_DEPTH
    parsed = _wsl_command_line(args)
    if parsed is None:
        return []
    rest, cd_dir, exec_mode = parsed
    if cd_dir is not None:
        native = _to_native_path(str(_wsl_native_word(cd_dir)))
        bases = frozenset({native}) if Path(native).is_absolute() else frozenset({None})
    _WSL_DEPTH += 1
    try:
        if exec_mode:
            targets, _ = _simple_command_targets(list(rest), bases, git_writes, depth)
            return targets
        return _scan_command(" ".join(str(word) for word in rest), bases, git_writes, depth + 1)
    finally:
        _WSL_DEPTH -= 1


# (path literal, the directory a relative one resolves against - None = unknown, interpreter language)
_InlineTarget = tuple[str, Optional[str], str]
_ECHO_FLAGS_RE = re.compile(r"^-[neE]+$")
# A printf format that prints its arguments and nothing else.
_PRINTF_ARGS_ONLY_RE = re.compile(r"^(?:%[sb]|\\n| )+$")


def _stdin_redirect(operator: str, word: str) -> Optional[str | bool]:
    """What an input redirection does to a command's standard input, for the inline-code reading: the
    literal text (a heredoc body, a here-string) as a `str`, or False for a redirection from something
    that is not literal text (a file, a descriptor, a heredoc whose body was not kept); None if the
    operator is no input redirection."""
    if operator == "<<":
        return getattr(word, "heredoc_text", False)
    if operator == "<<<":
        return str(word) + "\n"
    if operator in ("<", "<&", "<>"):
        return False
    return None


def _literal_output(words: list[str], stdin_text: Optional[str]) -> Optional[str]:
    """The text a simple command writes to its standard output when that text is literally known: `cat`
    without a file operand (its own standard input, a heredoc), `echo` and `printf` (their arguments).
    None for anything else - a pipe from `cat file.py` yields nothing."""
    at = _command_prefix_end(words)
    if at >= len(words):
        return None
    name = _command_name(words[at])
    args = [str(word) for word in words[at + 1:]]
    if name == "cat":
        return stdin_text if not [arg for arg in args if arg != "-" and not arg.startswith("-")] else None
    if name == "echo":
        while args and _ECHO_FLAGS_RE.match(args[0]):
            args = args[1:]
        return " ".join(args) + "\n"
    if name == "printf" and args:
        if "%" not in args[0]:
            return args[0].replace("\\n", "\n")
        if _PRINTF_ARGS_ONLY_RE.match(args[0]):
            return " ".join(args[1:]) + "\n"
    return None


def _collect_inline_code(
    words: list[str], bases: _Bases, stdin_redirected: bool, stdin_text: Optional[str], pipe_input: Optional[str],
    stdin_span: Optional[tuple[int, int]] = None,
) -> None:
    """If this simple command runs inline interpreter code (inline_code.py: `python -c`, `node -e`, or a
    program read from standard input), add the path literals of that code - when it holds a write call -
    to the active _INLINE_SINK, once per directory the command may run in, and the program text itself
    to the active _INLINE_CODE_SINK, with the span where it stands in the top-level text when that is
    known (`stdin_span` for a quoted heredoc body; the span of the one word behind `-c`/`-e` when bash
    leaves that word as written; else None). The program on standard input is a heredoc body or
    here-string of the command itself, else the literal output of the previous stage of its pipeline.
    Inside a wsl command line (_WSL_DEPTH) a path literal `/mnt/<x>/...` is drive <X>:, as the
    interpreter sees it there. Best effort: an error here costs this command's result, never the scan."""
    sink = _INLINE_SINK
    code_sink = _INLINE_CODE_SINK
    if sink is None and code_sink is None:
        return
    try:
        at = _command_prefix_end(words)
        if at >= len(words):
            return
        language = _inline_code.interpreter_language(_command_name(words[at]))
        if language is None:
            return
        kind, code, code_index = _inline_code.code_source_at(language, [str(word) for word in words[at + 1:]])
        span: Optional[tuple[int, int]] = None
        if kind == _inline_code.SOURCE_STDIN:
            code = stdin_text if stdin_redirected else pipe_input
            span = stdin_span if stdin_redirected else None
        elif kind != _inline_code.SOURCE_CODE:
            return
        elif code_index is not None:
            # The word that is the code: its span counts only when bash leaves the word as written -
            # no live syntax (an unquoted part, a `$` inside double quotes), no backtick span, no
            # `$(` at all (a `$(...)` is marked `.` in `live`, judged by its own rules, and the scan
            # reads every word holding one as command text, _rescan_word) - so that taking the word
            # out of the shell reading drops nothing bash itself would run.
            word = words[at + 1 + code_index]
            live = getattr(word, "live", None)
            if live is not None and "L" not in live and not getattr(word, "subs", ()) and "$(" not in word:
                span = getattr(word, "span", None)
        if code is None:
            return
        if any(str(word) in ("-C", "--chdir") or str(word).startswith("--chdir=") for word in words[:at]):
            bases = frozenset({None})  # `env -C dir python ...`: the directory is not followed
        ordered = sorted(bases, key=lambda candidate: (candidate is None, candidate or ""))
        if code_sink is not None:
            for base in ordered:
                code_sink.append((language, code, base, kind, span))
        if sink is None:
            return
        paths = _inline_code.write_paths(language, code)
        for path in paths:
            if _WSL_DEPTH:
                path = str(_wsl_native_word(path))
            for base in ordered:
                sink.append((path, base, language))
    except Exception as error:  # noqa: BLE001
        # Deliberately broad: whatever goes wrong while reading one command's inline code (newer,
        # best-effort code on top of the scan) must neither refuse the call nor end the walk over the
        # commands that follow - only this command's inline part is lost. Said on standard error.
        _inline_code.report_skipped("one command", error)


def _track_group_output(
    group_outputs: list[list[Optional[str]]], words: list[str], separator: Optional[str],
    produced: Optional[str], closed_group: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    """Inline-code reading only: follow the literal output of `{ ...; }` and `( ... )` groups through
    _scan_tokens, so a pipe behind a group (`{ cat <<'EOF'; } | python -`, `(echo ...) | node`) hands
    the group's text on. Called at the end of each segment with its words, its separator and the output
    its command produced; `group_outputs` holds one list per open group. Returns (the output the segment
    stands for - a closing `}` stands for its group, an empty segment behind a `)` for the subshell that
    closed -, the output of a subshell that this segment's `)` closes). A group with a statement whose
    output is not literal has none."""
    texts = [str(word) for word in words]
    if texts and texts[0] == "{":
        group_outputs.append([])
    if texts == ["}"] and group_outputs:
        produced = _joined_group_output(group_outputs.pop())
    elif not texts and closed_group is not None:
        produced = closed_group
    if (texts or produced is not None) and group_outputs:
        group_outputs[-1].append(produced)
    closed: Optional[str] = None
    if separator == "(":
        group_outputs.append([])
    elif separator == ")" and group_outputs:
        closed = _joined_group_output(group_outputs.pop())
    return produced, closed


def _joined_group_output(parts: list[Optional[str]]) -> Optional[str]:
    """The text the statements of a group wrote together, None if one of them has no literal output
    (or the group has no statement at all)."""
    if not parts or any(part is None for part in parts):
        return None
    return "".join(part for part in parts if part is not None)


def _arithmetic_parts(text: str) -> Optional[tuple[list[str], str]]:
    """The bodies of the `$((...))` constructs in `text`, and `text` with each of them replaced by `0`
    — or None when there is none, or one cannot be delimited (then the caller reads `text` whole, as
    before). The tokenizer keeps such a construct in its word verbatim, so a re-scan of the word as
    command text meets the same construct again; the bodies are what a re-scan has to read."""
    bodies: list[str] = []
    rest: list[str] = []
    index = 0
    while True:
        at = text.find("$((", index)
        if at < 0:
            break
        try:
            end = _collect_dq_expansion(text, at + 1, [])
        except ValueError:
            return None
        if end < at + 5 or text[end - 2:end] != "))":
            return None
        rest.append(text[index:at] + "0")
        bodies.append(text[at + 3:end - 2])
        index = end
    if not bodies:
        return None
    rest.append(text[index:])
    return bodies, "".join(rest)


def _rescan_word(word: str, bases: _Bases, git_writes: frozenset, depth: int) -> list[_Target]:
    """Read a word that holds `$(` as command text once more (a command substitution runs commands).
    An arithmetic expansion `$((...))` in it is not a command: its body is read as command text instead
    (a `$(...)` inside it still runs, `$(( a[$(cmd > f)] ))`; a `>` in it counts as a redirection, the
    safe side), and what is left of the word only when that still holds `$(`. Without this the
    expansion itself, `$((n+3))`, came back as a write target of its own."""
    parts = _arithmetic_parts(word)
    if parts is None:
        return _scan_command(word, bases, git_writes, depth + 1)
    bodies, rest = parts
    found: list[_Target] = []
    for body in bodies:
        found.extend(_scan_command(body, bases, git_writes, depth + 1))
    if "$(" in rest:
        found.extend(_scan_command(rest, bases, git_writes, depth + 1))
    return found


# What a `$(...)` that is easy to delimit looks like: no quote, backslash, backtick, `$` or parenthesis
# inside. Anything else is not cut apart (the caller then reads the whole word, the safe side).
_SIMPLE_SUBSTITUTION_RE = re.compile(r"\$\(([^()'\"`\\$]*)\)")


# Inside a `$(...)` these make bash end the substitution somewhere else than at the first `)`: a `case`
# pattern ends in `)`, a comment may hold one, a here-document body runs over lines.
_SUBSTITUTION_HAZARD_RE = re.compile(r"#|<<|[\r\n]|\bcase\b")


def _simple_substitutions(word: str) -> Optional[list[str]]:
    """The text inside every `$(...)` of `word`, or None when one of them is not easy to delimit — or when
    the word is not what it seems once they are cut out: a `)` left over that closes nothing in the rest
    of the word means a substitution ended later than its first `)` (`$(case a in a) cmd;; esac)`), and a
    `#`, `<<`, line break or `case` inside one means the same may be true (`$(true #)`, a line, `cmd)`).
    The caller then reads the whole word. Balanced parentheses in the rest (`python3 -c 'f("x")' $(date)`)
    are ordinary text."""
    inner: list[str] = []
    outside: list[str] = []
    index = 0
    while True:
        at = word.find("$(", index)
        if at < 0:
            outside.append(word[index:])
            break
        outside.append(word[index:at])
        match = _SIMPLE_SUBSTITUTION_RE.match(word, at)
        if match is None or _SUBSTITUTION_HAZARD_RE.search(match.group(1)):
            return None
        inner.append(match.group(1))
        index = match.end()
    depth = 0
    for char in "".join(outside):
        depth += (char == "(") - (char == ")")
        if depth < 0:
            return None
    return inner


# Set while _bash_write_targets / _bash_inline_code_targets walk a command a second time with the
# command text of a remote `ssh` call left out (see _ssh_remote_start). _REMOTE_SINK, when a list, then
# receives the targets that text used to produce (read whole as a local command, as before).
_SSH_REMOTE_IS_REMOTE = False
_REMOTE_SINK: Optional[list] = None
_SSH_WORD_RE = re.compile(r"(?<![\w-])ssh(?:\.exe)?(?![\w-])", re.IGNORECASE)
# A command in which the word `ssh` may not run the real program: a `PATH` set somewhere in it, a function
# of that name defined in it, or bash's command hash changed. No ssh call in such a command is read as a
# remote one (_ssh_may_run_remote).
_SSH_SHADOWED_RE = re.compile(
    r"(?<![\w])PATH\+?=|(?<![\w-])function\s+ssh(?![\w-])|(?<![\w-])ssh\s*\(\s*\)|(?<![\w-])hash(?![\w-])"
    r"|(?<![\w-])(?:alias|source|enable|command_not_found_handle)(?![\w-])|(?<![\w])BASH_ENV(?![\w])"
    r"|(?<![^\s;&|(){}])\.(?=\s)",
    re.IGNORECASE,
)
# The wrappers that may stand in front of an ssh call whose text counts as remote: each runs its command
# from its own argument list, not through a shell. Only their names, and a plain duration after `timeout`,
# are accepted there - no option of theirs (`sudo -s`, `env -S` would hand the words to a shell).
_SSH_ARGV_WRAPPERS = frozenset({"sudo", "env", "command", "exec", "nohup", "nice", "timeout", "stdbuf", "setsid"})
_SSH_DURATION_RE = re.compile(r"\d+(?:\.\d+)?[smhd]?")
# The allow list of _ssh_remote_start - what an ssh call must look like, word by word, for its command
# text to count as remote. The program: `ssh` itself, or the one of a system directory. A word up to and
# including the destination is plain when the shell expands nothing in it: no `$`, backtick, brace, glob
# character or tilde. The options: flags that change nothing about where the text runs (`-4`, `-6`, `-a`,
# `-C`, `-n`, `-q`, `-T`, `-t`, `-v`, `-x`, also combined, `-tt`, `-vvv`) and three that take a value
# (`-p` a port of digits, `-l` a login name, `-i` an identity file - glued or as the next word). Any other
# option (`-o`, `-F`, `-E`, `-J`, `-W`, `-L`, `-R`, `-D`, ...) can change the destination, run a program
# here or write a file here and is left off the list on purpose. The destination: `[user@]host`, a name
# or an address.
_SSH_PROGRAM_RE = re.compile(
    r"(?:/usr/bin/|/bin/|/usr/local/bin/|/opt/homebrew/bin/|[A-Za-z]:[\\/]Windows[\\/]System32[\\/]OpenSSH[\\/])?"
    r"ssh(?:\.exe)?",
    re.IGNORECASE,
)
_SSH_PLAIN_WORD_RE = re.compile(r"[^$`{*?\[~]+")
_SSH_OPTION_RE = re.compile(r"-([46aCnqTtvx]*)(?:([pli])(.*))?")
_SSH_PORT_RE = re.compile(r"[0-9]{1,5}")
_SSH_DESTINATION_RE = re.compile(r"(?:[\w.-]+@)?(?:[A-Za-z0-9][\w.-]*|[0-9A-Fa-f.]*:[0-9A-Fa-f:.]*)")
_NUMERIC_HOST_LABEL_RE = re.compile(r"(?:0x[0-9a-f]+|[0-9]+)", re.IGNORECASE)


def _numeric_host_is_local(name: str) -> Optional[bool]:
    """For a destination written as an IPv4 address in any of the forms a resolver accepts (`2130706433`,
    `0x7f000001`, `127.1`, `0177.0.0.1`, `0`): whether it lies in `127/8` or `0/8`; True also when the
    digits do not make an address. None when the name is not numeric."""
    labels = name.split(".")
    if not all(_NUMERIC_HOST_LABEL_RE.fullmatch(label) for label in labels) or len(labels) > 4:
        return None
    values: list[int] = []
    for label in labels:
        try:
            if label.lower().startswith("0x"):
                values.append(int(label, 16))
            elif len(label) > 1 and label.startswith("0"):
                values.append(int(label, 8))
            else:
                values.append(int(label))
        except ValueError:
            return True
    last_bits = 8 * (5 - len(values))
    if any(value > 255 for value in values[:-1]) or values[-1] >= 1 << last_bits:
        return True
    address = 0
    for value in values[:-1]:
        address = (address << 8) | value
    address = (address << last_bits) | values[-1]
    return (address >> 24) in (0, 127)


def _ipv6_host_is_local(name: str) -> bool:
    """True for an IPv6 destination that is the loopback or the unspecified address (also as an IPv4-mapped
    one) and for text that is no address at all."""
    try:
        address = ipaddress.ip_address(name.split("%", 1)[0])
    except ValueError:
        return True
    mapped = getattr(address, "ipv4_mapped", None)
    return address.is_loopback or address.is_unspecified or (mapped is not None and (mapped.is_loopback or mapped.is_unspecified))


def _is_local_ssh_host(host: str) -> bool:
    """True for a destination that is this machine — or whose address cannot be told: `localhost` and its
    variants (`localhost6`, `ip6-localhost`), any `127.x` and `0.x` address in whatever spelling
    (`127.1`, `0`, a whole number), the IPv6 loopback and unspecified address, this computer's own name
    (also as the first label of a longer name), and a destination the shell still expands. An alias in an
    ssh configuration that points at this machine cannot be seen from here."""
    text = host
    if text.lower().startswith("ssh://"):
        text = text[6:].split("/", 1)[0]
    text = text.rsplit("@", 1)[-1]
    if text.startswith("["):
        text = text[1:].split("]", 1)[0]
    elif text.count(":") == 1:
        text = text.split(":", 1)[0]
    name = text.lower().rstrip(".")
    if not name or _DYNAMIC_TARGET_RE.search(name) or "(" in name or ")" in name:
        return True
    if ":" in name:
        return _ipv6_host_is_local(name)
    numeric = _numeric_host_is_local(name)
    if numeric is not None:
        return numeric
    names = _local_host_names()
    return (
        name in names or name.split(".")[0] in names or name.startswith(("localhost", "ip6-"))
        or name.endswith(".localhost")
    )


def _ssh_may_run_remote(command: str) -> bool:
    """True when `command` names ssh and nothing in it can make that word run something else
    (_SSH_SHADOWED_RE): only then is the command text of an ssh call left out of the local reading."""
    return _SSH_WORD_RE.search(command) is not None and _SSH_SHADOWED_RE.search(command) is None


def _ssh_remote_start(words: list[str]) -> Optional[int]:
    """The index in `words` of the first word of the command an `ssh [options] <host> <command...>` call
    hands to the other machine - or None when the call is not exactly of the known, harmless form (an
    allow list: anything new or odd is read as before). None, then, for: a program word that is not `ssh`
    or the ssh of a system directory (_SSH_PROGRAM_RE); a word in front of it that assigns a variable
    (`PATH=`) or that is neither a reserved word (`if`, `{`, ...) nor a wrapper of _SSH_ARGV_WRAPPERS
    (`parallel`, `xargs`, an option of a wrapper: the words may reach a shell); a word from the first up
    to the destination that the shell still expands
    (_SSH_PLAIN_WORD_RE; the reserved words `if`, `{`, ... in front are plain); an option not in
    _SSH_OPTION_RE, or a port that is not digits; a destination that is not `[user@]host`
    (_SSH_DESTINATION_RE) or is this machine (_is_local_ssh_host); no command; a first command word that
    is empty or begins with `-` or with something the shell expands - ssh reads options after the
    destination too (a `--` in front of it ends them, which changes nothing here), and an expansion
    there can become one. Everything from the index on runs on the other machine."""
    at = _command_prefix_end(words)
    if at >= len(words) or _SSH_PROGRAM_RE.fullmatch(str(words[at])) is None:
        return None
    index = at + 1
    while index < len(words):
        arg = str(words[index])
        if arg == "--":
            index += 1
            break
        if not arg.startswith("-"):
            break
        option = _SSH_OPTION_RE.fullmatch(arg)
        if option is None or len(arg) < 2:
            return None
        letter, value = option.group(2), option.group(3)
        if letter is not None and not value:
            index += 1
            value = str(words[index]) if index < len(words) else ""
        if letter == "p" and _SSH_PORT_RE.fullmatch(value) is None:
            return None
        index += 1
    if index + 1 >= len(words):
        return None
    for position, word in enumerate(words[:index + 1]):
        plain = str(word)
        if position < at:
            after_timeout = position > 0 and str(words[position - 1]) == "timeout"
            if plain in _RESERVED_PREFIXES or plain in _SSH_ARGV_WRAPPERS:
                continue
            if after_timeout and _SSH_DURATION_RE.fullmatch(plain):
                continue
            return None
        if _SSH_PLAIN_WORD_RE.fullmatch(plain) is None or _ASSIGNMENT_RE.match(plain):
            return None
    host = str(words[index])
    if _SSH_DESTINATION_RE.fullmatch(host) is None or _is_local_ssh_host(host):
        return None
    first = str(words[index + 1])
    if not first or first[0] == "-" or _SSH_PLAIN_WORD_RE.fullmatch(first[0]) is None:
        return None
    return index + 1


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
    # Inline-code reading only (_INLINE_SINK): what the segment's standard input is, the literal output of
    # the previous stage of its pipeline, the outputs of the statements of each open `{ }` / `( )` group
    # (None for one that is not literal), and the output of the group that closed just before.
    stdin_redirected = False
    stdin_text: Optional[str] = None
    stdin_span: Optional[tuple[int, int]] = None
    pipe_input: Optional[str] = None
    group_outputs: list[list[Optional[str]]] = []
    closed_group: Optional[str] = None
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
                if _INLINE_SINK is not None:
                    redirect_input = _stdin_redirect(text, word)
                    if redirect_input is not None:
                        stdin_redirected = True
                        stdin_text = redirect_input if isinstance(redirect_input, str) else None
                        # Where the body stands in the top-level text, for a quoted heredoc only: bash
                        # expands an unquoted body before the program sees it, so that text must stay
                        # in the shell reading, where its substitutions count.
                        stdin_span = (
                            getattr(word, "body_span", None)
                            if text == "<<" and not getattr(word, "expands", True) else None
                        )
            index += 2 if has_word else 1
            continue

        separator = None if at_end else text
        produced: Optional[str] = None
        if words or redirect_targets or other_redirect_words:
            found.extend(_pairs(redirect_targets, bases))
            remote_start = _ssh_remote_start(words) if _SSH_REMOTE_IS_REMOTE else None
            for position, word in enumerate(words + redirect_targets):
                if "$(" not in word:
                    continue
                if remote_start is not None and remote_start <= position < len(words):
                    # The command text of an ssh call runs on the other machine: only a `$(...)` the
                    # local shell expands before the call (inside double quotes or unquoted) runs here,
                    # so those are read, not the rest of the text as if it were a local command.
                    inner = _simple_substitutions(word)
                    if inner is not None:
                        if _REMOTE_SINK is not None:
                            _REMOTE_SINK.extend(_scan_command(word, bases, git_writes, depth + 1))
                        for text in inner:
                            found.extend(_scan_command(text, bases, git_writes, depth + 1))
                        continue
                    if _REMOTE_SINK is not None and _arithmetic_parts(word) is not None:
                        # Not easy to cut apart, but _rescan_word reads only the body of an arithmetic
                        # expansion, never the text around it: that text is the remote one. Any other
                        # word is read whole below, and nothing of it is taken out of the legacy half.
                        _REMOTE_SINK.extend(_scan_command(word, bases, git_writes, depth + 1))
                found.extend(_rescan_word(word, bases, git_writes, depth))
            # Backtick spans the tokenizer found in these words (quote context already applied).
            for word in words + redirect_targets + other_redirect_words:
                for span in getattr(word, "subs", ()):
                    found.extend(_scan_command(span, bases, git_writes, depth + 1))
            targets, cd_change = _simple_command_targets(words, bases, git_writes, depth)
            found.extend(targets)
            if _INLINE_SINK is not None:
                _collect_inline_code(words, bases, stdin_redirected, stdin_text, pipe_input, stdin_span)
                produced = _literal_output(words, stdin_text)
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
        if _INLINE_SINK is not None:
            produced, closed_group = _track_group_output(group_outputs, words, separator, produced, closed_group)
        # A pipe hands the stage's literal output on; a `(` right behind a pipe (`cat <<EOF | (python -)`)
        # passes what it got to the first command inside.
        if separator in _PIPE_OPS:
            pipe_input = produced
        elif not (separator == "(" and not words):
            pipe_input = None
        words = []
        redirect_targets = []
        other_redirect_words = []
        stdin_redirected = False
        stdin_text = None
        stdin_span = None
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


def _scan_heredocs_for_inline_code(command: str, bases: _Bases, git_writes: frozenset, depth: int) -> None:
    """Inline-code reading only (_INLINE_SINK set), for a command that may use ANSI-C quoting `$'...'`:
    _scan_command then tokenizes the whole command without reading heredocs, so a program fed as a
    heredoc (`IFS=$'\\n'; python - <<'EOF' ...`) would never be seen. This walks the line-wise reading
    once more - the one that knows heredocs - and keeps only what it adds to the sink; its targets are
    dropped, and a `$'` this lexer misreads costs this pass its tokens from there on (what it read
    before still counts), never the result of any other check."""
    try:
        tokens = _line_mode_tokens(command)
    except ValueError as error:
        tokens = getattr(error, "partial", [])
    if tokens:
        _scan_tokens(tokens, bases, git_writes, depth)


def _scan_command(command: str, bases: _Bases, git_writes: frozenset, depth: int) -> list[_Target]:
    """All write targets of `command` (steps 1-4 of the section comment). Recursion depth is capped
    for nested `sh -c`/`eval`/`$(...)`; beyond it only the raw-text search runs. When neither
    tokenizing manages the whole command, the tokens each read before it failed are scanned too,
    next to the raw-text search."""
    quote_model = _quote_model_applies(command)
    command = _join_line_continuations(command)
    # Offsets are recorded only for the one text _bash_inline_code set as the top level (_SPAN_TEXT):
    # a nested text (`sh -c`, `eval`, a `$(...)`, a heredoc body a shell runs) gets none.
    with_spans = _SPAN_TEXT is not None and command == _SPAN_TEXT
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
            tokens = _line_mode_tokens(command, with_spans)
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
    if ansi_c_quoting and _INLINE_SINK is not None:
        _scan_heredocs_for_inline_code(command, bases, git_writes, depth)
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


def _without_remote_targets(
    command: str, base_cwd: str, git_writes: frozenset, current: list[_Target], legacy: list[_Target]
) -> tuple[list[_Target], list[_Target]]:
    """Both halves of _bash_write_targets without the targets that only the command text of a remote
    `ssh` call produced (see _ssh_remote_start). The lexer is walked a second time with that text left
    out, and the targets that text used to produce are collected (_REMOTE_SINK). The legacy half cannot
    be told to skip it, so its pairs of such a text and directory are dropped — unless the second walk
    found the same target elsewhere in the command (a local one), which then stays. `current` comes back
    as the second walk's result."""
    global _SSH_REMOTE_IS_REMOTE, _REMOTE_SINK
    remote: list[_Target] = []
    _SSH_REMOTE_IS_REMOTE, _REMOTE_SINK = True, remote
    try:
        local = _bash_write_targets_new(command, base_cwd, git_writes)
    finally:
        _SSH_REMOTE_IS_REMOTE, _REMOTE_SINK = False, None
    if not remote:
        return current, legacy
    local_places = {(str(pair[0]), pair[1]) for pair in local}
    remote_only = {(str(pair[0]), pair[1]) for pair in remote} - local_places
    kept = [pair for pair in legacy if (str(pair[0]), pair[1]) not in remote_only]
    return local, kept


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
    if _ssh_may_run_remote(command):
        try:
            current, legacy = _without_remote_targets(command, base_cwd, git_writes, current, legacy)
        except Exception:  # noqa: BLE001 — both halves stay as they are, the over-blocking side
            pass
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


def _bash_inline_code_targets(command: str, base_cwd: str) -> list[_InlineTarget]:
    """The path literals that inline interpreter code in a Bash command names next to a write call -
    (path, the directory it resolves against or None when unknown, language) - for the worker write
    scope only (check 1c); no other check calls this, and _bash_write_targets is unchanged. The command
    is walked once more with _INLINE_SINK set, so the interpreter calls are found in the same places
    and under the same directory tracking (`cd`, `&&` chains, `sh -c`, heredoc bodies fed to a shell)
    as every write target. A literal path is not a shell word: the caller must not map `/tmp` or
    expand braces or `~` in it. Best effort: a command that does not mention an interpreter, or whose
    scan fails, yields what was found so far (see inline_code.py for the reading and its limits)."""
    global _INLINE_SINK, _SSH_REMOTE_IS_REMOTE
    if not _inline_code.mentions_interpreter(command):
        return []
    found: list[_InlineTarget] = []
    previous = _INLINE_SINK
    previous_remote = _SSH_REMOTE_IS_REMOTE
    _INLINE_SINK = found
    _SSH_REMOTE_IS_REMOTE = _ssh_may_run_remote(command)
    try:
        _scan_command(command, frozenset({base_cwd}), frozenset(), depth=0)
    except (ValueError, RecursionError) as error:
        # What the tokenizers and the nested scans are known to raise on a command they cannot read;
        # the inline part ends here, with what was found so far. Another kind of error is a bug and
        # propagates (the dispatcher then decides, as for any check that fails).
        _inline_code.report_skipped("command scan", error)
    finally:
        _INLINE_SINK = previous
        _SSH_REMOTE_IS_REMOTE = previous_remote
    return list(dict.fromkeys(found))


# (interpreter language, program text, the directory the call runs in - None = unknown, where the text
# came from: inline_code.SOURCE_CODE for `-c`/`-e` code, SOURCE_STDIN for a heredoc body, here-string or
# literal pipe, the (start, end) span of the program in the top-level text or None - see _bash_inline_code)
_InlineCode = tuple[str, str, Optional[str], str, Optional[tuple[int, int]]]


def _bash_inline_code(command: str, base_cwd: Optional[str]) -> tuple[list[_InlineCode], str]:
    """Every program text that a Bash command hands to `python`/`node` as inline code - (language, code,
    the directory the call runs in or None when unknown, the source of the text, the span), once per
    directory the command may run in - and the text the spans index into: `command` with its line
    continuations joined, as the scan reads it. For a check that reads such a program on its own (the
    git-metadata guard reads Python this way). Found by the same walk as _bash_inline_code_targets,
    through a second side channel of _collect_inline_code (_INLINE_CODE_SINK), so the call, its code and
    its directory are the ones that reading sees: `-c` code, a heredoc body, a here-string, a literal
    piped in. The span says where exactly the program stands, so a caller can take it out of the text
    and nothing else: the one word behind `-c`/`-e` with its quotes, or the body lines of a quoted
    heredoc (start of the first body line to start of the end-word line); only for a program on the
    top level of the command, found by the line-wise tokenizer - None for one inside `sh -c`, `eval`,
    a `$(...)`, a wsl line or a heredoc a shell runs, for a here-string or a pipe, for an unquoted
    heredoc or a `-c` word bash still expands, and when the scan fell back to the whole-command
    tokenizer. What _bash_write_targets returns is not changed by it. Best effort, like
    _bash_inline_code_targets: a command without an interpreter, or one whose scan fails, yields what
    was found so far."""
    global _INLINE_SINK, _INLINE_CODE_SINK, _SSH_REMOTE_IS_REMOTE, _SPAN_TEXT
    text = _join_line_continuations(command)
    if not _inline_code.mentions_interpreter(command):
        return [], text
    found: list[_InlineCode] = []
    previous = (_INLINE_SINK, _INLINE_CODE_SINK, _SSH_REMOTE_IS_REMOTE, _SPAN_TEXT)
    # _INLINE_SINK set too: the walk tracks heredoc bodies, here-strings and pipes only then; its own
    # findings are dropped.
    _INLINE_SINK, _INLINE_CODE_SINK, _SPAN_TEXT = [], found, text
    _SSH_REMOTE_IS_REMOTE = _ssh_may_run_remote(command)
    try:
        _scan_command(text, frozenset({base_cwd}), frozenset(), depth=0)
    except (ValueError, RecursionError) as error:
        _inline_code.report_skipped("command scan", error)
    finally:
        _INLINE_SINK, _INLINE_CODE_SINK, _SSH_REMOTE_IS_REMOTE, _SPAN_TEXT = previous
    return list(dict.fromkeys(found)), text
