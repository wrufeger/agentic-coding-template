#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Reads inline interpreter code for checks/write_scope.py (check 1c): the program text a
#          worker's shell command hands to `python`/`node` (`python - <<'EOF' ... EOF`, `python -c
#          "..."`, `node -e "..."`, a here-string or a literal piped into `python -`) is searched for
#          a write call and for path literals, so a worker with a restricted write scope cannot write
#          outside it from inside such a program as long as the path stands in the code as a literal.
#          This module knows nothing about shells: shell_targets.py / powershell_targets.py find the
#          interpreter call, the code text and the directory the call runs in; this module answers
#          two questions about them -
#
#              code_source(language, args)   -> where the code comes from (an option value, stdin, none)
#              write_paths(language, code)   -> the path literals of the code, or [] without a write call
#
# What counts as a write call (regex level, run over the code with comments removed and every string
# literal blanked, so a call named inside a string or a comment is not one):
#   - Python: `open(` / `io.open(` / `codecs.open(` / `.open(` with a literal mode made only of
#     `rwaxbt+` that holds `w`, `a`, `x` or `+` (positional, or `mode=`); `.write_text(`,
#     `.write_bytes(`, `.touch(`, `.mkdir(`, `.unlink(`, `.rmdir(`, `.rename(`, `.symlink_to(`,
#     `.hardlink_to(`; `shutil.copy|copy2|copyfile|copytree|move|rmtree`; `os.remove|unlink|rename|
#     replace|makedirs|mkdir|rmdir|removedirs|symlink|link|truncate|open`.
#   - Node: `writeFile`, `writeFileSync`, `appendFile`, `appendFileSync`, `createWriteStream`,
#     `copyFile`, `copyFileSync`, `cp`, `cpSync`, `rename`, `renameSync`, `unlink`, `unlinkSync`, `rm`,
#     `rmSync`, `rmdir`, `rmdirSync`, `mkdir`, `mkdirSync`, `symlink`, `symlinkSync`, `truncate`,
#     `truncateSync`, as a call (`fs.writeFileSync(`, `fs.promises.writeFile(`, a destructured one).
#   Deliberately not one, to keep read-only one-liners free: a bare `.write(` (`sys.stdout.write`),
#   `.replace(` (`str.replace`), `print(..., file=...)`.
#
# What counts as a path literal: a string literal (Python `'..'`, `".."`, triple-quoted, prefixes
# r/b/u/f in any combination; Node `'..'`, `".."`, template literals) that, once the escapes of a
# non-raw literal are decoded the way its language does (`\\` -> `\`, `\xhh`, `\uXXXX`, `\N{name}`,
# octal; a raw Python literal stays as written), contains `/` or `\`, or is a bare file name with an
# extension (`name.ext`, the extension 1-8 letters or digits and not all digits, so `1.0` is none),
# and is not a URL (`scheme://`), not empty, holds no control character (a `\n`/`\r`/`\t` escape makes
# it text, not a path), is not made of separators alone (`'/'`, `'\\'` split or join names), and holds
# none of `*?[]^|()<>` (glob and regular-expression text is not judged). An interpolated literal (Python f-string `{...}`, Node
# `${...}`) is judged by its static prefix up to the last separator before the first interpolation;
# without a separator there it is no path.
#
# Windows tools with `/` switches: a literal that is only a switch (`/deny`, `/c`, `/grant:r`, `/MIR`,
# `/R:3`: one segment, at most 16 letters or digits, an optional `:value`) is no path in exactly one
# place - among the arguments of a call that starts a program, when the tool that knows the switch (the
# table per tool is _TOOL_SWITCHES; `icacls`, `cmd`, ... also as a `System32` path) is the literal in
# the tool's position of that very call: the first element of the list `subprocess.run`, `call`,
# `check_call`, `check_output` or `Popen` gets, the first argument of Node `spawn`, `spawnSync`,
# `execFile` or `execFileSync` with the list as the second, the program argument of `os.exec*` /
# `os.spawn*`. The tool's name is no path there either. A literal in that position that is a whole
# command line starting with the tool (`os.system('icacls d /deny x')`, `subprocess.run('...')`, Node
# `exec`/`execSync`) is cut into words, the tool and its switches dropped and every other word judged
# on its own - but only a line of one command: a `;`, `&`, `|`, `<`, `>`, `(`, `)`, `^`, `%`, `$`, backtick
# or line break in it keeps the literal whole. For `cmd` only the switches up to `/c` or `/k` drop: what
# follows is another program's command line and is judged as usual. Nothing else makes a switch: not a `'cmd'` elsewhere in the program (`print('cmd')`,
# `t = 'cmd'`), not the enclosing statement, block or any other call (`shutil.copytree('cmd', '/c')`),
# not a list built from parts; a switch the tool does not know and one that names a file
# (`/LOG:out.txt`) stay paths. The cost: a switch-like literal in the tool's own list is never judged
# as a file in the root of a drive.
#
# Known limits (a path missed here is simply not checked): a path built at run time (`Path(a) / b`,
# `os.path.join('out', name)` whose parts carry no separator, `os.environ[...]`, a variable holding
# the path); a bare name without an extension (`open('out', 'w')`), which includes a dotfile such as
# `.envrc` (a leading dot is no extension); a script file run by path; writes
# through `subprocess`/`os.system`/`child_process`; a write call that is not in the list (`.write(`,
# `Path.replace`, `fs.openSync`, `from shutil import rmtree` used bare); a string the lexer reads
# wrongly (a string nested in an f-string replacement field that reuses its own quote; a JavaScript
# regular-expression literal is told from a division by the token in front of it, so one after `)`,
# `]` or `}` reads as a division and a `//` in it starts a comment that hides the rest of its line);
# code that imports a name under another one; any
# other interpreter (perl, ruby, php, deno, bun). Best effort: it catches the common form, not every
# form.

from __future__ import annotations

import ast
import os
import re
import shlex
import sys
import unicodedata
from typing import NamedTuple, Optional

__all__ = [
    "PYTHON", "NODE", "SOURCE_CODE", "SOURCE_STDIN", "SOURCE_NONE",
    "interpreter_language", "code_source", "code_source_at", "write_paths", "path_literals", "has_write_call",
    "mentions_interpreter", "report_skipped",
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

_NOT_JUDGED_CHARS = frozenset("*?[]^|()<>")
_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_BARE_FILE_RE = re.compile(r"^[^\s/\\]+\.([A-Za-z0-9]{1,8})$")
_PY_MODE_RE = re.compile(r"""^(['"])([rwaxbt+]+)\1$""")
_PY_PREFIX_CHARS = "rRbBuUfF"
_ARG_SCAN_LIMIT = 300  # characters of one call's arguments read for a mode; bounds the work per call
_OPEN_CALL_LIMIT = 200  # open( calls examined; more than that is taken as a write (absurd code, fail closed)


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


def report_skipped(where: str, error: BaseException) -> None:
    """Say on standard error that inline interpreter code was not read because of `error` (its type and
    message, never the command): the reading is best effort and a failure of it must not refuse the
    call, but it must not pass unseen either."""
    print(f"[act] inline interpreter code not read ({where}): {type(error).__name__}: {error}", file=sys.stderr)


def _blank(body: str, quote: str) -> str:
    """A string literal as it stays in the skeleton the write calls are searched in: its quotes, and its
    text only where it can be an open() mode (`rwaxbt+`)."""
    keep = _PY_MODE_RE.match(quote + body + quote) is not None
    return quote + (body if keep else "_") + quote


def _python_scan(code: str) -> tuple[list[_Literal], str]:
    """(string literals in source order, skeleton): the skeleton is the code with comments dropped and
    every string literal blanked (see _blank)."""
    literals: list[_Literal] = []
    out: list[str] = []
    size = len(code)
    index = 0
    while index < size:
        char = code[index]
        if char == "#":
            end = code.find("\n", index)
            index = size if end < 0 else end
            continue
        if char not in "'\"":
            out.append(char)
            index += 1
            continue
        start = index
        while start > 0 and index - start < 3 and code[start - 1] in _PY_PREFIX_CHARS:
            start -= 1
        prefix = code[start:index]
        if start > 0 and (code[start - 1].isalnum() or code[start - 1] == "_"):
            prefix = ""  # the letters belong to a longer name: no string prefix
        if prefix:
            del out[len(out) - len(prefix):]
        triple = code.startswith(char * 3, index)
        width = 3 if triple else 1
        cursor = index + width
        closed = False
        while cursor < size:
            current = code[cursor]
            if current == "\\":
                cursor += 2
                continue
            if triple:
                if code.startswith(char * 3, cursor):
                    closed = True
                    break
            elif current == char:
                closed = True
                break
            elif current == "\n":
                break
            cursor += 1
        raw_body = code[index + width:min(cursor, size)]
        body = raw_body
        index = min(cursor + width, size) if closed else min(cursor, size)
        lowered = prefix.lower()
        interpolated = False
        if "f" in lowered:
            field = _python_field_start(body)
            if field is not None:
                body, interpolated = body[:field], True
            body = body.replace("{{", "{").replace("}}", "}")
        value = body if "r" in lowered else _decode_escapes(body, False, "b" not in lowered)
        literals.append(_Literal(value, interpolated))
        out.append(_blank(raw_body, char))
    return literals, "".join(out)


def _python_field_start(body: str) -> Optional[int]:
    """Index of the first replacement field `{` of an f-string body (`{{` is a literal brace), else None."""
    index = 0
    while index < len(body):
        if body.startswith("{{", index):
            index += 2
        elif body[index] == "{":
            return index
        else:
            index += 1
    return None


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
    """The JavaScript counterpart of _python_scan: `//` and `/* */` comments dropped, strings and
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


# Python write calls that need no argument reading.
_PY_CALL_RE = re.compile(
    r"\.\s*(?:write_text|write_bytes|touch|mkdir|unlink|rmdir|rename|symlink_to|hardlink_to)\s*\("
    r"|(?<![\w.])shutil\s*\.\s*(?:copy|copy2|copyfile|copytree|move|rmtree)\s*\("
    r"|(?<![\w.])os\s*\.\s*(?:remove|unlink|rename|replace|makedirs|mkdir|rmdir|removedirs|symlink|link"
    r"|truncate|open)\s*\("
)
_PY_OPEN_RE = re.compile(r"(?<![\w])open\s*\(")
_NODE_WRITE_RE = re.compile(
    r"(?<![\w$])(?:writeFile|writeFileSync|appendFile|appendFileSync|createWriteStream|copyFile|copyFileSync"
    r"|cp|cpSync|rename|renameSync|unlink|unlinkSync|rm|rmSync|rmdir|rmdirSync|mkdir|mkdirSync|symlink"
    r"|symlinkSync|truncate|truncateSync)\s*\("
)


def _call_arguments(skeleton: str, start: int) -> list[str]:
    """The top-level arguments of the call whose `(` ends just before `skeleton[start]`: split at commas
    outside any bracket, up to the closing parenthesis (or `_ARG_SCAN_LIMIT` characters)."""
    arguments: list[str] = []
    depth = 0
    current: list[str] = []
    for char in skeleton[start:start + _ARG_SCAN_LIMIT]:
        if char in "([{":
            depth += 1
        elif char in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif char == "," and depth == 0:
            arguments.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    arguments.append("".join(current).strip())
    return arguments


def _writes_mode(argument: str) -> bool:
    match = _PY_MODE_RE.match(argument)
    return match is not None and any(char in "wax+" for char in match.group(2))


def _open_call_writes(skeleton: str, match: "re.Match[str]") -> bool:
    """True if the `open(` call at `match` has a literal mode argument that writes: `mode=<mode>`, the
    second positional argument, or - for a method (`Path(...).open('w')`, `p.open('w')`) - the first."""
    method = skeleton[:match.start()].rstrip().endswith(".")
    for position, argument in enumerate(_call_arguments(skeleton, match.end())):
        keyword = re.match(r"mode\s*=\s*(.+)$", argument)
        if keyword:
            if _writes_mode(keyword.group(1).strip()):
                return True
        elif (position == 1 or (method and position == 0)) and _writes_mode(argument):
            return True
    return False


def _skeleton_has_write_call(language: str, skeleton: str) -> bool:
    if language == NODE:
        return _NODE_WRITE_RE.search(skeleton) is not None
    if _PY_CALL_RE.search(skeleton):
        return True
    for count, match in enumerate(_PY_OPEN_RE.finditer(skeleton)):
        if count >= _OPEN_CALL_LIMIT or _open_call_writes(skeleton, match):
            return True
    return False


def _path_candidate(literal: _Literal) -> Optional[str]:
    """The path a literal stands for (see the header for the rules), or None if it is not judged."""
    value = literal.value
    if literal.interpolated:
        cut = max(value.rfind("/"), value.rfind("\\"))
        if cut < 0:
            return None
        value = value[:cut + 1]
    if not value or any(ord(char) < 32 for char in value) or not value.strip("/\\"):
        return None
    if _URL_RE.match(value) or any(char in _NOT_JUDGED_CHARS for char in value):
        return None
    if "/" in value or "\\" in value:
        return value
    bare = _BARE_FILE_RE.match(value)
    if bare and not bare.group(1).isdigit():
        return value
    return None


def _scan(language: str, code: str) -> tuple[list[_Literal], str]:
    return _python_scan(code) if language == PYTHON else _javascript_scan(code)


def has_write_call(language: str, code: str) -> bool:
    """True if `code` contains a write call of its language (see the header)."""
    return _skeleton_has_write_call(language, _scan(language, code)[1])


def path_literals(language: str, code: str) -> list[str]:
    """Every path literal of `code` (see the header), in source order, each once."""
    found: dict[str, None] = {}
    for literal in _scan(language, code)[0]:
        candidate = _path_candidate(literal)
        if candidate is not None:
            found[candidate] = None
    return list(found)


# Windows command-line tools whose switches start with a slash (`icacls d /deny x`, `robocopy a b /MIR`,
# `cmd /c ...`), and the switches of each that this reads as switches - only in a call that starts the
# tool (see the header and _without_switches). A switch that names a file (`/LOG:out.txt`,
# `/EXCLUDE:list`) is left out of the table on purpose: it is judged like any path.
_TOOL_SWITCHES = {
    "icacls": "deny grant remove inheritance t c q l reset save restore setowner findsid verify substitute "
              "setintegritylevel",
    "cacls": "t m s e c g r p d",
    "robocopy": "mir e s purge r w mt copy copyall dcopy xd xf xo xc xn xx nfl ndl njh njs np ns nc l z b zb "
                "mov move lev create fft dst tee v ts fp bytes eta sec secfix timfix sl sj j",
    "xcopy": "e s i y -y q h r k c d f l t v w z o x p u n g b j",
    "takeown": "f r a d s u p skipsl",
    "attrib": "s d l",
    "cmd": "c k s q d a u t e f v x y r",
}
_SWITCH_NAMES = {tool: frozenset(("? " + names).split()) for tool, names in _TOOL_SWITCHES.items()}
_SWITCH_TOOLS = "(" + "|".join(_TOOL_SWITCHES) + r")(?:\.exe)?"
_SYSTEM32 = r"(?:[A-Za-z]:[\\/]Windows[\\/]System32[\\/])?"
_SWITCH_TOOL_RE = re.compile(_SYSTEM32 + _SWITCH_TOOLS, re.IGNORECASE)
_SWITCH_RE = re.compile(r"/(-?[A-Za-z?][A-Za-z0-9?]{0,15})(?::[^\s/\\]*)?")
_COMMAND_LINE_RE = re.compile(r'\s*"?' + _SYSTEM32 + _SWITCH_TOOLS + r'"?\s', re.IGNORECASE)
# A command line that holds more than one command or anything a shell expands or redirects is not cut into
# words: its later parts are another program's arguments, so its literal stays whole.
_LINE_OPERATOR_RE = re.compile(r"[;&|<>()^%$`\n\r]")
_COMMAND_WORD_RE = re.compile(r'"[^"]*"|\S+')
# The calls that start a program - the only place a literal counts as a switch. The group name says
# where the tool stands: `argv` - the tool and its arguments are one list, the call's first argument
# (`subprocess.run(['icacls', d, '/deny'])`; a string there is a whole command line), or the tool is the
# first argument and the list of its arguments the second (Node `spawnSync('icacls', [d, '/deny'])`);
# `line` - the first argument is a whole command line; `exec` / `spawn` - the tool is the first (for
# `spawn` the second) argument, its arguments the list behind it (`execv`, `spawnv`) or the call's own
# further arguments (`execl`, `spawnl`), the first of them its name once more.
_PY_START_CALL_RE = re.compile(
    r"(?<![\w.])(?:subprocess\s*\.\s*(?P<argv>run|call|check_call|check_output|Popen)"
    r"|os\s*\.\s*(?:(?P<line>system)|(?P<exec>exec[lv]p?e?)|(?P<spawn>spawn[lv]p?e?)))\s*\("
)
_JS_START_CALL_RE = re.compile(
    r"(?<![\w$])(?:(?P<argv>spawn|spawnSync|execFile|execFileSync)|(?P<line>exec|execSync))\s*\("
)
_QUOTE_CHARS = {PYTHON: "'\"", NODE: "'\"`"}


def _tool_of(text: str) -> Optional[str]:
    """The tool (a key of _TOOL_SWITCHES) that `text` names on its own (`icacls`, `icacls.exe`, a System32
    path to it), else None."""
    match = _SWITCH_TOOL_RE.fullmatch(text.strip())
    return match.group(1).lower() if match else None


def _is_switch_of(tool: str, text: str) -> bool:
    """True if `text` is one switch that `tool` knows (`/deny`, `/grant:r`, `/R:3`)."""
    match = _SWITCH_RE.fullmatch(text)
    return match is not None and match.group(1).lower() in _SWITCH_NAMES[tool]


def _literal_spans(language: str, skeleton: str) -> list[tuple[int, int]]:
    """(start, end) of every quote pair of the skeleton, in order: the n-th pair is the n-th literal of
    the program, as _python_scan / _javascript_scan keep every literal as one pair."""
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


def _without_switches(language: str, literals: list[_Literal], skeleton: str) -> list[_Literal]:
    """`literals` without what a call that starts a program makes of them (see the header): where the
    literal in the tool's position of such a call names a tool of _TOOL_SWITCHES, that literal and every
    argument literal of the call that is a switch the tool knows drop out (`subprocess.run(['icacls', d,
    '/deny', 'x'])`, `spawnSync('icacls', [d, '/deny'])`, `os.execlp('icacls', 'icacls', d, '/deny')`);
    a literal in that position that is a whole command line (`os.system('icacls d /deny x')`) is replaced
    by its words without the tool and its switches. Every other literal stays, and so does everything
    when the literals cannot be matched to the skeleton."""
    spans = _literal_spans(language, skeleton)
    if len(spans) != len(literals):
        return literals
    by_span = {span: index for index, span in enumerate(spans)}

    def trimmed(span: tuple[int, int]) -> tuple[int, int]:
        start, end = span
        while start < end and skeleton[start].isspace():
            start += 1
        while end > start and skeleton[end - 1].isspace():
            end -= 1
        return start, end

    def literal_in(span: tuple[int, int]) -> Optional[int]:
        """The index of the literal that is all of `span` but whitespace, else None."""
        index = by_span.get(trimmed(span))
        return None if index is None or literals[index].interpolated else index

    def elements_in(span: tuple[int, int]) -> list[tuple[int, int]]:
        """The element spans of the list or tuple that is all of `span` but whitespace, else []."""
        start, end = trimmed(span)
        if end - start < 2 or skeleton[start] not in "[(" or skeleton[end - 1] not in "])":
            return []
        elements = _argument_spans(skeleton, start + 1)
        return elements if elements[-1][1] == end - 1 else []

    dropped: set[int] = set()
    replaced: dict[int, list[_Literal]] = {}
    pattern = _PY_START_CALL_RE if language == PYTHON else _JS_START_CALL_RE
    for match in pattern.finditer(skeleton):
        arguments = _argument_spans(skeleton, match.end())
        kind = match.lastgroup
        tool_at = 1 if kind == "spawn" else 0
        if kind is None or tool_at >= len(arguments):
            continue
        line_form = kind == "line"
        words: list[tuple[int, int]] = []
        if kind == "argv" and language == PYTHON:
            words = elements_in(arguments[0])
            tool_index = literal_in(words[0]) if words else literal_in(arguments[0])
            line_form = not words
            words = words[1:]
        else:
            tool_index = literal_in(arguments[tool_at])
            if kind == "argv" and len(arguments) > 1:
                words = elements_in(arguments[1])
            elif kind in ("exec", "spawn"):
                if match.group(kind)[len(kind)] == "l":
                    words = arguments[tool_at + 1:]
                elif len(arguments) > tool_at + 1:
                    words = elements_in(arguments[tool_at + 1])
        if tool_index is None:
            continue
        value = literals[tool_index].value
        if line_form:
            line = _COMMAND_LINE_RE.match(value)
            if line is not None and _LINE_OPERATOR_RE.search(value) is None:
                tool = line.group(1).lower()
                kept: list[_Literal] = []
                own_words = True
                for part in _COMMAND_WORD_RE.findall(value):
                    word = part.strip('"')
                    if not word:
                        continue
                    if own_words and (_tool_of(word) == tool or _is_switch_of(tool, word)):
                        if tool == "cmd" and word.lower().split(":")[0] in ("/c", "/k"):
                            own_words = False
                        continue
                    kept.append(_Literal(word, False))
                replaced[tool_index] = kept
            continue
        tool = _tool_of(value)
        if tool is None:
            continue
        dropped.add(tool_index)
        for position, span in enumerate(words):
            index = literal_in(span)
            if index is None:
                if tool == "cmd":
                    break
                continue
            word = literals[index].value
            if _is_switch_of(tool, word) or (position == 0 and kind != "argv" and _tool_of(word) == tool):
                dropped.add(index)
                if tool == "cmd" and word.lower().split(":")[0] in ("/c", "/k"):
                    break
            elif tool == "cmd":
                break
    result: list[_Literal] = []
    for index, literal in enumerate(literals):
        if index not in dropped:
            result.extend(replaced.get(index, [literal]))
    return result

def write_paths(language: str, code: str) -> list[str]:
    """The path literals of `code` when it contains a write call, else []: the paths a check judges as
    possible write targets. The switches of a Windows tool the code starts are not paths (_without_switches)."""
    literals, skeleton = _scan(language, code)
    if not _skeleton_has_write_call(language, skeleton):
        return []
    found: dict[str, None] = {}
    for literal in _without_switches(language, literals, skeleton):
        candidate = _path_candidate(literal)
        if candidate is not None:
            found[candidate] = None
    return list(found)


# --- A Python program read as Python: the calls that run a command or write a file -------------------
#
# For a check that must know what a program DOES with a string rather than which strings it holds (the
# git-metadata guard reads a program handed to `python` this way): the program is parsed with `ast`,
# nothing of it runs, and every call of the families below is reported with the LITERAL values that go
# into it. A value the reading cannot see - a variable, an expression, a call, a starred argument, a
# non-literal receiver - is simply not reported: nothing follows a name, joins a path or expands a glob,
# and a call whose value is not written out is not judged (a static reading of Python is a guard rail
# against slips, not a wall). A program that does not parse as Python, is larger than _PROGRAM_SIZE_LIMIT
# or nests deeper than the interpreter can walk is not read at all (None back).
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
#     the receiver is the path when it is `Path(...)` of string literals, anything else is not reported.
#     For a copy the destination is the path, for a move, rename or link both operands are.
#   - CALL_CODE, Python text: builtin `exec` and `eval` with a literal; the caller reads that text again.
# A literal is a string constant, bytes (decoded), several of them joined with `+`, an f-string without
# fields, or a list/tuple of those. Not seen (a limit, the same as the string-literal reading above): a
# value that comes from a name, `os.path.join(...)`, `Path(...) / x`, an f-string with fields or a glob
# (writing through a variable is the limit the rules name for script files too), a callee reached through
# `getattr`, a subscript or a lambda, `.write(` on a stream, `str.replace` and `Path.replace` (left out on
# purpose), `runpy`, `importlib` loading a file, code built at run time.

CALL_RUN = "run"      # a command line the program hands to a shell or a program
CALL_WRITE = "write"  # a path the program writes, creates, moves, links or deletes
CALL_CODE = "code"    # Python text the program runs itself (`exec`, `eval`)

_PROGRAM_SIZE_LIMIT = 200_000  # characters of one program read as Python; a larger one is not read
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


def _mode_writes(call: ast.Call, position: int) -> bool:
    """True if the `mode` of an open-like call (positional `position` or `mode=`) writes: a mode-shaped
    literal (`rwaxbt+U` only) holding `w`, `a`, `x` or `+`, or a mode the reading cannot see (a variable).
    No mode at all is the default `r`; a literal that is no mode (`webbrowser.open(url)`, `tarfile.open(name)`)
    makes the call no open-for-writing."""
    node = _argument(call, position, "mode")
    if node is None:
        return False
    mode = _fold_string(node)
    if mode is None:
        return True
    return _PY_MODE_RE.match(f"'{mode}'") is not None and any(char in "wax+" for char in mode)


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


def _path_literal(node: Optional[ast.expr], aliases: _Aliases) -> Optional[str]:
    """The path a path argument or receiver names when it is written out: a string literal as
    _fold_string reads it, or `Path(...)` of such literals (joined as `os.path.join` joins them). None
    for anything else - a variable, an f-string with fields, `os.path.join(...)`, `Path(...) / x` -, which
    is not judged."""
    if node is None:
        return None
    text = _fold_string(node)
    if text is not None:
        return text
    if isinstance(node, ast.Call) and node.args and not node.keywords:
        func = node.func
        if isinstance(func, ast.Name):
            name = aliases.functions.get(func.id, ("", func.id))[1]
        elif isinstance(func, ast.Attribute):
            name = func.attr
        else:
            return None
        parts = [_fold_string(argument) for argument in node.args]
        if name in _PATH_CLASSES and None not in parts:
            return os.path.join(*parts)
    return None


def _read_call(call: ast.Call, aliases: _Aliases) -> Optional[ProgramCall]:
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
        if function == "open" and not _mode_writes(call, 0):
            return None
        nodes = [receiver]
        if _WRITE_METHODS.get(function, False):
            nodes.append(_argument(call, 0, "target"))
    else:
        positions = _WRITE_FUNCTIONS[(module, function)]
        if positions == ("mode",):
            if not _mode_writes(call, 1):
                return None
            positions = (0,)
        nodes = []
        for position in positions:
            node = _argument(call, position, ("src", "dst")[position] if position < 2 else None)
            if node is None and position == 0:
                node = _argument(call, 0, "file") or _argument(call, 0, "path")
            nodes.append(node)
    paths = (_path_literal(node, aliases) for node in nodes)
    return ProgramCall(name, CALL_WRITE, tuple(path for path in paths if path is not None), None, True, line)


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
        found: list[ProgramCall] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                call = _read_call(node, aliases)
                if call is not None:
                    found.append(call)
        blocker = _harmless_blocker(tree)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    return PythonProgram(sorted(found, key=lambda call: call.line), blocker is None, blocker)
