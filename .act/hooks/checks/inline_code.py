#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Reads inline interpreter code for the write checks (worker write scope, template write guard,
#          outside-root, git-metadata guard): the program text a shell command hands to `python`/`node`
#          (`python - <<'EOF' ... EOF`, `python -c "..."`, `node -e "..."`, a here-string or a literal piped
#          into `python -`). This module knows nothing about shells: shell_targets.py / powershell_targets.py
#          find the interpreter call, the code text and the directory the call runs in; this module answers
#
#              code_source(language, args)   -> where the code comes from (an option value, stdin, none)
#              write_targets(language, code) -> the paths a write call of the code names
#
# A check refuses only what the command text shows to be wrong, so write_targets reports only paths the text
# shows - and nothing else: a string that is merely mentioned (an import line, a comment, a path the code reads)
# is no target, and neither is a path that comes from a name bound twice, a loop variable, a parameter,
# `sys.argv`, a join or f-string with such a part or a call's result; code that cannot be read as Python gives
# no target. An unknown target passes.
#
# Python is read with `ast` (read_python_program, below): write calls are `open` with a writing mode (a mode the
# reading cannot see counts as writing), `os.remove|unlink|rmdir|removedirs|mkdir|makedirs|truncate|chmod|chown|
# utime|open|symlink|link|rename|replace`, `shutil.copy|copy2|copyfile|copymode|copystat|copytree|move|rmtree|
# chown`, and on any receiver the methods `write_text`, `write_bytes`, `touch`, `mkdir`, `unlink`, `rmdir`,
# `chmod`, `lchmod`, `rename`, `symlink_to`, `hardlink_to`, `link_to`; the path is what the text shows: a string
# literal, `Path(...)` / `os.path.join(...)` of such parts, a name bound once to such a value and used unchanged,
# `Path('<literal>').glob('<literal>')` on a relative folder and `glob.glob` of a literal pattern (_Env).
# The text of an `exec`/`eval` written out is read again.
#
# Node is read at regex level (comments dropped, every string literal blanked): `writeFile[Sync]`,
# `appendFile[Sync]`, `createWriteStream`, `copyFile[Sync]`, `cp[Sync]`, `rename[Sync]`, `unlink[Sync]`,
# `rm[Sync]`, `rmdir[Sync]`, `mkdir[Sync]`, `symlink[Sync]`, `truncate[Sync]` as a call; the path is a string
# literal, a name declared once as `const NAME = "literal"` or `path.join(...)` of such parts.
#
# A literal counts as a path when it holds `/` or `\` or is a bare file name with an extension (`name.ext`, not
# all digits) and is no URL, holds no control character, is not made of separators alone (_resolved_is_path).
#
# Known limits (a path missed here is simply not checked): a bare name without an extension (`open('out',
# 'w')`); a script file run by path; writes through `subprocess`/`os.system`/`child_process`; a write call that
# is not in the lists above (`.write(`, `Path.replace`, `fs.openSync`); code that imports a name under another
# one; any other interpreter (perl, ruby, php, deno, bun). Best effort: it catches the common form.

from __future__ import annotations

import ast
import fnmatch
import itertools
import os
import re
import shlex
import sys
import unicodedata
from pathlib import PurePosixPath, PureWindowsPath
from typing import NamedTuple, Optional

__all__ = [
    "PYTHON", "NODE", "SOURCE_CODE", "SOURCE_STDIN", "SOURCE_NONE",
    "interpreter_language", "code_source", "code_source_at", "write_targets", "WHOLE_FOLDER",
    "mentions_interpreter", "report_skipped", "ReaderFailure",
    "CALL_RUN", "CALL_WRITE", "CALL_CODE", "ProgramCall", "PythonProgram", "read_python_program",
]

PYTHON = "python"
NODE = "node"

SOURCE_CODE = "code"    # the code is an option value (`-c <code>`, `-e <code>`)
SOURCE_STDIN = "stdin"  # the code is read from standard input
SOURCE_NONE = "none"    # a script file, a module, a version query: no inline code

# A cheap test over a whole shell command: does it mention an interpreter this module reads at all?
# Callers run the real scan only then. Over-matching (a path component, a longer word) is harmless.
_MENTION_RE = re.compile(r"(?i)(?<![\w-])(?:python[\w.]*|pythonw[\w.]*|py|node)(?:\.exe)?(?![\w-])")

_PY_NAME_RE = re.compile(r"^(?:python|pythonw)(?:\d+(?:\.\d+)*)?$|^py$")
# `py -3`, `py -3.12`, `py -3.12-64`, `py -V:3.12`: the launcher's version selectors.
_PY_LAUNCHER_RE = re.compile(r"^-(?:\d[\w.-]*|V:\S*)$")
# Long options that take the next word as their value.
_PY_LONG_VALUE_OPTIONS = frozenset({"--check-hash-based-pycs"})

_NODE_VALUE_OPTIONS = frozenset({
    "-r", "--require", "--import", "--loader", "--experimental-loader", "-C", "--conditions", "--input-type",
})
_NODE_EVAL_OPTIONS = frozenset({"-e", "--eval", "-p", "--print", "-pe", "-ep"})
# Options after which node runs no program text of its own. (`-i`/`--interactive` is none of them: node
# runs the `-e` text before it opens its prompt.)
_NODE_NO_CODE_OPTIONS = frozenset({"-v", "--version", "-h", "--help", "-c", "--check"})

_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_BARE_FILE_RE = re.compile(r"^[^\s/\\]+\.([A-Za-z0-9]{1,8})$")
_PY_MODE_RE = re.compile(r"""^(['"])([rwaxbt+]+)\1$""")
_ARG_SCAN_LIMIT = 300  # characters of one call's arguments read for a mode; bounds the work per call


class _Literal(NamedTuple):
    value: str          # the text of the literal; for an interpolated one only the part before the first field
    interpolated: bool


def mentions_interpreter(command: str) -> bool:
    """True if `command` names `python`/`py`/`node` somewhere (see _MENTION_RE) - the cheap test in
    front of the real scan."""
    return bool(_MENTION_RE.search(command))


def interpreter_language(name: str) -> Optional[str]:
    """PYTHON or NODE for a command word naming a supported interpreter - `python`, `python3`,
    `python3.12`, `pythonw`, `py`, `node`, an optional `.exe` and directory in front - else None."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if base.endswith(".exe"):
        base = base[:-4]
    if _PY_NAME_RE.match(base):
        return PYTHON
    if base == "node":
        return NODE
    return None


def _stdin_or_none(args: list[str], index: int) -> tuple[str, Optional[str]]:
    """What follows the options (`args[index:]`): a lone `-` or no script at all reads the program from
    standard input, any other word is a script file."""
    if index < len(args):
        return (SOURCE_STDIN, None) if args[index] == "-" else (SOURCE_NONE, None)
    return SOURCE_STDIN, None


def _python_source(args: list[str]) -> tuple[str, Optional[str], Optional[int]]:
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            index += 1
            break
        if arg == "-":
            return SOURCE_STDIN, None, None
        if not arg.startswith("-"):
            return SOURCE_NONE, None, None
        if arg.startswith("--"):
            if arg in ("--version", "--help"):
                return SOURCE_NONE, None, None
            index += 2 if arg in _PY_LONG_VALUE_OPTIONS else 1
            continue
        if _PY_LAUNCHER_RE.match(arg):
            index += 1
            continue
        takes_next = False
        for position in range(1, len(arg)):
            char = arg[position]
            if char == "c":
                rest = arg[position + 1:]
                if rest:
                    return SOURCE_CODE, rest, None
                if index + 1 < len(args):
                    return SOURCE_CODE, args[index + 1], index + 1
                return SOURCE_NONE, None, None
            if char in "mVh?":
                return SOURCE_NONE, None, None
            if char in "WXQ":  # -W/-X take a value, glued or as the next word
                takes_next = position + 1 == len(arg)
                break
        index += 2 if takes_next else 1
    return (*_stdin_or_none(args, index), None)


def _node_source(args: list[str]) -> tuple[str, Optional[str], Optional[int]]:
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            index += 1
            break
        if arg == "-":
            return SOURCE_STDIN, None, None
        if not arg.startswith("-"):
            return SOURCE_NONE, None, None
        if arg.startswith(("--eval=", "--print=")):
            return SOURCE_CODE, arg.split("=", 1)[1], None
        if arg in _NODE_EVAL_OPTIONS:
            if index + 1 < len(args):
                return SOURCE_CODE, args[index + 1], index + 1
            return SOURCE_NONE, None, None
        if arg in _NODE_NO_CODE_OPTIONS:
            return SOURCE_NONE, None, None
        index += 2 if arg in _NODE_VALUE_OPTIONS else 1
    return (*_stdin_or_none(args, index), None)


def code_source(language: str, args: list[str]) -> tuple[str, Optional[str]]:
    """Where an interpreter call gets its program from, read from the call's arguments (the words after
    the command name): (SOURCE_CODE, the code) for `-c`/`-e`/`--eval`/`-p`, (SOURCE_STDIN, None) for a
    lone `-` or no script argument at all, (SOURCE_NONE, None) for a script file, a module (`-m`) or a
    query that runs nothing. Options before the code are skipped (`-X utf8 -I -c`, `py -3.12 -c`,
    `--input-type=module -e`); a cluster ending in `c` (`-Ic`) counts."""
    kind, code, _index = code_source_at(language, args)
    return kind, code


def code_source_at(language: str, args: list[str]) -> tuple[str, Optional[str], Optional[int]]:
    """code_source plus the index in `args` of the word that IS the code - the word after `-c`/`-e`/
    `--eval`/`-p` - or None when the code is only part of a word (`-cprint(1)`, `--eval=...`) or comes
    from standard input: a caller that wants to take the program out of the command text needs the
    whole word and nothing else."""
    return _python_source(args) if language == PYTHON else _node_source(args)


# One escape of a non-raw literal: a line continuation, \xhh, \u{...} (JavaScript), \uXXXX, \UXXXXXXXX,
# \N{name} (Python), an octal number, or any other single character.
_ESCAPE_RE = re.compile(
    r"\\(?:(\r?\n)|x([0-9A-Fa-f]{2})|u\{([0-9A-Fa-f]+)\}|u([0-9A-Fa-f]{4})|U([0-9A-Fa-f]{8})|N\{([^}]*)\}"
    r"|([0-7]{1,3})|(.))",
    re.DOTALL,
)
_SIMPLE_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v"}


def _decode_escapes(text: str, javascript: bool, text_literal: bool = True) -> str:
    """The value of a non-raw literal's body, its escapes decoded by the rules of its language: a
    backslash-newline -> nothing; `\\n`, `\\t`, `\\b` ... -> the control character (such a literal is text,
    not a path); `\\xhh`, `\\uXXXX`, octal -> that character; Python also `\\UXXXXXXXX` and `\\N{name}` (not
    in a bytes literal, `text_literal` False, where `\\u` stays as written), JavaScript also `\\u{...}`.
    Any other escape: JavaScript drops the backslash (`\\d` -> `d`, `\\/` -> `/`), Python keeps it,
    except for `\\\\`, `\\'` and `\\"`. An escape that does not decode (`\\N{no such name}`, a code point
    beyond U+10FFFF) stays as written."""
    def replace(match: "re.Match[str]") -> str:
        newline, hex2, brace, hex4, hex8, name, octal, other = match.groups()
        written = match.group(0)
        if newline is not None:
            return ""
        try:
            if hex2 is not None:
                return chr(int(hex2, 16))
            if octal is not None:
                return chr(int(octal, 8))
            if hex4 is not None and (javascript or text_literal):
                return chr(int(hex4, 16))
            if brace is not None and javascript:
                return chr(int(brace, 16))
            if hex8 is not None and text_literal and not javascript:
                return chr(int(hex8, 16))
            if name is not None and text_literal and not javascript:
                return unicodedata.lookup(name)
        except (ValueError, OverflowError, KeyError):  # chr() out of range, no such character name
            return written
        if other is None:
            return written
        if other in _SIMPLE_ESCAPES:
            return _SIMPLE_ESCAPES[other]
        if not javascript and other == "a":
            return "\a"
        if javascript or other in "\\'\"":
            return other
        return written

    return _ESCAPE_RE.sub(replace, text)


class ReaderFailure(Exception):
    """The reader of inline interpreter code failed with an error of its own program (a `TypeError`, a
    `KeyError` ...), not with a text it does not understand. Such a command is not let through unread:
    the callers refuse it and name the error."""


def report_skipped(where: str, error: BaseException) -> None:
    """Say on standard error that inline interpreter code was not read because of `error` (its type and
    message, never the command): the reading is best effort and a failure of it must not refuse the
    call, but it must not pass unseen either."""
    print(f"[act] inline interpreter code not read ({where}): {type(error).__name__}: {error}", file=sys.stderr)


def _skip_js_string(code: str, index: int) -> int:
    """Index just after the JavaScript string (any of the three quotes) that opens at `code[index]`; a
    string that is not closed ends at the end of its line (quotes ' and \") or of the text."""
    quote = code[index]
    cursor = index + 1
    while cursor < len(code):
        current = code[cursor]
        if current == "\\":
            cursor += 2
            continue
        if current == quote:
            return cursor + 1
        if current == "\n" and quote != "`":
            return cursor
        cursor += 1
    return len(code)


# What may stand in front of a `/` that opens a regular-expression literal: one of these characters, or
# one of these words. After anything else (a name, a number, a closing bracket, a string) it is a division.
_JS_REGEX_AFTER_CHARS = frozenset("(,=:[!&|?{};+-*%<>~^")
_JS_REGEX_AFTER_WORDS = frozenset({
    "return", "typeof", "case", "do", "else", "in", "of", "void", "delete", "throw", "new", "yield", "await",
    "instanceof",
})
_JS_WORD_AT_END_RE = re.compile(r"[A-Za-z_$][\w$]*$")
_JS_TAIL_WINDOW = 200  # characters of the skeleton looked at to find what stands in front of a `/`


def _js_regex_may_start(out: list[str]) -> bool:
    """True if a `/` after the skeleton `out` may open a regular-expression literal rather than divide."""
    tail = "".join(out[-_JS_TAIL_WINDOW:]).rstrip()
    if not tail:
        return True
    if tail[-1] in _JS_REGEX_AFTER_CHARS:
        return True
    word = _JS_WORD_AT_END_RE.search(tail)
    return word is not None and word.group(0) in _JS_REGEX_AFTER_WORDS


def _skip_js_regex(code: str, index: int) -> Optional[int]:
    """Index just after the regular-expression literal (flags included) that opens at `code[index]`, or
    None if no closing `/` is found on its line - the `/` is then taken as a division, so a doubt
    reads more code, never less. A `/` inside a character class `[...]` or after a backslash does not close."""
    cursor = index + 1
    in_class = False
    while cursor < len(code):
        current = code[cursor]
        if current == "\\":
            cursor += 2
            continue
        if current == "\n":
            return None
        if in_class:
            in_class = current != "]"
        elif current == "[":
            in_class = True
        elif current == "/":
            cursor += 1
            while cursor < len(code) and code[cursor].isalpha():
                cursor += 1
            return cursor
        cursor += 1
    return None


def _javascript_scan(code: str) -> tuple[list[_Literal], str]:
    """The JavaScript reader: `//` and `/* */` comments dropped, strings and
    template literals collected (a template's static part before its first `${` when it has one),
    regular-expression literals blanked (their `//` or quote is no comment or string)."""
    literals: list[_Literal] = []
    out: list[str] = []
    size = len(code)
    index = 0
    while index < size:
        char = code[index]
        if char == "/" and not code.startswith(("//", "/*"), index) and _js_regex_may_start(out):
            regex_end = _skip_js_regex(code, index)
            if regex_end is not None:
                out.append("/_/")
                index = regex_end
                continue
        if code.startswith("//", index):
            end = code.find("\n", index)
            index = size if end < 0 else end
            continue
        if code.startswith("/*", index):
            end = code.find("*/", index + 2)
            index = size if end < 0 else end + 2
            out.append(" ")
            continue
        if char not in "'\"`":
            out.append(char)
            index += 1
            continue
        cursor = index + 1
        field: Optional[int] = None
        while cursor < size:
            current = code[cursor]
            if current == "\\":
                cursor += 2
                continue
            if current == char:
                break
            if char == "`" and code.startswith("${", cursor):
                if field is None:
                    field = cursor
                depth = 1
                cursor += 2
                while cursor < size and depth:
                    inner = code[cursor]
                    if inner in "'\"`":
                        cursor = _skip_js_string(code, cursor)
                        continue
                    depth += (inner == "{") - (inner == "}")
                    cursor += 1
                continue
            if current == "\n" and char != "`":
                break
            cursor += 1
        closed = cursor < size and code[cursor] == char
        end_of_body = min(cursor, size)
        static_end = field if field is not None else end_of_body
        literals.append(_Literal(_decode_escapes(code[index + 1:static_end], True), field is not None))
        out.append(char + char)
        index = cursor + 1 if closed else end_of_body
    return literals, "".join(out)


_NODE_WRITE_RE = re.compile(
    r"(?<![\w$])(?:writeFile|writeFileSync|appendFile|appendFileSync|createWriteStream|copyFile|copyFileSync"
    r"|cp|cpSync|rename|renameSync|unlink|unlinkSync|rm|rmSync|rmdir|rmdirSync|mkdir|mkdirSync|symlink"
    r"|symlinkSync|truncate|truncateSync)\s*\("
)


_QUOTE_CHARS = {PYTHON: "'\"", NODE: "'\"`"}


def _literal_spans(language: str, skeleton: str) -> list[tuple[int, int]]:
    """(start, end) of every quote pair of the skeleton, in order: the n-th pair is the n-th literal of
    the program, as _javascript_scan keeps every literal as one pair."""
    quotes = _QUOTE_CHARS[language]
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(skeleton):
        char = skeleton[index]
        if char in quotes:
            end = skeleton.find(char, index + 1)
            end = len(skeleton) if end < 0 else end + 1
            spans.append((index, end))
            index = end
        else:
            index += 1
    return spans


def _argument_spans(skeleton: str, start: int) -> list[tuple[int, int]]:
    """(start, end) of each top-level argument of the call - or element of the list - whose opening
    bracket stands just before `skeleton[start]`: split at commas outside any bracket, up to the closing
    bracket or _ARG_SCAN_LIMIT characters. The last span ends where the reading stopped: at the closing
    bracket, or earlier when the limit cut the call (a literal beyond it is judged like any other)."""
    spans: list[tuple[int, int]] = []
    depth = 0
    begin = start
    index = start
    stop = min(len(skeleton), start + _ARG_SCAN_LIMIT)
    while index < stop:
        char = skeleton[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif char == "," and depth == 0:
            spans.append((begin, index))
            begin = index + 1
        index += 1
    spans.append((begin, index))
    return spans


_NODE_TWO_PATHS_RE = re.compile(r"(?:copyFile|cp|rename|symlink)")
_NODE_IDENTIFIER_RE = re.compile(r"[A-Za-z_$][\w$]*")
_NODE_JOIN_RE = re.compile(r"(?<![\w$.])path\s*\.\s*join\s*\(")
# What may follow the literal of `const NAME = "literal"` so that the literal is the whole value: the end of the
# statement, or a line break not continued by an operator, a call or a member access.
_NODE_INITIALIZER_END_RE = re.compile(r"[ \t]*(?:[;,]|$|\r?\n\s*(?![.(\[+\-*/%?:|&<>=]))")
_NODE_REBINDING_RE = re.compile(r"(?<![\w$])(?:eval|Function|vm)(?![\w$])")


def _node_const_ok(skeleton: str, name: str) -> bool:
    """True if `name` is declared once in the skeleton of Node code and is not bound or assigned any other way:
    no second declaration, destructuring, parameter, `catch` binding or assignment (a `const` cannot change, but
    an inner scope can hide it)."""
    word = re.escape(name)
    before = r"(?<![\w$.])"
    declarations = len(re.findall(before + r"(?:const|let|var)\s+" + word + r"(?![\w$])", skeleton))
    hidden = (
        before + r"(?:const|let|var)\s*[\[{][^=;]*?(?<![\w$.])" + word + r"(?![\w$])",
        r"\bfunction\b[^(]*\([^)]*(?<![\w$.])" + word + r"(?![\w$])",
        r"\([^()]*(?<![\w$.])" + word + r"(?![\w$])[^()]*\)\s*(?:=>|\{)",
        before + word + r"\s*=>",
        r"\bcatch\s*\(\s*" + word + r"(?![\w$])",
        before + word + r"\s*(?:\+\+|--)",
        r"(?:\+\+|--)\s*" + word + r"(?![\w$])",
    )
    assigns = len(re.findall(before + word + r"\s*(?:[-+*/%&|^]|\*\*|<<|>>>?|\?\?|&&|\|\|)?=(?!=)", skeleton))
    return declarations == 1 and assigns == 1 and not any(re.search(pattern, skeleton) for pattern in hidden)


def _node_write_targets(literals: list[_Literal], skeleton: str) -> list[str]:
    """The paths the write calls of Node code name when the text shows them: a path is a
    string literal, a name declared once as `const NAME = "literal"` (and not hidden or assigned again), or
    `path.join(...)` of such parts; the first two paths of a copy, move or link. Code that holds `eval`, `Function`
    or `vm` shows no name."""
    spans = _literal_spans(NODE, skeleton)
    if len(spans) != len(literals):
        return []
    by_span = {span: index for index, span in enumerate(spans)}
    names: dict[str, str] = {}
    if _NODE_REBINDING_RE.search(skeleton) is None:
        for match in re.finditer(r"(?<![\w$.])const\s+([A-Za-z_$][\w$]*)\s*=\s*(?=['\"`])", skeleton):
            index = next((i for i, span in enumerate(spans) if span[0] == match.end()), None)
            if index is None or literals[index].interpolated or not _node_const_ok(skeleton, match.group(1)):
                continue
            if _NODE_INITIALIZER_END_RE.match(skeleton, spans[index][1]):
                names[match.group(1)] = literals[index].value

    def path_of(span: tuple[int, int], depth: int = 0) -> Optional[str]:
        start, end = span
        while start < end and skeleton[start].isspace():
            start += 1
        while end > start and skeleton[end - 1].isspace():
            end -= 1
        text = skeleton[start:end]
        if (start, end) in by_span:
            literal = literals[by_span[(start, end)]]
            return None if literal.interpolated else literal.value
        if _NODE_IDENTIFIER_RE.fullmatch(text):
            return names.get(text)
        join = _NODE_JOIN_RE.match(text)
        if join is None or not text.endswith(")") or depth > _LITERAL_FOLD_DEPTH:
            return None
        parts = _argument_spans(skeleton, start + join.end())
        if parts[-1][1] != end - 1:
            return None
        values = [path_of(part, depth + 1) for part in parts]
        return None if None in values else os.path.join(*[value for value in values if value is not None])

    found: list[str] = []
    for match in _NODE_WRITE_RE.finditer(skeleton):
        count = 2 if _NODE_TWO_PATHS_RE.match(match.group()) else 1
        values = [path_of(span) for span in _argument_spans(skeleton, match.end())[:count]]
        found.extend(value for value in values if value is not None and _resolved_is_path(value))
    return found


def write_targets(language: str, code: str, depth: int = 0) -> list[str]:
    """The paths a write call of `code` names as literals - what a check judges that must not refuse a program
    for a path it only mentions. Only what the text shows: a path that comes from a name bound twice, a join
    with a variable, a call's result or an f-string with a field is no target, and code that cannot be read
    gives none - an unknown target passes. Python: the write calls the program reading reports
    (read_python_program: `open(<path>, 'w')`, `Path(<path>).write_text(...)`, `os.remove`, `shutil.copy` to its
    destination ...) and those of an `exec`/`eval` text written out (up to three levels). Node:
    _node_write_targets."""
    if language != PYTHON:
        return _node_write_targets(*_javascript_scan(code))
    found: dict[str, None] = {}
    program = read_python_program(code)
    for call in program.calls if program is not None else ():
        if call.kind == CALL_WRITE:
            found.update((value, None) for value in call.values if _resolved_is_path(value))
        elif call.kind == CALL_CODE and depth < 3:
            for text in call.values:
                found.update(dict.fromkeys(write_targets(PYTHON, text, depth + 1)))
    return list(found)


_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f]")


def _resolved_is_path(value: str) -> bool:
    """Whether a resolved value is judged as a path: the same shape rule as a literal (a separator, or a
    bare file name with an extension; no URL, no control character), but glob characters and a bare name that
    starts with a dot are allowed."""
    if not value.strip("/\\") or _CONTROL_CHAR_RE.search(value) is not None:
        return False
    if "://" in value and _URL_RE.match(value):  # the cheap test first: the regex backtracks over a long value
        return False
    if "/" in value or "\\" in value or re.match(r"\.[^.]", value):  # a dot name (`.act`, `.envrc`) is a path too
        return True
    if "." not in value[-10:]:
        return False  # no extension of up to 8 characters at the end: not a bare file name (same reason)
    bare = _BARE_FILE_RE.match(value)
    return bare is not None and not bare.group(1).isdigit()


# --- A Python program read as Python: the calls that run a command or write a file -------------------
#
# For a check that must know what a program DOES with a string rather than which strings it holds (the
# git-metadata guard reads a program handed to `python` this way): the program is parsed with `ast`,
# nothing of it runs, and every call of the families below is reported with the LITERAL values that go
# into it (a command line or Python text only when it is written out; the path of a write call as the allow-list
# in the header of this file shows it). A value the reading cannot see is not reported, and a CALL_WRITE call with
# such a path says so (ProgramCall.unknown_path); the write checks let it pass (an unknown target is no refusal). A program that does not
# parse as Python, is larger than _PROGRAM_SIZE_LIMIT or nests deeper than the interpreter can walk is not read at
# all (None back).
#
# Families (the callee is looked up through the program's own imports: `import subprocess as sp`,
# `from os import system as run`, `from os import *`; a dotted chain whose root is not a plain name -
# `importlib.import_module("os").system(...)` - counts as the family its last name belongs to):
#   - CALL_RUN, a command line: `os.system`, `os.popen`, `os.startfile`, `subprocess.run`, `call`,
#     `check_call`, `check_output`, `Popen`, `getoutput`, `getstatusoutput`, `os.exec*`, `os.spawn*`,
#     `os.posix_spawn[p]`, `asyncio.create_subprocess_shell` / `_exec`, `pty.spawn`. A list of literals
#     is reported as one command line with each word quoted (shlex.join); a literal `cwd=` is reported as
#     the directory the command runs in, a non-literal one as an unknown directory. The specific names
#     (`system`, `Popen`, `check_output`, ...) count on any receiver; the generic `run`, `call` and
#     `spawn` only on one of these modules or on a receiver that is no plain name.
#   - CALL_WRITE, a path: builtin / `io.` / `codecs.` `open` with a mode that writes (`w`, `a`, `x`, `+`;
#     a mode the reading cannot see counts as writing), `os.remove`, `unlink`, `rmdir`, `removedirs`,
#     `mkdir`, `makedirs`, `truncate`, `chmod`, `chown`, `utime`, `open`, `symlink`, `link`, `rename`,
#     `replace`, `shutil.copy`, `copy2`, `copyfile`, `copymode`, `copystat`, `copytree`, `move`, `rmtree`,
#     `chown`, and on any receiver the methods `write_text`, `write_bytes`, `touch`, `mkdir`, `unlink`,
#     `rmdir`, `chmod`, `lchmod`, `rename`, `symlink_to`, `hardlink_to`, `link_to`, `open` (writing mode):
#     the receiver is the path when the text shows it (`Path(...)` of literals, a name bound once), else unknown.
#     For a copy the destination is the path, for a move, rename or link both operands are.
#   - CALL_CODE, Python text: builtin `exec` and `eval` with a literal; the caller reads that text again.
# A literal is a string constant, bytes (decoded), several of them joined with `+`, an f-string without
# fields, or a list/tuple of those. Not seen (a limit, the same as the string-literal reading above): a
# command line or Python text that comes from a name, a join or an f-string with fields, a callee reached through
# `getattr`, a subscript or a lambda, `.write(` on a stream, `str.replace` and `Path.replace` (left out on
# purpose), `runpy`, `importlib` loading a file, code built at run time.

CALL_RUN = "run"      # a command line the program hands to a shell or a program
CALL_WRITE = "write"  # a path the program writes, creates, moves, links or deletes
CALL_CODE = "code"    # Python text the program runs itself (`exec`, `eval`)

_PROGRAM_SIZE_LIMIT = 32_768   # characters of one program read as Python (parsing costs ~3 ms per KB); a larger one is not read, and refused when it holds a write call
_LITERAL_FOLD_DEPTH = 64       # `"a" + "b" + ...` chains folded this deep; deeper is not a literal

# (module, function) -> how the arguments are read: "line" (the first argument is a command line),
# "args" (the first argument is a command line or an argv list), "words" (every positional literal is a
# word of the command line, an int such as a spawn mode is skipped).
_RUN_FUNCTIONS: dict[tuple[str, str], str] = {
    ("os", "system"): "line", ("os", "popen"): "line", ("os", "startfile"): "line",
    ("subprocess", "getoutput"): "line", ("subprocess", "getstatusoutput"): "line",
    ("asyncio", "create_subprocess_shell"): "line",
    ("subprocess", "run"): "args", ("subprocess", "call"): "args", ("subprocess", "check_call"): "args",
    ("subprocess", "check_output"): "args", ("subprocess", "Popen"): "args", ("pty", "spawn"): "args",
    ("asyncio", "create_subprocess_exec"): "words",
}
for _name in ("execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe", "spawnl", "spawnle",
              "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe", "posix_spawn", "posix_spawnp"):
    _RUN_FUNCTIONS[("os", _name)] = "words"
_RUN_ANY_RECEIVER = frozenset(
    name for module, name in _RUN_FUNCTIONS if name not in ("run", "call", "spawn")
)
_RUN_GENERIC = frozenset({"run", "call", "spawn"})

# (module, function) -> the positions of the path arguments ((0,) the first, (1,) the second, (0, 1) both);
# "mode" marks an open-like call whose first argument is the path only when its mode writes.
_WRITE_FUNCTIONS: dict[tuple[str, str], tuple] = {
    ("builtins", "open"): ("mode",), ("io", "open"): ("mode",), ("codecs", "open"): ("mode",),
    ("os", "open"): (0,), ("os", "remove"): (0,), ("os", "unlink"): (0,), ("os", "rmdir"): (0,),
    ("os", "removedirs"): (0,), ("os", "mkdir"): (0,), ("os", "makedirs"): (0,), ("os", "truncate"): (0,),
    ("os", "chmod"): (0,), ("os", "chown"): (0,), ("os", "utime"): (0,), ("os", "symlink"): (1,),
    ("os", "link"): (1,), ("os", "rename"): (0, 1), ("os", "replace"): (0, 1),
    ("shutil", "copy"): (1,), ("shutil", "copy2"): (1,), ("shutil", "copyfile"): (1,), ("shutil", "copymode"): (1,),
    ("shutil", "copystat"): (1,), ("shutil", "copytree"): (1,), ("shutil", "move"): (0, 1),
    ("shutil", "rmtree"): (0,), ("shutil", "chown"): (0,),
}
# method -> whether the first argument is a path too (a rename target, a link target)
_WRITE_METHODS: dict[str, bool] = {
    "write_text": False, "write_bytes": False, "touch": False, "mkdir": False, "unlink": False, "rmdir": False,
    "chmod": False, "lchmod": False, "rename": True, "symlink_to": True, "hardlink_to": True, "link_to": True,
}
_CODE_FUNCTIONS = frozenset({("builtins", "exec"), ("builtins", "eval")})
_BUILTIN_NAMES = frozenset({"open", "exec", "eval"})


class ProgramCall(NamedTuple):
    """One call of a program that runs a command, writes a file or runs Python text (see above)."""

    name: str                  # the callee as written: `os.system`, `subprocess.run`, `open`, `.write_text`
    kind: str                  # CALL_RUN, CALL_WRITE or CALL_CODE
    values: tuple[str, ...]    # the literal command lines, paths or code texts that go into the call; a value
                               # that is no literal is not here and is not judged by anyone
    directory: Optional[str]   # a literal `cwd=` of the call, else None
    directory_known: bool      # False when `cwd=` is given but is no literal: the directory is unknown
    line: int
    unknown_path: bool = False  # CALL_WRITE: a path of the call is no literal (the call is not judged by its values)


class _Aliases(NamedTuple):
    modules: dict           # local name -> module it stands for (`sp` -> "subprocess", `os` -> "os")
    functions: dict         # local name -> (module, function) from `from os import system [as s]`
    star: frozenset         # modules imported with `*`


def _module_aliases(tree: ast.AST) -> _Aliases:
    modules: dict[str, str] = {}
    functions: dict[str, tuple[str, str]] = {}
    star: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                modules[alias.asname or root] = root if alias.asname is None else alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                if alias.name == "*":
                    star.add(node.module)
                else:
                    functions[alias.asname or alias.name] = (node.module, alias.name)
    return _Aliases(modules, functions, frozenset(star))


def _fold_string(node: ast.expr, depth: int = 0) -> Optional[str]:
    """The text of a string literal: a constant (bytes decoded), constants joined with `+`, an f-string
    without replacement fields; None for anything else."""
    if depth > _LITERAL_FOLD_DEPTH:
        return None
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return node.value
        if isinstance(node.value, bytes):
            return node.value.decode("utf-8", errors="replace")
        return None
    if isinstance(node, ast.JoinedStr):
        parts = [_fold_string(value, depth + 1) for value in node.values]
        return None if any(part is None for part in parts) else "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _fold_string(node.left, depth + 1), _fold_string(node.right, depth + 1)
        return None if left is None or right is None else left + right
    return None


def _fold_strings(node: ast.expr) -> Optional[list[str]]:
    """The texts of a list or tuple of string literals; None when it is no such list or holds a value
    the reading cannot see (a starred element included)."""
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    found: list[str] = []
    for element in node.elts:
        text = _fold_string(element)
        if text is None:
            return None
        found.append(text)
    return found


def _dotted_root(node: ast.expr) -> tuple[Optional[str], list[str]]:
    """(the root name of an attribute chain, or None when the chain starts at something that is no
    plain name; the attribute names below the root, outermost last)."""
    names: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        names.insert(0, current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        return current.id, names
    return None, names


def _callee(func: ast.expr, aliases: _Aliases) -> Optional[tuple[str, str, Optional[ast.expr]]]:
    """(module, function, receiver) for a callee of one of the families: module "" with a receiver for
    a method on an object (`p.write_text`), module "?" for a family name on a chain whose root is no
    plain name; None for any other callee."""
    if isinstance(func, ast.Name):
        if func.id in aliases.functions:
            module, function = aliases.functions[func.id]
            if ((module, function) in _RUN_FUNCTIONS or (module, function) in _WRITE_FUNCTIONS
                    or (module, function) in _CODE_FUNCTIONS):
                return module, function, None
            if function in _BUILTIN_NAMES:
                # `from gzip import open` (also bz2, lzma, …): the imported `open`/`exec`/`eval` opens a
                # file or runs code like the builtin, so it is judged like the builtin, not freed as an
                # unknown import.
                return "builtins", function, None
            return None  # a from-import of something else (`from pathlib import Path`): no family
        for module in aliases.star:
            if (module, func.id) in _RUN_FUNCTIONS or (module, func.id) in _WRITE_FUNCTIONS:
                return module, func.id, None
        if func.id in _BUILTIN_NAMES and func.id not in aliases.modules:
            return "builtins", func.id, None
        return None
    if not isinstance(func, ast.Attribute):
        return None
    root, names = _dotted_root(func)
    attr = func.attr
    if root is not None and len(names) == 1:
        module = aliases.modules.get(root)
        if module is None and root in ("builtins", "os", "subprocess", "shutil", "io", "codecs", "asyncio", "pty"):
            module = root  # named without an import: the reading stays on the safe side
        if module is not None and ((module, attr) in _RUN_FUNCTIONS or (module, attr) in _WRITE_FUNCTIONS
                                   or (module, attr) in _CODE_FUNCTIONS):
            return module, attr, None
    if attr in _RUN_ANY_RECEIVER or (root is None and attr in _RUN_GENERIC):
        return "?", attr, func.value
    if attr in _WRITE_METHODS or attr == "open":
        return "", attr, func.value
    return None


def _argument(call: ast.Call, position: int, keyword: Optional[str]) -> Optional[ast.expr]:
    if position < len(call.args):
        return call.args[position]
    if keyword is not None:
        for item in call.keywords:
            if item.arg == keyword:
                return item.value
    return None


def _mode_writes(call: ast.Call, position: int, env: "_Env") -> bool:
    """True if the `mode` of an open-like call (positional `position` or `mode=`) writes: a mode-shaped
    literal (`rwaxbt+U` only) holding `w`, `a`, `x` or `+`, or a mode the reading cannot see (a variable).
    No mode at all is the default `r`; a literal that is no mode (`webbrowser.open(url)`, `tarfile.open(name)`)
    makes the call no open-for-writing."""
    node = _argument(call, position, "mode")
    if node is None:
        return False
    mode = env.text(node)
    if mode is None:
        return True
    return _PY_MODE_RE.match(f"'{mode}'") is not None and any(char in "wax+" for char in mode)


def _is_read_only_flag(node: Optional[ast.expr]) -> bool:
    """True for the flags `os.O_RDONLY` of an `os.open` call, written out as that and as nothing else."""
    return isinstance(node, ast.Attribute) and node.attr == "O_RDONLY" and isinstance(node.value, ast.Name)


def _literal_writing_mode(node: Optional[ast.expr], env: "_Env") -> bool:
    """True if `node` is a mode written out (a name bound once to one included) that writes."""
    mode = env.text(node)
    return mode is not None and _PY_MODE_RE.match(f"'{mode}'") is not None and any(char in "wax+" for char in mode)


def _command_values(call: ast.Call, how: str) -> tuple[str, ...]:
    """The command line a run-family call hands over, when it is written out as a literal; nothing
    when any part of it is a value the reading cannot see (it is then not judged at all)."""
    if how == "words":
        words: list[str] = []
        for argument in call.args:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, (int, float)) and not isinstance(argument.value, bool):
                continue  # a spawn mode
            text = _fold_string(argument)
            if text is not None:
                words.append(text)
                continue
            items = _fold_strings(argument)
            if items is None:
                return ()
            words.extend(items)
        return (shlex.join(words),) if words else ()
    node = _argument(call, 0, "args" if how == "args" else "command")
    if node is None:
        node = _argument(call, 0, "cmd")
    if node is None:
        return ()
    text = _fold_string(node)
    if text is not None:
        return (text,)
    if how == "args":
        items = _fold_strings(node)
        if items is not None:
            return (shlex.join(items),)
    return ()


def _directory_of(call: ast.Call) -> tuple[Optional[str], bool]:
    """(a literal `cwd=` of the call or None, whether the directory is known: no `cwd=` or a literal one)."""
    for item in call.keywords:
        if item.arg == "cwd":
            if isinstance(item.value, ast.Constant) and item.value.value is None:
                return None, True
            text = _fold_string(item.value)
            return (text, True) if text is not None else (None, False)
    return None, True


_PATH_CLASSES = frozenset({"Path", "PurePath", "PosixPath", "WindowsPath", "PurePosixPath", "PureWindowsPath"})
_JOIN_MODULES = {"os": ["path", "join"], "os.path": ["join"], "posixpath": ["join"], "ntpath": ["join"]}

# What the text of a program shows about a path (the allow-list; everything else is unknown):
#   - a string literal, or `Path(...)` / `PurePath(...)` / `os.path.join(...)` of such parts;
#   - a name bound exactly once, by a plain assignment, to such a value, and used unchanged: not a parameter, a loop
#     target, an import, a `with ... as` or a `global`, and the program rebinds nothing behind the text
#     (_REBINDING_NAMES, _REBINDING_ATTRIBUTES, an attribute stored on a module): else every name is unknown;
#   - those parts joined with `+`, `/` or put into an f-string field;
#   - `<such a path>.glob('<literal>')` / `.rglob(...)` as the iterable of a `for` loop: the files are somewhere
#     under that folder (_Under), when neither the folder nor the pattern holds `..` and the folder is relative;
#     so is a name bound once to `next(<such a glob>)`;
#   - the variable of a `for` loop over a list or tuple of literals (`for name, ans in [("a", "b"), ...]` too): it is
#     one of them, and a path or glob pattern built from it is judged once for each (at most _LOOP_COMBINATIONS);
#   - `<such a path>.with_suffix('<literal>')`, and `<file of a glob>.with_suffix(...)`: somewhere under the folder;
#   - the path parameter of a function the program uses only as `onerror=` / `onexc=` of `shutil.rmtree` calls whose
#     targets are shown: somewhere under those targets (when they hold no `..`), and only when the function uses its
#     first parameter for nothing but `first(path)`.
_REBINDING_NAMES = frozenset({
    "exec", "eval", "compile", "globals", "locals", "vars", "setattr", "getattr", "delattr", "__import__",
    "_getframe", "currentframe", "f_globals", "f_locals", "__dict__", "__setattr__", "__builtins__", "runpy",
    "cProfile", "importlib", "chdir", "fchdir",
})
_REBINDING_ATTRIBUTES = frozenset({"modules"})  # `sys.modules`
_MODULE_ROOTS = frozenset({"os", "sys", "builtins", "pathlib", "shutil", "posixpath", "ntpath"})
# Where a glob that may reach it is also judged (the first segment of each, matched against the pattern; a deep
# pattern reaches all of them): the places the guards of the template's own and of the git metadata files protect.
_PROTECTED_PROBES = (
    ".act/", ".git/hooks/", ".git/config", ".claude/settings.json", ".mcp.json", ".vscode/tasks.json",
    ".devcontainer/devcontainer.json", ".envrc",
)
_ANY_FILE = "(any file here)"
WHOLE_FOLDER = "(whole folder)"  # the folder a recursive delete removes as a whole: the guards judge it as a folder
_LOOP_COMBINATIONS = 64  # a path built from loop variables is judged once for each combination, up to this many


class _Under(NamedTuple):
    """The files a glob on a literal folder yields: somewhere under `base`."""

    base: str
    pattern: str
    recursive: bool
    whole: bool = False  # the folder itself goes too (a recursive delete), not only files below it


def _under_paths(under: _Under) -> list[str]:
    """The paths a check judges for `under`: a file in the folder and, for each protected place at or below the
    folder that the glob can reach (a deep pattern reaches every one, a single-segment one those its pattern
    matches), one in that place - `.act/` from the project root, `hooks` and `config` from `.git`. Below any other
    folder the glob stays inside that folder: only the folder is judged. An absolute folder may be the project root
    itself, so its `.act/` is judged too (not the git places: those are matched by text anywhere and would refuse
    every absolute folder). A folder that goes as a whole (`whole`) is also named as that, so a guard that knows the
    project root can refuse the root and each of its ancestors, which hold `.act/` without the path showing it."""
    base = os.path.normpath(under.base.replace("\\", "/")).replace("\\", "/")
    prefix = "./" if base == "." else f"{base}/"
    deep = under.recursive or "**" in under.pattern or "/" in under.pattern or "\\" in under.pattern
    found = [prefix + _ANY_FILE]
    absolute = _absolute_without_parent(base)
    if under.whole:
        found.append(prefix + WHOLE_FOLDER)
    for probe in (_PROTECTED_PROBES[:1] if absolute else _PROTECTED_PROBES):
        if base == "." or absolute:
            rel = probe
        elif probe.startswith(base.lower() + "/"):
            rel = probe[len(base) + 1:]
        else:
            continue
        if rel and (deep or fnmatch.fnmatchcase(rel.split("/")[0].lower(), under.pattern.lower())):
            found.append(prefix + rel + (_ANY_FILE if rel.endswith("/") else ""))
    return found


def _relative_without_parent(text: str) -> bool:
    """True for a path that is relative (no root, drive or `~`) and climbs nowhere (no `..` segment)."""
    if not text or text[0] in "/\\~" or re.match(r"[A-Za-z]:", text) or "$" in text:
        return False
    return ".." not in re.split(r"[\\/]+", text)


def _absolute_without_parent(text: str) -> bool:
    """True for a path that starts at a drive or a root (not `~`, not a `\\\\server` or `//server` share) and climbs
    nowhere (no `..` segment): where it lies is for the checks that resolve it against the project root."""
    if not text or text[:2] in ("//", "\\\\") or "$" in text or "~" in text:
        return False
    if not (text[0] in "/\\" or re.match(r"[A-Za-z]:[\\/]", text)):
        return False
    return ".." not in re.split(r"[\\/]+", text)


class _Env:
    """What the text of a program shows about the paths it writes (see the allow-list above)."""

    def __init__(self, tree: ast.AST, aliases: _Aliases) -> None:
        self.tree = tree
        self.aliases = aliases
        self.bound, star = _bindings(tree)
        self.imports: dict[str, int] = {}
        self.assigned: dict[str, ast.expr] = {}
        self.looped: dict[str, ast.expr] = {}
        self.functions: dict[str, ast.FunctionDef] = {}
        self.loops: dict[str, tuple[int, int]] = {}  # loop variable -> (the loop, its column in a row)
        self.loop_rows: dict[int, list[tuple[Optional[str], ...]]] = {}  # the loop -> the literals it goes through
        self.subst: dict[str, Optional[str]] = {}  # loop variable -> its value in the combination being judged
        self.handlers: Optional[dict[str, list]] = None
        self.memo: dict[str, Optional[str]] = {}
        self.active = not star
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    name = alias.asname or alias.name.split(".")[0]
                    self.imports[name] = self.imports.get(name, 0) + 1
            elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                self.assigned[node.targets[0].id] = node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None and isinstance(node.target, ast.Name):
                self.assigned[node.target.id] = node.value
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                if isinstance(node.target, ast.Name):
                    self.looped[node.target.id] = node.iter
                self._literal_loop(node)
            elif isinstance(node, ast.FunctionDef):
                self.functions[node.name] = node
            if self.active and self._rebinds(node):
                self.active = False

    def _literal_loop(self, node: "ast.For | ast.AsyncFor") -> None:
        """Take note of `for a in [<literals>]` and `for a, b in [(<literals>), ...]`: a list or tuple written out,
        each element a string (a column that is none stays unknown) or, for several names, a tuple of that length."""
        target, items = node.target, node.iter
        names = [target] if isinstance(target, ast.Name) else target.elts if isinstance(target, (ast.Tuple, ast.List)) else []
        if not names or not all(isinstance(name, ast.Name) for name in names):
            return
        if not isinstance(items, (ast.List, ast.Tuple)) or not items.elts:
            return
        if any(len(self.bound.get(name.id, ())) != 1 for name in names):  # type: ignore[union-attr]
            return  # a name the program binds again (or in another loop) keeps no literal
        rows: list[tuple[Optional[str], ...]] = []
        for element in items.elts:
            if isinstance(target, ast.Name):
                rows.append((_fold_string(element),))
            elif isinstance(element, (ast.Tuple, ast.List)) and len(element.elts) == len(names):
                rows.append(tuple(_fold_string(part) for part in element.elts))
            else:
                return
        self.loop_rows[id(node)] = rows
        for column, name in enumerate(names):
            self.loops[name.id] = (id(node), column)  # type: ignore[union-attr]

    def _loops_in(self, node: ast.expr) -> list[int]:
        """The literal loops whose variable `node` uses, directly or through a name bound once to a value, a glob
        or a loop that uses it."""
        found: dict[int, None] = {}
        seen: set[str] = set()
        todo = [node]
        while todo:
            for part in ast.walk(todo.pop()):
                if not isinstance(part, ast.Name) or part.id in seen or len(self.bound.get(part.id, ())) != 1:
                    continue
                seen.add(part.id)
                if part.id in self.loops:
                    found[self.loops[part.id][0]] = None
                elif part.id in self.assigned:
                    todo.append(self.assigned[part.id])
                elif part.id in self.looped:
                    todo.append(self.looped[part.id])
        return list(found)

    def _rebinds(self, node: ast.AST) -> bool:
        """True if `node` can change what a name or a function stands for behind the text of the call."""
        if isinstance(node, ast.Name):
            return node.id in _REBINDING_NAMES
        if not isinstance(node, ast.Attribute):
            return False
        if node.attr in _REBINDING_NAMES or node.attr in _REBINDING_ATTRIBUTES:
            return True
        if isinstance(node.ctx, ast.Load):
            return False
        root, _names = _dotted_root(node)
        return root in self.aliases.modules or root in self.aliases.functions or root in _MODULE_ROOTS

    def _imported_only(self, name: str) -> bool:
        """True if every binding of `name` in the program is an import (or it is not bound at all)."""
        return len(self.bound.get(name, ())) == self.imports.get(name, 0)

    def _is_path_class(self, func: ast.expr) -> bool:
        if isinstance(func, ast.Name):
            module, function = self.aliases.functions.get(func.id, ("pathlib", func.id))
            return module == "pathlib" and function in _PATH_CLASSES and self._imported_only(func.id)
        if isinstance(func, ast.Attribute) and func.attr in _PATH_CLASSES and isinstance(func.value, ast.Name):
            return self.aliases.modules.get(func.value.id) == "pathlib" and self._imported_only(func.value.id)
        return False

    def _is_join(self, func: ast.expr) -> bool:
        if isinstance(func, ast.Name):
            module, function = self.aliases.functions.get(func.id, ("", ""))
            return function == "join" and module in ("os.path", "posixpath", "ntpath") and self._imported_only(func.id)
        root, names = _dotted_root(func)
        module = self.aliases.modules.get(root) if root is not None else None
        if module is None and self.aliases.functions.get(root or "") == ("os", "path"):
            module = "os.path"  # `from os import path`
        return module in _JOIN_MODULES and names == _JOIN_MODULES[module] and self._imported_only(root or "")

    def text(self, node: Optional[ast.expr], depth: int = 0) -> Optional[str]:
        """The text `node` stands for when the program shows it, else None."""
        if node is None or depth > _LITERAL_FOLD_DEPTH:
            return None
        if isinstance(node, ast.Constant):
            return _fold_string(node)
        if isinstance(node, ast.JoinedStr):
            parts: list[Optional[str]] = []
            for value in node.values:
                if isinstance(value, ast.FormattedValue):
                    clean = self.active and value.conversion == -1 and value.format_spec is None
                    parts.append(self.text(value.value, depth + 1) if clean else None)
                else:
                    parts.append(self.text(value, depth + 1))
            return None if None in parts else "".join(part for part in parts if part is not None)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Div)):
            if isinstance(node.op, ast.Div) and not self.active:
                return None
            left, right = self.text(node.left, depth + 1), self.text(node.right, depth + 1)
            if left is None or right is None:
                return None
            return left + right if isinstance(node.op, ast.Add) else os.path.join(left, right)
        if isinstance(node, ast.Name) and self.active:
            return self._name_text(node.id, depth)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "with_suffix"
                and self.active and len(node.args) == 1 and not node.keywords):
            base, suffix = self.text(node.func.value, depth + 1), self.text(node.args[0], depth + 1)
            try:
                if base is not None and suffix is not None:
                    return str((PureWindowsPath if "\\" in base else PurePosixPath)(base).with_suffix(suffix))
            except ValueError:
                pass
            return None
        if isinstance(node, ast.Call) and node.args and not node.keywords:
            if self._is_path_class(node.func) or (self.active and self._is_join(node.func)):
                parts = [self.text(argument, depth + 1) for argument in node.args]
                return None if None in parts else os.path.join(*[part for part in parts if part is not None])
        return None

    def _name_text(self, name: str, depth: int) -> Optional[str]:
        if name in self.subst:
            return self.subst[name]
        if name not in self.memo:
            self.memo[name] = None  # a name that refers to itself is unknown
            if len(self.bound.get(name, ())) == 1 and name in self.assigned:
                self.memo[name] = self.text(self.assigned[name], depth + 1)
        return self.memo[name]

    def _is_glob_function(self, func: ast.expr) -> bool:
        """`glob.glob` / `glob.iglob` (also `from glob import glob`)."""
        if isinstance(func, ast.Name):
            module, function = self.aliases.functions.get(func.id, ("", ""))
            return module == "glob" and function in ("glob", "iglob") and self._imported_only(func.id)
        root, names = _dotted_root(func)
        return (root is not None and self.aliases.modules.get(root) == "glob" and len(names) == 1
                and names[0] in ("glob", "iglob") and self._imported_only(root))

    def glob(self, node: ast.expr) -> Optional[_Under]:
        """`<path>.glob('<pattern>')` / `.rglob(...)` on a folder the program shows, or `glob.glob('<pattern>')` /
        `glob.iglob(...)` (the folder is the literal part of the pattern before its first wildcard), also inside
        `sorted(...)` / `list(...)` when those names are not rebound, else None."""
        if not self.active or not isinstance(node, ast.Call):
            return None
        while (isinstance(node.func, ast.Name) and node.func.id in ("sorted", "list") and len(node.args) == 1
               and not node.keywords and not self.bound.get(node.func.id) and isinstance(node.args[0], ast.Call)):
            node = node.args[0]
        if self._is_glob_function(node.func):
            recursive = False
            for item in node.keywords:
                if item.arg != "recursive" or not isinstance(item.value, ast.Constant):
                    return None  # `root_dir=`, `include_hidden=` and the rest move or widen the search: not shown
                recursive = bool(item.value.value)
            pattern = self.text(node.args[0]) if len(node.args) == 1 else None
            if pattern is None or not _relative_without_parent(pattern):
                return None
            parts = re.split(r"[\\/]+", pattern)
            cut = next((index for index, part in enumerate(parts) if re.search(r"[*?\[]", part)), len(parts) - 1)
            base, rest = "/".join(parts[:cut]) or ".", "/".join(parts[cut:])
            return _Under(base, rest, recursive and "**" in rest)
        if not isinstance(node.func, ast.Attribute):
            return None
        if node.func.attr not in ("glob", "rglob") or len(node.args) != 1 or node.keywords:
            return None
        base, pattern = self.text(node.func.value), self.text(node.args[0])
        if base is None or pattern is None or not _relative_without_parent(base) or not _relative_without_parent(pattern):
            return None
        return _Under(base, pattern, node.func.attr == "rglob")

    def path_value(self, node: Optional[ast.expr]) -> "Optional[list[str | _Under]]":
        """The paths a write call's path argument or receiver names: its text, the folders a glob's files are under
        (`for f in Path('docs').glob('*.md'): f.write_text(...)`, `next(...)`, a handler's parameter), once for each
        combination of the literal loops it is built from - or None: not shown, so not judged."""
        loops = self._loops_in(node) if node is not None and self.active else []
        size = 1
        for key in loops:
            size *= len(self.loop_rows[key])
        if size > _LOOP_COMBINATIONS:
            return None
        saved = self.subst, self.memo
        found: list = []
        try:
            for rows in itertools.product(*(self.loop_rows[key] for key in loops)):
                if loops:
                    chosen = dict(zip(loops, rows))
                    self.subst = {name: chosen[key][column] for name, (key, column) in self.loops.items() if key in chosen}
                    self.memo = {}
                value = self._path_value_once(node)
                if value is None:
                    return None
                found.extend(value)
        finally:
            self.subst, self.memo = saved
        return found

    def with_dir_fd(self, call: ast.Call, position: int, paths: "Optional[list[str | _Under]]") -> "Optional[list[str | _Under]]":
        """`paths` (the shown paths of the argument at `position` of a write call) when no directory descriptor
        moves it. A `dir_fd=` (`src_dir_fd=` for the first path, `dst_dir_fd=` for the second) that is not `None`
        resolves the path against another directory, so the call writes where the text does not show: the paths
        come back joined onto that directory when it is shown (`os.open('<literal>', ...)`, written out or through a
        name bound once, no other keyword but `flags`), else None - not shown, and a refused write."""
        names = ("dir_fd", "src_dir_fd" if position == 0 else "dst_dir_fd")
        given = [item.value for item in call.keywords if item.arg in names
                 and not (isinstance(item.value, ast.Constant) and item.value.value is None)]
        if not given:
            return paths
        if paths is None or len(given) != 1 or any(isinstance(item, _Under) for item in paths):
            return None
        directory = self._descriptor_directory(given[0])
        return None if directory is None else [os.path.join(directory, str(item)) for item in paths]

    def _descriptor_directory(self, node: ast.expr) -> Optional[str]:
        """The directory a descriptor argument stands for when the text shows it: `os.open(<path>, ...)` of a
        shown path, directly or as a name bound once to it; else None."""
        if not self.active:
            return None
        if isinstance(node, ast.Name) and len(self.bound.get(node.id, ())) == 1:
            node = self.assigned.get(node.id, node)
        if not isinstance(node, ast.Call) or _callee(node.func, self.aliases) != ("os", "open", None):
            return None
        if any(item.arg != "flags" for item in node.keywords):
            return None
        return self.text(_argument(node, 0, "path"))

    def _path_value_once(self, node: Optional[ast.expr]) -> "Optional[list[str | _Under]]":
        text = self.text(node)
        if text is not None:
            return [text]
        if not self.active:
            return None
        return self._under(node)

    def _under(self, node: Optional[ast.expr]) -> "Optional[list[str | _Under]]":
        """The folders the files `node` stands for are under, when it is `Path(f)` of one of these: the variable of
        a `for` loop over a glob; a name bound once to `next(<glob>)`, or that call; `<one of these>.with_suffix(..)`
        (any suffix: the file stays in its folder); the path parameter of a handler (_handler_targets)."""
        if isinstance(node, ast.Call) and len(node.args) == 1 and not node.keywords and self._is_path_class(node.func):
            node = node.args[0]  # `Path(f)` of a loop variable is that variable
        if isinstance(node, ast.Name) and len(self.bound.get(node.id, ())) == 1:
            if node.id in self.looped:
                return self._globbed(self.looped[node.id])
            if node.id in self.assigned and self._next_argument(self.assigned[node.id]) is not None:
                return self._under(self.assigned[node.id])
            return self._handler_targets(node.id)
        if self._next_argument(node) is not None:
            return self._globbed(self._next_argument(node))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "with_suffix"
                and len(node.args) == 1 and not node.keywords):
            inner = self._under(node.func.value)
            if inner is None or any(not isinstance(item, _Under) for item in inner):
                return None
            return [_Under(item.base, "*", True) for item in inner if isinstance(item, _Under)]
        return None

    def _globbed(self, iterable: Optional[ast.expr]) -> "Optional[list[str | _Under]]":
        under = self.glob(iterable) if iterable is not None else None
        return [under] if under is not None else None

    def _next_argument(self, node: Optional[ast.expr]) -> Optional[ast.expr]:
        """The glob of `next(<glob>)` / `next(<glob>, None)` (when `next` is not rebound), else None."""
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "next"
                and not self.bound.get("next") and not node.keywords and node.args and len(node.args) <= 2
                and all(isinstance(item, ast.Constant) and item.value is None for item in node.args[1:])):
            return node.args[0]
        return None

    def _handler_targets(self, name: str) -> "Optional[list[str | _Under]]":
        """`path` of `def handler(function, path, excinfo)` when the program uses `handler` only as `onerror=` /
        `onexc=` of `shutil.rmtree` calls: it lies under what those calls delete, which must be shown, with no `..`.
        Any other use of the function (a call, a name, a decorator), or a first parameter that the handler uses
        for anything but `function(path)`, leaves `path` unknown."""
        if self.handlers is None:
            self.handlers = {}  # a handler whose target needs a handler is unknown
            self.handlers = self._find_handlers()
        return self.handlers.get(name)

    def _plain_rmtree(self, func: ast.expr) -> bool:
        """True if `func` is `shutil.rmtree` / `rmtree` and the program binds `shutil` (or `rmtree`) only by importing it."""
        root = func.id if isinstance(func, ast.Name) else _dotted_root(func)[0]
        return root is not None and self.imports.get(root, 0) > 0 and self._imported_only(root)

    def _only_calls_first(self, first: str, second: str) -> bool:
        """True when every load of the name `first` in the program is the callee of a call `first(second)`: one
        positional argument, the name `second`, no keyword; it is not stored, passed on or called otherwise."""
        callees: set[int] = set()
        for node in ast.walk(self.tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == first
                    and len(node.args) == 1 and not node.keywords and isinstance(node.args[0], ast.Name)
                    and node.args[0].id == second and isinstance(node.args[0].ctx, ast.Load)):
                callees.add(id(node.func))
        return all(id(node) in callees for node in ast.walk(self.tree) if isinstance(node, ast.Name) and node.id == first)

    def _find_handlers(self) -> dict[str, list]:
        calls: dict[str, list[ast.Call]] = {}
        as_handler: set[int] = set()
        for node in ast.walk(self.tree):
            if (isinstance(node, ast.Call) and _callee(node.func, self.aliases) == ("shutil", "rmtree", None)
                    and self._plain_rmtree(node.func)):
                for item in node.keywords:
                    if item.arg in ("onerror", "onexc") and isinstance(item.value, ast.Name):
                        calls.setdefault(item.value.id, []).append(node)
                        as_handler.add(id(item.value))
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and id(node) not in as_handler:
                calls.pop(node.id, None)  # the function is used otherwise
        found: dict[str, list] = {}
        for function, rmtrees in calls.items():
            definition = self.functions.get(function)
            if definition is None or definition.decorator_list or len(self.bound.get(function, ())) != 1:
                continue
            positional = definition.args.posonlyargs + definition.args.args
            if len(positional) < 2 or any(len(self.bound.get(item.arg, ())) != 1 for item in positional[:2]):
                continue
            if not self._only_calls_first(positional[0].arg, positional[1].arg):
                continue
            under: list = []
            for rmtree in rmtrees:
                targets = self.path_value(_argument(rmtree, 0, "path"))
                if targets is None:
                    under = []
                    break
                for target in targets:
                    if isinstance(target, _Under):
                        under.append(target)
                    elif _relative_without_parent(target) or _absolute_without_parent(target):
                        under.append(_Under(target, "*", True, True))
                    else:
                        under = []
                        break
                if not under:
                    break
            if under:
                found[positional[1].arg] = under
        return found


def _read_call(call: ast.Call, aliases: _Aliases, env: "_Env") -> Optional[ProgramCall]:
    found = _callee(call.func, aliases)
    if found is None:
        return None
    module, function, receiver = found
    name = f".{function}" if module in ("", "?") else (function if module == "builtins" else f"{module}.{function}")
    line = getattr(call, "lineno", 0)
    if (module, function) in _CODE_FUNCTIONS:
        node = _argument(call, 0, "source")
        text = _fold_string(node) if node is not None else None
        return ProgramCall(name, CALL_CODE, (text,) if text is not None else (), None, True, line)
    if (module, function) in _RUN_FUNCTIONS or module == "?":
        values = _command_values(call, _RUN_FUNCTIONS.get((module, function), "args"))
        directory, known = _directory_of(call)
        return ProgramCall(name, CALL_RUN, values, directory, known, line)
    if module == "":
        nodes = [receiver]
        if function == "open":
            # A method `.open` writes only with a mode written out: `p.open('w')` opens the receiver,
            # `gzip.open(name, 'wb')` / `x.open(name, mode='w')` the first argument. `Image.open(x)`,
            # `tarfile.open(name)` and `webbrowser.open(url)` hold none and are no writes - unless the receiver is
            # a path the program shows and the mode is a value it does not (`Path('x').open(sys.argv[1])`).
            first, second = _argument(call, 0, None), _argument(call, 1, None)
            keyword = next((item.value for item in call.keywords if item.arg == "mode"), None)
            if _literal_writing_mode(first, env):
                pass
            elif _literal_writing_mode(second, env) or _literal_writing_mode(keyword, env):
                nodes = [first] if first is not None else nodes
            elif env.path_value(receiver) is not None and any(
                    item is not None and env.text(item) is None for item in (first, keyword)):
                pass  # the receiver's path is shown and the mode is not: it may write the receiver
            else:
                return None
        elif _WRITE_METHODS.get(function, False):
            nodes.append(_argument(call, 0, "target"))
    else:
        positions = _WRITE_FUNCTIONS[(module, function)]
        if (module, function) == ("os", "open") and _is_read_only_flag(_argument(call, 1, "flags")):
            return None
        if positions == ("mode",):
            if not _mode_writes(call, 1, env):
                return None
            positions = (0,)
        nodes = []
        for position in positions:
            node = _argument(call, position, ("src", "dst")[position] if position < 2 else None)
            if node is None and position == 0:
                node = _argument(call, 0, "file") or _argument(call, 0, "path")
            nodes.append(node)
    paths = [env.path_value(node) for node in nodes]
    if module != "":
        paths = [env.with_dir_fd(call, position, path) for position, path in zip(positions, paths)]
    values: list[str] = []
    for path in paths:
        for item in path or ():
            if isinstance(item, _Under):
                values.extend(_under_paths(item))
            else:
                values.append(item)
                if (module, function) == ("shutil", "rmtree"):
                    values.append(item.rstrip("/\\") + "/" + WHOLE_FOLDER)  # the folder goes as a whole
    return ProgramCall(name, CALL_WRITE, tuple(values), None, True, line, None in paths)


# --- A harmless program: the allow-list -------------------------------------------------------------
#
# A program is HARMLESS - and a check may then take its text out of the shell reading of the command
# that hands it to python - only when everything it calls is on this allow-list and nothing in it can
# turn a value into a call later. The list is positive and short on purpose: a program it does not
# cover is read as before (its text as shell commands), which costs a false refusal at most, never a
# pass. The families above are judged by the caller whether or not the program is harmless.
#   - A builtin that computes, converts, inspects, iterates or prints a value and takes no callable:
#     _HARMLESS_BUILTINS (`type` with one argument only, `iter` without a sentinel) and the builtin
#     exception classes. Left out on purpose: `map`, `filter`, `iter(callable, sentinel)`,
#     `type(name, bases, dict)`, `getattr`/`setattr`/`delattr`/`vars`/`globals`/`locals`/`dir`,
#     `__import__`, `compile`, `exec`, `eval`, `open`, `input`, `breakpoint`, `help`, `super`,
#     `classmethod`/`staticmethod`/`property` - each runs or reaches a callable, reads a file or
#     builds code.
#   - A method on a literal receiver - a string, bytes, f-string, list, tuple, dict or set written
#     out - whose name is no dunder: whatever the method, it works on that value in memory.
#   - `sys.exit`, `sys.stdout.write`/`.flush`, `sys.stderr.write`/`.flush`, with `sys` bound by
#     `import sys` and by nothing else in the program; reading `sys.argv`, `sys.stdout`, `sys.stderr`.
# Not harmless, whatever else the program does: a keyword named `key` (a callable for `sorted`, `min`,
# `max`, `list.sort`) or a `**` unpacking (which can hide one); a call of an allow-listed name the
# program binds itself (`print = os.system`, `from os import system as len`, `def len`); a
# `from x import *`; a decorator; any class (its dunder slots run implicitly: `raise`, `e[...]`, a format
# spec); any dunder name but `__name__` and `__file__` (`__builtins__`); any attribute read other than
# the method of an allowed call and the `sys` attributes above (`os.system` as a value, a frame, a
# `__dict__`); a store or delete on
# an attribute or on any item (`os.system = ...`, `d['len'] = ...`), which could rebind what a later
# call reaches; a call of anything else - a name the program defines, a variable, a lambda, a call's
# result, a subscript, a module function.

_HARMLESS_BUILTINS = frozenset({
    "print", "len", "range", "enumerate", "zip", "reversed", "sorted", "sum", "min", "max", "abs",
    "round", "divmod", "pow", "any", "all", "bin", "hex", "oct", "chr", "ord", "repr", "ascii", "format",
    "hash", "id", "isinstance", "issubclass", "callable", "str", "int", "float", "complex", "bool",
    "bytes", "bytearray", "list", "tuple", "dict", "set", "frozenset", "slice", "object", "type", "iter",
    "next",
    "BaseException", "Exception", "SystemExit", "KeyboardInterrupt", "ValueError", "TypeError",
    "RuntimeError", "KeyError", "IndexError", "AssertionError", "NotImplementedError", "OSError",
    "FileNotFoundError", "AttributeError", "NameError", "StopIteration", "LookupError", "ArithmeticError",
    "ZeroDivisionError",
})
_HARMLESS_SYS_CALLS = frozenset({"exit", "stdout.write", "stdout.flush", "stderr.write", "stderr.flush"})
_HARMLESS_SYS_READS = frozenset({"argv", "stdout", "stderr"})
_HARMLESS_DUNDER_NAMES = frozenset({"__name__", "__file__"})  # plain strings, so `if __name__ == ...` stays
_LITERAL_RECEIVERS = (ast.Constant, ast.JoinedStr, ast.List, ast.Tuple, ast.Dict, ast.Set)


class PythonProgram(NamedTuple):
    """A program read as Python (read_python_program)."""

    calls: list                # ProgramCall: every call of the families, in source order
    harmless: bool             # every call on the allow-list above, nothing that can turn a value into a call
    blocker: Optional[str]     # what keeps it from being harmless, in words; None when it is


def _bindings(tree: ast.AST) -> tuple[dict[str, list[str]], bool]:
    """(every name the program binds, mapped to how - "import" for a plain `import name`, "other" for
    anything else: an assignment, a `def`/`class`, a parameter, `as`, `global`, a `from` import -;
    whether the program has a `from x import *`, which can bind any name)."""
    bound: dict[str, list[str]] = {}
    star = False

    def bind(name: str, how: str = "other") -> None:
        bound.setdefault(name, []).append(how)

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            bind(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bind(node.name)
        elif isinstance(node, ast.arg):
            bind(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bind(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for name in node.names:
                bind(name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                plain = alias.asname is None and "." not in alias.name
                bind(alias.asname or alias.name.split(".")[0], "import" if plain else "other")
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    star = True
                else:
                    bind(alias.asname or alias.name)
        elif type(node).__name__ in ("MatchAs", "MatchStar") and getattr(node, "name", None):
            bind(node.name)  # a capture of a `match` statement (Python 3.10+)
        elif type(node).__name__ == "MatchMapping" and getattr(node, "rest", None):
            bind(node.rest)
    return bound, star


def _callee_text(func: ast.expr) -> str:
    root, names = _dotted_root(func)
    return ".".join([root or "<expression>", *names])


def _call_blocker(call: ast.Call, bound: dict[str, list[str]]) -> Optional[str]:
    """What keeps one call off the allow-list above, in words; None when it is on it."""
    for keyword in call.keywords:
        if keyword.arg is None:
            return "a `**` unpacking in a call"
        if keyword.arg == "key":
            return "a `key=` argument"
    func = call.func
    if isinstance(func, ast.Name):
        if func.id in bound:
            return f"a call of `{func.id}`, which the program binds"
        if func.id not in _HARMLESS_BUILTINS:
            return f"a call of `{func.id}`"
        if func.id == "type" and (len(call.args) != 1 or call.keywords):
            return "`type` with more than one argument"
        if func.id == "iter" and len(call.args) != 1:
            return "`iter` with a sentinel"
        return None
    if isinstance(func, ast.Attribute):
        if func.attr.startswith("__"):
            return f"a call of `.{func.attr}`"
        if isinstance(func.value, _LITERAL_RECEIVERS):
            return None
        if _sys_only_imported(bound) and _is_sys_chain(func, _HARMLESS_SYS_CALLS):
            return None
        return f"a call of `{_callee_text(func)}`"
    return "a call of something that is no name"


def _sys_only_imported(bound: dict[str, list[str]]) -> bool:
    """`sys` is bound by a plain `import sys` and by nothing else in the program."""
    return bool(bound.get("sys")) and all(how == "import" for how in bound["sys"])


def _is_sys_chain(node: ast.expr, allowed: frozenset) -> bool:
    """`node` is `sys.<chain>` with the chain in `allowed`."""
    root, names = _dotted_root(node)
    return root == "sys" and ".".join(names) in allowed


def _allowed_attribute_reads(tree: ast.AST, bound: dict[str, list[str]]) -> set[int]:
    """The ids of the attribute nodes a harmless program may read: the method of a call on a literal
    receiver, the chain of an allowed `sys` call, and `sys.argv`/`sys.stdout`/`sys.stderr`."""
    allowed: set[int] = set()
    sys_ok = _sys_only_imported(bound)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, _LITERAL_RECEIVERS):
                allowed.add(id(node.func))
            elif sys_ok and _is_sys_chain(node.func, _HARMLESS_SYS_CALLS):
                current: ast.expr = node.func
                while isinstance(current, ast.Attribute):
                    allowed.add(id(current))
                    current = current.value
        elif isinstance(node, ast.Attribute) and sys_ok and _is_sys_chain(node, _HARMLESS_SYS_READS):
            allowed.add(id(node))
    return allowed


def _harmless_blocker(tree: ast.AST) -> Optional[str]:
    """The first construct that keeps the program from being harmless (see the allow-list above), in
    words; None when there is none."""
    bound, star = _bindings(tree)
    if star:
        return "a `from ... import *`"
    readable = _allowed_attribute_reads(tree, bound)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.decorator_list:
            return f"a decorator on `{node.name}`"
        if isinstance(node, ast.ClassDef):
            return f"a class `{node.name}`"
        if (isinstance(node, ast.Name) and node.id.startswith("__") and node.id.endswith("__")
                and node.id not in _HARMLESS_DUNDER_NAMES):
            return f"the name `{node.id}`"
        if isinstance(node, ast.Attribute):
            if not isinstance(node.ctx, ast.Load):
                return f"a store on attribute `{node.attr}`"
            if id(node) not in readable:
                return f"a read of attribute `{node.attr}`"
        if isinstance(node, ast.Subscript) and not isinstance(node.ctx, ast.Load):
            return "a store or delete on an item"
        if isinstance(node, ast.Call):
            blocker = _call_blocker(node, bound)
            if blocker is not None:
                return blocker
    return None


def read_python_program(code: str) -> Optional[PythonProgram]:
    """`code` read as Python: every call that runs a command, writes a file or runs Python text (the
    families in the section comment above), in source order, and whether the program is harmless by the
    allow-list above. None when the text is not read as Python: it does not parse (a syntax error, a
    null byte), is larger than _PROGRAM_SIZE_LIMIT, or nests deeper than can be walked."""
    if len(code) > _PROGRAM_SIZE_LIMIT:
        return None
    try:
        tree = ast.parse(code)
        aliases = _module_aliases(tree)
        env = _Env(tree, aliases)
        found: list[ProgramCall] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                call = _read_call(node, aliases, env)
                if call is not None:
                    found.append(call)
        blocker = _harmless_blocker(tree)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    return PythonProgram(sorted(found, key=lambda call: call.line), blocker is None, blocker)
