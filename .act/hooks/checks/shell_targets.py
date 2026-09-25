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
#          tokenizes instead — shlex in POSIX mode with the operator characters as their own
#          tokens — so quoting and escaping are decided by one tokenizer, and operators are read
#          from the token stream, never from raw text. Steps (_scan_command):
#   1. backslash-newline continuations are joined (_LINE_CONTINUATION_RE);
#   2. line mode: every line is tokenized on its own; a line whose token stream carries a real
#      `<<`/`<<-` operator plus delimiter has the heredoc body skipped up to its terminator line —
#      several heredocs on one line in turn, and nothing at all if a terminator line is missing
#      (_line_mode_tokens); the `$(...)`/backtick parts of an unquoted-delimiter body, which bash
#      does run, are kept as commands of their own;
#   3. conservative fallback when a line does not tokenize on its own (an unclosed quote, typically
#      a string spanning lines) or the command uses ANSI-C quoting `$'...'`, which shlex does not
#      know: the whole command is tokenized in one go (newline as an operator, a multi-line string
#      becomes one token, no heredoc skipping); if that fails too, or for `$'...'` in any case,
#      every word after a `>`-style operator in the raw text also counts as a target
#      (_raw_redirect_targets) — over-blocking is the accepted price there;
#   4. the token stream is walked command by command (_scan_tokens): redirections, the write
#      commands of _simple_command_targets, `cd` for the base directory, and the contents of
#      `sh -c "..."`, `eval`, `$(...)` and backticks scanned recursively.
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
#   - not recognized as writers at all (B112.3): `patch`, a `tar`/`unzip` extraction into the
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
#   - backticks are found by a regex over the already dequoted words (_scan_tokens,
#     _BACKTICK_SPAN_RE), with no quote context left by then (B112.1, open: a pre-tokenizing mask
#     of every span was tried on 2026-09-25 and taken out again the same day after failing review
#     twice — it lost `command_words.py`'s recursion, then mistook an apostrophe inside double
#     quotes for a single quote, opening more bypasses than it closed). Three consequences: a span
#     whose own text opens a quote leaks that quote into the rest of the command
#     (`` echo `echo '` > other/f `echo '` `` — bash runs the `>`, this scanner reads it as quoted
#     text: a known bypass); a backtick pair inside a single-quoted string (a commit message
#     `git commit -m 'note `rm x`'`) is still recursed into as if bash ran it (a false block when
#     that text names a protected path or a blocked command); and an unquoted span containing
#     whitespace is split into several words, so a redirection target or operand that starts one is
#     seen only as its first fragment (`echo x > \`echo .act/x\`` yields the target "`echo" — dynamic,
#     so check 1c denies it, but a caller's text-only fallback such as check 1's finds no `.act/`
#     in it; the span's own content is still scanned for writes of its own).

from __future__ import annotations

import bisect
import io
import re
import shlex
import sys
from pathlib import Path
from typing import Optional

__all__ = [
    "_SHELL_OPERATOR_CHARS", "_SHELL_OPERATORS", "_LIST_END_OPS", "_PIPE_OPS", "_SEPARATOR_OPS",
    "_WRITE_REDIRECT_OPS", "_FD_DUP_WORD_RE", "_LINE_CONTINUATION_RE", "_MIDWORD_HASH_RE",
    "_HASH_PLACEHOLDER", "_RAW_REDIRECT_RE", "_BACKTICK_SPAN_RE", "_HEREDOC_OPEN_RE",
    "_MAX_SCAN_DEPTH", "_GITBASH_DRIVE_RE", "_IGNORABLE_TARGETS", "_DYNAMIC_TARGET_RE",
    "_SIMPLE_DIR_RE", "_ASSIGNMENT_RE", "_RESERVED_PREFIXES", "_WRAPPER_COMMANDS",
    "_WRAPPER_ARG_RE", "_WRAPPER_VALUE_FLAGS", "_SHELL_NAMES", "_ALL_OPERAND_WRITERS",
    "_LAST_OPERAND_WRITERS", "_VALUE_FLAGS", "_SED_INPLACE_FLAG_RE", "_GIT_GLOBAL_VALUE_FLAGS",
    "_GIT_WRITES_TEMPLATE_GUARD", "_GIT_WRITES_WORKER_SCOPE", "_Token", "_Target", "_Bases",
    "_NO_HEREDOC_MARKERS", "_to_native_path", "_is_ignorable_write_target", "_is_dynamic_target",
    "_is_absolute_target", "_NewlineKeepingStream", "_ShellLexer", "_split_operator_run",
    "_shell_tokens", "_heredoc_delimiters", "_heredoc_terminator", "_body_substitutions",
    "_line_mode_tokens", "_raw_redirect_targets", "_command_name", "_operands", "_cd_bases",
    "_pairs", "_git_targets", "_download_targets", "_simple_command_targets", "_scan_tokens",
    "_scan_command", "_bash_write_targets",
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
# shlex starts a comment at *any* unquoted `#`, bash only at the start of a word — `echo x#y > f`
# would otherwise lose its redirection. A `#` glued to a preceding word character is swapped for a
# placeholder before tokenizing and restored afterwards.
_MIDWORD_HASH_RE = re.compile(r"(?<=[^\s();<>|&])#")
_HASH_PLACEHOLDER = "\ue000"
_RAW_REDIRECT_RE = re.compile(r"(?:&>>|&>|>>|>\||>&|<>|>)\s*([^\s;&|()<>]+)")
_BACKTICK_SPAN_RE = re.compile(r"`([^`]*)`")
# The word right after a heredoc operator in the raw line (not `<<<`), to see whether it was quoted.
_HEREDOC_OPEN_RE = re.compile(r"(?<!<)<<(?!<)-?[ \t]*(\S*)")
_MAX_SCAN_DEPTH = 4

# A Git-Bash-style absolute path ("/c/work/...", the MSYS form a worker's own Bash commands often
# use on Windows) rewritten to the native drive form ("C:/work/...") so Path() and glob matching
# treat it the same as a Windows-native absolute path. Only ever rewritten on win32 — elsewhere a
# leading "/x/..." is an ordinary absolute path and must be left alone.
_GITBASH_DRIVE_RE = re.compile(r"^[\\/]([A-Za-z])[\\/](.*)$")

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
    {"sudo", "env", "command", "builtin", "exec", "nohup", "nice", "timeout", "xargs", "stdbuf"}
)
# A wrapper's own option or number/duration (`nice -n 5`, `timeout 10s`), skipped before its command.
_WRAPPER_ARG_RE = re.compile(r"^(?:-.*|\d+(?:\.\d+)?[smhd]?)$")
# A wrapper's own option that takes a separate following word as its value (`env -u VAR rm`,
# `timeout -s KILL 5 rm`, `sudo -u name rm`) — that value word must be skipped too (B112.2), not
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
    # GNU xargs's lowercase `-i`/`-l` take their argument only glued on (`-ifoo`, `-l5`), never as a
    # separate following word — unlike `-I`/`-L`, which do (`-I {}`, `-L 5`); listing `-i`/`-l` here
    # too used to make the loop below eat the next *real* argument as if it were their value
    # (`xargs -i rm .act/rules/a.md` hid `rm` as `-i`'s value, target invisible; T76 review,
    # 2026-09-25) — the general "starts with -" skip already handles the glued form correctly on its
    # own, so they are deliberately left out of this set.
    "xargs": frozenset({"-a", "--arg-file", "-d", "--delimiter", "-E", "-I",
                         "-L", "--max-lines", "-n", "--max-args", "-P", "--max-procs",
                         "-s", "--max-chars"}),
}
_SHELL_NAMES = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
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


def _to_native_path(raw: str) -> str:
    """Rewrite a Git-Bash-style absolute path to its native Windows drive form; left unchanged
    everywhere else. See _GITBASH_DRIVE_RE."""
    match = _GITBASH_DRIVE_RE.match(raw)
    if match and sys.platform == "win32":
        drive, rest = match.groups()
        return f"{drive.upper()}:/{rest}"
    return raw


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


class _NewlineKeepingStream(io.StringIO):
    """shlex skips a `#` comment with readline(), which also swallows the newline. In whole-command
    mode that newline separates two commands, so it is left in the stream instead."""

    def readline(self, size: Optional[int] = -1, /) -> str:
        line = super().readline(size)
        if line.endswith("\n"):
            self.seek(self.tell() - 1)
            return line[:-1]
        return line


class _ShellLexer(shlex.shlex):
    """shlex in POSIX mode that also reports whether the token just read contained any quoting or
    escaping (`saw_quote`) — the one fact POSIX shlex drops along with the quotes. Without it a
    quoted `'>'` or `";"` would look exactly like the operator. Tracked through the `state`
    attribute, which shlex sets to the quote or escape character on entering one."""

    def __init__(self, text: str, newline_is_operator: bool) -> None:
        self.saw_quote = False
        operators = _SHELL_OPERATOR_CHARS + ("\n" if newline_is_operator else "")
        super().__init__(_NewlineKeepingStream(text), posix=True, punctuation_chars=operators)
        self.whitespace_split = True
        if newline_is_operator:
            self.whitespace = " \t\r"

    @property
    def state(self) -> Optional[str]:
        return self._state

    @state.setter
    def state(self, value: Optional[str]) -> None:
        if value and value in getattr(self, "quotes", "") + getattr(self, "escape", ""):
            self.saw_quote = True
        self._state = value


def _split_operator_run(run: str) -> list[str]:
    ops: list[str] = []
    pos = 0
    while pos < len(run):
        op = next((candidate for candidate in _SHELL_OPERATORS if run.startswith(candidate, pos)), run[pos])
        ops.append(op)
        pos += len(op)
    return ops


def _shell_tokens(text: str, newline_is_operator: bool) -> list[_Token]:
    """Tokenize `text` into (text, is_operator) pairs. Raises ValueError (from shlex) on an
    unclosed quote or a trailing escape."""
    lexer = _ShellLexer(_MIDWORD_HASH_RE.sub(_HASH_PLACEHOLDER, text), newline_is_operator)
    operator_chars = lexer.punctuation_chars
    tokens: list[_Token] = []
    while True:
        lexer.saw_quote = False
        token = lexer.get_token()
        if token is None:
            return tokens
        if token and not lexer.saw_quote and all(char in operator_chars for char in token):
            tokens.extend((op, True) for op in _split_operator_run(token))
        else:
            tokens.append((token.replace(_HASH_PLACEHOLDER, "#"), False))


# Constructs in which bash does not read `<<` as a heredoc (or reads it as one that ends early):
# arithmetic `$[1<<2]`, `${arr[1<<2]}`, an array index `a[1<<2]=x`, and a heredoc opened inside
# backticks, whose body ends at the closing backtick. A line containing any of them opens no
# heredoc here, so its following lines are scanned as commands — over-scanning is the safe side.
_NO_HEREDOC_MARKERS = ("$[", "${", "[", "`")


def _heredoc_delimiters(tokens: list[_Token], line: str) -> list[tuple[set[str], bool]]:
    """Every heredoc a line opens, in order, as (terminator candidates, whether its body is
    expanded). A line with `((` in it (arithmetic like `$((1<<2))`, where `<<` is a shift) or with
    one of _NO_HEREDOC_MARKERS opens none — skipping nothing is the safe side. `<<-EOF` reaches
    here as `<<` plus `-EOF`; both "EOF" and "-EOF" are accepted as the terminator, whichever comes first, since ending a body early only
    ever scans more. A body is expanded (so `$(...)` and backticks in it run) unless the delimiter
    was quoted; the tokens no longer show quoting, so that is read from the raw line, and if the two
    do not line up the body is treated as expanded."""
    if "((" in line or any(marker in line for marker in _NO_HEREDOC_MARKERS):
        return []
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
    return [
        (candidates, not aligned or not any(char in raw_words[position] for char in "'\"\\"))
        for position, candidates in enumerate(delimiters)
    ]


def _body_substitutions(body_lines: list[str]) -> list[str]:
    """The command substitutions an expanded heredoc body runs: each backtick span as a subshell
    `( ... )`, and the rest of a line from its first `$(`."""
    snippets = []
    for body_line in body_lines:
        snippets.extend(f"( {span} )" for span in _BACKTICK_SPAN_RE.findall(body_line))
        if "$(" in body_line:
            snippets.append(body_line[body_line.index("$("):])
    return snippets


def _heredoc_terminator(line_positions: dict[str, list[int]], candidates: set[str], start: int) -> Optional[int]:
    """The smallest line index >= `start` whose stripped text is one of `candidates`, read from
    `line_positions` (every line's stripped text mapped to its own sorted occurrence indices,
    built once per command by _line_mode_tokens) via a binary search per candidate rather than
    rescanning the remaining lines from `start` to the end (B112.4: that rescan made an unterminated
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
    skipped only up to a terminator line that exists (found via _heredoc_terminator, B112.4);
    without one, nothing is skipped, so the rest is scanned as commands. The command substitutions
    of an expanded body are kept (as commands of their own after the heredoc line). Raises
    ValueError if any line does not tokenize on its own."""
    lines = command.split("\n")
    line_positions: dict[str, list[int]] = {}
    for position, raw_line in enumerate(lines):
        line_positions.setdefault(raw_line.strip(), []).append(position)
    tokens: list[_Token] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        line_tokens = _shell_tokens(line, newline_is_operator=False)
        tokens.extend(line_tokens)
        tokens.append(("\n", True))
        index += 1
        for candidates, expands in _heredoc_delimiters(line_tokens, line):
            end = _heredoc_terminator(line_positions, candidates, index)
            if end is None:
                break
            if expands:
                for snippet in _body_substitutions(lines[index:end]):
                    tokens.extend(_shell_tokens(snippet, newline_is_operator=False))
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
    name = word.lstrip("`").replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


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


def _cd_bases(bases: _Bases, directory: str) -> _Bases:
    """The possible directories after `cd <directory>` from each of `bases`. A rooted path without
    a drive on Windows (`/tmp`, Git Bash's own mount points) has no knowable native location."""
    native = _to_native_path(directory)
    if Path(native).is_absolute():
        return frozenset({native})
    if native.startswith(("/", "\\")):
        return frozenset({None})
    return frozenset(str(Path(_to_native_path(base)) / native) if base is not None else None for base in bases)


def _pairs(raw_targets: list[str], bases: _Bases) -> list[_Target]:
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
                    # module already cannot resolve (T76 review, 2026-09-25).
                    bases_unknown = True
                    index += 1 if arg.startswith("--chdir=") else (2 if index + 1 < len(words) else 1)
                elif arg in wrapper_value_flags:
                    # B112.2: `env -u VAR`, `timeout -s KILL`, `sudo -u name` — the value is its own
                    # word, matching neither _WRAPPER_ARG_RE nor an assignment, so it must be
                    # skipped explicitly too or it gets read as the wrapped command's own name.
                    index += 2 if index + 1 < len(words) else 1
                elif _WRAPPER_ARG_RE.match(arg) or _ASSIGNMENT_RE.match(arg):
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
        # B112.3: only the explicit-directory case is worth the cheap detection here — `tar -x`
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
            index += 2 if has_word else 1
            continue

        separator = None if at_end else text
        if words or redirect_targets:
            found.extend(_pairs(redirect_targets, bases))
            for word in words + redirect_targets:
                if "$(" in word:
                    found.extend(_scan_command(word, bases, git_writes, depth + 1))
            # Backticks: an unquoted `...` is split into several words by the tokenizer, so the
            # spans are looked for across the command's words joined back together.
            for span in _BACKTICK_SPAN_RE.findall(" ".join(words + redirect_targets)):
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
    for nested `sh -c`/`eval`/`$(...)`; beyond it only the raw-text search runs."""
    command = _LINE_CONTINUATION_RE.sub(r"\1", command)
    if depth > _MAX_SCAN_DEPTH:
        return [(target, None) for target in _raw_redirect_targets(command)]
    found: list[_Target] = []
    tokens: Optional[list[_Token]] = None
    ansi_c_quoting = "$'" in command
    if not ansi_c_quoting:
        try:
            tokens = _line_mode_tokens(command)
        except ValueError:
            tokens = None
    if tokens is None:
        try:
            tokens = _shell_tokens(command, newline_is_operator=True)
        except ValueError:
            tokens = None
        if tokens is None or ansi_c_quoting:
            found.extend((target, None) for target in _raw_redirect_targets(command))
    if tokens is not None:
        found.extend(_scan_tokens(tokens, bases, git_writes, depth))
    return found


def _bash_write_targets(command: str, base_cwd: str, git_writes: frozenset) -> list[_Target]:
    """The paths a Bash command writes to, each paired with the directory a relative one resolves
    against (`base_cwd`, the Bash tool's own cwd, moved by any `cd` the scanner can follow) or None
    where that directory is unknown — see the module docstring for how and its known limits. A
    target reachable from several possible directories is listed once per directory. Null devices
    and standard streams are dropped. `git_writes` names the git subcommands that count as writes
    for the calling check (_GIT_WRITES_TEMPLATE_GUARD / _GIT_WRITES_WORKER_SCOPE)."""
    try:
        pairs = _scan_command(command, frozenset({base_cwd}), git_writes, depth=0)
    except Exception:
        # A bug in the scanner must never turn into a silent allow (dispatch.py's docstring,
        # "when in doubt, deny"): fall back to the coarse raw-text search with the base unknown.
        pairs = [(target, None) for target in _raw_redirect_targets(command)]
    result: list[_Target] = []
    for pair in pairs:
        if not _is_ignorable_write_target(pair[0]) and pair not in result:
            result.append(pair)
    return result
