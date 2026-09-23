#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Single entry point for every hook event this template wires into the assistant's
#          harness (currently PreToolUse and SessionStart). One script per event would scatter
#          the same "read stdin, load actlib, check config" boilerplate across files; dispatch.py
#          does that once and hands off to one handler per event. PreToolUse runs three checks, in
#          order, the first block wins: the template write-guard (check_write_guard), the
#          no-sub-sub-agents guard (check_worker_nesting_guard, R-role-worker), and the per-worker
#          write-scope guard (check_worker_write_scope, R-cost-delegate) — a worker may only write
#          where its assignment's `Write scope:` line allows.
#
# Usage:
#   python .act/hooks/dispatch.py <event>
#   ... with the hook's JSON payload piped in on stdin (may be empty or malformed; handled).
#
#   Recognized <event> values: "PreToolUse", "SessionStart". Any other value (or none) does
#   nothing and exits 0 — an unknown event must never break the caller's hook chain.
#
# Output format:
#   PreToolUse:   exit 0 (allow) or exit 2 with a one-line reason on stderr (deny) — the
#                 harness convention for "block this tool call and show the assistant why".
#   SessionStart: one or more lines on stdout — an optional block of orchestrator-only rules
#                 (main session only, never seen by a sub-agent), zero or more "[act] note: ..."
#                 lines (a changed/unrefreshable bridge, an unresolvable tier/reasoning value, a
#                 project .act/ pulled in without update.py — each best-effort and independently
#                 gated, see refresh_session()), then the fixed-format status line "[act]
#                 branch=<name> [· inbox: <n> waiting] · board updated [· rules: <n>]
#                 [· role-bridges refreshed: <n>]", and finally, as a deliberate postscript after
#                 that status line, an optional "a template update is available" note — always a
#                 *previous* SessionStart's finding, consumed from .act-local/update-check-
#                 result.json, never something looked up during this run (see
#                 _spawn_update_check_worker: the actual `git ls-remote` runs detached, in the
#                 background, so it can never delay this session — a SessionStart hook has a
#                 fixed timeout, and an unreachable template source measured at 21s against a
#                 5s subprocess timeout before this fix, see that function's docstring). Also
#                 re-derives the model/effort frontmatter of every existing .claude/agents/*.md
#                 role bridge (tiers.py), leaving the rest of each file untouched;
#                 exit 0 always — a session start must never fail the session over a mechanism
#                 error.
#
#   "_update-check-worker" <root>: internal only, never a real harness hook event — this is what
#                 _spawn_update_check_worker() launches as a detached background process (see
#                 main() below). Not documented to the harness, not something a hook config ever
#                 names.
#
# Exit-code contract for PreToolUse specifically: a mechanism error while checking a candidate
# write is NOT swallowed the way a SessionStart error is. Every other check in this template
# fails open (never blocks the session on its own bug); the write-guard is the one exception —
# "im Zweifel ablehnen" (when in doubt, deny) — because a false allow here means the template
# silently loses its own files to an edit the next update overwrites anyway.

from __future__ import annotations

import fnmatch
import io
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import actlib  # noqa: E402 (sys.path setup above must run first)
import manifest  # noqa: E402
import tiers  # noqa: E402

# Force UTF-8 on stdout/stderr: on Windows, Python otherwise picks the console's legacy code
# page (e.g. cp1252), which silently mangles the em dash in _WRITE_GUARD_MESSAGE below into a
# different byte than the UTF-8 the harness expects. reconfigure() is Python 3.7+; the
# try/except keeps this a no-op on a stream that does not support it instead of crashing.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _read_payload() -> dict:
    """Read the hook's JSON payload from stdin. Returns {} for empty/malformed input — a
    payload we cannot parse is never grounds to crash, only to fall back to defaults."""
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _check_mode(config: dict[str, str], key: str, default: str) -> str:
    """Look up one row of the Checks table in docs/ai/config.md ("block" | "warn" | "off").
    Falls back to `default` for a missing key or an unrecognized value: default deny means
    an unrecognized value is treated the same as an absent row."""
    value = config.get(key, "").strip().lower()
    return value if value in ("block", "warn", "off") else default


# ---------------------------------------------------------------------------
# Bash write targets — shared by check 1 (template write-guard) and check 1c (write scope)
# ---------------------------------------------------------------------------
#
# Both checks need the same answer for a Bash command: which paths does it write to, and against
# which directory is a relative one resolved. Two earlier versions answered that with regexes over
# the raw text and failed review both times (2026-09-23): the first read a `>` inside quotes or a
# heredoc body as a redirection, the second masked quotes and heredocs by regex and thereby hid
# real redirections (`echo \" > f \"`, `echo don\'t > f`, a quoted "<<EOF", ...). This version
# tokenizes instead — shlex in POSIX mode with the operator characters as their own tokens — so
# quoting and escaping are decided by one tokenizer, and operators are read from the token stream,
# never from raw text. Steps (_scan_command):
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
#     the base unknown rather than guessed.

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

# A Git-Bash-style absolute path ("/d/dev/...", the MSYS form a worker's own Bash commands often
# use on Windows) rewritten to the native drive form ("D:/dev/...") so Path() and glob matching
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


def _line_mode_tokens(command: str) -> list[_Token]:
    """Tokenize line by line with heredoc bodies skipped (step 2 of the section comment). A body is
    skipped only up to a terminator line that exists; without one, nothing is skipped, so the rest
    is scanned as commands. The command substitutions of an expanded body are kept (as commands of
    their own after the heredoc line). Raises ValueError if any line does not tokenize on its own."""
    lines = command.split("\n")
    tokens: list[_Token] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        line_tokens = _shell_tokens(line, newline_is_operator=False)
        tokens.extend(line_tokens)
        tokens.append(("\n", True))
        index += 1
        for candidates, expands in _heredoc_delimiters(line_tokens, line):
            end = next((k for k in range(index, len(lines)) if lines[k].strip() in candidates), None)
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
    while index < len(words):
        word = words[index]
        if _ASSIGNMENT_RE.match(word):
            index += 1
        elif word in _RESERVED_PREFIXES:
            prefixed = True
            index += 1
        elif _command_name(word) in _WRAPPER_COMMANDS:
            prefixed = True
            index += 1
            while index < len(words) and (_WRAPPER_ARG_RE.match(words[index]) or _ASSIGNMENT_RE.match(words[index])):
                index += 1
        else:
            break
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
    where that directory is unknown — see the section comment above for how and its known limits.
    A target reachable from several possible directories is listed once per directory. Null
    devices and standard streams are dropped. `git_writes` names the git subcommands that count as
    writes for the calling check (_GIT_WRITES_TEMPLATE_GUARD / _GIT_WRITES_WORKER_SCOPE)."""
    try:
        pairs = _scan_command(command, frozenset({base_cwd}), git_writes, depth=0)
    except Exception:
        # A bug in the scanner must never turn into a silent allow (module docstring, "im Zweifel
        # ablehnen"): fall back to the coarse raw-text search with the base unknown.
        pairs = [(target, None) for target in _raw_redirect_targets(command)]
    result: list[_Target] = []
    for pair in pairs:
        if not _is_ignorable_write_target(pair[0]) and pair not in result:
            result.append(pair)
    return result


# ---------------------------------------------------------------------------
# Check 1 — template write-guard (PreToolUse), checked before anything else
# ---------------------------------------------------------------------------

# ".act" as a whole path segment: ".act/" or ".act\" anywhere in the string, or ".act" at the
# very end — never as a prefix of another name. Deliberately no required prefix character
# before ".act" (a shell command has it after a space, quote, "=", redirect symbol, "(", and
# so on — enumerating all of those is more fragile than just not requiring one). The suffix
# check is what excludes ".act-lock.json" and ".act-local/", both project-level state next to
# the template tree rather than inside it, from this guard.
_PROTECTED_PATH_RE = re.compile(r"\.act(?:[\\/]|$)")

def _bash_targets_protected_path(command: str, base_cwd: str) -> bool:
    """True if a Bash command writes to a path under .act/ — judged from the write targets the
    shared scanner finds (_bash_write_targets), not from a mere mention: `cat .act/x > /tmp/y`,
    `python .act/scripts/doctor.py 2>&1 | tail` and `grep -rn x .act/ 2>/dev/null` are reads and
    pass. Of the git subcommands only `git mv`/`git rm` count here (_GIT_WRITES_TEMPLATE_GUARD):
    `git checkout`/`git restore` stay allowed, since the orchestrator uses them to switch branches,
    unstage, and fetch the template's own version of a .act/ file back. A target whose directory
    is unknown (after `pushd`, a `cd $VAR`, inside a subshell, ...) or that contains a variable is
    denied only if its own text names .act/ — everything else about it cannot be decided here."""
    for raw, base in _bash_write_targets(command, base_cwd, _GIT_WRITES_TEMPLATE_GUARD):
        if _PROTECTED_PATH_RE.search(raw):
            return True
        if base is None or _is_dynamic_target(raw):
            continue
        try:
            resolved = (Path(_to_native_path(base)) / _to_native_path(raw)).resolve()
        except (OSError, ValueError):
            return True  # cannot place it — fail closed, see the module docstring
        if _PROTECTED_PATH_RE.search(resolved.as_posix()):
            return True
    return False


# Which tool_input field holds the write target, per tool. Bash has no single target field and
# is handled separately by _bash_targets_protected_path.
_TOOL_PATH_FIELDS = {
    "Write": ("file_path",),
    "Edit": ("file_path",),
    "MultiEdit": ("file_path",),
    "NotebookEdit": ("notebook_path", "file_path"),
}

_WRITE_GUARD_MESSAGE = (
    "[act] .act/ belongs to the template and is replaced on update. Put your version in "
    "docs/ai/local/<same path> — it wins over the template (ADR-5)."
)


def _targets_protected_path(tool_name: str, tool_input: dict, base_cwd: str) -> bool:
    """True if this tool call writes somewhere under .act/, based on the write-target field(s)
    that specific tool uses. Unknown tools never match — this guard only needs to understand
    the tools named in the PreToolUse matcher in settings.hooks.json. `base_cwd` is the directory
    a relative Bash target is resolved against (the Bash tool's own cwd)."""
    if tool_name == "Bash":
        command = tool_input.get("command")
        return isinstance(command, str) and _bash_targets_protected_path(command, base_cwd)
    for field in _TOOL_PATH_FIELDS.get(tool_name, ()):
        value = tool_input.get(field)
        if isinstance(value, str) and _PROTECTED_PATH_RE.search(value):
            return True
    return False


def check_write_guard(payload: dict) -> int:
    """Check 1: deny an AI write under .act/**, pointing at docs/ai/local/<path> instead
    (ADR-5). See the module docstring for why this check's error handling — fail closed, not
    open — differs from the rest of the script."""
    config = actlib.read_config()
    mode = _check_mode(config, "template-write-guard", default="block")
    if mode == "off":
        return 0

    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
        return 0  # nothing to check a write target against

    cwd_raw = payload.get("cwd")
    base_cwd = cwd_raw if isinstance(cwd_raw, str) and cwd_raw else os.getcwd()
    if not _targets_protected_path(tool_name, tool_input, base_cwd):
        return 0

    if mode == "warn":
        print(_WRITE_GUARD_MESSAGE)
        return 0

    print(_WRITE_GUARD_MESSAGE, file=sys.stderr)
    return 2


# ---------------------------------------------------------------------------
# Check 1b — no sub-sub-agents (R-role-worker, PreToolUse)
# ---------------------------------------------------------------------------

# A role's own `tools` frontmatter never lists "Agent"/"Task" (docs/project/concepts/ai-dev-app/
# 02-directory-plan.md § "Brücken" in the template-pflege repo, .act/agents/README.md) — this is
# the mechanical backstop for that rule: a PreToolUse call to either tool whose payload carries an
# "agent_id" did not come from the orchestrator (the harness stamps every sub-agent's own tool
# calls with its agent_id; the main session's calls carry none — confirmed 2026-09-23 against a
# real Claude Code run's payload capture, D:/dev/rufeger/act-live-probe/.act-local/probe/
# payloads.jsonl: every PreToolUse fired from inside a spawned sub-agent carries "agent_id", the
# orchestrator's own PreToolUse for "Agent" does not). Denied regardless of what a role's own
# tools list says, since a hand-edited role bridge could otherwise re-add the tool.
#
# The same probe also shows the guard's live blind spot: the sub-agent it spawned (role
# quick-check, tools Read/Grep/Glob/Bash/SubagentHandback) never got the "Agent"/"Task" tool at
# all, so no PreToolUse for either ever fired to test the guard against — the *payload field* this
# guard relies on is confirmed, the guard's own denial path was not exercised live. The nesting
# guard's Bash-level escape-hatch check (`claude -p`/`--print`) is unaffected by that, since Bash
# was in the sub-agent's tool list.
#
# The same guard also catches the CLI-level escape hatch: a sub-agent that cannot call
# Agent/Task directly can still reach for `claude -p "..."` (or `--print`) via Bash to spawn an
# unsupervised second harness instance. Same test (agent_id present -> not the orchestrator),
# same verdict. Known gap, not fixable from this payload alone: a skill invoked with
# `context: fork` runs as its own harness call, indistinguishable here from an ordinary
# sub-agent Bash call — this guard cannot see the difference and does not try to.
_WORKER_TOOL_NAMES = {"Agent", "Task"}
_WORKER_NESTING_MESSAGE = (
    "[act] only the orchestrator starts workers — return a split proposal instead"
)
_CLAUDE_PRINT_MESSAGE = (
    "[act] only the orchestrator starts workers — no `claude -p`/--print from inside a sub-agent"
)

# Segment a shell command on the operators that start a new command (&&, ||, ;, |, &, newline),
# so a `claude -p` buried after an unrelated first command (e.g. `cd x && claude -p "y"`) is
# still caught, without needing a real shell parser.
_SHELL_SEP_RE = re.compile(r"&&|\|\||[;&|\n]")
# "claude" as the *command* of a segment, not merely a word appearing in it (so `echo claude -p`
# stays allowed): after leading whitespace, an optional path prefix (`/usr/local/bin/claude`,
# `./claude`) and/or a leading `npx`/its flags (`npx claude -p`, `npx -y claude -p`), "claude"
# (optionally .exe/.cmd on Windows) must be the next token, followed by whitespace or the end of
# the segment — that trailing boundary is what excludes "claude-code"/"claude.md" as a
# substring match.
_CLAUDE_COMMAND_WORD_RE = re.compile(
    r"^\s*(?:(?:npx|-{1,2}\S+)\s+)*(?:[\w./\\~-]*[/\\])?claude(?:\.exe|\.cmd)?(?=\s|$)"
)
_PRINT_FLAG_RE = re.compile(r"(?:^|\s)(?:-p|--print)(?:[\s=]|$)")


def _bash_starts_claude_print(command: str) -> bool:
    """True if some segment of `command` runs the `claude` CLI with -p/--print — the print-mode
    invocation that runs one prompt to completion and exits, usable to spawn an unsupervised
    second harness instance from inside a sub-agent. See the comment above _WORKER_TOOL_NAMES
    for the known gap (a `context: fork` skill is not detectable this way)."""
    for segment in _SHELL_SEP_RE.split(command):
        if _CLAUDE_COMMAND_WORD_RE.search(segment) and _PRINT_FLAG_RE.search(segment):
            return True
    return False


def check_worker_nesting_guard(payload: dict) -> int:
    """Check 1b: deny a sub-agent starting a further sub-agent, directly (Agent/Task) or via the
    `claude -p` CLI escape hatch (Bash). See the module docstring for why PreToolUse checks fail
    closed rather than open."""
    config = actlib.read_config()
    mode = _check_mode(config, "worker-nesting-guard", default="block")
    if mode == "off":
        return 0

    if not payload.get("agent_id"):
        return 0  # the orchestrator's own call — never stamped with an agent_id

    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    message: Optional[str] = None
    if tool_name in _WORKER_TOOL_NAMES:
        message = _WORKER_NESTING_MESSAGE
    elif tool_name == "Bash" and isinstance(tool_input, dict):
        command = tool_input.get("command")
        if isinstance(command, str) and _bash_starts_claude_print(command):
            message = _CLAUDE_PRINT_MESSAGE

    if message is None:
        return 0

    if mode == "warn":
        print(message)
        return 0

    print(message, file=sys.stderr)
    return 2


# ---------------------------------------------------------------------------
# Check 1c — per-worker write scope (R-cost-delegate, PreToolUse)
# ---------------------------------------------------------------------------
#
# R-cost-delegate (.act/rules/orchestrator/30-cost.md) has the orchestrator name a `Write scope:`
# line in every assignment — one or more comma-separated glob patterns (project-root-relative,
# "/" as the separator; a bullet prefix and backticks around a pattern are both tolerated, see
# _parse_write_scope), or the literal `none` for a read-only assignment. Missing the line at all
# means "unrestricted" (no scope beyond the template's own .act/ write-guard, check 1 above) — a
# project that never writes the line never sees this check do anything beyond bookkeeping.
#
# Binding a worker's tool call back to the scope its assignment named runs through the harness's
# own bookkeeping (2026-09-23 live-probe, see the comment above _WORKER_TOOL_NAMES for the file):
# the orchestrator's PreToolUse for "Agent"/"Task" carries "tool_use_id" and
# "tool_input.prompt"; the harness then writes <transcript_path-without-".jsonl">/subagents/
# agent-<agent_id>.meta.json for that spawned worker, whose "toolUseId" field is exactly that same
# tool_use_id, and agent-<agent_id>.jsonl, whose first line is the worker's own initial user
# message (message.content == the assignment prompt verbatim). So: record the scope parsed from
# the assignment prompt, in its own file keyed by tool_use_id (see _worker_scope_file — one file
# per id, not a shared JSON document, so N parallel Agent/Task starts never race each other into a
# lost update), when the orchestrator starts a worker; look it up again, keyed by
# agent_id -> meta.json -> toolUseId, when that worker later tries to write something. A second
# path (reading the assignment prompt straight out of the worker's own first transcript line)
# covers a missing/unreadable meta.json. If neither works, the binding is unresolved for *this*
# call — see _resolve_worker_scope and check_worker_write_scope's docstring for what happens then
# (it is fail-closed only when scoping is demonstrably in use nearby, not unconditionally).

_WORKER_SCOPES_DIRNAME = "worker-scopes"
_SCOPE_ENTRY_TTL = timedelta(hours=24)

# A tool_use_id becomes an entry's filename (see _worker_scope_file), so it is validated first —
# the harness's own ids look like "toolu_01Ab...", but nothing here may assume that without
# checking, since the string ultimately lands in a Path().
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# "Write scope: <patterns>" — one line, read top to bottom (first match wins, same as a human
# skimming the assignment). An optional leading "- "/"* " bullet is tolerated (assignments are
# often written as a bulleted list), and so is Markdown bold around the key (`**Write scope:**`,
# `**Write scope**:`, also with `__`). "none" (case-insensitive) means read-only; anything else is a
# comma-separated pattern list, each pattern optionally wrapped in backticks (`` `src/**` ``) and/or
# ending in "/" (read as "/**", i.e. a bare directory name means "everything under it"). A prompt
# with no such line at all is "unrestricted", which is deliberately a different value than an
# (impossible) empty pattern list — see _parse_write_scope.
_SCOPE_LINE_RE = re.compile(
    r"^[ \t]*(?:[-*]\s+)?(?:\*\*|__)?Write scope(?:\*\*|__)?:(?:\*\*|__)?\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _strip_backticks(text: str) -> str:
    if len(text) >= 2 and text[0] == "`" and text[-1] == "`":
        return text[1:-1].strip()
    return text


def _parse_write_scope(prompt: str) -> Optional[dict]:
    """Parse the first `Write scope: ...` line out of an assignment prompt (see _SCOPE_LINE_RE for
    the accepted line shapes: an optional bullet, patterns optionally backtick-wrapped and/or
    ending in "/"). Returns None if no such line is present at all ("unrestricted" — deliberately
    distinct from a scope that names zero patterns, which cannot happen: an empty pattern list
    falls back to None too). Otherwise {"mode": "none"} or {"mode": "patterns", "patterns": [...]}.
    """
    match = _SCOPE_LINE_RE.search(prompt)
    if not match:
        return None
    raw = match.group(1).strip()
    parts = [_strip_backticks(p.strip()) for p in raw.split(",")]
    parts = [p for p in parts if p]
    if not parts:
        return None
    if len(parts) == 1 and parts[0].lower() == "none":
        return {"mode": "none"}
    patterns = []
    for part in parts:
        pattern = part.replace("\\", "/")
        if pattern.endswith("/"):
            pattern += "**"
        patterns.append(pattern)
    return {"mode": "patterns", "patterns": patterns}


def _worker_scopes_dir(root: Path) -> Path:
    return root / ".act-local" / _WORKER_SCOPES_DIRNAME


def _worker_scope_file(root: Path, tool_use_id: str) -> Optional[Path]:
    """Path for one worker's recorded scope — one file per tool_use_id, so N parallel Agent/Task
    starts each own their own file and never race each other into a lost update the way a single
    shared JSON file did under concurrent read-modify-write (2026-09-23 review, t26_race.py: 8
    parallel starts lost 6 of 8 entries against the old single-file scheme). None if `tool_use_id`
    is not a safe filename (see _SAFE_ID_RE) — such an id is simply never recorded, not written
    somewhere unsafe."""
    if not isinstance(tool_use_id, str) or not _SAFE_ID_RE.match(tool_use_id):
        return None
    return _worker_scopes_dir(root) / f"{tool_use_id}.json"


def _read_json_object(path: Path) -> Optional[dict]:
    """Local, minimal twin of actlib._read_json — kept in this file rather than imported since
    that helper is private to actlib.py. Same contract: None for missing/unreadable/non-object."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _entry_is_fresh(entry: dict) -> bool:
    ts = entry.get("ts")
    try:
        when = datetime.fromisoformat(ts) if isinstance(ts, str) else None
    except ValueError:
        when = None
    return when is not None and when >= datetime.now(timezone.utc) - _SCOPE_ENTRY_TTL


def _prune_worker_scope_files(dir_path: Path, skip: Path) -> None:
    """Delete every scope file older than _SCOPE_ENTRY_TTL, or unreadable/malformed — run
    opportunistically on each write rather than on a schedule, so no separate cleanup process is
    needed. `skip` is the file just written in this same call, left alone unconditionally (it
    cannot be stale — it was just stamped with the current time)."""
    try:
        candidates = list(dir_path.glob("*.json"))
    except OSError:
        return
    for path in candidates:
        if path == skip:
            continue
        entry = _read_json_object(path)
        if entry is None or not _entry_is_fresh(entry):
            try:
                path.unlink()
            except OSError:
                pass


def _record_worker_scope(root: Path, tool_use_id: str, scope: dict) -> None:
    """Record one Agent/Task start's write scope in its own file (see _worker_scope_file), so a
    worker's later call can look it up via its meta.json's "toolUseId" (_scope_via_meta). Always
    called — even for "unrestricted" — so _recent_restricted_scope_registered can tell "a start was
    registered here and named no restriction" from "nothing has run against this check yet" (see
    that function and check_worker_write_scope's fail-closed fallback). Best-effort: a failed write
    here only weakens that fallback, it never blocks the orchestrator's own call.

    Written via a temp file plus os.replace in the same directory, so a concurrent reader never
    observes a partially written file — os.replace is an atomic rename on both POSIX and Windows."""
    path = _worker_scope_file(root, tool_use_id)
    if path is None:
        return  # unsafe id -- never recorded, not an error
    entry = dict(scope)
    entry["ts"] = datetime.now(timezone.utc).isoformat()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # suffix ".tmp", not ".json": _prune_worker_scope_files globs "*.json", and a temp file
        # that matched that pattern was briefly visible (between creation and the os.replace
        # below) to a *concurrent* writer's own prune pass — which could delete it before this
        # replace runs, dropping this write silently (2026-09-23 review, t26_race.py: 8 parallel
        # starts sometimes wrote as few as 4 of 8 files under the old ".json"-suffixed temp name).
        fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", suffix=".tmp", dir=str(path.parent))
    except OSError:
        return
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp_name, path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        return
    _prune_worker_scope_files(path.parent, skip=path)


def _read_worker_scope_entry(root: Path, tool_use_id: str) -> Optional[dict]:
    """The scope recorded for one tool_use_id, or None if it was never recorded, is unreadable, or
    has aged past _SCOPE_ENTRY_TTL."""
    path = _worker_scope_file(root, tool_use_id)
    if path is None:
        return None
    entry = _read_json_object(path)
    if entry is None or not _entry_is_fresh(entry):
        return None
    return entry


def _recent_restricted_scope_registered(root: Path) -> bool:
    """True if any worker-scopes file, within _SCOPE_ENTRY_TTL, holds an entry whose mode is "none"
    or "patterns" (i.e. an assignment actually named a restriction) — as opposed to only
    "unrestricted" entries or none at all. Used by check_worker_write_scope's fail-closed fallback:
    a binding failure is only treated as suspicious when scoping is demonstrably in active use
    nearby.

    A damaged file (unreadable, not JSON, no usable "mode") does not count as "restricted" — so if
    such files are all there is, an unbound worker is allowed. Deliberate: a broken bookkeeping file
    must not lock every worker out; it is pruned on the orchestrator's next Agent/Task start
    (_prune_worker_scope_files), and a bound worker is unaffected either way."""
    try:
        candidates = list(_worker_scopes_dir(root).glob("*.json"))
    except OSError:
        return False
    for path in candidates:
        entry = _read_json_object(path)
        if entry is None or entry.get("mode") not in ("none", "patterns"):
            continue
        if _entry_is_fresh(entry):
            return True
    return False


def _scope_via_meta(root: Path, transcript_path: object, agent_id: str) -> Optional[dict]:
    """Look up the scope recorded for this worker via <session>/subagents/agent-<id>.meta.json's
    "toolUseId" (see the Check 1c header comment). None if the meta.json is missing/unreadable, has
    no usable "toolUseId", or nothing was ever recorded under that id."""
    if not isinstance(transcript_path, str) or not transcript_path:
        return None
    meta_path = Path(transcript_path).with_suffix("") / "subagents" / f"agent-{agent_id}.meta.json"
    meta = _read_json_object(meta_path)
    if not meta:
        return None
    tool_use_id = meta.get("toolUseId")
    if not isinstance(tool_use_id, str) or not tool_use_id:
        return None
    return _read_worker_scope_entry(root, tool_use_id)


def _scope_via_transcript(transcript_path: object, agent_id: str) -> Optional[dict]:
    """Fallback for _scope_via_meta: read the assignment prompt straight out of the worker's own
    first transcript line (<session>/subagents/agent-<id>.jsonl, message.content of the first
    record) and parse a `Write scope:` line out of it directly — no tool_use_id round-trip needed.
    None if the file is missing/unreadable or its first line has no usable message content."""
    if not isinstance(transcript_path, str) or not transcript_path:
        return None
    agent_transcript = Path(transcript_path).with_suffix("") / "subagents" / f"agent-{agent_id}.jsonl"
    if not agent_transcript.is_file():
        return None
    try:
        with open(agent_transcript, "r", encoding="utf-8") as handle:
            first_line = handle.readline()
    except OSError:
        return None
    try:
        record = json.loads(first_line)
    except json.JSONDecodeError:
        return None
    message = record.get("message") if isinstance(record, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        return None
    return _parse_write_scope(content) or {"mode": "unrestricted"}


def _resolve_worker_scope(root: Path, payload: dict) -> Optional[dict]:
    """Bind this PreToolUse call's agent_id to the scope its assignment named: meta.json first,
    the worker's own transcript as fallback (see the Check 1c header comment). None if neither
    resolves — a genuinely unbound call, handled by the fail-closed fallback in the caller."""
    agent_id = payload.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id:
        return None
    transcript_path = payload.get("transcript_path")
    try:
        entry = _scope_via_meta(root, transcript_path, agent_id)
    except Exception:
        entry = None
    if entry is not None:
        return entry
    try:
        entry = _scope_via_transcript(transcript_path, agent_id)
    except Exception:
        entry = None
    return entry


def _normalize_candidate_path(raw: str, root: Path, base: str) -> Optional[str]:
    """Turn a write-target path (absolute Windows, forward-slash, or Git-Bash `/d/...` form, or
    one already relative — resolved against `base`, not always `root`: a Bash target is relative to
    the tool call's own `cwd`, tracked forward through any `cd` the command made, see
    _bash_write_targets) into a project-root-relative POSIX path for glob matching. None if it
    cannot be placed under `root` at all — an out-of-root target never matches any pattern (it is
    out of scope by definition, module comment step 4), except the worker's own scratchpad, which
    the caller checks separately before ever calling this."""
    if not raw:
        return None
    candidate = _to_native_path(raw)
    try:
        path = Path(candidate)
        if not path.is_absolute():
            path = Path(_to_native_path(base)) / candidate
        rel = path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    return rel.as_posix()


def _within_scratchpad(raw: str, scratchpad_dir: str) -> bool:
    """True if `raw` resolves under the worker's own scratchpad_dir (from the hook payload) —
    exempt from write-scope enforcement per the module comment step 4 (a worker's temp files are
    never "the project" in the sense a Write scope line means)."""
    try:
        target = Path(_to_native_path(raw))
        if not target.is_absolute():
            return False
        target = target.resolve()
        target.relative_to(Path(scratchpad_dir).resolve())
        return True
    except (OSError, ValueError):
        return False


def _matches_scope(rel_posix: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel_posix, pattern) for pattern in patterns)


def _write_scope_message(target: str, scope: dict) -> str:
    if scope.get("mode") == "none":
        allowed = "none (read-only assignment)"
    else:
        allowed = ", ".join(scope.get("patterns") or []) or "none"
    return f"[act] outside this assignment's write scope: {target} (allowed: {allowed})"


def check_worker_write_scope(payload: dict) -> int:
    """Check 1c: a worker may only write where its assignment's `Write scope:` line allows
    (R-cost-delegate). See the Check 1c header comment for the binding mechanism. Unlike check 1
    (the template write-guard), this one is *not* unconditionally fail-closed: when a call's
    agent_id cannot be bound to a recorded scope at all, it is denied only if a restricted scope
    was demonstrably registered recently (_recent_restricted_scope_registered) — i.e. only when
    scoping is in active use nearby. With no restricted scope registered anywhere recently (the
    common case for a project that never writes a `Write scope:` line), an unresolved binding is
    allowed, same as an explicit "unrestricted" scope would be."""
    config = actlib.read_config()
    mode = _check_mode(config, "worker-write-scope", default="block")
    if mode == "off":
        return 0

    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
        return 0

    try:
        root = actlib.repo_root()
    except RuntimeError:
        return 0  # not inside a template-managed project — nothing to enforce against

    if not payload.get("agent_id"):
        # The orchestrator's own call: never write-scope-restricted itself (check 1 already
        # guards .act/). If this is an Agent/Task start, record the scope it names for the
        # worker it is about to spawn.
        if tool_name in _WORKER_TOOL_NAMES:
            tool_use_id = payload.get("tool_use_id")
            prompt = tool_input.get("prompt")
            if isinstance(tool_use_id, str) and tool_use_id and isinstance(prompt, str):
                scope = _parse_write_scope(prompt) or {"mode": "unrestricted"}
                _record_worker_scope(root, tool_use_id, scope)
        return 0

    write_targets: list[tuple[str, Optional[str]]] = []
    if tool_name in _TOOL_PATH_FIELDS:
        for field in _TOOL_PATH_FIELDS[tool_name]:
            value = tool_input.get(field)
            if isinstance(value, str) and value:
                write_targets.append((value, str(root)))
    elif tool_name == "Bash":
        command = tool_input.get("command")
        if isinstance(command, str):
            cwd_raw = payload.get("cwd")
            base_cwd = cwd_raw if isinstance(cwd_raw, str) and cwd_raw else str(root)
            write_targets = _bash_write_targets(command, base_cwd, _GIT_WRITES_WORKER_SCOPE)
    if not write_targets:
        return 0  # not a tool/shape this check understands as a write

    scope = _resolve_worker_scope(root, payload)
    if scope is None:
        if not _recent_restricted_scope_registered(root):
            return 0  # scoping is not demonstrably in use nearby — nothing to fail closed against
        message = (
            "[act] could not bind this worker to its assignment's write scope, and a restricted "
            "scope was registered recently — denying as a precaution (R-cost-delegate)"
        )
        if mode == "warn":
            print(message)
            return 0
        print(message, file=sys.stderr)
        return 2

    if scope.get("mode") == "unrestricted":
        return 0

    scratchpad_dir = payload.get("scratchpad_dir")
    for raw_target, base in write_targets:
        dynamic = _is_dynamic_target(raw_target)
        if (
            not dynamic
            and isinstance(scratchpad_dir, str)
            and scratchpad_dir
            and _within_scratchpad(raw_target, scratchpad_dir)
        ):
            continue
        if scope.get("mode") == "none":
            offending = raw_target
        elif dynamic or (base is None and not _is_absolute_target(raw_target)):
            # The shell still expands this target ($VAR, $(...), ~, {a,b}), or it is relative and
            # the directory it resolves against is unknown (pushd, a subshell `cd`, `cd $X`, ...,
            # see _scan_tokens) — deny rather than check it against a guessed path.
            offending = raw_target
        else:
            rel = _normalize_candidate_path(raw_target, root, base if base is not None else str(root))
            if rel is not None and _matches_scope(rel, scope.get("patterns") or []):
                continue
            offending = raw_target
        message = _write_scope_message(offending, scope)
        if mode == "warn":
            print(message)
            return 0
        print(message, file=sys.stderr)
        return 2
    return 0


# ---------------------------------------------------------------------------
# Check 2 — session start: inbox count, bridge re-derivation, board refresh,
#           orchestrator-only rules delivered as hook context
# ---------------------------------------------------------------------------

def _current_branch(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=root, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    name = result.stdout.strip()
    return name if result.returncode == 0 and name else "unknown"


_STATUS_RE = re.compile(r"^status:\s*(\S+)", re.IGNORECASE)


def _count_inbox_waiting(root: Path) -> int:
    """
    Count inbox entries that are "answered, not yet processed": a file in docs/ai/inbox/ (one
    per entry, "YYYY-MM-DD-<slug>.md") whose header says `status: answered`.

    The header carries three fields: `for:` (who it is addressed to), `status:` and the date in
    the file name. `status` runs `open` -> `answered` -> `done`: the human (or the assistant, when
    the answer came up in chat) sets `answered`, and whoever works the entry into its place sets
    `done`. Only `answered` is counted — `open` is still waiting on a person, `done` is finished.
    """
    inbox_dir = root / "docs" / "ai" / "inbox"
    if not inbox_dir.is_dir():
        return 0
    count = 0
    for entry in inbox_dir.glob("*.md"):
        if entry.name.lower() == "readme.md":
            continue
        try:
            lines = entry.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines[:20]:  # header fields live at the top of the file
            match = _STATUS_RE.match(line.strip())
            if match:
                if match.group(1).strip().lower() == "answered":
                    count += 1
                break
    return count


def _refresh_board(root: Path) -> None:
    """Run .act/scripts/board.py if it exists yet (a parallel task builds it); do nothing,
    silently, otherwise — per the build order for this script (T15 depends only on T14)."""
    board_script = root / ".act" / "scripts" / "board.py"
    if not board_script.is_file():
        return
    try:
        subprocess.run([sys.executable, str(board_script)], cwd=root, timeout=15, capture_output=True)
    except (OSError, subprocess.TimeoutExpired):
        pass  # a broken board refresh must not block the session


# Destination (repo-root-relative) -> source filename under .act/bridges/, for exactly the
# bridges .act/bridges/gitattributes marks `merge=ours`. Only these are re-derived here; keep
# this map and that file's merge=ours lines in sync if a later stage adds more bridges.
_BRIDGE_MAP = {
    "CLAUDE.md": "CLAUDE.md",
    "AGENTS.md": "AGENTS.md",
    "docs/ai/rules.md": "rules.md",
}


def _refresh_bridges(root: Path, write: bool) -> tuple[list[str], list[str]]:
    """
    Re-derive every generated bridge that is still exactly as it was last generated (current
    hash matches .act-local/cache.json) from its .act/bridges/ source — this stands in for a
    registered `merge=ours` driver (see .act/bridges/gitattributes), which needs a per-machine
    `git config` no checkout is guaranteed to have. A bridge whose hash no longer matches was
    edited locally and is left untouched either way.

    With `write=False` (check-mode-`warn`), nothing is written — the "refreshed" list reports
    what would have changed instead.

    Returns (changed, refreshed): `changed` are destinations left alone because they were
    edited locally; `refreshed` are destinations re-derived from the template (or that would
    have been, under write=False).
    """
    cache = actlib.read_cache()
    generated = cache["generated"]
    changed: list[str] = []
    refreshed: list[str] = []

    for dest_rel, source_name in _BRIDGE_MAP.items():
        dest_path = root / dest_rel
        source_path = root / ".act" / "bridges" / source_name
        if not dest_path.is_file() or not source_path.is_file():
            continue  # not generated yet, or template source missing — nothing to do here

        recorded_hash = generated.get(dest_rel)
        if recorded_hash is None:
            continue  # never tracked as generated — not ours to touch

        current_hash = actlib.sha256_file(dest_path)
        if current_hash != recorded_hash:
            changed.append(dest_rel)
            continue

        refreshed.append(dest_rel)
        if write:
            content = source_path.read_text(encoding="utf-8")
            dest_path.write_text(content, encoding="utf-8")
            generated[dest_rel] = actlib.sha256_file(dest_path)

    if write and refreshed:
        actlib.write_cache({"generated": generated})
    return changed, refreshed


# ---------------------------------------------------------------------------
# Check 2b — template awareness at session start: a project .act/ that was brought to a clean
# template state by something other than update.py (e.g. a plain `git pull` of the shared history
# some projects still keep from before Q73a), and, at most once a day, whether the template's own
# remote has moved past what .act-lock.json last recorded. Both read-only, both best-effort — see
# refresh_session()'s try/except around each call; neither ever raises out of this function.
# ---------------------------------------------------------------------------

def _manifest_fingerprint(act_dir: Path) -> str:
    """CRLF-folded fingerprint of act_dir/MANIFEST.json, matching what .act-lock.json's
    template.manifest_sha256 is meant to record (Q73a) -- unlike a raw `actlib.sha256_file()` of
    the file, this is unaffected by the checkout's line endings (core.autocrlf), so a MANIFEST.json
    checked out with CRLF on Windows still fingerprints the same as the LF copy that produced the
    recorded hash. Prefers manifest.py's own `manifest_fingerprint()` (added alongside this fix);
    falls back to manifest.py's existing `content_hash()` — which already does the same CRLF
    folding for every other file under .act/ — applied to MANIFEST.json directly, in case that
    function has not landed yet. Returns "" if MANIFEST.json cannot be read at all."""
    fingerprint_fn = getattr(manifest, "manifest_fingerprint", None)
    if callable(fingerprint_fn):
        try:
            return fingerprint_fn(act_dir)
        except Exception:
            pass  # fall through to the content_hash() fallback below
    try:
        return manifest.content_hash(act_dir / "MANIFEST.json")
    except OSError:
        return ""


def _pulled_without_update(root: Path) -> bool:
    """True when .act/ matches its own MANIFEST.json exactly (so not a hand-edit — that is a
    different, already-covered concern, see doctor.py's manifest-drift check) but the fingerprint
    of that MANIFEST.json does not match the one .act-lock.json recorded at the last
    update.py/init.py run (`template.manifest_sha256`, Q73a) -- the fingerprint that tells a
    project's own regular state apart from one a plain `git pull` (or any other means outside
    update.py) just landed."""
    manifest_path = root / ".act" / "MANIFEST.json"
    if not manifest_path.is_file():
        return False
    try:
        recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(recorded, dict) or manifest.collect_files(root / ".act") != recorded:
        return False  # hand-edited (or unreadable) -- not what this check is looking for
    lock = actlib.read_lock()
    expected = (lock.get("template") or {}).get("manifest_sha256") or ""
    return _manifest_fingerprint(root / ".act") != expected


def _update_check_state_path(root: Path) -> Path:
    return root / ".act-local" / "update-check.json"


def _already_checked_today(root: Path) -> bool:
    try:
        data = json.loads(_update_check_state_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and data.get("last_checked") == date.today().isoformat()


def _mark_checked_today(root: Path) -> None:
    path = _update_check_state_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"last_checked": date.today().isoformat()}) + "\n", encoding="utf-8")
    except OSError:
        pass


def _remote_update_available(root: Path) -> Optional[bool]:
    """None if the check could not be made at all (no source/commit recorded, no network, the
    source is not a git remote/repo, or it took too long) -- always silent in that case, never a
    reported error (module docstring: a SessionStart check fails open). True/False otherwise.

    Only ever called from _run_update_check_worker(), i.e. inside the detached background
    process _spawn_update_check_worker() starts -- never directly from the SessionStart hook, so
    however long `git ls-remote` actually takes here never delays a session (see the header
    comment above _pulled_without_update).

    stdout/stderr go to a real temp file, not a pipe: `subprocess.run(capture_output=True, ...)`
    was measured at 21s against an unreachable address on Windows even with `timeout=5`, because
    a grandchild process git spawns (e.g. for the ssh transport) can keep the write end of the
    pipe open past the point `timeout` kills the immediate `git` process, and `communicate()`
    then blocks reading from that still-open pipe until the grandchild itself gives up. Waiting
    on a real file's process exit status has no such pipe to drain, so the timeout is enforced
    as written. GIT_TERMINAL_PROMPT/GCM_INTERACTIVE/GIT_SSH_COMMAND keep git from ever pausing
    for a credential prompt or a slow ssh handshake in an unattended background process."""
    lock = actlib.read_lock()
    template = lock.get("template") or {}
    source = template.get("source") or ""
    commit = template.get("commit") or ""
    if not source or not commit:
        return None
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o ConnectTimeout=3")
    try:
        with tempfile.TemporaryDirectory(prefix="act-update-check-") as tmp_dir:
            out_path = Path(tmp_dir) / "ls-remote.out"
            with open(out_path, "wb") as out_file:
                result = subprocess.run(
                    ["git", "ls-remote", "--", source, "HEAD"],
                    cwd=root, stdout=out_file, stderr=subprocess.DEVNULL,
                    timeout=5, env=env,
                    # no console window for git.exe on Windows, where the worker has none
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            if result.returncode != 0:
                return None
            output = out_path.read_text(encoding="utf-8", errors="replace").strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    if not output:
        return None
    remote_commit = output.split()[0].strip()
    return bool(remote_commit) and remote_commit != commit


def _update_check_result_path(root: Path) -> Path:
    return root / ".act-local" / "update-check-result.json"


def _consume_pending_update_note(root: Path) -> Optional[str]:
    """Reads and deletes .act-local/update-check-result.json, written by a previous
    _run_update_check_worker() run (see _spawn_update_check_worker) -- consuming it means the
    note surfaces exactly once, on the first SessionStart after the background check finished,
    same as the old synchronous check only ever reported it once (the run that found it). Silent
    on any I/O problem; a missing file (nothing pending) is the common case, not an error."""
    path = _update_check_result_path(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        path.unlink()
    except OSError:
        pass
    if isinstance(data, dict) and data.get("available"):
        return "[act] note: a template update is available -- run `python .act/scripts/update.py`"
    return None


def _run_update_check_worker(root: Path) -> int:
    """Body of the detached background process _spawn_update_check_worker() launches: the actual
    network lookup, isolated from the SessionStart hook so its result can only ever help the
    *next* session, never delay this one. Writes update-check-result.json on a conclusive
    True/False; leaves any existing file alone on None (inconclusive), so a stale-but-valid
    earlier result is not clobbered by a run that itself couldn't tell. Always exits 0 -- nothing
    reads this process's own exit code, and every exception here must stay inside this process."""
    try:
        available = _remote_update_available(root)
    except Exception:
        return 0
    if available is None:
        return 0
    try:
        path = _update_check_result_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"available": bool(available)}) + "\n", encoding="utf-8")
    except OSError:
        pass
    return 0


def _spawn_update_check_worker(root: Path) -> None:
    """Fire-and-forget: launches this same script as a fully detached background process running
    _run_update_check_worker(root) (dispatched via main()'s "_update-check-worker" internal
    event, never a real harness hook event) and returns immediately without waiting on it. Its
    stdin/stdout/stderr all go to DEVNULL, never a pipe back to this process -- a pipe here would
    reintroduce exactly the blocking this exists to avoid, just one level up. Best-effort: a
    failure to spawn is silent, same as every other note in this check."""
    script = Path(__file__).resolve()
    args = [sys.executable, str(script), "_update-check-worker", str(root)]
    try:
        if sys.platform == "win32":
            subprocess.Popen(
                args, cwd=root,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
        else:
            subprocess.Popen(
                args, cwd=root,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True, close_fds=True,
            )
    except OSError:
        pass


def _check_update_awareness(root: Path, config: dict[str, str]) -> tuple[list[str], list[str]]:
    """Check 2b's two notes, gated by the single `update-check` row (docs/ai/config.md § Checks,
    default "block" == on; "off" skips both notes and never spawns the background worker below).

    Returns (pre_notes, post_notes) -- pre_notes belong before the fixed-format status line,
    post_notes after it (module docstring / SessionStart output format): the pulled-without-
    update note is local, cheap and synchronous, so it stays a pre_note like before; the remote
    "update available" note is now always a *previous* run's finding (see _spawn_update_check_
    worker below), so it prints as a postscript after the status line rather than ahead of it.

    The remote lookup itself is throttled to once a day via .act-local/update-check.json
    (gitignored, per-checkout): when not yet checked today, this kicks off a detached background
    process (_spawn_update_check_worker) and marks today as checked immediately, without waiting
    for that process -- its result, if any, is picked up by _consume_pending_update_note() on a
    later SessionStart. Never raises."""
    mode = _check_mode(config, "update-check", default="block")
    if mode == "off":
        return [], []
    pre_notes: list[str] = []
    post_notes: list[str] = []
    if _pulled_without_update(root):
        pre_notes.append("[act] note: .act/ was pulled in without update.py -- run `python .act/scripts/update.py` (or --catch-up) to finish it")
    pending = _consume_pending_update_note(root)
    if pending:
        post_notes.append(pending)
    if not _already_checked_today(root):
        _mark_checked_today(root)
        _spawn_update_check_worker(root)
    return pre_notes, post_notes


# ---------------------------------------------------------------------------
# Orchestrator-only rules (.act/rules/orchestrator/) — delivered as SessionStart hook context,
# never @-imported into docs/ai/rules.md, so a sub-agent (which only ever loads that file) never
# sees them. See the "Overrides" note on _read_rule_states for the docs/ai/rules.md syntax this
# reads.
# ---------------------------------------------------------------------------

_CHECKBOX_RE = re.compile(r"^\s*-\s*\[([ xX])\]\s*`(R-[\w-]+)`")
_OVERRIDE_RE = re.compile(r"^-?\s*replaces\s+`(R-[\w-]+)`\s*:\s*(.+)$", re.IGNORECASE)
_SECTION_HEADING_RE = re.compile(r"^##\s+(.*)$")
_RULE_ID_IN_TEXT_RE = re.compile(r"`(R-[\w-]+)`")


def _read_rule_states(root: Path) -> tuple[dict[str, bool], dict[str, str]]:
    """
    Parse docs/ai/rules.md (the project's own copy, generated from .act/bridges/rules.md and free
    to be hand-edited afterwards) for two things:

      - enabled: rule id -> False for every "- [ ] `R-id`" checkbox found anywhere in the file.
        A rule id never mentioned there at all is on by default, so a template update that adds a
        new rule takes effect without the project having to touch this file.
      - overrides: rule id -> replacement text, read from a line of the form
        "replaces `R-id`: <text>" (the skeleton ships this as an HTML-commented example under
        "## Overrides"; a real override is an uncommented line in that same shape, so any line
        starting with "<!--" is skipped here rather than matched).

    Returns ({}, {}) if the file is missing or unreadable — nothing found means nothing to filter
    on, not an error.
    """
    path = root / "docs" / "ai" / "rules.md"
    enabled: dict[str, bool] = {}
    overrides: dict[str, str] = {}
    if not path.is_file():
        return enabled, overrides
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return enabled, overrides

    for line in lines:
        checkbox_match = _CHECKBOX_RE.match(line)
        if checkbox_match:
            mark, rule_id = checkbox_match.groups()
            enabled[rule_id] = mark.strip().lower() == "x"
            continue
        stripped = line.strip()
        if stripped.startswith("<!--"):
            continue  # the skeleton's own placeholder example, never a real override
        override_match = _OVERRIDE_RE.match(stripped)
        if override_match:
            rule_id, text = override_match.groups()
            overrides[rule_id] = text.strip()
    return enabled, overrides


def _filter_orchestrator_file(
    text: str, enabled: dict[str, str], overrides: dict[str, str]
) -> tuple[str, int]:
    """
    Split one .act/rules/orchestrator/*.md file into its "## " sections. A section whose heading
    carries a `R-...` id (every actual rule) is dropped when that id is off in `enabled` and has
    no entry in `overrides`; if it has one, the override text replaces the section body. A
    section without an id in its heading (the file's title/intro, a plain reference table such as
    "Role assignment" in 00-role.md) is never gated and always kept.

    Returns (filtered_text, rule_count): the filtered file, and how many gated sections survived
    (original or overridden) — the caller sums this across files for the status line.
    """
    lines = text.splitlines()
    kept: list[str] = []
    rule_count = 0

    section_lines: Optional[list[str]] = None
    section_rule_id: Optional[str] = None

    def _flush() -> None:
        nonlocal section_lines, section_rule_id, rule_count
        if section_lines is None:
            return
        if section_rule_id is None:
            kept.extend(section_lines)
        elif enabled.get(section_rule_id, True):
            kept.extend(section_lines)
            rule_count += 1
        elif section_rule_id in overrides:
            heading = section_lines[0] if section_lines else f"## `{section_rule_id}`"
            kept.append(f"{heading} (project override)")
            kept.append("")
            kept.append(overrides[section_rule_id])
            rule_count += 1
        # else: off, no override on file -> section dropped entirely
        section_lines = None
        section_rule_id = None

    preamble: list[str] = []
    in_section = False
    for line in lines:
        heading_match = _SECTION_HEADING_RE.match(line)
        if heading_match:
            _flush()
            in_section = True
            section_lines = [line]
            id_match = _RULE_ID_IN_TEXT_RE.search(heading_match.group(1))
            section_rule_id = id_match.group(1) if id_match else None
            continue
        if in_section:
            section_lines.append(line)
        else:
            preamble.append(line)
    _flush()

    return "\n".join(preamble + kept).rstrip("\n") + "\n", rule_count


def _deliver_orchestrator_rules(root: Path, config: dict[str, str]) -> Optional[int]:
    """
    Read every .act/rules/orchestrator/*.md file, in ascending filename order, filter it through
    _read_rule_states/_filter_orchestrator_file, and print what survives as SessionStart hook
    context — the one channel this template has that reaches only the main session (a sub-agent
    only ever sees docs/ai/rules.md, and these files are deliberately not @-imported there; see
    .act/bridges/rules.md).

    Returns None (and prints nothing) if the check is off or the directory does not exist yet —
    an older checkout, or a build stage before this directory was added, does nothing here rather
    than erroring. Otherwise returns the number of rules delivered (0 if every one was checked
    off), for the caller's status line.

    "block" and "warn" behave the same here: unlike the other two checks, this one has no side
    effect to withhold under "warn" — it only ever prints hook context, never writes a file — so
    both non-off values simply deliver the filtered rules.
    """
    mode = _check_mode(config, "orchestrator-rules", default="block")
    if mode == "off":
        return None

    rules_dir = root / ".act" / "rules" / "orchestrator"
    if not rules_dir.is_dir():
        return None

    enabled, overrides = _read_rule_states(root)
    total = 0
    blocks: list[str] = []
    for path in sorted(rules_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        filtered, count = _filter_orchestrator_file(text, enabled, overrides)
        total += count
        if count:
            blocks.append(filtered.rstrip("\n"))

    if blocks:
        print("[act] orchestrator rules (main session only, not seen by sub-agents):")
        print()
        print("\n\n".join(blocks))
        print()
    return total


def refresh_session(payload: dict) -> int:
    """Check 2: runs only for SessionStart. Never fails the session — every sub-step is best
    effort and swallows its own errors; the fixed-format status line always comes right after
    every other note except one deliberate postscript: an "update available" note, which is
    always a previous run's background finding and prints after the status line (see
    _check_update_awareness's pre_notes/post_notes split)."""
    config = actlib.read_config()
    mode = _check_mode(config, "session-start-refresh", default="block")
    if mode == "off":
        return 0

    try:
        root = actlib.repo_root()
    except RuntimeError:
        return 0  # not inside a template-managed project — nothing to report

    branch = _current_branch(root)

    try:
        waiting = _count_inbox_waiting(root)
    except Exception:
        waiting = 0

    changed_bridges: list[str] = []
    refreshed_bridges: list[str] = []
    try:
        changed_bridges, refreshed_bridges = _refresh_bridges(root, write=(mode == "block"))
    except Exception:
        pass

    try:
        _refresh_board(root)
    except Exception:
        pass

    for dest_rel in changed_bridges:
        print(f"[act] note: {dest_rel} was changed locally, template version not applied")
    if mode == "warn":
        for dest_rel in refreshed_bridges:
            print(f"[act] note: {dest_rel} would be refreshed from .act/bridges/ (warn mode, not applied)")

    # Role bridges (.claude/agents/*.md): only the `model`/`effort` frontmatter pair is refreshed
    # here, never the rest of the file — see tiers.py's refresh_project_bridge_frontmatter() and
    # 13-model-tiers.md § "Pflege der Zuordnungstabelle" for why this differs from _refresh_bridges
    # above, which replaces a whole file or leaves it alone.
    role_frontmatter_changed: list[str] = []
    tier_notes: list[str] = []
    try:
        role_frontmatter_changed = tiers.refresh_project_bridge_frontmatter(root, apply=(mode == "block"), notes=tier_notes)
    except Exception:
        pass
    if mode == "warn":
        for dest_rel in role_frontmatter_changed:
            print(f"[act] note: {dest_rel} model/effort would be refreshed from tiers.json/config.md (warn mode, not applied)")
    # An unknown tier/reasoning value (config.md § Roles or tiers.json) is reported once here as a
    # single line, whatever the role count — previously this only ever surfaced in init.py/
    # update.py's own notes, never at session start (Q29).
    if tier_notes:
        print("[act] note: " + "; ".join(tier_notes))

    post_update_notes: list[str] = []
    try:
        pre_update_notes, post_update_notes = _check_update_awareness(root, config)
        for note in pre_update_notes:
            print(note)
    except Exception:
        pass  # template-awareness is informational only, must never block the session

    rules_delivered: Optional[int] = None
    try:
        rules_delivered = _deliver_orchestrator_rules(root, config)
    except Exception:
        pass  # a broken rules delivery must not block the session

    inbox_part = f" · inbox: {waiting} waiting" if waiting else ""
    rules_part = f" · rules: {rules_delivered}" if rules_delivered is not None else ""
    roles_part = f" · role-bridges refreshed: {len(role_frontmatter_changed)}" if mode == "block" and role_frontmatter_changed else ""
    print(f"[act] branch={branch}{inbox_part} · board updated{rules_part}{roles_part}")
    # Printed after the status line, not before: an "update available" note here is always a
    # previous SessionStart's background finding (_consume_pending_update_note), never something
    # this run just checked, so it reads as a postscript rather than part of this run's status.
    for note in post_update_notes:
        print(note)
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    # "_update-check-worker" is the one exception to the "exactly one arg" harness contract
    # below: it is never a harness hook event, only what _spawn_update_check_worker() launches
    # (argv[1] is the project root as a string). Checked first so a stray extra argv entry here
    # can never fall through to "no event named".
    if len(argv) == 2 and argv[0] == "_update-check-worker":
        return _run_update_check_worker(Path(argv[1]))

    if len(argv) != 1:
        return 0  # no event named — nothing to dispatch, never an error for the caller

    event = argv[0]
    payload = _read_payload()

    if event == "PreToolUse":
        write_result = check_write_guard(payload)
        if write_result != 0:
            return write_result
        nesting_result = check_worker_nesting_guard(payload)
        if nesting_result != 0:
            return nesting_result
        return check_worker_write_scope(payload)
    if event == "SessionStart":
        return refresh_session(payload)
    return 0  # unknown event — do nothing, exit 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
