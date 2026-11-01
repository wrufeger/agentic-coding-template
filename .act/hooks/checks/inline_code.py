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

import re
import sys
import unicodedata
from typing import NamedTuple, Optional

__all__ = [
    "PYTHON", "NODE", "SOURCE_CODE", "SOURCE_STDIN", "SOURCE_NONE",
    "interpreter_language", "code_source", "write_paths", "path_literals", "has_write_call",
    "mentions_interpreter", "report_skipped",
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


def _python_source(args: list[str]) -> tuple[str, Optional[str]]:
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            index += 1
            break
        if arg == "-":
            return SOURCE_STDIN, None
        if not arg.startswith("-"):
            return SOURCE_NONE, None
        if arg.startswith("--"):
            if arg in ("--version", "--help"):
                return SOURCE_NONE, None
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
                    return SOURCE_CODE, rest
                if index + 1 < len(args):
                    return SOURCE_CODE, args[index + 1]
                return SOURCE_NONE, None
            if char in "mVh?":
                return SOURCE_NONE, None
            if char in "WXQ":  # -W/-X take a value, glued or as the next word
                takes_next = position + 1 == len(arg)
                break
        index += 2 if takes_next else 1
    return _stdin_or_none(args, index)


def _node_source(args: list[str]) -> tuple[str, Optional[str]]:
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            index += 1
            break
        if arg == "-":
            return SOURCE_STDIN, None
        if not arg.startswith("-"):
            return SOURCE_NONE, None
        if arg.startswith(("--eval=", "--print=")):
            return SOURCE_CODE, arg.split("=", 1)[1]
        if arg in _NODE_EVAL_OPTIONS:
            if index + 1 < len(args):
                return SOURCE_CODE, args[index + 1]
            return SOURCE_NONE, None
        if arg in _NODE_NO_CODE_OPTIONS:
            return SOURCE_NONE, None
        index += 2 if arg in _NODE_VALUE_OPTIONS else 1
    return _stdin_or_none(args, index)


def code_source(language: str, args: list[str]) -> tuple[str, Optional[str]]:
    """Where an interpreter call gets its program from, read from the call's arguments (the words after
    the command name): (SOURCE_CODE, the code) for `-c`/`-e`/`--eval`/`-p`, (SOURCE_STDIN, None) for a
    lone `-` or no script argument at all, (SOURCE_NONE, None) for a script file, a module (`-m`) or a
    query that runs nothing. Options before the code are skipped (`-X utf8 -I -c`, `py -3.12 -c`,
    `--input-type=module -e`); a cluster ending in `c` (`-Ic`) counts."""
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
